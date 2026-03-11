"""
TracesPlotter Tab
"""

import numpy as np
from collections import deque, defaultdict
import time
import json
from pathlib import Path
import csv
import traceback
import os

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
    QTabWidget,
    QSizePolicy,
    QScrollArea
)
from PyQt6.QtCore import QTimer, QThread, pyqtSignal, Qt
import pyqtgraph as pg

import pixie16 as px

# Import spectrum plotter for histogram functionality
from .spectrum_plotter import ContinuousSpectrumPlotter

from ...analyze import (
    compute_fast_trigger_validation,
    compute_energy_filter,
    convert_trace_to_FPGA,
    calculate_CFD,
    calculate_filter,
    get_fast_trigger_index,
)
from .traces_replay import TraceReplayWidget, StoredTrace
from .coincidence_logic_tab import CoincidenceLogicTab
from .persistence_histogram import PersistenceHistogram

class WindowOptimizationWorker(QThread):
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

    request_right_panel_swap = pyqtSignal(object)

    def __init__(self, channels=None, title="PIXIE-16 Traces", hardware_manager=None):
        super().__init__()

        self.channels = channels or list(range(16))
        self.display_channels = self.channels.copy()
        self.hardware_manager = hardware_manager  # Reference to hardware manager

        # Trace storage with overflow tracking
        self.trace_data = {ch: deque(maxlen=1000) for ch in self.channels}
        self.trace_overflow_count = {ch: 0 for ch in self.channels}
        self.last_traces = {ch: None for ch in self.channels}

        # Display settings (simplified for Raw Traces)
        self.max_traces_display = 10
        self.amplitude_threshold = 0.001
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
        
        # Per-channel polarity settings (True = normal, False = inverted)
        self.channel_polarity = {ch: True for ch in self.channels}

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
        
        # Software offset correction based on L and G parameters
        self.enable_offset_correction = True
        self.offset_corrections = {}  # Cache computed offsets

        # Add parameter display labels
        self.parameter_info_label = None

        # Initialize replay system first
        self.replay_widget = None
        self.replay_mode = False

        # Store when alignment mode was activated
        self.alignment_reference_timestamp = None
        self.alignment_mode_start_time = None

        # Time alignment settings
        self.time_alignment_mode = "zero"  # Start with zero alignment (no filtering)
        self.alignment_reference_channel = 0
        
        # Timestamp storage with overflow tracking
        self.trace_timestamps = {ch: deque(maxlen=1000) for ch in self.channels}
        self.timestamp_overflow_count = {ch: 0 for ch in self.channels}

        self.single_channel_persistence = False
        self.single_persistence_count = 3
        self.single_persistence_normalize = False
        self.single_persistence_alpha_fade = False
        self.single_persistence_data = {ch: deque(maxlen=5000) for ch in self.channels}  # Limit persistence buffer
        self.single_persistence_overflow_count = {ch: 0 for ch in self.channels}
        
        # Persistence histogram
        self.persistence_histogram = {ch: PersistenceHistogram() for ch in self.channels}
        self.persistence_image_item = None 
        self.persistence_update_counter = {ch: 0 for ch in self.channels}  # Track traces since last update
        self.persistence_update_interval = 10  # Update image every N traces

        self.single_channel_controls_widget = None

        self.init_ui()

        # Update timer
        self.update_timer = QTimer(self)  # Add self as parent
        self.update_timer.timeout.connect(self.update_plots)
        self.update_timer.setSingleShot(False)
        
    def sync_parameters_to_coincidence_tab(self):
        if hasattr(self, 'coincidence_tab') and self.coincidence_tab:
            self.coincidence_tab.set_hardware_params(self.hardware_params)
            
    def restore_current_sidebar(self):
        if hasattr(self, 'tab_widget'):
            current_index = self.tab_widget.currentIndex()
            tab_name = self.tab_widget.tabText(current_index)
            
            # Trigger the tab change handler to restore correct sidebar
            self.on_tab_changed(current_index)
        else:
            if hasattr(self, 'parent') and hasattr(self.parent(), 'swap_right_panel_controls'):
                self.parent().swap_right_panel_controls(None)

    def init_ui(self):
        layout = QVBoxLayout()

        # Create tabbed interface
        self.tab_widget = QTabWidget()

        # Add histogram tab for ListMode energy spectra
        self.histogram_tab = ContinuousSpectrumPlotter(
            app=None,
            instrument_name="pixie16",
            display_name="PIXIE-16 List Mode Energy Spectra",
            channels=self.channels,
            energy_range=(0, 80000),
            bins=2000,
        )
        self.tab_widget.addTab(self.histogram_tab, "Histogram")

        raw_traces_tab = self.create_raw_traces_tab()
        self.tab_widget.addTab(raw_traces_tab, "Raw Traces")

        hardware_validation_tab = self.create_hardware_validation_tab()
        self.tab_widget.addTab(hardware_validation_tab, "Single Channel Analysis")

        self.coincidence_tab = CoincidenceLogicTab(
            channels=self.channels, hardware_manager=self.hardware_manager, parent=self
        )
        self.coincidence_tab.set_hardware_params(self.hardware_params)
        self.coincidence_tab.parameter_changed.connect(self.parameter_changed)
        
        self.coincidence_tab.request_controls_widget.connect(self.handle_controls_widget_request)
        
        self.tab_widget.addTab(self.coincidence_tab, "Coincidence Logic")

        self.sync_parameters_to_coincidence_tab()

        self.tab_widget.currentChanged.connect(self.on_tab_changed)

        layout.addWidget(self.tab_widget)
        self.setLayout(layout)

    def create_raw_traces_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        controls_group = QGroupBox("Display Controls")
        controls_group.setMaximumHeight(120)
        controls_layout = (
            QGridLayout()
        )  
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
        self.threshold_spin.setValue(0.001)
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

        # Add polarity button
        self.polarity_btn = QPushButton("Polarity")
        self.polarity_btn.clicked.connect(self.show_polarity_dialog)
        controls_layout.addWidget(self.polarity_btn, 2, 3)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_data)
        controls_layout.addWidget(self.clear_btn, 2, 4)

        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
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

            # print(
            #     f"DEBUG: Leading edge trigger for Ch{channel}: baseline={baseline:.1f}, "
            #     f"noise={baseline_noise:.1f}, threshold={leading_edge_threshold:.1f}, "
            #     f"trigger_points={trigger_indices}"
            # )

            return trigger_indices

        except Exception as e:
            print(f"Error calculating leading edge trigger for channel {channel}: {e}")
            return []

    def update_time_alignment_mode(self, mode_text):
        if mode_text == "Zero":
            self.time_alignment_mode = "zero"
            self.alignment_ref_combo.setEnabled(False)
            self.alignment_reference_timestamp = None
            self.raw_plot_widget.setTitle("PIXIE-16 Raw Traces - Zero Alignment")
            if self.auto_scale:
                self.raw_plot_widget.autoRange()
            self.raw_plot_widget.setLabel("bottom", "Time (ns)")
            
        elif mode_text == "Channel":
            self.time_alignment_mode = "channel_aligned"
            self.alignment_ref_combo.setEnabled(True)
            self.alignment_reference_timestamp = None  # Reset reference

            ref_ch = self.channels[self.alignment_ref_combo.currentIndex()]
            self.raw_plot_widget.setTitle(
                f"PIXIE-16 Raw Traces - Aligned to Ch{ref_ch}"
            )
            print(
                f"DEBUG: Channel alignment mode enabled, waiting for Ch{ref_ch} trace..."
            )
            
        elif mode_text == "None":
            self.time_alignment_mode = "real_time_axis"
            self.alignment_ref_combo.setEnabled(False)
            self.alignment_reference_timestamp = None
            self.raw_plot_widget.setTitle(
                "PIXIE-16 Raw Traces - Relative Time Alignment"
            )
            if self.auto_scale:
                self.raw_plot_widget.autoRange()
            self.raw_plot_widget.setLabel("bottom", "Time (ns)")

    def update_alignment_reference(self):
        self.alignment_reference_channel = self.channels[
            self.alignment_ref_combo.currentIndex()
        ]
        # Reset reference timestamp when changing reference channel
        self.alignment_reference_timestamp = None
        
        if self.time_alignment_mode == "channel_aligned":
            self.raw_plot_widget.setTitle(
                f"PIXIE-16 Raw Traces - Aligned to Ch{self.alignment_reference_channel}"
            )


    def calculate_aligned_time_axis(self, trace_length, event_timestamp=None):
        if (
            self.time_alignment_mode == "channel_aligned"
            and event_timestamp is not None
        ):
            # Get reference timestamp for alignment
            ref_timestamp = self.get_reference_timestamp()
            if ref_timestamp is not None:
                # Calculate time difference in ns (timestamps are in 10ns units)
                time_offset_ns = (event_timestamp - ref_timestamp) * 10.0
                
                # Create time axis in nanoseconds (keep existing scale)
                trace_time_axis_ns = np.arange(trace_length) * self.sampling_period_ns
                return trace_time_axis_ns + time_offset_ns
            else:
                # No reference yet, use default
                return np.arange(trace_length) * self.sampling_period_ns

        elif (
            self.time_alignment_mode == "real_time_axis" and event_timestamp is not None
        ):
            latest_timestamp = self.get_latest_timestamp_across_channels()

            if latest_timestamp is not None:
                time_from_now_ns = (event_timestamp - latest_timestamp) * 10.0

                # Create time axis starting from this relative time
                trace_time_axis_ns = np.arange(trace_length) * self.sampling_period_ns
                return trace_time_axis_ns + time_from_now_ns
        else:
            # Default: keep original behavior
            return np.arange(trace_length) * self.sampling_period_ns

    def get_latest_timestamp_across_channels(self):
        latest = None
        for ch in self.channels:
            if ch in self.trace_timestamps and len(self.trace_timestamps[ch]) > 0:
                ch_latest = self.trace_timestamps[ch][-1]
                if latest is None or ch_latest > latest:
                    latest = ch_latest
        return latest

    def get_reference_timestamp(self):
        if self.alignment_reference_timestamp is None:
            # Set reference when first trace from reference channel arrives
            ref_ch = self.alignment_reference_channel
            if (
                ref_ch in self.trace_timestamps
                and len(self.trace_timestamps[ref_ch]) > 0
            ):
                # Use the first timestamp as reference, not the latest
                # This prevents all previous traces from becoming "misaligned"
                self.alignment_reference_timestamp = self.trace_timestamps[ref_ch][0]
        return self.alignment_reference_timestamp
    
    def on_tab_changed(self, index):
        current_tab = self.tab_widget.widget(index)
        tab_name = self.tab_widget.tabText(index)
                
        # Only run compute-intensive updates for active tab
        if tab_name in ["Raw Traces", "Single Channel Analysis"]:
            if not self.update_timer.isActive():
                is_remote_desktop = (
                    os.environ.get('SSH_CLIENT') is not None or
                    os.environ.get('SSH_TTY') is not None or
                    os.environ.get('SESSIONNAME', '').lower() in ['rdp-tcp', 'console'] or
                    'nomachine' in os.environ.get('NX_CLIENT', '').lower()
                )
                interval = 200 if is_remote_desktop else 100
                self.update_timer.start(interval)
                print(f"TracesPlotter: Resumed compute-intensive updates for {tab_name} ({interval}ms interval)")
        else:
            # Pause main traces processing when viewing coincidence logic only
            if self.update_timer.isActive() and tab_name == "Coincidence Logic":
                self.update_timer.stop()
                print("TracesPlotter: Paused main traces processing - coincidence logic handles its own")
        
        # Deactivate all tabs
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if hasattr(tab, 'on_tab_deactivated'):
                if tab != current_tab:
                    tab.on_tab_deactivated()
        
        # Handle based on which tab was selected
        if tab_name == "Single Channel Analysis":
            # Show single channel controls
            controls = self.create_single_channel_controls_widget()
            self.request_right_panel_swap.emit(controls)
            print(f"TracesPlotter: Emitted right panel swap with widget: {controls}")
            
        elif tab_name == "Coincidence Logic":
            # Coincidence tab handles its own activation
            if hasattr(current_tab, 'on_tab_activated'):
                current_tab.on_tab_activated()
                
        else:
            # restore default controls
            self.request_right_panel_swap.emit(None)
            print("TracesPlotter: Requested default controls")

    def create_hardware_validation_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Just keep the plot and status labels
        self.channel_plot = pg.PlotWidget()
        self.channel_plot.setLabel("left", "Amplitude")
        self.channel_plot.setLabel("bottom", "Time (ns)")
        self.channel_plot.setTitle(f"Channel {self.selected_channel} Validation")
        self.channel_plot.showGrid(True, True, alpha=0.3)
        self.channel_plot.setBackground("w")
        self.channel_plot.addLegend(offset=(10, 10))
        
        self.channel_plot.setSizePolicy(
            QSizePolicy.Policy.Expanding,  # Horizontal: expand
            QSizePolicy.Policy.Expanding   # Vertical: expand (allows resizing)
        )
        self.channel_plot.setMinimumHeight(300)  # Minimum height
        
        layout.addWidget(self.channel_plot, stretch=1)
        
        self.hardware_status_label = QLabel("Hardware Status: Ready")
        self.hardware_status_label.setMaximumHeight(25)
        layout.addWidget(self.hardware_status_label)
        
        self.persistence_stats_label = QLabel("Persistence: Ready")
        self.persistence_stats_label.setMaximumHeight(25)
        layout.addWidget(self.persistence_stats_label)
        
        # Initialize plot curves
        self.hw_curves = {}
        trace_colors = {
            "raw": "#1f77b4",
            "fast_trigger": "#ff7f0e",
            "energy_filter": "#2ca02c",
            "cfd": "#d62728",
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
    
    def clear_persistence_only(self):
        for channel in self.channels:
            self.single_persistence_data[channel].clear()
            self.persistence_histogram[channel].reset()
            self.persistence_update_counter[channel] = 0
        
        # Clear the image item if it exists
        if self.persistence_image_item is not None:
            self.channel_plot.removeItem(self.persistence_image_item)
            self.persistence_image_item = None
        
        selected_channel = self.channels[self.channel_combo.currentIndex()]
        self.update_persistence_statistics(selected_channel)
        
        self.update_plots()
        
        print("Cleared persistence data and histogram for all channels")
                
    def save_traces_buffer(self):
        try:
            # Get unified data directory path
            if hasattr(self.parent(), 'data_storage_manager'):
                data_manager = self.parent().data_storage_manager
            else:
                from .data_manager import DataSettingsManager
                data_manager = DataSettingsManager()
            
            selected_channel = self.channels[self.channel_combo.currentIndex()]
            timestamp = int(time.time())
            
            # Save single channel persistence data if available
            if (selected_channel in self.single_persistence_data and 
                len(self.single_persistence_data[selected_channel]) > 0):
                
                traces_list = list(self.single_persistence_data[selected_channel])
                trace_count = len(traces_list)
                
                # Warn user about large datasets
                if trace_count > 5000:
                    from PyQt6.QtWidgets import QMessageBox
                    reply = QMessageBox.question(
                        self, "Large Dataset Warning", 
                        f"You are about to save {trace_count} traces. This may take a while and create a large file. Continue?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        return
                
                traces_array = np.array(traces_list)
                save_path = data_manager.get_save_path('traces', f"traces_ch{selected_channel}_{timestamp}.npy")
                np.save(save_path, traces_array)
                
                # Save peak sample locations and amplitudes if available
                peak_samples_data = {}
                if selected_channel in self.peak_sample_points:
                    peak_samples_data = self.peak_sample_points[selected_channel].copy()
                    
                    # Add amplitude data for each peak sample
                    if selected_channel in self.trace_data and len(self.trace_data[selected_channel]) > 0:
                        latest_trace = list(self.trace_data[selected_channel])[-1]
                        
                        # Calculate amplitudes at peak sample locations
                        for trace_type, peak_indices in peak_samples_data.items():
                            if trace_type == "energy_filter" and peak_indices:
                                amplitudes = []
                                energy_signal = self.compute_hardware_traces("energy_filter", latest_trace, selected_channel)
                                if energy_signal is not None:
                                    # Apply same scaling as used in plotting
                                    raw_amplitude = np.max(latest_trace) - np.min(latest_trace)
                                    if np.max(energy_signal) > np.min(energy_signal):
                                        signal_amplitude = np.max(energy_signal) - np.min(energy_signal)
                                        scale_factor = (2 * raw_amplitude) / signal_amplitude
                                        energy_signal = (energy_signal - np.min(energy_signal)) * scale_factor + np.min(latest_trace)
                                    
                                    for peak_idx in peak_indices:
                                        if 0 <= peak_idx < len(energy_signal):
                                            amplitudes.append(float(energy_signal[peak_idx]))
                                        else:
                                            amplitudes.append(None)
                                else:
                                    amplitudes = [None] * len(peak_indices)
                                
                                # Store both locations and amplitudes
                                peak_samples_data[trace_type] = {
                                    "locations": peak_indices,
                                    "amplitudes": amplitudes
                                }
                    
                if peak_samples_data:
                    peak_samples_path = data_manager.get_save_path('traces', f"peak_samples_ch{selected_channel}_{timestamp}.json")
                    with open(peak_samples_path, 'w') as f:
                        json.dump(peak_samples_data, f, indent=2)
                    print(f"Saved peak sample locations and amplitudes to {peak_samples_path}")

                # Save metadata
                metadata = {
                    "channel": selected_channel,
                    "timestamp": timestamp,
                    "trace_count": trace_count,
                    "sampling_period_ns": self.sampling_period_ns,
                    "hardware_params": self.hardware_params.copy(),
                    "peak_samples_saved": bool(peak_samples_data)
                }
                
                metadata_path = data_manager.get_save_path('traces', f"traces_ch{selected_channel}_{timestamp}_metadata.json")
                with open(metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=2)
                
                file_size_mb = save_path.stat().st_size / (1024 * 1024)
                save_message = (
                    f"Saved {trace_count} traces to {save_path}\n"
                    f"File size: {file_size_mb:.1f} MB\n"
                    f"Metadata: {metadata_path}"
                )
                if peak_samples_data:
                    save_message += f"\nPeak sample locations & amplitudes: {peak_samples_path}"
                
                QMessageBox.information(self, "Traces Saved", save_message)
            else:
                QMessageBox.warning(
                    self, "No Data", 
                    f"No persistence data available for channel {selected_channel}"
                )
                
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save traces: {e}")

    def update_single_persistence_count(self):
        new_count = self.single_persistence_count_spin.value()
        self.single_persistence_count = new_count
        print(f"Updated persistence display count to {new_count} traces")
        
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

            self.sync_parameters_to_coincidence_tab()

    def toggle_simple_coincidence(self, enabled):
        if hasattr(self, "coincidence_tab") and self.coincidence_tab:
            if hasattr(self.coincidence_tab, 'set_coincidence_mode'):
                self.coincidence_tab.set_coincidence_mode(enabled)
            elif hasattr(self.coincidence_tab, 'coincidence_mode'):
                self.coincidence_tab.coincidence_mode = enabled
        
        # Update the plot title
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

    def toggle_single_persistence(self, enabled):
        self.single_channel_persistence = enabled
        
        if enabled:
            selected_channel = self.channels[self.channel_combo.currentIndex()]
            self.persistence_histogram[selected_channel].reset()
            print(f"Persistence histogram mode enabled for channel {selected_channel}")

    def update_single_persistence_count(self):
        self.single_persistence_count = self.single_persistence_count_spin.value()

    def toggle_single_normalize(self, enabled):
        self.single_persistence_normalize = enabled

    def toggle_single_alpha_fade(self, enabled):
        self.single_persistence_alpha_fade = enabled
        
    def calculate_trace_baseline(self, trace):
        if len(trace) < 20:
            return np.mean(trace)
        
        # Use first 20% of trace, but at least 20 samples and at most 1/3 of trace
        baseline_samples = max(20, int(len(trace) * 0.2))
        baseline_samples = min(baseline_samples, len(trace) // 3)
        
        return np.mean(trace[:baseline_samples])
    
    def normalize_trace_to_zero_baseline(self, trace, trace_type="raw"):
        if len(trace) == 0:
            return trace
            
        baseline = self.calculate_trace_baseline(trace)
        return trace - baseline
    
    def apply_time_correction(self, time_axis, trace_type, L=None, G=None):
        if not self.enable_offset_correction or time_axis is None or len(time_axis) <= 1:
            return time_axis
        
        # Get L/G parameters with defaults
        if L is None:
            L = self.hardware_params.get(f"{trace_type.split('_')[0]}_L", 0)
        if G is None:
            G = self.hardware_params.get(f"{trace_type.split('_')[0]}_G", 0)
        
        # Check cache
        cache_key = f"{trace_type}_{L}_{G}"
        if cache_key not in self.offset_corrections:
            # Calculate offset based on trace type
            offset_map = {
                "fast_trigger": (L + G // 2) * 5,  # FPGA to raw sample conversion
                "energy_filter": (L + G // 2) * (2 ** self.hardware_params.get("energy_R", 3)) * 5,
                "cfd": 1
            }
            self.offset_corrections[cache_key] = offset_map.get(trace_type, 0)
        
        offset_samples = self.offset_corrections[cache_key]
        if offset_samples == 0:
            return time_axis
            
        # Apply time correction
        time_step = time_axis[1] - time_axis[0]
        return time_axis - (offset_samples * time_step)

    def _update_curve_names(self):
        try:
            for channel in self.channels:
                curve = self.raw_curves[channel]
                if channel in self.display_channels:
                    # Set name for displayed channels
                    curve.opts['name'] = f"Ch {channel}"
                else:
                    # Remove name for hidden channels
                    curve.opts['name'] = None
        except Exception as e:
            print(f"Error updating curve names: {e}")
    
    def _update_legend(self):
        try:
            # Remove existing legend
            if self.raw_plot_widget.plotItem.legend is not None:
                self.raw_plot_widget.plotItem.legend.scene().removeItem(self.raw_plot_widget.plotItem.legend)
                self.raw_plot_widget.plotItem.legend = None
            
            # Create new legend and add only displayed channels
            self.raw_plot_widget.addLegend()
            for channel in self.display_channels:
                if channel in self.raw_curves:
                    curve = self.raw_curves[channel]
                    # Add to legend manually
                    self.raw_plot_widget.plotItem.legend.addItem(curve, f"Ch {channel}")
        except Exception as e:
            print(f"Error updating raw traces legend: {e}")

    # Hardware validation
    def update_selected_channel(self):
        if hasattr(self, 'channel_combo') and self.channel_combo.currentIndex() >= 0:
            self.selected_channel = self.channels[self.channel_combo.currentIndex()]
            self.channel_plot.setTitle(f"Channel {self.selected_channel} Validation")
            
            # Update polarity combo to reflect selected channel's polarity
            if hasattr(self, 'polarity_combo'):
                current_polarity = self.channel_polarity.get(self.selected_channel, True)
                self.polarity_combo.setCurrentIndex(0 if current_polarity else 1)
            
            # Force immediate plot update for the new channel
            self.update_hardware_validation_plots()

        else:
            pass  # channel_combo not available or invalid index

    def update_channel_polarity(self):
        if hasattr(self, 'channel_combo') and hasattr(self, 'polarity_combo'):
            selected_channel = self.channels[self.channel_combo.currentIndex()]
            # 0 = Normal (True), 1 = Inverted (False)
            polarity_normal = self.polarity_combo.currentIndex() == 0
            self.channel_polarity[selected_channel] = polarity_normal
            print(f"Channel {selected_channel} polarity set to {'normal' if polarity_normal else 'inverted'}")
            
            # Force immediate plot update to show polarity change
            self.update_plots()

    def show_polarity_dialog(self):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QDialogButtonBox, QLabel
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Channel Polarity Settings")
        dialog.setFixedSize(300, 400)
        
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Select channels to invert:"))
        
        # Create checkboxes for each channel
        channel_checkboxes = {}
        for channel in self.channels:
            cb = QCheckBox(f"Channel {channel}")
            # Set current polarity state (inverted = checked)
            cb.setChecked(not self.channel_polarity.get(channel, True))
            channel_checkboxes[channel] = cb
            layout.addWidget(cb)
        
        # Add buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        dialog.setLayout(layout)
        
        # Show dialog and process result
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Update polarity settings based on checkboxes
            inverted_channels = []
            for channel, checkbox in channel_checkboxes.items():
                # Checkbox checked = inverted (False), unchecked = normal (True)
                is_inverted = checkbox.isChecked()
                self.channel_polarity[channel] = not is_inverted
                if is_inverted:
                    inverted_channels.append(channel)
            
            # Update polarity combo in single channel tab if it exists
            if hasattr(self, 'polarity_combo') and hasattr(self, 'channel_combo'):
                selected_channel = self.channels[self.channel_combo.currentIndex()]
                current_polarity = self.channel_polarity.get(selected_channel, True)
                self.polarity_combo.setCurrentIndex(0 if current_polarity else 1)
            
            # Force plot update
            self.update_plots()
            
            # Save settings if save method exists
            if hasattr(self.parent(), 'save_settings'):
                self.parent().save_settings()

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

    def add_event_with_trace(self, event, trace_data):
        event_timestamp = getattr(event, "timestamp", None)
        


        # Add to raw traces display
        self.add_trace(event.channel, trace_data, event_timestamp)

        # Feed to coincidence logic tab
        if hasattr(self, "coincidence_tab"):
            self.coincidence_tab.add_event_with_trace(event, trace_data)

    def add_trace(self, channel, trace_data, event_timestamp=None):
        try:





            
            if channel not in self.channels:

                return

            if not isinstance(trace_data, np.ndarray):
                trace_data = np.array(trace_data)

            if len(trace_data) == 0:

                return

            # Store timestamp for alignment with overflow tracking
            if event_timestamp is not None:
                timestamp_buffer_was_full = len(self.trace_timestamps[channel]) == self.trace_timestamps[channel].maxlen
                self.trace_timestamps[channel].append(event_timestamp)
                
                if timestamp_buffer_was_full:
                    self.timestamp_overflow_count[channel] += 1
                    # Reset counter periodically to prevent memory buildup
                    if self.timestamp_overflow_count[channel] > 100000:
                        self.timestamp_overflow_count[channel] = 0

            if len(trace_data) > 10:
                amplitude = np.max(trace_data) - np.min(trace_data)

                
                if amplitude >= self.amplitude_threshold:

                    # Store in original buffer with overflow tracking
                    buffer_was_full = len(self.trace_data[channel]) == self.trace_data[channel].maxlen
                    self.trace_data[channel].append(trace_data)
                    
                    if buffer_was_full:
                        self.trace_overflow_count[channel] += 1
                        # Reset counter periodically to prevent memory buildup
                        if self.trace_overflow_count[channel] > 100000:
                            self.trace_overflow_count[channel] = 0
                        if self.trace_overflow_count[channel] % 100 == 1:
                            #print(f"Buffer overflow on channel {channel}: removed oldest trace (#{self.trace_overflow_count[channel]})")
                            pass

                    # Store in single channel persistence buffer with overflow tracking
                    if self.single_channel_persistence:
                        persistence_buffer_was_full = len(self.single_persistence_data[channel]) == self.single_persistence_data[channel].maxlen
                        self.single_persistence_data[channel].append(trace_data)
                        
                        if persistence_buffer_was_full:
                            self.single_persistence_overflow_count[channel] += 1
                            # Reset counter periodically to prevent memory buildup
                            if self.single_persistence_overflow_count[channel] > 100000:
                                self.single_persistence_overflow_count[channel] = 0
                            if self.single_persistence_overflow_count[channel] % 500 == 1:
                                print(f"Persistence buffer overflow on channel {channel}: removed oldest data (#{self.single_persistence_overflow_count[channel]})")
                        # Update histogram in real-time for raw traces
                        time_axis = self.calculate_real_time_axis(len(trace_data), channel)
                        self.persistence_histogram[channel].add_trace(time_axis, trace_data)
                        
                        # Increment counter for this channel
                        self.persistence_update_counter[channel] += 1

                    # Store in replay buffer
                    if (
                        hasattr(self, "replay_widget")
                        and self.replay_widget is not None
                        and not self.replay_mode
                    ):
                        self.replay_widget.add_trace(trace_data, channel, amplitude)
                else:
                    pass  # REJECTED trace - amplitude below threshold
            else:

                # Store in original buffer with overflow tracking
                buffer_was_full = len(self.trace_data[channel]) == self.trace_data[channel].maxlen
                self.trace_data[channel].append(trace_data)
                
                if buffer_was_full:
                    self.trace_overflow_count[channel] += 1
                    # Reset counter periodically to prevent memory buildup
                    if self.trace_overflow_count[channel] > 100000:
                        self.trace_overflow_count[channel] = 0
                    if self.trace_overflow_count[channel] % 100 == 1:
                        #print(f"Buffer overflow on channel {channel}: removed oldest trace (#{self.trace_overflow_count[channel]})")
                        pass

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
            # Count total traces for debug
            total_traces = sum(len(self.trace_data[ch]) for ch in self.channels if ch in self.trace_data)

            
            self.update_raw_traces_plot()
            self.update_hardware_validation_plots()

        except Exception as e:
            print(f"Error updating plots: {e}")

    def update_raw_traces_plot(self):
        try:
            if self.replay_mode:
                return

            total_traces = 0


            # Update legend to only show displayed channels
            self._update_legend()
            
            # Process all channels for raw traces display (no trace limiting)
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
                
                # Use all traces, don't limit
                display_traces = traces[-self.max_traces_display:]
                display_timestamps = (
                    timestamps[-self.max_traces_display:]
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
                                trace_length, timestamp
                            )

                            # Apply polarity inversion if enabled for this channel
                            y_data = trace
                            if not self.channel_polarity.get(channel, True):
                                y_data = -y_data

                            combined_x.extend(time_axis)
                            combined_x.append(np.nan)
                            combined_y.extend(y_data)
                            combined_y.append(np.nan)

                    if combined_x and combined_y:
                        self.raw_curves[channel].setData(combined_x, combined_y)

            # Set focused axis limits for channel alignment mode
            if self.time_alignment_mode == "channel_aligned" and total_traces > 0:
                alignment_window_ns = 20000
                self.raw_plot_widget.setXRange(-alignment_window_ns, alignment_window_ns)
                
                ref_ch = self.alignment_reference_channel
                self.raw_plot_widget.setLabel("bottom", "Time (ns)", f"Relative to Ch{ref_ch} trigger")
                
                # Disable auto-range in alignment mode to maintain focus
                auto_range_enabled = False
            else:
                # Re-enable auto-range for other modes
                auto_range_enabled = self.auto_scale
                self.raw_plot_widget.setLabel("bottom", "Time (ns)")

            # Update statistics
            stats_text = f"Total Traces: {total_traces} | "
            if (hasattr(self, "coincidence_tab") and self.coincidence_tab and hasattr(self.coincidence_tab, "coincidence_mode") and self.coincidence_tab.coincidence_mode):
                stats_text += (
                    f"Coincidences: {len(self.coincidence_tab.coincidence_events)} | "
                )

            stats_text += f"Displayed Channels: {len(self.display_channels)} | "
            stats_text += f"Alignment: {self.time_alignment_mode}"
            if self.time_alignment_mode == "channel_aligned":
                stats_text += f" (Ref: Ch{self.alignment_reference_channel}, ±20µs window)"

            self.raw_stats_label.setText(stats_text)

            # Apply auto-range only when appropriate
            if auto_range_enabled and total_traces > 0:
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
                plot_widget.clear()
                return

            if self.single_channel_persistence and len(self.single_persistence_data[channel]) > 0:
                # In persistence mode: remove ALL items except the persistence image
                items_to_remove = []
                for item in plot_widget.items():
                    # Keep the image item, remove everything else
                    if item != self.persistence_image_item:
                        items_to_remove.append(item)
                
                for item in items_to_remove:
                    plot_widget.removeItem(item)
                
                # Clear the legend
                if plot_widget.plotItem.legend is not None:
                    plot_widget.plotItem.legend.scene().removeItem(plot_widget.plotItem.legend)
                    plot_widget.plotItem.legend = None
            else:
                # Not in persistence mode: clear everything including image
                plot_widget.clear()
                # Make sure image item is gone
                if self.persistence_image_item is not None:
                    try:
                        plot_widget.removeItem(self.persistence_image_item)
                    except:
                        pass
                    self.persistence_image_item = None

            if self.single_channel_persistence and len(self.single_persistence_data[channel]) > 0:
                # Persistence mode - plot histogram + overlays
                self._plot_persistence_traces_single_channel(channel, plot_widget)
                total_stored = len(self.single_persistence_data[channel])
                displayed = min(self.single_persistence_count, total_stored)
                plot_widget.setTitle(f"{label} - Ch {channel} (Persistence: {displayed}/{total_stored} traces)")
            else:
                # Normal mode - plot just the latest trace
                self._plot_single_trace(channel, plot_widget)
                plot_widget.setTitle(f"{label} - Ch {channel}")
            
            # Add legend (it will be recreated with each update)
            plot_widget.addLegend()
                
            self.update_persistence_statistics(channel)

        except Exception as e:
            print(f"CRITICAL ERROR updating {label} plot for channel {channel}: {e}")
            traceback.print_exc()
            try:
                plot_widget.clear()
                plot_widget.setTitle(f"{label} - Ch {channel} (ERROR)")
            except:
                pass
    
    def update_persistence_statistics(self, channel):
        if hasattr(self, 'persistence_stats_label'):
            if self.single_channel_persistence:
                total_stored = self.persistence_histogram[channel].trace_count
                self.persistence_stats_label.setText(
                    f"Persistence: {total_stored} traces (histogram mode)"
                )
            else:
                self.persistence_stats_label.setText("Persistence: Disabled")
                
    def _plot_single_trace(self, channel, plot_widget):
        traces_list = list(self.trace_data[channel])
        if not traces_list:
            return

        latest_trace = traces_list[-1]
        if latest_trace is None or len(latest_trace) == 0:
            return
            
        target_length = len(latest_trace)
        time_axis = self.calculate_real_time_axis(target_length, channel)

        # Calculate trigger points for the latest trace
        try:
            main_trigger_points = self.calculate_main_trigger_point(latest_trace, channel)
            if main_trigger_points:
                self._store_trigger_info(channel, main_trigger_points, "main_trigger")
            else:
                self._store_trigger_info(channel, [], "main_trigger")
        except Exception as e:
            print(f"Error calculating main trigger for channel {channel}: {e}")
            self._store_trigger_info(channel, [], "main_trigger")

        # Apply polarity inversion to the source trace before any processing
        working_trace = latest_trace
        if not self.channel_polarity.get(channel, True):
            working_trace = -working_trace

        # Plot enabled traces with proper scaling
        for trace_type, enabled in self.trace_types.items():
            if not enabled:
                continue

            try:
                if trace_type == "raw":
                    signal = working_trace
                elif trace_type == "fast_trigger":
                    # Compute actual fast trigger using hardware parameters
                    traces_fpga = convert_trace_to_FPGA(latest_trace[np.newaxis, :])
                    
                    fast_result = compute_fast_trigger_validation(
                        traces_fpga,
                        L=self.hardware_params["fast_L"],
                        G=self.hardware_params["fast_G"],
                        threshold=self.hardware_params["fast_threshold"],
                    )
                    
                    if fast_result["validation_passed"] and fast_result["fast_triggers"] is not None:
                        # Extract the fast trigger trace (first trace if multiple)
                        signal = fast_result["fast_triggers"][0]
                        # Resize to match original trace length if needed
                        if len(signal) != target_length:
                            signal = self._resize_trace_to_match(signal, target_length, "fast_trigger")
                    else:
                        continue  # Skip if computation failed
                elif trace_type == "cfd":
                    # Compute CFD using hardware parameters
                    # First compute fast trigger for CFD input
                    traces_fpga = convert_trace_to_FPGA(latest_trace[np.newaxis, :])
                    
                    fast_result = compute_fast_trigger_validation(
                        traces_fpga,
                        L=self.hardware_params["fast_L"],
                        G=self.hardware_params["fast_G"],
                        threshold=self.hardware_params["fast_threshold"],
                    )
                    
                    if fast_result["validation_passed"] and fast_result["fast_triggers"] is not None:
                        # Use fast trigger as input to CFD
                        fast_trace = fast_result["fast_triggers"][0]
                        
                        # Calculate CFD with hardware parameters
                        cfd_result, cfdtime, fast_filter, cfd_errors = calculate_CFD(
                            fast_trace[np.newaxis, :],  # CFD expects 2D array
                            CFD_threshold=self.hardware_params.get("CFD_threshold", 50),
                            w=self.hardware_params.get("CFD_delay", 5),
                            FF_threshold=self.hardware_params.get("FF_threshold", 100)
                        )
                        
                        if cfd_result is not None and len(cfd_result) > 0:
                            signal = cfd_result[0]  # Extract first trace
                            # Resize to match original trace length if needed
                            if len(signal) != target_length:
                                signal = self._resize_trace_to_match(signal, target_length, "cfd")
                        else:
                            continue  # Skip if CFD computation failed
                    else:
                        continue  # Skip if fast trigger computation failed
                elif trace_type == "energy_filter":
                    # Energy filter - use hardware algorithm
                    traces_fpga = convert_trace_to_FPGA(latest_trace[np.newaxis, :])

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
                                # Use the same delay-corrected calculation as in fast trigger processing
                                fpga_idx = fast_trigger_indices[0][0]
                                fast_L = self.hardware_params["fast_L"]
                                fast_G = self.hardware_params["fast_G"]
                                fpga_delay = fast_L + (fast_G // 2)
                                fast_trigger_raw_pos = (fpga_idx + fpga_delay) * 5

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

                                    L = self.hardware_params["energy_L"]
                                    G = self.hardware_params["energy_G"]
                                    P = self.hardware_params["energy_P"]
                                    
                                    ramp_duration = (L + G) * samples_per_energy_cycle
                                    flat_area_start = ramp_duration
                                    flat_area_length = P * samples_per_energy_cycle
                                    # Position peak sample in the center of the flat top for stability
                                    optimal_offset = flat_area_start + (flat_area_length // 2)
                                    peak_sample_raw_pos = fast_trigger_raw_pos + optimal_offset
                                    



                                    peak_sample_points = (
                                        [peak_sample_raw_pos]
                                        if peak_sample_raw_pos < target_length
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
                            signal = self._resize_trace_to_match(
                                energy_aligned, target_length, "energy_filter"
                            )
                        else:
                            print(f"Energy filter calculation failed for channel {channel}")
                            continue  # Skip this trace type
                else:
                    # For other trace types, skip if we don't have real hardware data
                    # Only raw traces come from hardware, other types need actual hardware traces
                    continue

                # Apply baseline normalization to align all traces to zero baseline
                signal = self.normalize_trace_to_zero_baseline(signal, trace_type)
                
                if trace_type == "fast_trigger":
                    fpga_sampling_period = 10.0  # ns per FPGA cycle
                    raw_sampling_period = 2.0   # ns per raw sample
                    pretrigger_offset_ns = 200.0  # ns
                    
                    # Create time axes for interpolation with offset compensation
                    fast_time_points = np.arange(len(signal)) * fpga_sampling_period + pretrigger_offset_ns
                    target_time_points = np.arange(target_length) * raw_sampling_period
                    
                    # Interpolate fast trigger to match raw trace timing
                    from scipy import interpolate
                    interp_func = interpolate.interp1d(
                        fast_time_points, signal, 
                        kind='linear', bounds_error=False, fill_value=0
                    )
                    signal = interp_func(target_time_points)
                    
                    # Use standard time axis correction
                    corrected_time_axis = self.apply_time_correction(time_axis, trace_type)
                else:
                    # Apply offset correction to time axis for other trace types
                    corrected_time_axis = self.apply_time_correction(time_axis, trace_type)
                
                # Color coding for different trace types
                trace_colors = {"raw": "#1f77b4", "fast_trigger": "#ff7f0e", "energy_filter": "#2ca02c", "cfd": "#d62728"}
                color = trace_colors.get(trace_type, "#333333")
                name = trace_type.replace("_", " ").title()

                # Plot the trace
                plot_widget.plot(corrected_time_axis, signal, pen=pg.mkPen(color=color, width=2), name=name)

            except Exception as e:
                print(f"Hardware computation error for {trace_type}: {e}")
                continue

        # Add trigger markers and threshold lines
        self._add_trigger_markers(plot_widget, channel, time_axis)
        self._add_threshold_lines(plot_widget, latest_trace)

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
        # print(
        #     f"DEBUG: Stored {len(trigger_indices)} {trace_type} trigger points for channel {channel}: {trigger_indices}"
        # )

        if trace_type == "energy_filter" and peak_samples:
            self.peak_sample_points[channel][trace_type] = peak_samples
            # print(
            #     f"DEBUG: Stored {len(peak_samples)} peak sample points: {peak_samples}"
            # )

    def _resize_trace_to_match(
        self, processed_trace, target_length, trace_type="unknown"
    ):
        if processed_trace is None:
            return np.zeros(target_length)

        processed_trace = np.asarray(processed_trace)
        current_length = len(processed_trace)

        if current_length == target_length:
            return processed_trace

        elif current_length < target_length:
            # Pad with zeros at the end to preserve timing alignment
            # The traces start at the correct time, just need to extend length
            pad_length = target_length - current_length
            return np.concatenate([processed_trace, np.zeros(pad_length)])

        else:
            # Truncate from the end to preserve timing alignment
            # The traces start at the correct time, just need to shorten length
            return processed_trace[:target_length]

    def _add_trigger_markers(self, plot_widget, channel, time_axis):
        # Don't add markers for channels that are not displayed
        if channel not in self.display_channels:
            return
            
        if channel not in self.trigger_points:

            return

        trigger_info = self.trigger_points[channel]


        # Get the latest trace to read signal values
        if channel not in self.trace_data or len(self.trace_data[channel]) == 0:

            return

        traces_list = list(self.trace_data[channel])
        if not traces_list:

            return

        latest_trace = traces_list[-1]
        if latest_trace is None or len(latest_trace) == 0:
            return
            
        target_length = len(latest_trace)

        if len(time_axis) != target_length:
            print(
                f"WARNING: Time axis length ({len(time_axis)}) != trace length ({target_length}) for channel {channel}"
            )
            time_axis = self.calculate_real_time_axis(target_length, channel)

        # Track which marker types we've added to legend
        added_to_legend = set()

        if ("main_trigger" in trigger_info and trigger_info["main_trigger"] 
            and self.trace_types.get("raw", False)):
            main_trigger_points = trigger_info["main_trigger"]
            # Use corrected time axis for raw trace alignment
            raw_corrected_time_axis = self.apply_time_correction(time_axis, "raw")
            for idx, trigger_idx in enumerate(main_trigger_points):
                if 0 <= trigger_idx < len(raw_corrected_time_axis) and 0 <= trigger_idx < target_length:
                    trigger_time = raw_corrected_time_axis[trigger_idx]
                    trigger_amplitude = self.normalize_trace_to_zero_baseline(latest_trace, "raw")[trigger_idx]
                    # add name to first instance
                    plot_widget.plot(
                        [trigger_time],
                        [trigger_amplitude],
                        pen=None,
                        symbol="t1",
                        symbolBrush="darkgreen",
                        symbolPen=pg.mkPen(color="black", width=2),
                        symbolSize=10,
                        name="Leading Edge" if idx == 0 else None,
                    )

        # Add other trigger markers
        for trace_type, trigger_indices in trigger_info.items():
            if (not trigger_indices or trace_type == "main_trigger" 
                or not self.trace_types.get(trace_type, False)):
                continue



            # Get the signal data for this trace type
            if trace_type == "raw":
                signal_data = latest_trace
            else:
                signal_data = self.compute_hardware_traces(trace_type, latest_trace, channel)
                if signal_data is None or len(signal_data) == 0:
                    continue

                # Apply the same scaling and baseline normalization that was used in the plot
                if trace_type == "fast_trigger":
                    raw_amplitude = np.max(latest_trace) - np.min(latest_trace)
                    if np.max(signal_data) > 0:
                        scale_factor = raw_amplitude / (3 * np.max(signal_data))
                        signal_data = signal_data * scale_factor
                elif trace_type == "cfd":
                    # CFD oscillates around zero, no baseline adjustment needed
                    pass
                elif trace_type == "energy_filter":
                    # Apply same scaling as in plot, then normalize baseline
                    raw_amplitude = np.max(latest_trace) - np.min(latest_trace)
                    if np.max(signal_data) > np.min(signal_data):
                        signal_amplitude = np.max(signal_data) - np.min(signal_data)
                        scale_factor = (2 * raw_amplitude) / signal_amplitude
                        signal_data = (signal_data - np.min(signal_data)) * scale_factor
                    # Apply baseline normalization to match plot
                    signal_data = self.normalize_trace_to_zero_baseline(signal_data, trace_type)
                
                # Apply baseline normalization for raw trace and others that need it
                if trace_type == "raw":
                    signal_data = self.normalize_trace_to_zero_baseline(signal_data, trace_type)

            corrected_time_axis = self.apply_time_correction(time_axis, trace_type)
            for idx, trigger_idx in enumerate(trigger_indices):
                if 0 <= trigger_idx < len(corrected_time_axis) and 0 <= trigger_idx < len(signal_data):
                    trigger_time = corrected_time_axis[trigger_idx]
                    trigger_amplitude = signal_data[trigger_idx]

                    if trace_type == "fast_trigger":
                        plot_widget.plot(
                            [trigger_time],
                            [trigger_amplitude],
                            pen=None,
                            symbol="t1",  # Triangle symbol for fast trigger
                            symbolBrush="red",
                            symbolPen=pg.mkPen(color="black", width=2),
                            symbolSize=10,
                            name="Fast Trigger" if idx == 0 else None,
                        )
                        # Add LNo text label for fast trigger alignment
                        lno_text = pg.TextItem(f"L{trigger_idx}", color=(255, 100, 0), anchor=(0.5, -0.5))
                        lno_text.setPos(trigger_time, trigger_amplitude)
                        plot_widget.addItem(lno_text)
                    elif trace_type == "energy_filter":
                        plot_widget.plot(
                            [trigger_time],
                            [trigger_amplitude],
                            pen=None,
                            symbol="t",
                            symbolBrush="blue",
                            symbolPen=pg.mkPen(color="black", width=2),
                            symbolSize=8,
                            name="Energy Trigger" if idx == 0 else None,
                        )
                        # Add LNo text label for energy trigger alignment
                        lno_text = pg.TextItem(f"L{trigger_idx}", color=(0, 100, 255), anchor=(0.5, 1.5))
                        lno_text.setPos(trigger_time, trigger_amplitude)
                        plot_widget.addItem(lno_text)
                    elif trace_type == "cfd":
                        plot_widget.plot(
                            [trigger_time],
                            [trigger_amplitude],
                            pen=None,
                            symbol="s",
                            symbolBrush="magenta",
                            symbolPen=pg.mkPen(color="black", width=2),
                            symbolSize=8,
                            name="CFD Crossing" if idx == 0 else None,
                        )

        # Add peak sample markers - only if energy_filter trace type is enabled
        peak_info = self.peak_sample_points.get(channel, {})
        if ("energy_filter" in peak_info 
            and self.trace_types.get("energy_filter", False)):
            peak_samples = peak_info["energy_filter"]

            for idx, peak_idx in enumerate(peak_samples):
                if 0 <= peak_idx < len(time_axis) and 0 <= peak_idx < target_length:
                    corrected_time_axis = self.apply_time_correction(time_axis, "energy_filter")
                    peak_time = corrected_time_axis[peak_idx] if peak_idx < len(corrected_time_axis) else time_axis[peak_idx]

                    energy_signal = self.compute_hardware_traces("energy_filter", latest_trace, channel)
                    if energy_signal is not None and len(energy_signal) > peak_idx:
                        # Apply same scaling and baseline normalization as in plot
                        raw_amplitude = np.max(latest_trace) - np.min(latest_trace)
                        if np.max(energy_signal) > np.min(energy_signal):
                            signal_amplitude = np.max(energy_signal) - np.min(energy_signal)
                            scale_factor = (2 * raw_amplitude) / signal_amplitude
                            energy_signal = (energy_signal - np.min(energy_signal)) * scale_factor
                        # Apply baseline normalization to match plot
                        energy_signal = self.normalize_trace_to_zero_baseline(energy_signal, "energy_filter")

                        peak_amplitude = energy_signal[peak_idx]
                    else:
                        # Fallback to raw trace value with baseline normalization
                        raw_normalized = self.normalize_trace_to_zero_baseline(latest_trace, "raw")
                        peak_amplitude = raw_normalized[peak_idx] if peak_idx < len(raw_normalized) else raw_normalized[-1]

                    plot_widget.plot(
                        [peak_time],
                        [peak_amplitude],
                        pen=None,
                        symbol="d",
                        symbolBrush="cyan",
                        symbolPen=pg.mkPen(color="black", width=2),
                        symbolSize=12,
                        name="Peak Sample" if idx == 0 else None,
                    )

        # Add trapezoidal integration window lines (L-G-L regions)
        self._add_trapezoidal_window_lines(plot_widget, channel, time_axis, latest_trace)

    def _add_trapezoidal_window_lines(self, plot_widget, channel, time_axis, latest_trace):
        """Add vertical lines indicating the trapezoidal integration windows (L-G-L regions)."""
        # Only show lines if energy filter is enabled
        if not self.trace_types.get("energy_filter", False):
            return
            
        # Get trigger information
        trigger_info = self.trigger_points.get(channel, {})
        if "energy_filter" not in trigger_info or not trigger_info["energy_filter"]:
            return
            
        # Get energy filter parameters
        L = self.hardware_params["energy_L"]
        G = self.hardware_params["energy_G"]
        energy_R = self.hardware_params["energy_R"]
        
        # Calculate samples per energy cycle (energy filter decimation)
        samples_per_energy_cycle = 2 ** energy_R
        
        # Get the energy trigger position (where the trapezoidal filter starts)
        energy_trigger_indices = trigger_info["energy_filter"]
        if not energy_trigger_indices:
            return
            
        # Use the first trigger point
        energy_trigger_idx = energy_trigger_indices[0]
        
        # Apply time correction for energy filter
        corrected_time_axis = self.apply_time_correction(time_axis, "energy_filter")
        
        # Calculate the time positions for L-G-L regions
        if energy_trigger_idx < len(corrected_time_axis):
            trigger_time = corrected_time_axis[energy_trigger_idx]
            
            # Convert L and G from energy cycles to raw samples
            L_samples = L * samples_per_energy_cycle
            G_samples = G * samples_per_energy_cycle
            
            # Calculate time step
            time_step = corrected_time_axis[1] - corrected_time_axis[0] if len(corrected_time_axis) > 1 else 2.0
            
            # Calculate the boundary times
            leading_end_time = trigger_time + (L_samples * time_step)
            gap_end_time = leading_end_time + (G_samples * time_step)
            trailing_end_time = gap_end_time + (L_samples * time_step)
            
            # Add vertical lines for the boundaries
            # Leading edge end (start of gap)
            plot_widget.addItem(pg.InfiniteLine(
                pos=leading_end_time,
                angle=90,  # Vertical line
                pen=pg.mkPen(color='darkblue', style=pg.QtCore.Qt.PenStyle.DashLine, width=1.5),
                label='L',
                labelOpts={'position': 0.95, 'color': 'darkblue', 'anchor': (0, 1)}
            ))
            
            # Gap end (start of trailing edge)
            plot_widget.addItem(pg.InfiniteLine(
                pos=gap_end_time,
                angle=90,  # Vertical line
                pen=pg.mkPen(color='darkgreen', style=pg.QtCore.Qt.PenStyle.DashLine, width=1.5),
                label='G',
                labelOpts={'position': 0.95, 'color': 'darkgreen', 'anchor': (0, 1)}
            ))
            
            # Trailing edge end
            plot_widget.addItem(pg.InfiniteLine(
                pos=trailing_end_time,
                angle=90,  # Vertical line
                pen=pg.mkPen(color='darkblue', style=pg.QtCore.Qt.PenStyle.DashLine, width=1.5),
                label='L',
                labelOpts={'position': 0.95, 'color': 'darkblue', 'anchor': (0, 1)}
            ))

    def _add_threshold_lines(self, plot_widget, trace_data):
        if self.amplitude_threshold <= 0:
            return
            
        # Calculate baseline for threshold reference
        baseline = self.calculate_trace_baseline(trace_data)
        threshold_line = baseline + self.amplitude_threshold
        
        # Add horizontal threshold line
        plot_widget.addItem(pg.InfiniteLine(
            pos=threshold_line,
            angle=0,  # Horizontal line
            pen=pg.mkPen(color='red', style=pg.QtCore.Qt.PenStyle.DashLine, width=2),
            label=f'Threshold: {self.amplitude_threshold:.3f}',
            labelOpts={'position': 0.95, 'color': 'red'}
        ))

    def compute_hardware_traces(self, trace_type, latest_trace, channel):
        if trace_type == "raw":
            return latest_trace
        elif trace_type == "fast_trigger":
            # Compute actual fast trigger using real hardware parameters
            traces_fpga = convert_trace_to_FPGA(latest_trace[np.newaxis, :])
            
            fast_result = compute_fast_trigger_validation(
                traces_fpga,
                L=self.hardware_params["fast_L"],       # Real hardware parameter
                G=self.hardware_params["fast_G"],       # Real hardware parameter  
                threshold=self.hardware_params["fast_threshold"], # Real hardware parameter
            )
            
            if fast_result["validation_passed"] and fast_result["fast_triggers"] is not None:
                signal = fast_result["fast_triggers"][0]
                # Resize to match original trace length if needed
                target_length = len(latest_trace)
                if len(signal) != target_length:
                    signal = self._resize_trace_to_match(signal, target_length, "fast_trigger")
                return signal
            else:
                return None
        elif trace_type == "cfd":
            # Compute CFD using real hardware parameters
            traces_fpga = convert_trace_to_FPGA(latest_trace[np.newaxis, :])
            
            fast_result = compute_fast_trigger_validation(
                traces_fpga,
                L=self.hardware_params["fast_L"],       # Real hardware parameter
                G=self.hardware_params["fast_G"],       # Real hardware parameter
                threshold=self.hardware_params["fast_threshold"], # Real hardware parameter
            )
            
            if fast_result["validation_passed"] and fast_result["fast_triggers"] is not None:
                fast_trace = fast_result["fast_triggers"][0]
                
                # Calculate CFD with real hardware parameters
                cfd_result, cfdtime, fast_filter, cfd_errors = calculate_CFD(
                    fast_trace[np.newaxis, :],
                    CFD_threshold=self.hardware_params.get("CFD_threshold", 50),  # Real hardware parameter
                    w=self.hardware_params.get("CFD_delay", 5),                   # Real hardware parameter  
                    FF_threshold=self.hardware_params.get("FF_threshold", 100)    # Real hardware parameter
                )
                
                if cfd_result is not None and len(cfd_result) > 0:
                    signal = cfd_result[0]
                    # Resize to match original trace length if needed
                    target_length = len(latest_trace)
                    if len(signal) != target_length:
                        signal = self._resize_trace_to_match(signal, target_length, "cfd")
                    return signal
                else:
                    return None
            else:
                return None
        elif trace_type == "energy_filter":
            # Compute energy filter using real hardware parameters
            traces_fpga = convert_trace_to_FPGA(latest_trace[np.newaxis, :])
            
            fast_result = compute_fast_trigger_validation(
                traces_fpga,
                L=self.hardware_params["fast_L"],       # Real hardware parameter
                G=self.hardware_params["fast_G"],       # Real hardware parameter
                threshold=self.hardware_params["fast_threshold"], # Real hardware parameter
            )
            
            if fast_result["validation_passed"]:
                energy_result = compute_energy_filter(
                    traces_fpga,
                    R=self.hardware_params["energy_R"],     # Real hardware parameter
                    L=self.hardware_params["energy_L"],     # Real hardware parameter (L-G-L controls!)
                    G=self.hardware_params["energy_G"],     # Real hardware parameter (L-G-L controls!)
                    P=self.hardware_params["energy_P"],     # Real hardware parameter
                    decay_ns=self.hardware_params["decay_ns"], # Real hardware parameter
                    trigger_indices=fast_result["trigger_indices"],
                    baseline_index=fast_result["baseline_stats"]["baseline_index"],
                )
                
                if energy_result.get("energy_results"):
                    energy_expanded = energy_result["energy_results"][0]
                    
                    # Resize to match original length
                    target_length = len(latest_trace)
                    signal = self._resize_trace_to_match(energy_expanded, target_length, "energy_filter")
                    return signal
                else:
                    return None
            else:
                return None
        else:
            # Unknown trace type - no real algorithm available
            return None

    def verify_energy_calculation(self, channel, trace, pixie_reported_energy=None):
        try:
            if trace is None or len(trace) == 0:
                return {"error": "No trace data available"}
                
            # Get current hardware parameters
            L = self.hardware_params["energy_L"]
            G = self.hardware_params["energy_G"]
            R = self.hardware_params["energy_R"]
            P = self.hardware_params["energy_P"]
            
            # Convert to FPGA format
            fpga_trace = convert_trace_to_FPGA(np.array([trace]), R)
            
            # Get fast trigger position first 
            fast_result = compute_fast_trigger_validation(
                fpga_trace, 
                self.hardware_params["fast_L"],
                self.hardware_params["fast_G"],
                self.hardware_params["fast_threshold"],
                baseline_index=50
            )
            
            if not fast_result["validation_passed"] or not fast_result["trigger_indices"]:
                return {"error": "No valid trigger found"}
                
            trigger_index = fast_result["trigger_indices"][0]
            
            # Use energy filter computation instead
            energy_result = compute_energy_filter(fpga_trace, R, L, G, baseline_index=50)
            energy_data = energy_result["energy_results"][0] if energy_result.get("energy_results") else []
            
            # Calculate energy at peak sample position
            slow_filter_range = 2**R
            samples_per_energy_cycle = slow_filter_range * 5  # Convert to raw sample timing
            
            # Calculate peak sample position
            ramp_duration = (L + G) * samples_per_energy_cycle
            flat_area_start = ramp_duration  
            flat_area_length = P * samples_per_energy_cycle
            peak_sample_offset = flat_area_start + (flat_area_length // 2)
            
            # Calculate raw sample position
            fast_trigger_raw_pos = trigger_index * samples_per_energy_cycle
            peak_sample_raw_pos = fast_trigger_raw_pos + peak_sample_offset
            
            # Get energy value from energy filter
            energy_index = int(peak_sample_raw_pos // samples_per_energy_cycle)
            
            calculated_energy = None
            if 0 <= energy_index < len(energy_data):
                calculated_energy = energy_data[energy_index]
            
            # Also calculate using the hardware energy filter function
            energy_result = compute_energy_filter(
                fpga_trace,
                R=R, L=L, G=G, P=P,
                decay_ns=self.hardware_params["decay_ns"],
                trigger_indices=[trigger_index],
                baseline_index=50
            )
            
            hardware_calculated_energy = None
            if energy_result["energy_values"]:
                hardware_calculated_energy = energy_result["energy_values"][0]
            
            return {
                "channel": channel,
                "calculated_energy_manual": calculated_energy,
                "calculated_energy_hardware_function": hardware_calculated_energy, 
                "pixie_reported_energy": pixie_reported_energy,
                "peak_sample_position": peak_sample_raw_pos,
                "trigger_position": fast_trigger_raw_pos,
                "energy_index": energy_index,
                "parameters": {"L": L, "G": G, "R": R, "P": P},
                "energy_at_peak": calculated_energy
            }
            
        except Exception as e:
            return {"error": f"Energy verification failed: {str(e)}"}

    def clear_data(self):
        # Clear histogram data
        if hasattr(self, 'histogram_tab') and hasattr(self.histogram_tab, 'clear_data'):
            self.histogram_tab.clear_data()
            
        for channel in self.channels:
            self.trace_data[channel].clear()
            self.last_traces[channel] = None
            # Reset overflow counters to prevent memory leaks
            self.trace_overflow_count[channel] = 0
            self.timestamp_overflow_count[channel] = 0
            self.single_persistence_overflow_count[channel] = 0
            # Clear timestamps and persistence histogram
            self.trace_timestamps[channel].clear()
            self.persistence_histogram[channel].reset()
            self.persistence_update_counter[channel] = 0
            
        if hasattr(self, "coincidence_tab"):
            self.coincidence_tab.clear_data()
        for channel in self.channels:
            if channel in self.raw_curves:
                self.raw_curves[channel].setData([], [])
        for channel in self.channels:
            self.single_persistence_data[channel].clear()

        if self.replay_widget:
            self.replay_widget.clear_traces()

        self.update_plots()

    def set_display_channels(self, channels):
        print(f"TracesPlotter: set_display_channels called with {channels}")
        self.display_channels = channels if channels else []
        print(f"TracesPlotter: display_channels set to {self.display_channels}")
        
        # Update histogram tab
        if hasattr(self, 'histogram_tab'):
            self.histogram_tab.set_display_channels(self.display_channels)
        
        if hasattr(self, 'coincidence_tab') and self.coincidence_tab:
            self.coincidence_tab.set_channels(self.display_channels)
            print(f"TracesPlotter: Updated coincidence tab channels to {self.display_channels}")
        
        self.update_plots()

    def add_event(self, event):
        if hasattr(self, 'histogram_tab'):
            channel = getattr(event, 'channel', 0)
            energy = getattr(event, 'energy', 0)
            
            # Energy histogram handling - either calculated or Pixie-reported
            if hasattr(self.histogram_tab, 'use_calculated_energy') and self.histogram_tab.use_calculated_energy:
                # Calculated energy mode: compute energy from trace data
                trace = getattr(event, 'trace', None)
                if trace is not None and hasattr(self.histogram_tab, 'add_trace_for_energy_calculation'):
                    self.histogram_tab.add_trace_for_energy_calculation(channel, trace, self.hardware_params)
                # Skip Pixie-reported energy for histogram, but continue for trace display
            else:
                # Standard pixie-reported energy mode
                if hasattr(self.histogram_tab, 'add_energy_event'):
                    self.histogram_tab.add_energy_event(channel, energy)

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

        # Update histogram tab channels
        if hasattr(self, 'histogram_tab'):
            self.histogram_tab.set_channels(channels)

        # Update coincidence tab channels
        if hasattr(self, "coincidence_tab"):
            self.coincidence_tab.set_channels(channels)

        for ch in self.channels:
            self.channel_combo.addItem(f"Ch {ch}")

    def start_live_updates(self):        
        if hasattr(self, 'histogram_tab') and hasattr(self.histogram_tab, 'start_live_updates'):
            self.histogram_tab.start_live_updates()
            
        # Start coincidence tab updates if coincidence tab exists
        if hasattr(self, 'coincidence_tab') and hasattr(self.coincidence_tab, 'update_timer'):
            if not self.coincidence_tab.update_timer.isActive():
                self.coincidence_tab.update_timer.start(100)
                print("Traces Plotter: Started coincidence tab updates")
        
        if self.update_timer.thread() != self.thread():
            print("WARNING: Timer thread mismatch - recreating timer")
            self.update_timer = QTimer(self)
            self.update_timer.timeout.connect(self.update_plots)
            self.update_timer.setSingleShot(False)
    
        if not self.update_timer.isActive():
            self.update_timer.start(100)
            print("Traces Plotter: Started live updates - timer now active")
        else:
            pass

    def stop_live_updates(self):
        # Stop histogram updates if histogram tab exists
        if hasattr(self, 'histogram_tab') and hasattr(self.histogram_tab, 'stop_live_updates'):
            self.histogram_tab.stop_live_updates()
            
        # Stop coincidence tab updates if coincidence tab exists
        if hasattr(self, 'coincidence_tab') and hasattr(self.coincidence_tab, 'update_timer'):
            if self.coincidence_tab.update_timer.isActive():
                self.coincidence_tab.update_timer.stop()
                print("Traces Plotter: Stopped coincidence tab updates")
            
        if self.update_timer.isActive():
            self.update_timer.stop()
            print("Traces Plotter: Stopped live updates")

    def set_timing_settings(self, settings):
        self.trace_delay_ns = settings.get("trace_delay_ns", {})
        self.sampling_period_ns = settings.get("sampling_period_ns", 2.0)

    def get_coincidence_statistics(self):
        if hasattr(self, "coincidence_tab"):
            return self.coincidence_tab.get_coincidence_statistics()
        else:
            return {}

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
        self.replay_mode = enabled

        if enabled:
            # Switch to replay mode for hardware validation
            if self.replay_widget is not None:
                current_trace = self.replay_widget.get_current_trace()
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

    def create_single_channel_controls_widget(self):
        if self.single_channel_controls_widget is not None:
            return self.single_channel_controls_widget
        
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # ===== Channel Selection =====
        selector_group = QGroupBox("Channel Selection")
        selector_layout = QHBoxLayout()
        selector_layout.addWidget(QLabel("Channel:"))
        
        channel_combo = QComboBox()
        for ch in self.channels:
            channel_combo.addItem(f"Ch {ch}")
        channel_combo.setCurrentIndex(0)
        channel_combo.currentIndexChanged.connect(self.update_selected_channel)
        selector_layout.addWidget(channel_combo)
        self.channel_combo = channel_combo
        
        # Add polarity control for selected channel
        selector_layout.addWidget(QLabel("Polarity:"))
        polarity_combo = QComboBox()
        polarity_combo.addItem("Normal")
        polarity_combo.addItem("Inverted")
        polarity_combo.setCurrentIndex(0)
        polarity_combo.currentIndexChanged.connect(self.update_channel_polarity)
        selector_layout.addWidget(polarity_combo)
        self.polarity_combo = polarity_combo
        
        selector_layout.addStretch()
        selector_group.setLayout(selector_layout)
        selector_group.setMaximumHeight(80)
        layout.addWidget(selector_group)
        
        # ===== Trace Replay =====
        replay_widget = TraceReplayWidget(initial_buffer_size=1000)
        replay_widget.trace_selected.connect(self.on_hardware_replay_trace_selected)
        replay_widget.replay_mode_changed.connect(self.on_hardware_replay_mode_changed)
        replay_widget.setMaximumHeight(150)
        layout.addWidget(replay_widget)
        self.replay_widget = replay_widget
        
        # ===== Trace Types =====
        trace_types_group = QGroupBox("Trace Types")
        trace_types_layout = QGridLayout()
        
        raw_traces_cb = QCheckBox("Raw")
        raw_traces_cb.setChecked(True)
        raw_traces_cb.toggled.connect(lambda: self.toggle_trace_type("raw"))
        trace_types_layout.addWidget(raw_traces_cb, 0, 0)
        self.raw_traces_cb = raw_traces_cb
        
        fast_trigger_cb = QCheckBox("Fast Trigger")
        fast_trigger_cb.toggled.connect(lambda: self.toggle_trace_type("fast_trigger"))
        trace_types_layout.addWidget(fast_trigger_cb, 0, 1)
        self.fast_trigger_cb = fast_trigger_cb
        
        energy_filter_cb = QCheckBox("Energy")
        energy_filter_cb.toggled.connect(lambda: self.toggle_trace_type("energy_filter"))
        trace_types_layout.addWidget(energy_filter_cb, 1, 0)
        self.energy_filter_cb = energy_filter_cb
        
        cfd_cb = QCheckBox("CFD")
        cfd_cb.toggled.connect(lambda: self.toggle_trace_type("cfd"))
        trace_types_layout.addWidget(cfd_cb, 1, 1)
        self.cfd_cb = cfd_cb
        
        # Energy Filter Calibration Controls
        energy_filter_group = self.create_energy_filter_controls()
        trace_types_layout.addWidget(energy_filter_group, 2, 0, 1, 2)  # Span both columns
        
        trace_types_group.setLayout(trace_types_layout)
        
        # Wrap trace types in scroll area for better visibility  
        scroll_area = QScrollArea()
        scroll_area.setWidget(trace_types_group)
        scroll_area.setWidgetResizable(True)
        scroll_area.setMaximumHeight(200)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(scroll_area)
        
        # ===== Persistence Controls =====
        persistence_group = QGroupBox("Persistence")
        persistence_layout = QGridLayout()
        
        single_persistence_cb = QCheckBox("Enable")
        single_persistence_cb.toggled.connect(self.toggle_single_persistence)
        persistence_layout.addWidget(single_persistence_cb, 0, 0)
        self.single_persistence_cb = single_persistence_cb
        
        persistence_layout.addWidget(QLabel("Count:"), 0, 1)
        single_persistence_count_spin = QSpinBox()
        single_persistence_count_spin.setRange(2, 10000)
        single_persistence_count_spin.setValue(1000)
        single_persistence_count_spin.valueChanged.connect(self.update_single_persistence_count)
        persistence_layout.addWidget(single_persistence_count_spin, 0, 2)
        self.single_persistence_count_spin = single_persistence_count_spin
        
        single_normalize_cb = QCheckBox("Normalize")
        single_normalize_cb.toggled.connect(self.toggle_single_normalize)
        persistence_layout.addWidget(single_normalize_cb, 1, 0)
        self.single_normalize_cb = single_normalize_cb
        
        single_alpha_fade_cb = QCheckBox("Alpha Fade")
        single_alpha_fade_cb.toggled.connect(self.toggle_single_alpha_fade)
        persistence_layout.addWidget(single_alpha_fade_cb, 1, 1)
        self.single_alpha_fade_cb = single_alpha_fade_cb
        
        
        save_btn = QPushButton("Save Buffer")
        save_btn.clicked.connect(self.save_traces_buffer)
        persistence_layout.addWidget(save_btn, 2, 0, 1, 2)
        
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_persistence_only)
        persistence_layout.addWidget(clear_btn, 2, 2)
        
        persistence_group.setLayout(persistence_layout)
        persistence_group.setMaximumHeight(120)
        layout.addWidget(persistence_group)
        
        # ===== Current Parameters =====
        params_group = QGroupBox("Current Parameters")
        params_layout = QVBoxLayout()
        
        parameter_info_label = QLabel()
        parameter_info_label.setStyleSheet("font-family: monospace; font-size: 8pt;")
        parameter_info_label.setWordWrap(True)
        parameter_info_label.setMinimumHeight(80)
        self.parameter_info_label = parameter_info_label
        self.update_parameter_info_display()
        
        params_layout.addWidget(parameter_info_label)
        params_group.setLayout(params_layout)
        params_group.setMaximumHeight(150)
        layout.addWidget(params_group)
        
        layout.addStretch()
        
        widget.setLayout(layout)
        self.single_channel_controls_widget = widget
        
        print(f"Created Single Channel controls widget with {len(widget.findChildren(QWidget))} child widgets")
        
        return widget

    def create_energy_filter_controls(self):
        """Create real-time L/G energy filter controls for calibration."""
        
        group = QGroupBox("Energy Filter (L-G-L) - Live Calibration")
        
        # Use vertical layout to fit more information
        main_layout = QVBoxLayout()
        
        # Add explanatory text
        info_label = QLabel("Trapezoidal Filter: L samples (leading) + G samples (gap) + L samples (trailing)")
        info_label.setStyleSheet("font-size: 10px; color: gray; font-style: italic;")
        main_layout.addWidget(info_label)
        
        # Controls layout
        controls_layout = QHBoxLayout()
        
        # Energy L control with more prominent styling
        l_label = QLabel("L (both edges):")
        l_label.setStyleSheet("font-weight: bold; color: blue;")
        controls_layout.addWidget(l_label)
        
        self.energy_L_spin = QSpinBox()
        self.energy_L_spin.setRange(1, 200)
        self.energy_L_spin.setValue(self.hardware_params.get("energy_L", 10))
        self.energy_L_spin.valueChanged.connect(self.on_energy_L_changed)
        self.energy_L_spin.setMinimumWidth(60)  # Make sure it's visible
        self.energy_L_spin.setToolTip("Length of both leading and trailing edges in L-G-L trapezoidal filter")
        controls_layout.addWidget(self.energy_L_spin)
        
        # Add some spacing
        controls_layout.addWidget(QLabel("  "))
        
        # Energy G control with more prominent styling  
        g_label = QLabel("G (gap):")
        g_label.setStyleSheet("font-weight: bold; color: green;")
        controls_layout.addWidget(g_label)
        
        self.energy_G_spin = QSpinBox()
        self.energy_G_spin.setRange(1, 100)
        self.energy_G_spin.setValue(self.hardware_params.get("energy_G", 5))
        self.energy_G_spin.valueChanged.connect(self.on_energy_G_changed)
        self.energy_G_spin.setMinimumWidth(60)  # Make sure it's visible
        self.energy_G_spin.setToolTip("Length of flat top (gap) in L-G-L trapezoidal filter")
        controls_layout.addWidget(self.energy_G_spin)
        
        # Add stretch to prevent compression
        controls_layout.addStretch()
        
        main_layout.addLayout(controls_layout)
        
        # Auto-enable energy filter when controls are visible
        if hasattr(self, 'energy_filter_cb'):
            self.energy_filter_cb.setChecked(True)
            self.toggle_trace_type("energy_filter")
        
        group.setLayout(main_layout)
        group.setMinimumHeight(80)  # Increased for vertical layout
        return group
    
    def on_energy_L_changed(self, value):
        """Handle real-time L parameter changes."""
        self.hardware_params["energy_L"] = value
        # Force immediate trace recomputation and display update
        self.update_hardware_validation_plots()
        
    def on_energy_G_changed(self, value):
        """Handle real-time G parameter changes."""
        self.hardware_params["energy_G"] = value  
        # Force immediate trace recomputation and display update
        self.update_hardware_validation_plots()

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
                    # Apply polarity inversion if enabled for this channel
                    if not self.channel_polarity.get(channel, True):
                        signal = -signal
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
            
            # Use auto-range with padding
            plot_widget.autoRange(padding=0.02)  # 2% padding
            
        except Exception as e:
            print(f"Error updating {label} replay plot: {e}")
    
    def enable_enhanced_coincidence_analysis(self, reference_channel=9):
        if not hasattr(self, 'coincidence_tab'):
            print("No coincidence tab available")
            return
        
        # Set reference channel 
        if reference_channel in self.channels:
            ref_idx = self.channels.index(reference_channel)
            self.coincidence_tab.center_channel_combo.setCurrentIndex(ref_idx)
            self.coincidence_tab.center_channel = reference_channel
            
            # Set as first channel for binary logic
            self.coincidence_tab.ch1_combo.setCurrentIndex(ref_idx)
            self.coincidence_tab.channel1 = reference_channel
        
        # Find second channel 
        second_channel = next((ch for ch in self.channels if ch != reference_channel), self.channels[0])
        if second_channel in self.channels:
            ch2_idx = self.channels.index(second_channel)
            self.coincidence_tab.ch2_combo.setCurrentIndex(ch2_idx)
            self.coincidence_tab.channel2 = second_channel
        
        # Set reasonable coincidence window
        self.coincidence_tab.time_window_spin.setValue(20.0)
        self.coincidence_tab.update_coincidence_window()
        
        # Enable binary logic visualization
        self.coincidence_tab.enable_checkbox.setChecked(True)
        self.coincidence_tab.toggle_binary_logic(True)
        
        # Sync parameters
        self.sync_parameters_to_coincidence_tab()
        
        print(f"  Reference channel: {reference_channel}")
        print(f"  Second channel: {second_channel}")
        print("Enhanced coincidence analysis ready!")
    
    def handle_controls_widget_request(self, widget):
        # Forward the request to main app
        self.request_right_panel_swap.emit(widget)
        print(f"TracesPlotter: Forwarding controls widget request: {widget}")