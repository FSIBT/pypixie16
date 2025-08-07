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
    QSlider,
    QFrame,
    QSplitter,
)
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal
import pyqtgraph as pg

import pixie16 as px


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
        self.selected_channel_a = 0
        self.selected_channel_b = 1
        self.selected_channels = [0, 1]
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

        self.setWindowTitle(title)
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
        self.tab_widget.addTab(hardware_validation_tab, "Hardware Trigger Validation")

        coincidence_analysis_tab = self.create_coincidence_analysis_tab()
        self.tab_widget.addTab(coincidence_analysis_tab, "Coincidence Analysis")

        layout.addWidget(self.tab_widget)
        self.setLayout(layout)

    def create_raw_traces_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        controls_group = QGroupBox("Display Controls")
        controls_group.setMaximumHeight(100)
        controls_layout = QHBoxLayout()

        # Max traces
        controls_layout.addWidget(QLabel("Max Traces:"))
        self.max_traces_spin = QSpinBox()
        self.max_traces_spin.setRange(1, 50)
        self.max_traces_spin.setValue(self.max_traces_display)
        self.max_traces_spin.valueChanged.connect(self.update_max_traces)
        controls_layout.addWidget(self.max_traces_spin)

        # Threshold
        controls_layout.addWidget(QLabel("Threshold:"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 2.0)
        self.threshold_spin.setValue(self.amplitude_threshold)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.valueChanged.connect(self.update_threshold)
        controls_layout.addWidget(self.threshold_spin)

        # Auto scale
        self.auto_scale_cb = QCheckBox("Auto Scale")
        self.auto_scale_cb.setChecked(True)
        self.auto_scale_cb.toggled.connect(self.toggle_auto_scale)
        controls_layout.addWidget(self.auto_scale_cb)

        # Simple coincidence mode toggle
        self.simple_coincidence_cb = QCheckBox("Coincidence Mode")
        self.simple_coincidence_cb.toggled.connect(self.toggle_simple_coincidence)
        controls_layout.addWidget(self.simple_coincidence_cb)

        # Clear button
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_data)
        controls_layout.addWidget(self.clear_btn)

        controls_layout.addStretch()
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

    def create_hardware_validation_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Channel pair selector
        selector_group = QGroupBox("Channel Pair Selection")
        selector_layout = QHBoxLayout()
        selector_layout.setContentsMargins(8, 2, 8, 2)
        selector_layout.setSpacing(8)

        selector_layout.addWidget(QLabel("Channel A:"))
        self.channel_a_combo = QComboBox()
        for ch in self.channels:
            self.channel_a_combo.addItem(f"Ch {ch}")
        self.channel_a_combo.setCurrentIndex(0)
        self.channel_a_combo.currentIndexChanged.connect(self.update_channel_a)
        selector_layout.addWidget(self.channel_a_combo)

        selector_layout.addWidget(QLabel("Channel B:"))
        self.channel_b_combo = QComboBox()
        for ch in self.channels:
            self.channel_b_combo.addItem(f"Ch {ch}")
        self.channel_b_combo.setCurrentIndex(1 if len(self.channels) > 1 else 0)
        self.channel_b_combo.currentIndexChanged.connect(self.update_channel_b)
        selector_layout.addWidget(self.channel_b_combo)

        selector_layout.addStretch()
        selector_group.setLayout(selector_layout)
        layout.addWidget(selector_group)

        # Hardware parameter controls
        params_group = QGroupBox("Hardware Timing Parameters")
        params_layout = QGridLayout()

        # Fast Trigger Backplane Delay (0-255)
        params_layout.addWidget(QLabel("Fast Trigger Backplane Delay:"), 0, 0)
        self.ft_backplane_delay_slider = QSlider(Qt.Orientation.Horizontal)
        self.ft_backplane_delay_slider.setRange(0, 255)
        self.ft_backplane_delay_slider.setValue(100)
        self.ft_backplane_delay_slider.valueChanged.connect(
            self.update_ft_backplane_delay
        )
        params_layout.addWidget(self.ft_backplane_delay_slider, 0, 1)
        self.ft_backplane_delay_label = QLabel("100")
        params_layout.addWidget(self.ft_backplane_delay_label, 0, 2)

        # Fast Trigger Backplane Length (1-511)
        params_layout.addWidget(QLabel("Fast Trigger Backplane Length:"), 1, 0)
        self.ft_backplane_length_slider = QSlider(Qt.Orientation.Horizontal)
        self.ft_backplane_length_slider.setRange(1, 511)
        self.ft_backplane_length_slider.setValue(100)
        self.ft_backplane_length_slider.valueChanged.connect(
            self.update_ft_backplane_length
        )
        params_layout.addWidget(self.ft_backplane_length_slider, 1, 1)
        self.ft_backplane_length_label = QLabel("100")
        params_layout.addWidget(self.ft_backplane_length_label, 1, 2)

        # Channel Trigger Stretch (1-511)
        params_layout.addWidget(QLabel("Channel Trigger Stretch:"), 2, 0)
        self.channel_trigger_stretch_slider = QSlider(Qt.Orientation.Horizontal)
        self.channel_trigger_stretch_slider.setRange(1, 511)
        self.channel_trigger_stretch_slider.setValue(100)
        self.channel_trigger_stretch_slider.valueChanged.connect(
            self.update_channel_trigger_stretch
        )
        params_layout.addWidget(self.channel_trigger_stretch_slider, 2, 1)
        self.channel_trigger_stretch_label = QLabel("100")
        params_layout.addWidget(self.channel_trigger_stretch_label, 2, 2)

        # External Delay Length (1-511)
        params_layout.addWidget(QLabel("External Delay Length:"), 3, 0)
        self.external_delay_length_slider = QSlider(Qt.Orientation.Horizontal)
        self.external_delay_length_slider.setRange(1, 511)
        self.external_delay_length_slider.setValue(100)
        self.external_delay_length_slider.valueChanged.connect(
            self.update_external_delay_length
        )
        params_layout.addWidget(self.external_delay_length_slider, 3, 1)
        self.external_delay_length_label = QLabel("100")
        params_layout.addWidget(self.external_delay_length_label, 3, 2)

        # Apply to Hardware button
        self.apply_hw_btn = QPushButton("Apply to Hardware")
        self.apply_hw_btn.clicked.connect(self.apply_hardware_parameters)
        params_layout.addWidget(self.apply_hw_btn, 4, 0, 1, 3)

        params_group.setLayout(params_layout)
        layout.addWidget(params_group)

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

        # Dual-panel display
        display_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Channel A panel
        channel_a_widget = QWidget()
        channel_a_layout = QVBoxLayout(channel_a_widget)
        channel_a_layout.addWidget(QLabel("Channel A"))
        self.channel_a_plot = pg.PlotWidget()
        self.channel_a_plot.setLabel("left", "Amplitude")
        self.channel_a_plot.setLabel("bottom", "Time (ns)")
        self.channel_a_plot.setTitle("Channel A Validation")
        self.channel_a_plot.showGrid(True, True, alpha=0.3)
        self.channel_a_plot.setBackground("w")
        channel_a_layout.addWidget(self.channel_a_plot)

        # Channel B panel
        channel_b_widget = QWidget()
        channel_b_layout = QVBoxLayout(channel_b_widget)
        channel_b_layout.addWidget(QLabel("Channel B"))
        self.channel_b_plot = pg.PlotWidget()
        self.channel_b_plot.setLabel("left", "Amplitude")
        self.channel_b_plot.setLabel("bottom", "Time (ns)")
        self.channel_b_plot.setTitle("Channel B Validation")
        self.channel_b_plot.showGrid(True, True, alpha=0.3)
        self.channel_b_plot.setBackground("w")
        channel_b_layout.addWidget(self.channel_b_plot)

        display_splitter.addWidget(channel_a_widget)
        display_splitter.addWidget(channel_b_widget)
        layout.addWidget(display_splitter)

        self.hardware_status_label = QLabel("Hardware Status: Ready")
        layout.addWidget(self.hardware_status_label)

        # Initialize plot curves for hardware validation
        self.hw_curves_a = {}
        self.hw_curves_b = {}
        for trace_type in self.trace_types.keys():
            self.hw_curves_a[trace_type] = self.channel_a_plot.plot(
                pen=pg.mkPen(color="blue", width=1.5), name=trace_type
            )
            self.hw_curves_b[trace_type] = self.channel_b_plot.plot(
                pen=pg.mkPen(color="red", width=1.5), name=trace_type
            )

        return tab

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
    def update_channel_a(self):
        self.selected_channel_a = self.channels[self.channel_a_combo.currentIndex()]

    def update_channel_b(self):
        self.selected_channel_b = self.channels[self.channel_b_combo.currentIndex()]

    def update_ft_backplane_delay(self, value):
        self.ft_backplane_delay_label.setText(str(value))

        if not self.hardware_manager:
            return
        if self.hardware_manager.dummy_mode:
            print(f"DUMMY MODE: FastTrigBackplaneEna = {value}")
            return

        try:
            import pixie16 as px

            px.control.set_module_parameter("FastTrigBackplaneEna", value, 0)
            print(f"HARDWARE: Applied FastTrigBackplaneEna = {value}")
        except Exception as e:
            print(f"Hardware Error: {e}")

    def update_ft_backplane_length(self, value):
        self.ft_backplane_length_label.setText(str(value))

        if not self.hardware_manager:
            return
        if self.hardware_manager.dummy_mode:
            print(f"DUMMY MODE: FastTrigBackLen = {value}")
            return

        try:
            import pixie16 as px

            for channel in [self.selected_channel_a, self.selected_channel_b]:
                px.control.set_channel_parameter("FastTrigBackLen", value, 0, channel)
            print(f"HARDWARE: Applied FastTrigBackLen = {value}")
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
                f"FastTrigBackLen: {self.ft_backplane_length_slider.value()}",  # CHANNEL
                f"ChanTrigStretch: {self.channel_trigger_stretch_slider.value()}",  # CHANNEL
                f"ExternDelayLen: {self.external_delay_length_slider.value()}",  # CHANNEL
                f"Channels: {[self.selected_channel_a, self.selected_channel_b]}",
            ]

            QMessageBox.information(
                self,
                "Dummy Mode",
                f"DUMMY MODE: Would apply parameters:\n" + "\n".join(params_summary),
            )
            return

        try:
            import pixie16 as px

            success_count = 0
            failed_params = []
            selected_channels = [self.selected_channel_a, self.selected_channel_b]

            # Module-level parameter
            try:
                px.control.set_module_parameter(
                    "FastTrigBackplaneEna", self.ft_backplane_delay_slider.value(), 0
                )
                success_count += 1
            except Exception as e:
                failed_params.append(f"FastTrigBackplaneEna: {e}")

            # Channel-level parameters
            channel_params = {
                "FastTrigBackLen": self.ft_backplane_length_slider.value(),
                "ChanTrigStretch": self.channel_trigger_stretch_slider.value(),
                "ExternDelayLen": self.external_delay_length_slider.value(),
            }

            for param_name, value in channel_params.items():
                try:
                    for channel in selected_channels:
                        px.control.set_channel_parameter(param_name, value, 0, channel)
                    success_count += len(selected_channels)
                except Exception as e:
                    failed_params.append(f"{param_name}: {e}")

            # Report results
            if success_count > 0 and not failed_params:
                QMessageBox.information(
                    self,
                    "Parameters Applied",
                    f"HARDWARE: Successfully applied {success_count} parameter updates",
                )
            elif failed_params:
                QMessageBox.warning(
                    self,
                    "Partial Failure",
                    f"Some parameters failed:\n" + "\n".join(failed_params),
                )
            else:
                QMessageBox.warning(
                    self, "Application Failed", "No parameters applied successfully"
                )

        except Exception as e:
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
            import csv

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
        if not self.coincidence_mode:
            self.add_trace(event.channel, trace_data)
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

    def add_trace(self, channel, trace_data):
        try:
            if channel not in self.channels:
                return

            if not isinstance(trace_data, np.ndarray):
                trace_data = np.array(trace_data)

            if len(trace_data) == 0:
                return

            # Apply amplitude threshold filter
            if len(trace_data) > 10:
                amplitude = np.max(trace_data) - np.min(trace_data)
                if amplitude >= self.amplitude_threshold:
                    self.trace_data[channel].append(trace_data)
            else:
                self.trace_data[channel].append(trace_data)

        except Exception as e:
            print(f"Error adding trace to channel {channel}: {e}")

    def calculate_real_time_axis(self, trace_length, channel):
        if not self.use_realtime_axis:
            return np.arange(trace_length)

        trace_delay = self.trace_delay_ns.get(channel, 200)
        sample_times = np.arange(trace_length) * self.sampling_period_ns
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
                total_traces += len(traces)
                display_traces = traces[-self.max_traces_display :]

                if display_traces:
                    trace_length = len(display_traces[0])
                    time_axis = self.calculate_real_time_axis(trace_length, channel)

                    combined_y = []
                    combined_x = []

                    for i, trace in enumerate(display_traces):
                        if len(trace) == trace_length:
                            offset = i * 0.01
                            y_data = trace + offset

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
            stats_text += f"Displayed Channels: {len(self.display_channels)}"

            self.raw_stats_label.setText(stats_text)

            # Auto scale if enabled
            if self.auto_scale and total_traces > 0:
                self.raw_plot_widget.autoRange()

        except Exception as e:
            print(f"Error updating raw traces plot: {e}")

    def update_hardware_validation_plots(self):
        try:
            # Update Channel A plot
            self.update_channel_validation_plot(
                self.selected_channel_a,
                self.channel_a_plot,
                self.hw_curves_a,
                "Channel A",
            )

            # Update Channel B plot
            self.update_channel_validation_plot(
                self.selected_channel_b,
                self.channel_b_plot,
                self.hw_curves_b,
                "Channel B",
            )

        except Exception as e:
            print(f"Error updating hardware validation plots: {e}")

    def update_channel_validation_plot(self, channel, plot_widget, curves, label):
        try:
            if channel not in self.trace_data or len(self.trace_data[channel]) == 0:
                # Clear all curves if no data
                for trace_type, curve in curves.items():
                    curve.setData([], [])
                return

            # Get latest trace
            latest_trace = list(self.trace_data[channel])[-1]
            time_axis = self.calculate_real_time_axis(len(latest_trace), channel)

            # Update enabled trace types
            for trace_type, enabled in self.trace_types.items():
                if enabled and trace_type in curves:
                    if trace_type == "raw":
                        curves[trace_type].setData(time_axis, latest_trace)
                    else:
                        # Use unified hardware computation for all processed trace types
                        signal = self.compute_hardware_traces(
                            trace_type, latest_trace, channel
                        )
                        if signal is not None:
                            curves[trace_type].setData(time_axis, signal)
                        else:
                            curves[trace_type].setData([], [])
                else:
                    curves[trace_type].setData([], [])

            plot_widget.setTitle(f"{label} - Ch {channel}")

        except Exception as e:
            print(f"Error updating {label} plot: {e}")

    def compute_hardware_traces(self, trace_type, raw_trace, channel):
        if not self.hardware_manager:
            return self.fallback_simulation(trace_type, raw_trace)

        if self.hardware_manager.dummy_mode:
            return self.fallback_simulation(trace_type, raw_trace)

        # Import pixie16 control
        try:
            import pixie16 as px
        except ImportError:
            return self.fallback_simulation(trace_type, raw_trace)

        try:
            # Convert for PIXIE SDK
            trace_length = len(raw_trace)
            raw_trace_buffer = raw_trace.astype(np.uint16)

            # UPDATE: Handle the actual trace type names from your checkboxes
            if trace_type in [
                "fast_trigger",
                "cfd",
            ]:  # Note: 'fast_trigger' not 'fast_filter'
                # Allocate output buffers
                fast_filter_buffer = np.zeros(trace_length, dtype=np.float64)
                cfd_buffer = np.zeros(trace_length, dtype=np.float64)

                # REAL HARDWARE: Call PIXIE SDK
                ret_val = px.control.compute_fast_filters_offline(
                    module_number=0,
                    channel_number=channel,
                    recorded_trace=raw_trace_buffer,
                    fast_filter_output=fast_filter_buffer,
                    cfd_output=cfd_buffer,
                )

                if ret_val == 0:  # Success
                    if trace_type == "fast_trigger":  # UPDATE: match checkbox name
                        return fast_filter_buffer
                    elif trace_type == "cfd":
                        return cfd_buffer

            elif trace_type == "energy_filter":
                # Use hardware parameters
                rise_time = (
                    self.hardware_manager.get_parameter("ENERGY_RISETIME", 0, channel)
                    or 10.0
                )
                flat_top = (
                    self.hardware_manager.get_parameter("ENERGY_FLATTOP", 0, channel)
                    or 5.0
                )
                return self.compute_trapezoidal_filter(raw_trace, rise_time, flat_top)

        except Exception as e:
            print(f"Hardware error: {e}")

        return self.fallback_simulation(trace_type, raw_trace)

    def fallback_simulation(self, trace_type, trace):
        if trace_type == "fast_trigger":  # UPDATE: match checkbox name
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
