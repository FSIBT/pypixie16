"""
TracesPlotter with Reorganized Functional Tabs
- Raw Traces: Simplified trace display only
- Hardware Trigger Validation: Real-time parameter control and signal visualization
- Coincidence Analysis: Statistical analysis and window optimization
"""

import numpy as np
from collections import deque, defaultdict
import time
import json
from pathlib import Path
import csv

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QPushButton,
    QComboBox,
    QTextEdit,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QProgressBar,
    QMessageBox,
)
from PyQt6.QtCore import QTimer, QThread, pyqtSignal
import pyqtgraph as pg

import pixie16 as px

from ...analyze import (
    compute_fast_trigger_validation,
    compute_energy_filter,
    convert_trace_to_FPGA,
    calculate_CFD,
    calculate_filter,
    get_fast_trigger_index,
)
from .traces_replay import TraceReplayWidget, StoredTrace


class WindowOptimizationWorker(QThread):
    """Worker thread for optimizing coincidence windows"""

    progress = pyqtSignal(int)
    result = pyqtSignal(dict)
    status = pyqtSignal(str)

    def __init__(self, coincidence_events, window_range, center_channel):
        super().__init__()
        self.coincidence_events = coincidence_events
        self.window_range = window_range  # (min_ns, max_ns, step_ns)
        self.center_channel = center_channel

    def run(self):
        min_window, max_window, step = self.window_range
        results = {}

        total_steps = int((max_window - min_window) / step) + 1

        for i, window_ns in enumerate(np.arange(min_window, max_window + step, step)):
            self.status.emit(f"Testing {window_ns:.1f}ns window...")

            valid_coincidences = 0
            total_time_diffs = []

            for coinc_event in self.coincidence_events:
                # Count events within this window
                events_in_window = []
                for event, trace in coinc_event.associated_events:
                    time_diff = abs(
                        self._calculate_time_difference(
                            event.timestamp, coinc_event.center_event.timestamp
                        )
                    )

                    if time_diff <= window_ns:
                        events_in_window.append((event, time_diff))
                        total_time_diffs.append(time_diff)

                if events_in_window:
                    valid_coincidences += 1

            # Calculate statistics
            efficiency = (
                valid_coincidences / len(self.coincidence_events)
                if self.coincidence_events
                else 0
            )
            mean_dt = np.mean(total_time_diffs) if total_time_diffs else 0
            std_dt = np.std(total_time_diffs) if total_time_diffs else 0

            results[window_ns] = {
                "coincidences": valid_coincidences,
                "efficiency": efficiency,
                "mean_dt": mean_dt,
                "std_dt": std_dt,
                "total_events": len(total_time_diffs),
            }

            self.progress.emit(int((i + 1) / total_steps * 100))

        self.result.emit(results)
        self.status.emit("Optimization complete")

    def _calculate_time_difference(self, timestamp1, timestamp2):
        dt_ticks = timestamp1 - timestamp2
        dt_ns = dt_ticks * 10.0  # Convert to nanoseconds
        return dt_ns


class CoincidenceEvent:
    def __init__(self, center_event, center_trace, associated_events_with_traces):
        self.center_event = center_event
        self.center_trace = center_trace
        self.associated_events = []
        self.time_differences = []

        for event, trace in associated_events_with_traces:
            self.associated_events.append((event, trace))
            # Handle timestamp units properly
            dt_ns = self._calculate_time_difference(
                event.timestamp, center_event.timestamp
            )
            self.time_differences.append(dt_ns)

    def _calculate_time_difference(self, timestamp1, timestamp2):
        # Timestamps are typically in 10ns units
        dt_ticks = timestamp1 - timestamp2
        dt_ns = dt_ticks * 10.0  # Convert to nanoseconds
        return dt_ns


class TracesPlotter(QWidget):
    # Signal for hardware parameter changes
    parameter_changed = pyqtSignal(
        str, object, int, int
    )  # param_name, value, module, channel

    def __init__(self, channels=None, title="PIXIE-16 Traces", hardware_manager=None):
        super().__init__()

        self.channels = channels or list(range(16))
        self.display_channels = self.channels.copy()
        self.hardware_manager = hardware_manager  # Reference to hardware manager

        # Trace storage
        self.trace_data = {ch: deque(maxlen=1000) for ch in self.channels}
        self.last_traces = {ch: None for ch in self.channels}

        # Event storage for coincidence analysis
        self.event_buffer = deque(maxlen=50000)
        self.coincidence_events = deque(maxlen=10000)

        # Display settings (simplified for Raw Traces)
        self.max_traces_display = 10
        self.amplitude_threshold = 0.1
        self.auto_scale = True

        # Real-time axis settings
        self.use_realtime_axis = True
        self.trace_delay_ns = {}
        self.sampling_period_ns = 2.0

        # Hardware validation settings
        self.selected_channel = 0
        self.hardware_status_label = None

        self.trace_types = {
            "raw": True,
            "fast_trigger": False,
            "energy_filter": False,
            "cfd": False,
        }

        # Coincidence analysis settings
        self.coincidence_mode = False
        self.center_channel = 9
        self.coincidence_window_ns = 20.0
        self.validation_window_optimization = False
        self.optimization_active = False
        self.optimization_results = {}
        self.optimal_window_ns = 20.0

        # Channel colors
        self.colors = [
            "#1f77b4",
            "#ff7f0e",
            "#2ca02c",
            "#d62728",
            "#9467bd",
            "#8c564b",
            "#e377c2",
            "#7f7f7f",
            "#bcbd22",
            "#17becf",
            "#aec7e8",
            "#ffbb78",
            "#98df8a",
            "#ff9896",
            "#c5b0d5",
            "#c49c94",
        ]

        self.hardware_params = {
            "fast_L": 2,  # FPGA units
            "fast_G": 2,  # FPGA units
            "fast_threshold": 100,  # Trigger threshold
            "cfd_threshold": 100,  # CFD threshold
            "energy_R": 1,  # Range (slow_filter_range = 2**R)
            "energy_L": 10,  # Energy filter L steps
            "energy_G": 5,  # Energy filter G steps
            "energy_P": 10,  # Peak sample
            "decay_ns": 28.0,  # Decay time in nanoseconds
        }

        self.trigger_points = {ch: {} for ch in self.channels}
        self.peak_sample_points = {ch: {} for ch in self.channels}

        # Add parameter display labels
        self.parameter_info_label = None

        # Initialize replay system first
        self.replay_widget = None
        self.replay_mode = False

        # Store when alignment mode was activated
        self.alignment_reference_timestamp = None
        self.alignment_mode_start_time = None

        # Time alignment settings
        self.time_alignment_mode = "zero"
        self.alignment_reference_channel = 0
        self.trace_timestamps = {ch: deque(maxlen=1000) for ch in self.channels}

        self.init_ui()

        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_plots)

    def init_ui(self):
        layout = QVBoxLayout()

        # Create tabbed interface
        self.tab_widget = QTabWidget()

        raw_traces_tab = self.create_raw_traces_tab()
        self.tab_widget.addTab(raw_traces_tab, "Raw Traces")

        hardware_validation_tab = self.create_hardware_validation_tab()
        self.tab_widget.addTab(hardware_validation_tab, "Single Trace Validation")

        coincidence_analysis_tab = self.create_coincidence_analysis_tab()
        self.tab_widget.addTab(coincidence_analysis_tab, "Coincidence Logic")

        layout.addWidget(self.tab_widget)
        self.setLayout(layout)

    def create_raw_traces_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        controls_group = QGroupBox("Display Controls")
        controls_group.setMaximumHeight(120)
        controls_layout = (
            QGridLayout()
        )  # Changed to QGridLayout for better organization

        # Row 1: Basic controls
        controls_layout.addWidget(QLabel("Max Traces:"), 0, 0)
        self.max_traces_spin = QSpinBox()
        self.max_traces_spin.setRange(1, 100)
        self.max_traces_spin.setValue(self.max_traces_display)
        self.max_traces_spin.valueChanged.connect(self.update_max_traces)
        controls_layout.addWidget(self.max_traces_spin, 0, 1)

        controls_layout.addWidget(QLabel("Threshold:"), 0, 2)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 2.0)
        self.threshold_spin.setValue(self.amplitude_threshold)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.valueChanged.connect(self.update_threshold)
        controls_layout.addWidget(self.threshold_spin, 0, 3)

        # Row 2: Time alignment controls
        controls_layout.addWidget(QLabel("Time Alignment:"), 1, 0)
        self.time_alignment_combo = QComboBox()
        self.time_alignment_combo.addItems(["Zero", "Channel", "None"])
        self.time_alignment_combo.currentTextChanged.connect(
            self.update_time_alignment_mode
        )
        controls_layout.addWidget(self.time_alignment_combo, 1, 1)

        controls_layout.addWidget(QLabel("Ref Channel:"), 1, 2)
        self.alignment_ref_combo = QComboBox()
        for ch in self.channels:
            self.alignment_ref_combo.addItem(f"Ch {ch}")
        self.alignment_ref_combo.setCurrentIndex(0)
        self.alignment_ref_combo.currentIndexChanged.connect(
            self.update_alignment_reference
        )
        self.alignment_ref_combo.setEnabled(
            False
        )  # Disabled until channel aligned mode is selected
        controls_layout.addWidget(self.alignment_ref_combo, 1, 3)

        # Row 3: Other controls
        self.auto_scale_cb = QCheckBox("Auto Scale")
        self.auto_scale_cb.setChecked(True)
        self.auto_scale_cb.toggled.connect(self.toggle_auto_scale)
        controls_layout.addWidget(self.auto_scale_cb, 2, 0)

        self.simple_coincidence_cb = QCheckBox("Coincidence Mode")
        self.simple_coincidence_cb.toggled.connect(self.toggle_simple_coincidence)
        controls_layout.addWidget(self.simple_coincidence_cb, 2, 1)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_data)
        controls_layout.addWidget(self.clear_btn, 2, 2)

        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)

        # Rest of the method remains the same...
        # Plot area
        self.raw_plot_widget = pg.PlotWidget()
        self.raw_plot_widget.setLabel("left", "Amplitude (V)")
        self.raw_plot_widget.setLabel("bottom", "Time (ns)")
        self.raw_plot_widget.setTitle("PIXIE-16 Raw Traces")
        self.raw_plot_widget.showGrid(True, True, alpha=0.3)
        self.raw_plot_widget.addLegend()
        self.raw_plot_widget.setBackground("w")
        layout.addWidget(self.raw_plot_widget)

        # Basic statistics
        self.raw_stats_label = QLabel("Statistics: Waiting for traces...")
        layout.addWidget(self.raw_stats_label)

        # Initialize plot curves for raw traces
        self.raw_curves = {}
        for i, channel in enumerate(self.channels):
            color = self.colors[i % len(self.colors)]
            self.raw_curves[channel] = self.raw_plot_widget.plot(
                pen=pg.mkPen(color=color, width=1.5), name=f"Ch {channel}"
            )

        return tab

    def calculate_main_trigger_point(self, raw_trace, channel):
        """Calculate the main trigger point - leading edge detection for nuclear spectroscopy"""
        try:
            if raw_trace is None or len(raw_trace) == 0:
                return []

            raw_trace = np.asarray(raw_trace)
            if len(raw_trace) < 20:  # Need enough samples for analysis
                return []

            # Get baseline from first 20% of trace (more conservative for nuclear pulses)
            baseline_samples = max(20, int(len(raw_trace) * 0.2))
            baseline_samples = min(baseline_samples, len(raw_trace) // 3)

            baseline = np.mean(raw_trace[:baseline_samples])
            baseline_noise = np.std(raw_trace[:baseline_samples])

            # Leading edge trigger: baseline + small multiple of noise (typically 2-5 sigma)
            # This catches the pulse as soon as it starts rising above noise
            leading_edge_threshold = baseline + (
                3.0 * baseline_noise
            )  # 3-sigma above baseline

            # Also calculate derivative to find steepest rise
            if len(raw_trace) > 5:
                # Simple derivative (difference between adjacent points)
                derivative = np.diff(raw_trace)
                # Smooth the derivative to reduce noise
                if len(derivative) > 3:
                    derivative = np.convolve(derivative, [0.25, 0.5, 0.25], mode="same")

            # Find first point where trace crosses leading edge threshold (rising edge)
            trigger_indices = []

            # Start looking after baseline region
            search_start = baseline_samples

            for i in range(search_start, len(raw_trace) - 1):
                # Check for threshold crossing
                if (
                    raw_trace[i] < leading_edge_threshold
                    and raw_trace[i + 1] >= leading_edge_threshold
                ):
                    # Additional validation: check if this is a real rising edge
                    # Look at the next few points to confirm it's going up
                    if i + 5 < len(raw_trace):
                        next_few = raw_trace[i : i + 5]
                        if (
                            np.mean(next_few) > leading_edge_threshold
                        ):  # Confirm it stays up
                            trigger_indices.append(
                                i + 1
                            )  # Return the point that crossed
                            break  # Only take first trigger
                    else:
                        trigger_indices.append(i + 1)
                        break

            print(
                f"DEBUG: Leading edge trigger for Ch{channel}: baseline={baseline:.1f}, "
                f"noise={baseline_noise:.1f}, threshold={leading_edge_threshold:.1f}, "
                f"trigger_points={trigger_indices}"
            )

            return trigger_indices

        except Exception as e:
            print(f"Error calculating leading edge trigger for channel {channel}: {e}")
            return []

    def update_time_alignment_mode(self, mode_text):
        if mode_text == "Zero":
            self.time_alignment_mode = "none"
            self.alignment_ref_combo.setEnabled(False)
            self.alignment_reference_timestamp = None
            self.raw_plot_widget.setTitle("PIXIE-16 Raw Traces - No Time Alignment")
        elif mode_text == "Channel":
            self.time_alignment_mode = "channel_aligned"
            self.alignment_ref_combo.setEnabled(True)
            self.alignment_reference_timestamp = None

            ref_ch = self.channels[self.alignment_ref_combo.currentIndex()]
            self.raw_plot_widget.setTitle(
                f"PIXIE-16 Raw Traces - Aligned to Ch{ref_ch}"
            )
            print(
                f"DEBUG: Channel alignment mode enabled, waiting for Ch{ref_ch} trace..."
            )
        elif mode_text == "Real Time Axis":
            self.time_alignment_mode = "real_time_axis"
            self.alignment_ref_combo.setEnabled(False)
            self.raw_plot_widget.setTitle("PIXIE-16 Raw Traces - Real Time Axis")

    def update_alignment_reference(self):
        self.alignment_reference_channel = self.channels[
            self.alignment_ref_combo.currentIndex()
        ]
        self.alignment_reference_timestamp = None
        if self.time_alignment_mode == "channel_aligned":
            self.raw_plot_widget.setTitle(
                f"PIXIE-16 Raw Traces - Aligned to Ch{self.alignment_reference_channel}"
            )

    def calculate_aligned_time_axis(self, trace_length, channel, event_timestamp=None):
        if (
            self.time_alignment_mode == "channel_aligned"
            and event_timestamp is not None
        ):
            # Get reference timestamp for alignment
            ref_timestamp = self.get_reference_timestamp()
            if ref_timestamp is not None:
                # Calculate time difference in ns (assuming 10ns timestamp units)
                time_offset = (event_timestamp - ref_timestamp) * 10.0

                return np.arange(trace_length) * self.sampling_period_ns + time_offset
            else:
                # No reference yet, use default
                return np.arange(trace_length) * self.sampling_period_ns

        elif self.time_alignment_mode == "real_time_axis":
            # TODO
            return np.arange(trace_length) * self.sampling_period_ns

        else:
            # Fallback to default
            return np.arange(trace_length) * self.sampling_period_ns

    def get_reference_timestamp(self):
        if self.alignment_reference_timestamp is None:
            # Set reference when first trace from reference channel arrives
            ref_ch = self.alignment_reference_channel
            if (
                ref_ch in self.trace_timestamps
                and len(self.trace_timestamps[ref_ch]) > 0
            ):
                self.alignment_reference_timestamp = self.trace_timestamps[ref_ch][-1]
                print(
                    f"DEBUG: Auto-set reference timestamp to {self.alignment_reference_timestamp} from Ch{ref_ch}"
                )

        return self.alignment_reference_timestamp

    def create_hardware_validation_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Channel selector
        selector_group = QGroupBox("Channel Selection")
        selector_layout = QHBoxLayout()
        selector_layout.setContentsMargins(8, 2, 8, 2)
        selector_layout.setSpacing(8)

        selector_layout.addWidget(QLabel("Channel:"))
        self.channel_combo = QComboBox()
        for ch in self.channels:
            self.channel_combo.addItem(f"Ch {ch}")
        self.channel_combo.setCurrentIndex(0)
        self.channel_combo.currentIndexChanged.connect(self.update_selected_channel)
        selector_layout.addWidget(self.channel_combo)

        selector_layout.addStretch()
        selector_group.setLayout(selector_layout)
        layout.addWidget(selector_group)

        # Add replay controls for single trace validation
        self.replay_widget = TraceReplayWidget(initial_buffer_size=1000)
        self.replay_widget.trace_selected.connect(
            self.on_hardware_replay_trace_selected
        )
        self.replay_widget.replay_mode_changed.connect(
            self.on_hardware_replay_mode_changed
        )
        layout.addWidget(self.replay_widget)
        print(f"Successfully created replay widget: {self.replay_widget}")

        # Trace type controls
        trace_types_group = QGroupBox("Trace Types")
        trace_types_layout = QHBoxLayout()
        trace_types_layout.setContentsMargins(8, 2, 8, 2)
        trace_types_layout.setSpacing(12)

        self.raw_traces_cb = QCheckBox("Raw Traces")
        self.raw_traces_cb.setChecked(True)
        self.raw_traces_cb.toggled.connect(lambda: self.toggle_trace_type("raw"))
        trace_types_layout.addWidget(self.raw_traces_cb)

        self.fast_trigger_cb = QCheckBox("Fast Trigger (FO0)")
        self.fast_trigger_cb.toggled.connect(
            lambda: self.toggle_trace_type("fast_trigger")
        )
        trace_types_layout.addWidget(self.fast_trigger_cb)

        self.energy_filter_cb = QCheckBox("Energy Filter")
        self.energy_filter_cb.toggled.connect(
            lambda: self.toggle_trace_type("energy_filter")
        )
        trace_types_layout.addWidget(self.energy_filter_cb)

        self.cfd_cb = QCheckBox("CFD Traces")
        self.cfd_cb.toggled.connect(lambda: self.toggle_trace_type("cfd"))
        trace_types_layout.addWidget(self.cfd_cb)

        trace_types_layout.addStretch()
        trace_types_group.setLayout(trace_types_layout)
        layout.addWidget(trace_types_group)

        params_info_group = QGroupBox("Current Parameters")
        params_info_layout = QVBoxLayout()
        params_info_layout.setContentsMargins(8, 2, 8, 2)

        self.parameter_info_label = QLabel()
        self.parameter_info_label.setStyleSheet(
            "font-family: monospace; font-size: 10pt;"
        )
        self.update_parameter_info_display()
        params_info_layout.addWidget(self.parameter_info_label)

        params_info_group.setLayout(params_info_layout)
        layout.addWidget(params_info_group)

        self.channel_plot = pg.PlotWidget()
        self.channel_plot.setLabel("left", "Amplitude")
        self.channel_plot.setLabel("bottom", "Time (ns)")
        self.channel_plot.setTitle(f"Channel {self.selected_channel} Validation")
        self.channel_plot.showGrid(True, True, alpha=0.3)
        self.channel_plot.setBackground("w")
        self.channel_plot.addLegend(offset=(10, 10))
        layout.addWidget(self.channel_plot)

        self.hardware_status_label = QLabel("Hardware Status: Ready")
        layout.addWidget(self.hardware_status_label)

        # Initialize plot curves for hardware validation
        self.hw_curves = {}

        trace_colors = {
            "raw": "#1f77b4",  # Blue
            "fast_trigger": "#ff7f0e",  # Orange
            "energy_filter": "#2ca02c",  # Green
            "cfd": "#d62728",  # Red
        }

        trace_names = {
            "raw": "Raw Trace",
            "fast_trigger": "Fast Trigger",
            "energy_filter": "Energy Filter",
            "cfd": "CFD",
        }

        for trace_type in self.trace_types.keys():
            self.hw_curves[trace_type] = self.channel_plot.plot(
                pen=pg.mkPen(color=trace_colors[trace_type], width=2),
                name=trace_names[trace_type],
            )

        return tab

    def update_parameter_info_display(self):
        if self.parameter_info_label:
            params_text = (
                f"Fast Filter: L={self.hardware_params['fast_L']} FPGA, "
                f"G={self.hardware_params['fast_G']} FPGA, "
                f"Threshold={self.hardware_params['fast_threshold']} ADC\n"
                f"Energy Filter: R={self.hardware_params['energy_R']}, "
                f"L={self.hardware_params['energy_L']}, "
                f"G={self.hardware_params['energy_G']}, "
                f"P={self.hardware_params['energy_P']}\n"
                f"CFD: Threshold={self.hardware_params['cfd_threshold']} ADC, "
                f"Decay={self.hardware_params['decay_ns']:.1f}ns"
            )
            self.parameter_info_label.setText(params_text)

    def create_coincidence_analysis_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Coincidence settings
        settings_group = QGroupBox("Coincidence Settings")
        settings_layout = QGridLayout()

        # Center channel selection
        settings_layout.addWidget(QLabel("Center Channel:"), 0, 0)
        self.center_channel_combo = QComboBox()
        for ch in self.channels:
            self.center_channel_combo.addItem(f"Ch {ch}")
        self.center_channel_combo.setCurrentIndex(9 if 9 in self.channels else 0)
        self.center_channel_combo.currentIndexChanged.connect(
            self.update_center_channel
        )
        settings_layout.addWidget(self.center_channel_combo, 0, 1)

        # Coincidence window
        settings_layout.addWidget(QLabel("Time Window:"), 0, 2)
        self.time_window_spin = QDoubleSpinBox()
        self.time_window_spin.setRange(5.0, 1000.0)
        self.time_window_spin.setValue(self.coincidence_window_ns)
        self.time_window_spin.setSuffix(" ns")
        self.time_window_spin.valueChanged.connect(self.update_coincidence_window)
        settings_layout.addWidget(self.time_window_spin, 0, 3)

        # Quick window presets
        settings_layout.addWidget(QLabel("Quick Presets:"), 1, 0)
        self.quick_window_combo = QComboBox()
        self.quick_window_combo.addItems(
            ["10ns", "20ns", "50ns", "100ns", "200ns", "500ns"]
        )
        self.quick_window_combo.setCurrentText("20ns")
        self.quick_window_combo.currentTextChanged.connect(self.set_quick_window)
        settings_layout.addWidget(self.quick_window_combo, 1, 1)

        # Live validation mode
        self.validation_cb = QCheckBox("Live Validation")
        self.validation_cb.toggled.connect(self.toggle_validation_mode)
        settings_layout.addWidget(self.validation_cb, 1, 2)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # Window optimization controls
        optimization_group = QGroupBox("Window Optimization")
        optimization_layout = QGridLayout()

        # Test range
        optimization_layout.addWidget(QLabel("Test Range:"), 0, 0)
        self.min_window_spin = QDoubleSpinBox()
        self.min_window_spin.setRange(5.0, 1000.0)
        self.min_window_spin.setValue(10.0)
        self.min_window_spin.setSuffix(" ns")
        optimization_layout.addWidget(self.min_window_spin, 0, 1)

        optimization_layout.addWidget(QLabel("to"), 0, 2)
        self.max_window_spin = QDoubleSpinBox()
        self.max_window_spin.setRange(10.0, 2000.0)
        self.max_window_spin.setValue(200.0)
        self.max_window_spin.setSuffix(" ns")
        optimization_layout.addWidget(self.max_window_spin, 0, 3)

        optimization_layout.addWidget(QLabel("Step:"), 0, 4)
        self.step_window_spin = QDoubleSpinBox()
        self.step_window_spin.setRange(1.0, 50.0)
        self.step_window_spin.setValue(10.0)
        self.step_window_spin.setSuffix(" ns")
        optimization_layout.addWidget(self.step_window_spin, 0, 5)

        # Optimize button
        self.optimize_btn = QPushButton("Optimize Window")
        self.optimize_btn.clicked.connect(self.start_window_optimization)
        optimization_layout.addWidget(self.optimize_btn, 1, 0, 1, 2)

        # Progress bar
        self.optimization_progress = QProgressBar()
        optimization_layout.addWidget(self.optimization_progress, 1, 2, 1, 4)

        optimization_group.setLayout(optimization_layout)
        layout.addWidget(optimization_group)

        # Results display in tabbed format
        results_tabs = QTabWidget()

        # Optimization results tab
        opt_results_tab = QWidget()
        opt_results_layout = QVBoxLayout(opt_results_tab)

        self.optimization_plot = pg.PlotWidget()
        self.optimization_plot.setLabel("left", "Efficiency (%)")
        self.optimization_plot.setLabel("bottom", "Window Size (ns)")
        self.optimization_plot.setTitle("Window Optimization Results")
        self.optimization_plot.showGrid(True, True, alpha=0.3)
        self.optimization_plot.setBackground("w")
        opt_results_layout.addWidget(self.optimization_plot)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels(
            [
                "Window (ns)",
                "Coincidences",
                "Efficiency (%)",
                "Mean Δt (ns)",
                "Std Δt (ns)",
            ]
        )
        self.results_table.setMaximumHeight(150)
        opt_results_layout.addWidget(self.results_table)

        results_tabs.addTab(opt_results_tab, "Optimization Results")

        # Timing analysis tab
        timing_tab = QWidget()
        timing_layout = QVBoxLayout(timing_tab)

        self.timing_plot = pg.PlotWidget()
        self.timing_plot.setLabel("left", "Counts")
        self.timing_plot.setLabel("bottom", "Time Difference (ns)")
        self.timing_plot.setTitle("Coincidence Timing Distribution")
        self.timing_plot.showGrid(True, True, alpha=0.3)
        self.timing_plot.setBackground("w")
        timing_layout.addWidget(self.timing_plot)

        self.timing_stats_text = QTextEdit()
        self.timing_stats_text.setMaximumHeight(100)
        self.timing_stats_text.setReadOnly(True)
        timing_layout.addWidget(self.timing_stats_text)

        results_tabs.addTab(timing_tab, "Timing Analysis")

        layout.addWidget(results_tabs)

        # Status and control buttons
        control_layout = QHBoxLayout()
        self.optimization_status = QLabel("Ready to optimize")
        control_layout.addWidget(self.optimization_status)

        control_layout.addStretch()

        self.save_settings_btn = QPushButton("Save Settings")
        self.save_settings_btn.clicked.connect(self.save_coincidence_settings)
        control_layout.addWidget(self.save_settings_btn)

        self.export_timing_btn = QPushButton("Export Timing Data")
        self.export_timing_btn.clicked.connect(self.export_timing_data)
        control_layout.addWidget(self.export_timing_btn)

        layout.addLayout(control_layout)

        return tab

    # ==================== Raw Traces Tab Methods ====================

    def toggle_simple_coincidence(self, enabled):
        self.coincidence_mode = enabled
        if enabled:
            self.raw_plot_widget.setTitle("PIXIE-16 Raw Traces - Coincidence Mode")
        else:
            self.raw_plot_widget.setTitle("PIXIE-16 Raw Traces")

    def update_max_traces(self):
        self.max_traces_display = self.max_traces_spin.value()

    def update_threshold(self):
        self.amplitude_threshold = self.threshold_spin.value()

    def toggle_auto_scale(self, enabled):
        self.auto_scale = enabled

    # Hardware validation
    def update_selected_channel(self):
        self.selected_channel = self.channels[self.channel_combo.currentIndex()]
        self.channel_plot.setTitle(f"Channel {self.selected_channel} Validation")

    def update_ft_backplane_delay(self, value):
        self.ft_backplane_delay_label.setText(str(value))

        if not self.hardware_manager:
            return
        if self.hardware_manager.dummy_mode:
            print(f"DUMMY MODE: FastTrigBackplaneEna = {value}")
            return

        try:
            px.control.set_module_parameter("FastTrigBackplaneEna", value, 0)
            print(f"HARDWARE: Applied FastTrigBackplaneEna = {value}")
        except Exception as e:
            print(f"Hardware Error: {e}")

    def update_ft_backplane_length(self, value):
        self.ft_backplane_length_label.setText(str(value))

        if not self.hardware_manager:
            return
        if self.hardware_manager.dummy_mode:
            print(f"DUMMY MODE: FASTTRIGBACKLEN = {value}")
            return

        try:
            for channel in [self.selected_channel_a, self.selected_channel_b]:
                px.control.set_channel_parameter("FASTTRIGBACKLEN", value, 0, channel)
            print(f"HARDWARE: Applied FASTTRIGBACKLEN = {value}")
        except Exception as e:
            print(f"Hardware Error: {e}")

    def update_channel_trigger_stretch(self, value):
        self.channel_trigger_stretch_label.setText(str(value))

        if not self.hardware_manager:
            return
        if self.hardware_manager.dummy_mode:
            print(f"DUMMY MODE: ChanTrigStretch = {value}")
            return

        try:
            for channel in [self.selected_channel_a, self.selected_channel_b]:
                px.control.set_channel_parameter("ChanTrigStretch", value, 0, channel)
            print(f"HARDWARE: Applied ChanTrigStretch = {value}")
        except Exception as e:
            print(f"Hardware Error: {e}")

    def update_external_delay_length(self, value):
        self.external_delay_length_label.setText(str(value))

        if not self.hardware_manager:
            return
        if self.hardware_manager.dummy_mode:
            print(f"DUMMY MODE: ExternDelayLen = {value}")
            return

        try:
            for channel in [self.selected_channel_a, self.selected_channel_b]:
                px.control.set_channel_parameter("ExternDelayLen", value, 0, channel)
            print(f"HARDWARE: Applied ExternDelayLen = {value}")
        except Exception as e:
            print(f"Hardware Error: {e}")

    def toggle_trace_type(self, trace_type):
        checkbox_map = {
            "raw": self.raw_traces_cb,
            "fast_trigger": self.fast_trigger_cb,
            "energy_filter": self.energy_filter_cb,
            "cfd": self.cfd_cb,
        }

        if trace_type in checkbox_map:
            self.trace_types[trace_type] = checkbox_map[trace_type].isChecked()

    def apply_hardware_parameters(self):
        if not self.hardware_manager:
            QMessageBox.warning(self, "No Hardware", "No hardware manager available")
            return

        if self.hardware_manager.dummy_mode:
            params_summary = [
                f"FastTrigBackplaneEna: {self.ft_backplane_delay_slider.value()}",  # MODULE
                f"FASTTRIGBACKLEN: {self.ft_backplane_length_slider.value()}",  # CHANNEL
                f"ChanTrigStretch: {self.channel_trigger_stretch_slider.value()}",  # CHANNEL
                f"ExternDelayLen: {self.external_delay_length_slider.value()}",  # CHANNEL
                f"Channels: {[self.selected_channel_a, self.selected_channel_b]}",
            ]

            print("DUMMY MODE: Would apply parameters:")
            for param in params_summary:
                print(f"  {param}")

            QMessageBox.information(
                self,
                "Dummy Mode",
                f"DUMMY MODE: Would apply parameters:\n" + "\n".join(params_summary),
            )
            return

        try:
            success_count = 0
            failed_params = []
            selected_channels = [self.selected_channel_a, self.selected_channel_b]

            # Module-level parameter
            try:
                px.control.set_module_parameter(
                    "FastTrigBackplaneEna", self.ft_backplane_delay_slider.value(), 0
                )
                success_count += 1
                print(
                    f"Applied FastTrigBackplaneEna = {self.ft_backplane_delay_slider.value()}"
                )
            except Exception as e:
                failed_params.append(f"FastTrigBackplaneEna: {e}")
                print(f"Failed FastTrigBackplaneEna: {e}")

            # Channel-level parameters
            channel_params = {
                "FASTTRIGBACKLEN": self.ft_backplane_length_slider.value(),
                "ChanTrigStretch": self.channel_trigger_stretch_slider.value(),
                "ExternDelayLen": self.external_delay_length_slider.value(),
            }

            for param_name, value in channel_params.items():
                param_applied = False
                for channel in selected_channels:
                    try:
                        px.control.set_channel_parameter(param_name, value, 0, channel)
                        if not param_applied:  # Only count once per parameter
                            success_count += 1
                            param_applied = True
                        print(f"Applied {param_name} = {value} to Ch{channel}")
                    except Exception as e:
                        failed_params.append(f"{param_name} Ch{channel}: {e}")
                        print(f"Failed {param_name} Ch{channel}: {e}")

            try:
                if hasattr(self.hardware_manager, "stop_acquisition"):
                    self.hardware_manager.stop_acquisition()
                time.sleep(0.2)
                if hasattr(self.hardware_manager, "start_acquisition_mode"):
                    self.hardware_manager.start_acquisition_mode("traces")
                print("PIXIE data acquisition restarted")
            except Exception as e:
                print(f"Warning: Could not restart acquisition: {e}")

            # Report results
            if success_count > 0 and not failed_params:
                QMessageBox.information(
                    self,
                    "Parameters Applied",
                    f"HARDWARE: Successfully applied {success_count} parameter updates\nData acquisition restarted",
                )
            elif failed_params:
                QMessageBox.warning(
                    self,
                    "Partial Failure",
                    f"Applied {success_count} parameters successfully.\nSome parameters failed:\n"
                    + "\n".join(failed_params),
                )
            else:
                QMessageBox.warning(
                    self, "Application Failed", "No parameters applied successfully"
                )

        except Exception as e:
            print(f"Critical error in apply_hardware_parameters: {e}")
            QMessageBox.critical(
                self, "Critical Error", f"Hardware system error: {str(e)}"
            )

    def update_center_channel(self):
        self.center_channel = self.channels[self.center_channel_combo.currentIndex()]

    def update_coincidence_window(self):
        self.coincidence_window_ns = self.time_window_spin.value()

    def set_quick_window(self, window_text):
        window_ns = float(window_text.replace("ns", ""))
        self.time_window_spin.setValue(window_ns)
        self.update_coincidence_window()

    def toggle_validation_mode(self, enabled):
        self.validation_window_optimization = enabled

    def start_window_optimization(self):
        if not self.coincidence_events:
            QMessageBox.warning(
                self, "No Data", "No coincidence events available for optimization."
            )
            return

        if self.optimization_active:
            QMessageBox.warning(
                self, "Already Running", "Optimization already in progress."
            )
            return

        # Get optimization parameters
        min_window = self.min_window_spin.value()
        max_window = self.max_window_spin.value()
        step = self.step_window_spin.value()

        if min_window >= max_window:
            QMessageBox.warning(
                self,
                "Invalid Range",
                "Minimum window must be less than maximum window.",
            )
            return

        # Start optimization worker
        self.optimization_active = True
        self.optimize_btn.setEnabled(False)

        self.optimization_worker = WindowOptimizationWorker(
            list(self.coincidence_events),
            (min_window, max_window, step),
            self.center_channel,
        )

        self.optimization_worker.progress.connect(self.optimization_progress.setValue)
        self.optimization_worker.status.connect(self.optimization_status.setText)
        self.optimization_worker.result.connect(self.handle_optimization_results)
        self.optimization_worker.finished.connect(self.optimization_finished)

        self.optimization_worker.start()

    def handle_optimization_results(self, results):
        self.optimization_results = results

        # Plot results
        windows = list(results.keys())
        coincidences = [results[w]["coincidences"] for w in windows]
        efficiencies = [results[w]["efficiency"] * 100 for w in windows]

        self.optimization_plot.clear()
        self.optimization_plot.plot(
            windows, efficiencies, pen="b", symbol="o", name="Efficiency"
        )

        # Find optimal window (maximum efficiency with reasonable count)
        max_efficiency = max(efficiencies)
        optimal_windows = [
            w
            for w in windows
            if results[w]["efficiency"] * 100 >= max_efficiency * 0.95
        ]
        self.optimal_window_ns = min(optimal_windows)

        # Update results table
        self.update_results_table(results)

        # Update status
        self.optimization_status.setText(
            f"Optimal window: {self.optimal_window_ns:.1f}ns "
            f"(efficiency: {results[self.optimal_window_ns]['efficiency'] * 100:.1f}%)"
        )

    def update_results_table(self, results):
        self.results_table.setRowCount(len(results))

        for i, (window, data) in enumerate(results.items()):
            self.results_table.setItem(i, 0, QTableWidgetItem(f"{window:.1f}"))
            self.results_table.setItem(
                i, 1, QTableWidgetItem(str(data["coincidences"]))
            )
            self.results_table.setItem(
                i, 2, QTableWidgetItem(f"{data['efficiency'] * 100:.1f}")
            )
            self.results_table.setItem(i, 3, QTableWidgetItem(f"{data['mean_dt']:.1f}"))
            self.results_table.setItem(i, 4, QTableWidgetItem(f"{data['std_dt']:.1f}"))

    def optimization_finished(self):
        self.optimization_active = False
        self.optimize_btn.setEnabled(True)

        # Ask user if they want to apply optimal window
        if self.optimization_results:
            reply = QMessageBox.question(
                self,
                "Apply Optimal Window?",
                f"Apply optimal window of {self.optimal_window_ns:.1f}ns?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.time_window_spin.setValue(self.optimal_window_ns)
                self.update_coincidence_window()

    def save_coincidence_settings(self):
        settings = {
            "center_channel": self.center_channel,
            "coincidence_window_ns": self.coincidence_window_ns,
            "optimal_window_ns": self.optimal_window_ns,
            "optimization_results": self.optimization_results,
            "timestamp": time.time(),
        }

        settings_file = Path("coincidence_settings.json")
        try:
            with open(settings_file, "w") as f:
                json.dump(settings, f, indent=2)
            QMessageBox.information(
                self, "Settings Saved", f"Coincidence settings saved to {settings_file}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Failed to save settings: {e}")

    def export_timing_data(self):
        if not self.coincidence_events:
            QMessageBox.warning(
                self, "No Data", "No coincidence timing data to export."
            )
            return

        # Collect all timing data
        export_data = []
        for i, coinc_event in enumerate(self.coincidence_events):
            center_timestamp = coinc_event.center_event.timestamp
            center_channel = coinc_event.center_event.channel
            center_energy = getattr(coinc_event.center_event, "energy", 0)

            for j, (event, time_diff) in enumerate(
                zip(coinc_event.associated_events, coinc_event.time_differences)
            ):
                export_data.append(
                    {
                        "coincidence_id": i,
                        "center_channel": center_channel,
                        "center_timestamp": center_timestamp,
                        "center_energy": center_energy,
                        "associated_channel": event[0].channel,
                        "associated_timestamp": event[0].timestamp,
                        "associated_energy": getattr(event[0], "energy", 0),
                        "time_difference_ns": time_diff,
                        "abs_time_difference_ns": abs(time_diff),
                    }
                )

        # Write to CSV
        try:
            filename = f"timing_data_{int(time.time())}.csv"

            with open(filename, "w", newline="") as csvfile:
                if export_data:
                    fieldnames = export_data[0].keys()
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(export_data)

            QMessageBox.information(
                self, "Export Complete", f"Timing data exported to {filename}"
            )

        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Failed to export data: {e}")

    def add_event_with_trace(self, event, trace_data):
        # Extract timestamp from event
        event_timestamp = getattr(event, "timestamp", None)

        if not self.coincidence_mode:
            self.add_trace(event.channel, trace_data, event_timestamp)
            return

        self.event_buffer.append((event, trace_data))

        # If this is a center channel event, look for coincidences
        if event.channel == self.center_channel:
            self._find_and_store_coincidence(event, trace_data)

    def _find_and_store_coincidence(self, center_event, center_trace):
        coincident_events_with_traces = []

        # Look through recent events for coincidences
        for buffered_event, buffered_trace in self.event_buffer:
            if buffered_event == center_event:
                continue  # Skip the center event itself

            # Calculate time difference using timestamp format
            time_diff_ns = abs(
                self._calculate_pixie_time_difference(
                    buffered_event.timestamp, center_event.timestamp
                )
            )

            # Check if within coincidence window
            if time_diff_ns <= self.coincidence_window_ns:
                coincident_events_with_traces.append((buffered_event, buffered_trace))

        # Create and store coincidence event
        if coincident_events_with_traces:  # Only store if there are coincidences
            coinc_event = CoincidenceEvent(
                center_event, center_trace, coincident_events_with_traces
            )
            self.coincidence_events.append(coinc_event)

            # Add traces to display (center + coincident)
            self.add_trace(center_event.channel, center_trace)
            for event, trace in coincident_events_with_traces:
                self.add_trace(event.channel, trace)

            # Update timing analysis
            self.update_timing_analysis()

    def _calculate_pixie_time_difference(self, timestamp1, timestamp2):
        dt_ticks = timestamp1 - timestamp2
        dt_ns = dt_ticks * 10.0  # ns
        return dt_ns

    def update_timing_analysis(self):
        if not self.coincidence_events:
            return

        all_time_diffs = []
        for coinc_event in self.coincidence_events:
            all_time_diffs.extend(coinc_event.time_differences)

        if not all_time_diffs:
            return

        # Create histogram
        hist, bins = np.histogram(all_time_diffs, bins=100)
        self.timing_plot.clear()
        self.timing_plot.plot(
            bins[:-1], hist, stepMode=True, fillLevel=0, brush=(0, 0, 255, 80)
        )

        # Update statistics
        mean_dt = np.mean(all_time_diffs)
        std_dt = np.std(all_time_diffs)
        min_dt = np.min(all_time_diffs)
        max_dt = np.max(all_time_diffs)

        stats_text = f"""
            Timing Statistics:
            Total Coincidences: {len(self.coincidence_events)}
            Total Time Differences: {len(all_time_diffs)}
            Mean Δt: {mean_dt:.2f} ns
            Std Δt: {std_dt:.2f} ns
            Min Δt: {min_dt:.2f} ns
            Max Δt: {max_dt:.2f} ns

            Current Window: ±{self.coincidence_window_ns:.1f} ns
            Center Channel: {self.center_channel}
        """

        self.timing_stats_text.setPlainText(stats_text)

    def add_trace(self, channel, trace_data, event_timestamp=None):
        try:
            if channel not in self.channels:
                return

            if not isinstance(trace_data, np.ndarray):
                trace_data = np.array(trace_data)

            if len(trace_data) == 0:
                return

            # Store timestamp for alignment
            if event_timestamp is not None:
                self.trace_timestamps[channel].append(event_timestamp)

            # Apply amplitude threshold filter
            if len(trace_data) > 10:
                amplitude = np.max(trace_data) - np.min(trace_data)
                if amplitude >= self.amplitude_threshold:
                    # Store in original buffer
                    self.trace_data[channel].append(trace_data)

                    # Store in replay buffer
                    if (
                        hasattr(self, "replay_widget")
                        and self.replay_widget is not None
                        and not self.replay_mode
                    ):
                        self.replay_widget.add_trace(trace_data, channel, amplitude)
            else:
                # Store in original buffer
                self.trace_data[channel].append(trace_data)

                # Store in replay buffer
                if (
                    hasattr(self, "replay_widget")
                    and self.replay_widget is not None
                    and not self.replay_mode
                ):
                    self.replay_widget.add_trace(trace_data, channel, 0)

        except Exception as e:
            print(f"Error adding trace to channel {channel}: {e}")

    def calculate_real_time_axis(self, trace_length, channel):
        if not self.use_realtime_axis:
            return np.arange(trace_length)

        trace_delay = self.trace_delay_ns.get(channel, 200)
        sampling_period_ns = 2.0  # For 500 MHz module
        sample_times = np.arange(trace_length) * sampling_period_ns
        real_times = sample_times - trace_delay

        return real_times

    def update_plots(self):
        try:
            self.update_raw_traces_plot()
            self.update_hardware_validation_plots()

        except Exception as e:
            print(f"Error updating plots: {e}")

    def update_raw_traces_plot(self):
        try:
            if self.replay_mode:
                return

            total_traces = 0

            # Process all channels for raw traces display
            for channel in self.channels:
                has_data = (
                    channel in self.trace_data and len(self.trace_data[channel]) > 0
                )

                if not has_data or channel not in self.display_channels:
                    self.raw_curves[channel].setData([], [])
                    continue

                traces = list(self.trace_data[channel])
                timestamps = (
                    list(self.trace_timestamps[channel])
                    if channel in self.trace_timestamps
                    else [None] * len(traces)
                )
                total_traces += len(traces)
                display_traces = traces[-self.max_traces_display :]
                display_timestamps = (
                    timestamps[-self.max_traces_display :]
                    if timestamps
                    else [None] * len(display_traces)
                )

                if display_traces:
                    trace_length = len(display_traces[0])

                    combined_y = []
                    combined_x = []

                    for i, (trace, timestamp) in enumerate(
                        zip(display_traces, display_timestamps)
                    ):
                        if len(trace) == trace_length:
                            # Calculate time axis with alignment
                            time_axis = self.calculate_aligned_time_axis(
                                trace_length, channel, timestamp
                            )

                            y_data = trace

                            combined_x.extend(time_axis)
                            combined_x.append(np.nan)
                            combined_y.extend(y_data)
                            combined_y.append(np.nan)

                    if combined_x and combined_y:
                        self.raw_curves[channel].setData(combined_x, combined_y)

            # Update statistics
            stats_text = f"Total Traces: {total_traces} | "
            if self.coincidence_mode:
                stats_text += f"Coincidences: {len(self.coincidence_events)} | "
            stats_text += f"Displayed Channels: {len(self.display_channels)} | "
            stats_text += f"Alignment: {self.time_alignment_mode}"
            if self.time_alignment_mode == "channel_aligned":
                stats_text += f" (Ref: Ch{self.alignment_reference_channel})"

            self.raw_stats_label.setText(stats_text)

            if self.auto_scale and total_traces > 0:
                self.raw_plot_widget.autoRange()

        except Exception as e:
            print(f"Error updating raw traces plot: {e}")

    def update_hardware_validation_plots(self):
        try:
            # Update single channel plot
            self.update_channel_validation_plot(
                self.selected_channel,
                self.channel_plot,
                self.hw_curves,
                f"Channel {self.selected_channel}",
            )

        except Exception as e:
            print(f"Error updating hardware validation plots: {e}")

    def update_channel_validation_plot(self, channel, plot_widget, curves, label):
        try:
            # Clear trigger points for this channel before computing new ones
            if channel not in self.trigger_points:
                self.trigger_points[channel] = {}
            else:
                self.trigger_points[channel] = {}

            if channel not in self.peak_sample_points:
                self.peak_sample_points[channel] = {}
            else:
                self.peak_sample_points[channel] = {}

            if channel not in self.trace_data or len(self.trace_data[channel]) == 0:
                for trace_type, curve in curves.items():
                    curve.setData([], [])
                return

            # Get latest trace with safety checks
            traces_list = list(self.trace_data[channel])
            if not traces_list:
                for trace_type, curve in curves.items():
                    curve.setData([], [])
                return

            latest_trace = traces_list[-1]
            if latest_trace is None or len(latest_trace) == 0:
                print(f"DEBUG: Empty or None trace for channel {channel}")
                for trace_type, curve in curves.items():
                    curve.setData([], [])
                return

            time_axis = self.calculate_real_time_axis(len(latest_trace), channel)

            try:
                main_trigger_points = self.calculate_main_trigger_point(
                    latest_trace, channel
                )
                if main_trigger_points:
                    self._store_trigger_info(
                        channel, main_trigger_points, "main_trigger"
                    )
                else:
                    # Store empty list so we know we tried
                    self._store_trigger_info(channel, [], "main_trigger")
            except Exception as e:
                print(f"Error calculating main trigger for channel {channel}: {e}")
                self._store_trigger_info(channel, [], "main_trigger")

            # Clear plot
            plot_widget.clear()

            # Plot enabled traces with proper scaling
            plotted_traces = {}

            for trace_type, enabled in self.trace_types.items():
                if not enabled:
                    continue

                try:
                    if trace_type == "raw":
                        signal = latest_trace
                        color = "#1f77b4"  # Blue
                        name = "Raw Trace"

                    else:
                        signal = self.compute_hardware_traces(
                            trace_type, latest_trace, channel
                        )
                        if signal is None or len(signal) == 0:
                            print(
                                f"DEBUG: No {trace_type} signal for channel {channel}"
                            )
                            continue

                        trace_colors = {
                            "fast_trigger": "#ff7f0e",  # Orange
                            "energy_filter": "#2ca02c",  # Green
                            "cfd": "#d62728",  # Red
                        }
                        color = trace_colors.get(trace_type, "#333333")
                        name = trace_type.replace("_", " ").title()

                        # Apply amplitude scaling for visibility
                        if trace_type == "fast_trigger":
                            raw_amplitude = np.max(latest_trace) - np.min(latest_trace)
                            if np.max(signal) > 0:
                                scale_factor = raw_amplitude / (3 * np.max(signal))
                                signal = signal * scale_factor

                        elif trace_type == "cfd":
                            baseline = np.mean(latest_trace[:100])
                            signal = signal + baseline

                        elif trace_type == "energy_filter":
                            raw_amplitude = np.max(latest_trace) - np.min(latest_trace)
                            if np.max(signal) > np.min(signal):
                                signal_amplitude = np.max(signal) - np.min(signal)
                                scale_factor = (2 * raw_amplitude) / signal_amplitude
                                signal = (
                                    signal - np.min(signal)
                                ) * scale_factor + np.min(latest_trace)

                    # Plot the trace
                    plotted_traces[trace_type] = plot_widget.plot(
                        time_axis, signal, pen=pg.mkPen(color=color, width=2), name=name
                    )

                except Exception as e:
                    print(f"Error plotting {trace_type} for channel {channel}: {e}")

            try:
                self._add_trigger_markers(plot_widget, channel, time_axis)
            except Exception as e:
                print(f"Error adding trigger markers for channel {channel}: {e}")

            try:
                self._add_threshold_lines(plot_widget, latest_trace)
            except Exception as e:
                print(f"Error adding threshold lines for channel {channel}: {e}")

            plot_widget.setTitle(f"{label} - Ch {channel}")

            try:
                plot_widget.addLegend()
            except Exception as e:
                print(f"Error adding legend for channel {channel}: {e}")

        except Exception as e:
            print(f"CRITICAL ERROR updating {label} plot for channel {channel}: {e}")
            try:
                plot_widget.clear()
                plot_widget.setTitle(f"{label} - Ch {channel} (ERROR)")
            except:
                pass

    def _add_threshold_lines(self, plot_widget, raw_trace):
        try:
            if raw_trace is None or len(raw_trace) == 0:
                print("DEBUG: Cannot add threshold lines - no trace data")
                return

            raw_trace = np.asarray(raw_trace)

            # Get baseline from first 20% of trace (consistent with leading edge calculation)
            baseline_samples = max(20, int(len(raw_trace) * 0.2))
            baseline_samples = min(baseline_samples, len(raw_trace) // 3)

            if baseline_samples >= len(raw_trace):
                baseline_samples = min(10, len(raw_trace) - 1)

            baseline = np.mean(raw_trace[:baseline_samples])
            baseline_noise = np.std(raw_trace[:baseline_samples])

            # Leading edge threshold line (green dotted line) - matches main trigger calculation
            leading_edge_threshold = baseline + (3.0 * baseline_noise)
            leading_edge_line = pg.InfiniteLine(
                pos=leading_edge_threshold,
                angle=0,
                pen=pg.mkPen(
                    color="darkgreen", style=pg.QtCore.Qt.PenStyle.DotLine, width=2
                ),
            )
            plot_widget.addItem(leading_edge_line)

            # Fast trigger threshold (orange dashed line)
            fast_threshold = self.hardware_params["fast_threshold"]
            fast_threshold_line = pg.InfiniteLine(
                pos=baseline + fast_threshold,
                angle=0,
                pen=pg.mkPen(
                    color="orange", style=pg.QtCore.Qt.PenStyle.DashLine, width=2
                ),
            )
            plot_widget.addItem(fast_threshold_line)

            # CFD threshold (red dashed line)
            cfd_threshold = self.hardware_params["cfd_threshold"]
            cfd_threshold_line = pg.InfiniteLine(
                pos=baseline + cfd_threshold,
                angle=0,
                pen=pg.mkPen(
                    color="red", style=pg.QtCore.Qt.PenStyle.DashDotLine, width=2
                ),
            )
            plot_widget.addItem(cfd_threshold_line)

            print(
                f"DEBUG: Added threshold lines - Leading Edge: {leading_edge_threshold:.1f}, "
                f"Fast: {baseline + fast_threshold:.1f}, CFD: {baseline + cfd_threshold:.1f}"
            )

        except Exception as e:
            print(f"Error adding threshold lines: {e}")

    def compute_hardware_traces(self, trace_type, raw_trace, channel):
        if self.hardware_manager and self.hardware_manager.dummy_mode:
            return self.fallback_simulation(trace_type, raw_trace)

        try:
            raw_trace = np.asarray(raw_trace, dtype=np.uint16)
            original_length = len(raw_trace)

            if trace_type == "fast_trigger":
                # Use the analyze.py functions
                fast_result = calculate_filter(
                    raw_trace[np.newaxis, :],
                    L=self.hardware_params["fast_L"]
                    * 0.01,  # Convert FPGA units to microseconds
                    G=self.hardware_params["fast_G"] * 0.01,
                    filter_range=0,
                )

                fast_trigger = fast_result[0]

                # Find trigger points using analyze.py function
                trigger_indices = get_fast_trigger_index(
                    fast_trigger[np.newaxis, :], self.hardware_params["fast_threshold"]
                )

                # Convert trigger indices to raw sample indices
                raw_trigger_indices = []
                if len(trigger_indices) > 0 and len(trigger_indices[0]) > 0:
                    for fpga_idx in trigger_indices[0]:
                        # Convert FPGA index back to raw sample index
                        raw_idx = fpga_idx * 5  # 5 raw samples per FPGA sample
                        if 0 <= raw_idx < original_length:
                            raw_trigger_indices.append(raw_idx)

                # Store trigger points
                self._store_trigger_info(
                    channel, raw_trigger_indices, "fast_trigger", clear_existing=True
                )

                return self._resize_trace_to_match(
                    fast_trigger, original_length, "fast_trigger"
                )

            elif trace_type == "cfd":
                cfd_result = calculate_CFD(
                    raw_trace[np.newaxis, :],
                    CFD_threshold=self.hardware_params["cfd_threshold"],
                    FF_threshold=self.hardware_params["fast_threshold"],
                    Lf=self.hardware_params["fast_L"] * 0.01,
                    Gf=self.hardware_params["fast_G"] * 0.01,
                    w=1,
                    B=5,
                    D=5,
                    L=1,
                )

                cfd_traces, cfd_times, fast_filter, error_indices = cfd_result

                if len(error_indices) == 0 and cfd_traces is not None:
                    cfd_trace = cfd_traces[0]

                    # Store CFD zero crossing points
                    cfd_trigger_points = []
                    if (
                        cfd_times is not None
                        and len(cfd_times) > 0
                        and cfd_times[0] is not None
                    ):
                        cfd_sample_index = int(cfd_times[0] / 2.0)
                        if 0 <= cfd_sample_index < original_length:
                            cfd_trigger_points = [cfd_sample_index]

                    self._store_trigger_info(channel, cfd_trigger_points, "cfd")

                    return self._resize_trace_to_match(
                        cfd_trace, original_length, "cfd"
                    )
                else:
                    print(f"CFD calculation failed for channel {channel}")
                    return np.zeros(original_length)

            elif trace_type == "energy_filter":
                # Energy filter - use hardware algorithm
                traces_fpga = convert_trace_to_FPGA(raw_trace[np.newaxis, :])

                fast_result = compute_fast_trigger_validation(
                    traces_fpga,
                    L=self.hardware_params["fast_L"],
                    G=self.hardware_params["fast_G"],
                    threshold=self.hardware_params["fast_threshold"],
                )

                if fast_result["validation_passed"]:
                    energy_result = compute_energy_filter(
                        traces_fpga,
                        R=self.hardware_params["energy_R"],
                        L=self.hardware_params["energy_L"],
                        G=self.hardware_params["energy_G"],
                        P=self.hardware_params["energy_P"],
                        decay_ns=self.hardware_params["decay_ns"],
                        trigger_indices=fast_result["trigger_indices"],
                        baseline_index=fast_result["baseline_stats"]["baseline_index"],
                    )

                    if energy_result["energy_traces"]:
                        energy_trace = energy_result["energy_traces"][0]["result"]
                        trigger_pos = energy_result["energy_traces"][0]["trigger_pos"]

                        slow_filter_range = 2 ** self.hardware_params["energy_R"]
                        samples_per_energy_cycle = slow_filter_range * 5

                        # Expand energy trace to raw sample timing
                        energy_expanded = np.repeat(
                            energy_trace, samples_per_energy_cycle
                        )

                        # Calculate proper trigger alignment
                        fast_trigger_indices = fast_result["trigger_indices"]
                        if (
                            len(fast_trigger_indices) > 0
                            and len(fast_trigger_indices[0]) > 0
                        ):
                            # Fast trigger position in raw samples
                            fast_trigger_raw_pos = fast_trigger_indices[0][0] * 5

                            # Energy trigger position in raw samples
                            if trigger_pos is not None:
                                energy_trigger_raw_pos = (
                                    trigger_pos * samples_per_energy_cycle
                                )
                                alignment_offset = (
                                    fast_trigger_raw_pos - energy_trigger_raw_pos
                                )

                                # Apply alignment
                                if alignment_offset > 0:
                                    energy_aligned = np.concatenate(
                                        [
                                            np.zeros(int(alignment_offset)),
                                            energy_expanded,
                                        ]
                                    )
                                elif alignment_offset < 0:
                                    trim_amount = int(-alignment_offset)
                                    energy_aligned = (
                                        energy_expanded[trim_amount:]
                                        if trim_amount < len(energy_expanded)
                                        else energy_expanded
                                    )
                                else:
                                    energy_aligned = energy_expanded

                                # Calculate trigger and peak sample points in raw sample coordinates
                                energy_trigger_points = [
                                    fast_trigger_raw_pos
                                ]  # Use fast trigger position

                                # Peak sample is P energy cycles after the energy trigger
                                peak_sample_raw_pos = fast_trigger_raw_pos + (
                                    self.hardware_params["energy_P"]
                                    * samples_per_energy_cycle
                                )
                                peak_sample_points = (
                                    [peak_sample_raw_pos]
                                    if peak_sample_raw_pos < original_length
                                    else []
                                )

                            else:
                                energy_aligned = energy_expanded
                                energy_trigger_points = []
                                peak_sample_points = []
                        else:
                            energy_aligned = energy_expanded
                            energy_trigger_points = []
                            peak_sample_points = []

                        # Store trigger and peak sample info
                        self._store_trigger_info(
                            channel,
                            energy_trigger_points,
                            "energy_filter",
                            peak_sample_points,
                        )

                        # Resize to match original length
                        energy_resized = self._resize_trace_to_match(
                            energy_aligned, original_length, "energy_filter"
                        )

                        return energy_resized

                print(f"Energy filter calculation failed for channel {channel}")
                return np.zeros(original_length)

            print(f"Unknown trace type: {trace_type}")
            return np.zeros(original_length)

        except Exception as e:
            print(f"Hardware computation error for {trace_type}: {e}")
            return np.zeros(original_length)

    def _store_trigger_info(
        self,
        channel,
        trigger_indices,
        trace_type,
        peak_samples=None,
        clear_existing=False,
    ):
        if channel not in self.trigger_points:
            self.trigger_points[channel] = {}
        if channel not in self.peak_sample_points:
            self.peak_sample_points[channel] = {}

        # Clear existing trigger points for this trace type if requested
        if clear_existing:
            self.trigger_points[channel] = {}
            self.peak_sample_points[channel] = {}

        self.trigger_points[channel][trace_type] = trigger_indices

        # Debug output
        print(
            f"DEBUG: Stored {len(trigger_indices)} {trace_type} trigger points for channel {channel}: {trigger_indices}"
        )

        if trace_type == "energy_filter" and peak_samples:
            self.peak_sample_points[channel][trace_type] = peak_samples
            print(
                f"DEBUG: Stored {len(peak_samples)} peak sample points: {peak_samples}"
            )

    def _resize_trace_to_match(
        self, processed_trace, original_length, trace_type="unknown"
    ):
        if processed_trace is None:
            return np.zeros(original_length)

        processed_trace = np.asarray(processed_trace)
        current_length = len(processed_trace)

        if current_length == original_length:
            return processed_trace

        elif current_length < original_length:
            # Pad with zeros at the end to preserve timing alignment
            # The traces start at the correct time, just need to extend length
            pad_length = original_length - current_length
            return np.concatenate([processed_trace, np.zeros(pad_length)])

        else:
            # Truncate from the end to preserve timing alignment
            # The traces start at the correct time, just need to shorten length
            return processed_trace[:original_length]

    def _add_trigger_markers(self, plot_widget, channel, time_axis):
        if channel not in self.trigger_points:
            print(f"DEBUG: No trigger points stored for channel {channel}")
            return

        trigger_info = self.trigger_points[channel]
        print(f"DEBUG: Trigger info for channel {channel}: {trigger_info}")

        # Get the latest trace to read signal values
        if channel not in self.trace_data or len(self.trace_data[channel]) == 0:
            print(f"DEBUG: No trace data for channel {channel}")
            return

        traces_list = list(self.trace_data[channel])
        if not traces_list:
            print(f"DEBUG: Empty trace list for channel {channel}")
            return

        latest_trace = traces_list[-1]
        if latest_trace is None or len(latest_trace) == 0:
            print(f"DEBUG: Invalid latest trace for channel {channel}")
            return

        if len(time_axis) != len(latest_trace):
            print(
                f"WARNING: Time axis length ({len(time_axis)}) != trace length ({len(latest_trace)}) for channel {channel}"
            )
            # Recreate time axis to match trace length
            time_axis = self.calculate_real_time_axis(len(latest_trace), channel)

        # Add main trigger point first
        if "main_trigger" in trigger_info and trigger_info["main_trigger"]:
            main_trigger_points = trigger_info["main_trigger"]
            for trigger_idx in main_trigger_points:
                if 0 <= trigger_idx < len(time_axis) and 0 <= trigger_idx < len(
                    latest_trace
                ):
                    trigger_time = time_axis[trigger_idx]
                    trigger_amplitude = latest_trace[trigger_idx]
                    plot_widget.plot(
                        [trigger_time],
                        [trigger_amplitude],
                        pen=None,
                        symbol="^",  # Triangle up for leading edge trigger
                        symbolBrush="darkgreen",
                        symbolPen=pg.mkPen(color="black", width=2),
                        symbolSize=10,
                        name="Leading Edge Trigger",
                    )

        # Add other trigger markers
        for trace_type, trigger_indices in trigger_info.items():
            if not trigger_indices or trace_type == "main_trigger":
                continue

            print(f"DEBUG: Adding {len(trigger_indices)} {trace_type} markers")

            # Get the signal data for this trace type
            if trace_type == "raw":
                signal_data = latest_trace
            else:
                signal_data = self.compute_hardware_traces(
                    trace_type, latest_trace, channel
                )
                if signal_data is None or len(signal_data) == 0:
                    continue

                # Apply the same scaling that was used in the plot
                if trace_type == "fast_trigger":
                    raw_amplitude = np.max(latest_trace) - np.min(latest_trace)
                    if np.max(signal_data) > 0:
                        scale_factor = raw_amplitude / (3 * np.max(signal_data))
                        signal_data = signal_data * scale_factor
                elif trace_type == "cfd":
                    baseline = np.mean(latest_trace[:100])
                    signal_data = signal_data + baseline
                elif trace_type == "energy_filter":
                    raw_amplitude = np.max(latest_trace) - np.min(latest_trace)
                    if np.max(signal_data) > np.min(signal_data):
                        signal_amplitude = np.max(signal_data) - np.min(signal_data)
                        scale_factor = (2 * raw_amplitude) / signal_amplitude
                        signal_data = (
                            signal_data - np.min(signal_data)
                        ) * scale_factor + np.min(latest_trace)

            # Plot markers at the actual signal amplitude
            for trigger_idx in trigger_indices:
                if 0 <= trigger_idx < len(time_axis) and 0 <= trigger_idx < len(
                    signal_data
                ):
                    trigger_time = time_axis[trigger_idx]
                    trigger_amplitude = signal_data[trigger_idx]

                    if trace_type == "fast_trigger":
                        plot_widget.plot(
                            [trigger_time],
                            [trigger_amplitude],
                            pen=None,
                            symbol="o",
                            symbolBrush="red",
                            symbolPen=pg.mkPen(color="black", width=2),
                            symbolSize=10,
                            name="Fast Trigger",
                        )
                    elif trace_type == "energy_filter":
                        plot_widget.plot(
                            [trigger_time],
                            [trigger_amplitude],
                            pen=None,
                            symbol="t",
                            symbolBrush="blue",
                            symbolPen=pg.mkPen(color="black", width=2),
                            symbolSize=8,
                            name="Energy Trigger",
                        )
                    elif trace_type == "cfd":
                        plot_widget.plot(
                            [trigger_time],
                            [trigger_amplitude],
                            pen=None,
                            symbol="s",
                            symbolBrush="magenta",
                            symbolPen=pg.mkPen(color="black", width=2),
                            symbolSize=8,
                            name="CFD Zero Crossing",
                        )

        # Add peak sample markers with proper positioning
        peak_info = self.peak_sample_points.get(channel, {})
        if "energy_filter" in peak_info:
            peak_samples = peak_info["energy_filter"]
            print(f"DEBUG: Adding {len(peak_samples)} peak sample markers")

            for peak_idx in peak_samples:
                if 0 <= peak_idx < len(time_axis) and 0 <= peak_idx < len(latest_trace):
                    peak_time = time_axis[peak_idx]

                    # Find the maximum value in the energy filter trace around this time
                    energy_signal = self.compute_hardware_traces(
                        "energy_filter", latest_trace, channel
                    )
                    if energy_signal is not None and len(energy_signal) > peak_idx:
                        # Apply same scaling as energy filter
                        raw_amplitude = np.max(latest_trace) - np.min(latest_trace)
                        if np.max(energy_signal) > np.min(energy_signal):
                            signal_amplitude = np.max(energy_signal) - np.min(
                                energy_signal
                            )
                            scale_factor = (2 * raw_amplitude) / signal_amplitude
                            energy_signal = (
                                energy_signal - np.min(energy_signal)
                            ) * scale_factor + np.min(latest_trace)

                        peak_amplitude = energy_signal[peak_idx]
                    else:
                        # Fallback to raw trace amplitude
                        peak_amplitude = (
                            latest_trace[peak_idx]
                            if peak_idx < len(latest_trace)
                            else latest_trace[-1]
                        )

                    plot_widget.plot(
                        [peak_time],
                        [peak_amplitude],
                        pen=None,
                        symbol="d",
                        symbolBrush="cyan",
                        symbolPen=pg.mkPen(color="black", width=2),
                        symbolSize=12,
                        name="Peak Sample",
                    )

    def fallback_simulation(self, trace_type, trace):
        if trace_type == "fast_trigger":
            fast_filter = np.convolve(trace, [-1] * 5 + [1] * 5, mode="same")
            return np.maximum(fast_filter, 0)
        elif trace_type == "cfd":
            if len(trace) < 10:
                return np.zeros_like(trace)
            delay = 5
            delayed_trace = np.pad(trace[:-delay], (delay, 0), mode="constant")
            return trace - 0.5 * delayed_trace
        elif trace_type == "energy_filter":
            kernel = [-1] * 10 + [0] * 5 + [1] * 10
            return np.convolve(trace, kernel, mode="same")
        return trace

    def compute_trapezoidal_filter(self, trace, rise_time_us, flat_top_us):
        if len(trace) < 20:
            return np.zeros_like(trace)

        # Convert microseconds to samples (assuming 2ns sampling)
        rise_samples = int(rise_time_us * 1000 / 2)  # μs to ns, then to samples
        flat_samples = int(flat_top_us * 1000 / 2)

        # Ensure minimum sizes
        rise_samples = max(rise_samples, 5)
        flat_samples = max(flat_samples, 2)

        # Create trapezoidal kernel
        kernel = [-1] * rise_samples + [0] * flat_samples + [1] * rise_samples
        energy_filter = np.convolve(trace, kernel, mode="same")
        return energy_filter

    def clear_data(self):
        for channel in self.channels:
            self.trace_data[channel].clear()
            self.last_traces[channel] = None

        # Clear coincidence data
        self.event_buffer.clear()
        self.coincidence_events.clear()

        # Clear optimization results
        self.optimization_results = {}
        self.optimization_plot.clear()
        self.timing_plot.clear()
        self.timing_stats_text.clear()
        self.results_table.setRowCount(0)

        # Clear all plot displays
        for channel in self.channels:
            if channel in self.raw_curves:
                self.raw_curves[channel].setData([], [])
            if channel in self.hw_curves_a:
                for curve in self.hw_curves_a.values():
                    curve.setData([], [])
            if channel in self.hw_curves_b:
                for curve in self.hw_curves_b.values():
                    curve.setData([], [])

        if self.replay_widget:
            self.replay_widget.clear_traces()

        self.update_plots()

    def set_display_channels(self, channels):
        self.display_channels = channels if channels else []
        self.update_plots()

    def set_channels(self, channels):
        # Clear old curves
        for channel in self.channels:
            if channel in self.raw_curves:
                self.raw_plot_widget.removeItem(self.raw_curves[channel])

        self.channels = channels

        # Update trace data storage
        new_trace_data = {}
        for ch in self.channels:
            new_trace_data[ch] = self.trace_data.get(ch, deque(maxlen=1000))
        self.trace_data = new_trace_data

        # Create new curves
        self.raw_curves = {}
        for i, channel in enumerate(self.channels):
            color = self.colors[i % len(self.colors)]
            self.raw_curves[channel] = self.raw_plot_widget.plot(
                pen=pg.mkPen(color=color, width=1.5), name=f"Ch {channel}"
            )

        # Update combo boxes
        self.center_channel_combo.clear()
        self.channel_a_combo.clear()
        self.channel_b_combo.clear()

        for ch in self.channels:
            self.center_channel_combo.addItem(f"Ch {ch}")
            self.channel_a_combo.addItem(f"Ch {ch}")
            self.channel_b_combo.addItem(f"Ch {ch}")

    def start_live_updates(self):
        if not self.update_timer.isActive():
            self.update_timer.start(100)
            print("Traces Plotter: Started live updates")

    def stop_live_updates(self):
        if self.update_timer.isActive():
            self.update_timer.stop()
            print("Traces Plotter: Stopped live updates")

    def set_timing_settings(self, settings):
        self.trace_delay_ns = settings.get("trace_delay_ns", {})
        self.sampling_period_ns = settings.get("sampling_period_ns", 2.0)

    def get_coincidence_statistics(self):
        stats = {
            "coincidence_mode": self.coincidence_mode,
            "center_channel": self.center_channel,
            "coincidence_window_ns": self.coincidence_window_ns,
            "optimal_window_ns": self.optimal_window_ns,
            "total_coincidences": len(self.coincidence_events),
            "events_in_buffer": len(self.event_buffer),
            "optimization_active": self.optimization_active,
        }

        if len(self.coincidence_events) > 0:
            recent_coincidences = list(self.coincidence_events)[-100:]
            all_time_diffs = []
            for coinc in recent_coincidences:
                all_time_diffs.extend(coinc.time_differences)

            if all_time_diffs:
                stats.update(
                    {
                        "mean_time_difference_ns": np.mean(all_time_diffs),
                        "std_time_difference_ns": np.std(all_time_diffs),
                        "min_time_difference_ns": np.min(all_time_diffs),
                        "max_time_difference_ns": np.max(all_time_diffs),
                        "events_in_window": len(
                            [
                                dt
                                for dt in all_time_diffs
                                if abs(dt) <= self.coincidence_window_ns
                            ]
                        ),
                        "window_efficiency": len(
                            [
                                dt
                                for dt in all_time_diffs
                                if abs(dt) <= self.coincidence_window_ns
                            ]
                        )
                        / len(all_time_diffs)
                        * 100,
                    }
                )

        return stats

    def on_hardware_replay_trace_selected(self, stored_trace):
        if self.replay_mode and stored_trace:
            # Update single channel plot with the trace
            channel = stored_trace.channel
            trace_data = stored_trace.trace_data

            # Update plot if it matches the selected channel
            if channel == self.selected_channel:
                self.update_single_channel_validation_plot(
                    channel,
                    trace_data,
                    self.channel_plot,
                    self.hw_curves,
                    f"Channel {self.selected_channel}",
                )

    def on_hardware_replay_mode_changed(self, enabled):
        print(f"DEBUG: Replay mode changed to: {enabled}")
        print(f"DEBUG: self.replay_widget = {self.replay_widget}")
        print(f"DEBUG: type(self.replay_widget) = {type(self.replay_widget)}")

        self.replay_mode = enabled

        if enabled:
            # Switch to replay mode for hardware validation
            if self.replay_widget is not None:
                current_trace = self.replay_widget.get_current_trace()
                print(f"DEBUG: current_trace = {current_trace}")
                if current_trace:
                    self.on_hardware_replay_trace_selected(current_trace)
                else:
                    current_pos, total_traces, _ = self.replay_widget.get_buffer_stats()
                    self.hardware_status_label.setText(
                        f"REPLAY MODE - No traces available ({total_traces} stored)"
                    )
            else:
                self.hardware_status_label.setText(
                    "REPLAY MODE - Widget not initialized"
                )
        else:
            # Return to live mode for hardware validation
            self.hardware_status_label.setText("Hardware Status: Live mode resumed")

    def update_single_channel_validation_plot(
        self, channel, trace_data, plot_widget, curves, label
    ):
        try:
            # Clear plot
            plot_widget.clear()

            time_axis = self.calculate_real_time_axis(len(trace_data), channel)

            # Plot enabled traces with proper scaling
            for trace_type, enabled in self.trace_types.items():
                if not enabled:
                    continue

                if trace_type == "raw":
                    signal = trace_data
                    color = "#1f77b4"  # Blue
                    name = "Raw Trace"
                else:
                    signal = self.compute_hardware_traces(
                        trace_type, trace_data, channel
                    )
                    if signal is None or len(signal) == 0:
                        continue

                    trace_colors = {
                        "fast_trigger": "#ff7f0e",  # Orange
                        "energy_filter": "#2ca02c",  # Green
                        "cfd": "#d62728",  # Red
                    }
                    color = trace_colors.get(trace_type, "#333333")
                    name = trace_type.replace("_", " ").title()

                    # Apply amplitude scaling for visibility
                    if trace_type == "fast_trigger":
                        raw_amplitude = np.max(trace_data) - np.min(trace_data)
                        if np.max(signal) > 0:
                            scale_factor = raw_amplitude / (3 * np.max(signal))
                            signal = signal * scale_factor
                    elif trace_type == "cfd":
                        baseline = np.mean(trace_data[:100])
                        signal = signal + baseline
                    elif trace_type == "energy_filter":
                        raw_amplitude = np.max(trace_data) - np.min(trace_data)
                        if np.max(signal) > np.min(signal):
                            signal_amplitude = np.max(signal) - np.min(signal)
                            scale_factor = (2 * raw_amplitude) / signal_amplitude
                            signal = (signal - np.min(signal)) * scale_factor + np.min(
                                trace_data
                            )

                # Plot the trace
                plot_widget.plot(
                    time_axis, signal, pen=pg.mkPen(color=color, width=2), name=name
                )

            # Add trigger markers and threshold lines
            self._add_trigger_markers(plot_widget, channel, time_axis)
            self._add_threshold_lines(plot_widget, trace_data)

            plot_widget.setTitle(f"{label} - Ch {channel} (REPLAY)")
            plot_widget.addLegend()

        except Exception as e:
            print(f"Error updating {label} replay plot: {e}")
