"""
TracesPlotter with Coincidence Analysis and Window Optimization
Displays real-time ADC traces from PIXIE-16 channels
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
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal
import pyqtgraph as pg


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
        """Test different window sizes and count valid coincidences"""
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
        """Calculate time difference in nanoseconds"""
        # PIXIE-16 timestamps are typically in 10ns units
        dt_ticks = timestamp1 - timestamp2
        dt_ns = dt_ticks * 10.0  # Convert to nanoseconds
        return dt_ns


class CoincidenceEvent:
    """Represents a coincidence event with center event and associated traces"""

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
    """TracesPlotter with coincidence analysis and window optimization"""

    def __init__(self, channels=None, title="PIXIE-16 Traces"):
        super().__init__()

        self.channels = channels or list(range(16))
        self.display_channels = self.channels.copy()

        # Trace storage
        self.trace_data = {ch: deque(maxlen=1000) for ch in self.channels}
        self.last_traces = {ch: None for ch in self.channels}

        # Event storage for coincidence analysis
        self.event_buffer = deque(maxlen=50000)  # Increased buffer size
        self.coincidence_events = deque(maxlen=10000)  # Increased storage

        # Display settings
        self.max_traces_display = 10
        self.trace_length_ns = 1000
        self.time_per_sample = 2.0
        self.amplitude_threshold = 0.1
        self.auto_scale = True
        self.show_statistics = True

        # Real-time axis settings
        self.use_realtime_axis = True
        self.trace_delay_ns = {}
        self.sampling_period_ns = 2.0
        self.alpha_channel = 9

        self.coincidence_mode = False
        self.center_channel = 9
        self.coincidence_window_ns = 20.0  # Start with smaller window
        self.show_timing_stats = True
        self.validation_window_optimization = False

        # Window optimization settings
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

        # Main traces tab
        main_tab = QWidget()
        main_layout = QVBoxLayout(main_tab)

        # Controls
        controls = self.create_controls()
        main_layout.addWidget(controls)

        # Plot area
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel("left", "Amplitude (V)")
        self.plot_widget.setLabel("bottom", "Time (ns) - Real-Time Axis")
        self.plot_widget.setTitle("PIXIE-16 Traces - Real-Time Axis")
        self.plot_widget.showGrid(True, True, alpha=0.3)
        self.plot_widget.addLegend()
        self.plot_widget.setBackground("w")
        main_layout.addWidget(self.plot_widget)

        # Statistics display
        self.stats_label = QLabel("Statistics: Waiting for traces...")
        main_layout.addWidget(self.stats_label)

        # Coincidence statistics
        self.coincidence_stats_label = QLabel("Coincidence: Disabled")
        main_layout.addWidget(self.coincidence_stats_label)

        self.tab_widget.addTab(main_tab, "Traces")

        # Window optimization tab
        optimization_tab = self.create_optimization_tab()
        self.tab_widget.addTab(optimization_tab, "Window Optimization")

        # Timing analysis tab
        timing_tab = self.create_timing_analysis_tab()
        self.tab_widget.addTab(timing_tab, "Timing Analysis")

        layout.addWidget(self.tab_widget)
        self.setLayout(layout)

        # Initialize plot curves
        self.curves = {}
        for i, channel in enumerate(self.channels):
            color = self.colors[i % len(self.colors)]
            self.curves[channel] = self.plot_widget.plot(
                pen=pg.mkPen(color=color, width=1.5), name=f"Ch {channel}"
            )

    def create_controls(self):
        group = QGroupBox("Trace & Coincidence Controls")
        group.setMaximumHeight(200)
        layout = QVBoxLayout()
        layout.setSpacing(3)

        # Row 1 - Basic controls
        row1_layout = QHBoxLayout()
        row1_layout.addWidget(QLabel("Max:"))
        self.max_traces_spin = QSpinBox()
        self.max_traces_spin.setRange(1, 50)
        self.max_traces_spin.setValue(self.max_traces_display)
        self.max_traces_spin.valueChanged.connect(self.update_max_traces)
        row1_layout.addWidget(self.max_traces_spin)

        row1_layout.addWidget(QLabel("Threshold:"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 2.0)
        self.threshold_spin.setValue(self.amplitude_threshold)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.valueChanged.connect(self.update_threshold)
        row1_layout.addWidget(self.threshold_spin)

        self.auto_scale_cb = QCheckBox("Auto Scale")
        self.auto_scale_cb.setChecked(True)
        self.auto_scale_cb.toggled.connect(self.toggle_auto_scale)
        row1_layout.addWidget(self.auto_scale_cb)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_data)
        row1_layout.addWidget(self.clear_btn)

        row1_layout.addStretch()

        # Row 2 - Coincidence controls
        row2_layout = QHBoxLayout()

        self.coincidence_cb = QCheckBox("Coincidence Mode")
        self.coincidence_cb.toggled.connect(self.toggle_coincidence_mode)
        row2_layout.addWidget(self.coincidence_cb)

        row2_layout.addWidget(QLabel("Center Ch:"))
        self.center_channel_combo = QComboBox()
        for ch in self.channels:
            self.center_channel_combo.addItem(f"Ch {ch}")
        self.center_channel_combo.setCurrentIndex(9 if 9 in self.channels else 0)
        self.center_channel_combo.currentIndexChanged.connect(
            self.update_center_channel
        )
        row2_layout.addWidget(self.center_channel_combo)

        row2_layout.addWidget(QLabel("Window:"))
        self.time_window_spin = QDoubleSpinBox()
        self.time_window_spin.setRange(5.0, 1000.0)
        self.time_window_spin.setValue(self.coincidence_window_ns)
        self.time_window_spin.setSuffix(" ns")
        self.time_window_spin.valueChanged.connect(self.update_coincidence_window)
        row2_layout.addWidget(self.time_window_spin)

        # Quick window presets
        self.quick_window_combo = QComboBox()
        self.quick_window_combo.addItems(
            ["10ns", "20ns", "50ns", "100ns", "200ns", "500ns"]
        )
        self.quick_window_combo.setCurrentText("20ns")
        self.quick_window_combo.currentTextChanged.connect(self.set_quick_window)
        row2_layout.addWidget(self.quick_window_combo)

        row2_layout.addStretch()

        # Row 3 - Optimization controls
        row3_layout = QHBoxLayout()

        self.optimize_btn = QPushButton("Optimize Window")
        self.optimize_btn.clicked.connect(self.start_window_optimization)
        row3_layout.addWidget(self.optimize_btn)

        self.validation_cb = QCheckBox("Live Validation")
        self.validation_cb.toggled.connect(self.toggle_validation_mode)
        row3_layout.addWidget(self.validation_cb)

        self.save_settings_btn = QPushButton("Save Settings")
        self.save_settings_btn.clicked.connect(self.save_coincidence_settings)
        row3_layout.addWidget(self.save_settings_btn)

        row3_layout.addStretch()

        layout.addLayout(row1_layout)
        layout.addLayout(row2_layout)
        layout.addLayout(row3_layout)

        group.setLayout(layout)
        return group

    def create_optimization_tab(self):
        """Create window optimization tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Optimization controls
        controls_group = QGroupBox("Window Optimization Settings")
        controls_layout = QVBoxLayout()

        # Range settings
        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel("Test Range:"))

        self.min_window_spin = QDoubleSpinBox()
        self.min_window_spin.setRange(5.0, 1000.0)
        self.min_window_spin.setValue(10.0)
        self.min_window_spin.setSuffix(" ns")
        range_layout.addWidget(self.min_window_spin)

        range_layout.addWidget(QLabel("to"))

        self.max_window_spin = QDoubleSpinBox()
        self.max_window_spin.setRange(10.0, 2000.0)
        self.max_window_spin.setValue(200.0)
        self.max_window_spin.setSuffix(" ns")
        range_layout.addWidget(self.max_window_spin)

        range_layout.addWidget(QLabel("Step:"))
        self.step_window_spin = QDoubleSpinBox()
        self.step_window_spin.setRange(1.0, 50.0)
        self.step_window_spin.setValue(10.0)
        self.step_window_spin.setSuffix(" ns")
        range_layout.addWidget(self.step_window_spin)

        controls_layout.addLayout(range_layout)

        # Progress bar
        self.optimization_progress = QProgressBar()
        controls_layout.addWidget(self.optimization_progress)

        # Status label
        self.optimization_status = QLabel("Ready to optimize")
        controls_layout.addWidget(self.optimization_status)

        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)

        # Results plot
        self.optimization_plot = pg.PlotWidget()
        self.optimization_plot.setLabel("left", "Coincidence Count")
        self.optimization_plot.setLabel("bottom", "Window Size (ns)")
        self.optimization_plot.setTitle("Window Size Optimization Results")
        self.optimization_plot.showGrid(True, True, alpha=0.3)
        layout.addWidget(self.optimization_plot)

        # Results table
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
        self.results_table.setMaximumHeight(200)
        layout.addWidget(self.results_table)

        return tab

    def create_timing_analysis_tab(self):
        """Create timing analysis tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Timing histogram
        self.timing_plot = pg.PlotWidget()
        self.timing_plot.setLabel("left", "Counts")
        self.timing_plot.setLabel("bottom", "Time Difference (ns)")
        self.timing_plot.setTitle("Coincidence Timing Distribution")
        self.timing_plot.showGrid(True, True, alpha=0.3)
        layout.addWidget(self.timing_plot)

        # Timing statistics
        self.timing_stats_text = QTextEdit()
        self.timing_stats_text.setMaximumHeight(150)
        self.timing_stats_text.setReadOnly(True)
        layout.addWidget(self.timing_stats_text)

        return tab

    def set_quick_window(self, window_text):
        """Set coincidence window from quick preset"""
        window_ns = float(window_text.replace("ns", ""))
        self.time_window_spin.setValue(window_ns)
        self.update_coincidence_window()

    def toggle_coincidence_mode(self, enabled):
        self.coincidence_mode = enabled
        if enabled:
            print(
                f"Coincidence mode enabled: Center=Ch{self.center_channel}, Window=±{self.coincidence_window_ns}ns"
            )
            self.coincidence_stats_label.setText(
                f"Coincidence: Ch{self.center_channel} ±{self.coincidence_window_ns}ns"
            )
            self.plot_widget.setTitle(
                f"Coincidence Analysis (Ch{self.center_channel} ±{self.coincidence_window_ns}ns)"
            )
        else:
            print("Coincidence mode disabled")
            self.coincidence_stats_label.setText("Coincidence: Disabled")
            self.plot_widget.setTitle("Traces - Real-Time Axis")

    def toggle_validation_mode(self, enabled):
        """Toggle live validation mode"""
        self.validation_window_optimization = enabled
        if enabled:
            print("Live validation mode enabled - will test multiple windows")
        else:
            print("Live validation mode disabled")

    def start_window_optimization(self):
        """Start window optimization process"""
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
        """Handle optimization results"""
        self.optimization_results = results

        # Plot results
        windows = list(results.keys())
        coincidences = [results[w]["coincidences"] for w in windows]
        efficiencies = [results[w]["efficiency"] * 100 for w in windows]

        self.optimization_plot.clear()
        self.optimization_plot.plot(
            windows, coincidences, pen="b", symbol="o", name="Coincidences"
        )

        # Find optimal window (maximum efficiency with reasonable count)
        max_efficiency = max(efficiencies)
        optimal_windows = [
            w
            for w in windows
            if results[w]["efficiency"] * 100 >= max_efficiency * 0.95
        ]
        self.optimal_window_ns = min(
            optimal_windows
        )  # Choose smallest window with near-max efficiency

        # Update results table
        self.update_results_table(results)

        # Update status
        self.optimization_status.setText(
            f"Optimal window: {self.optimal_window_ns:.1f}ns (efficiency: {results[self.optimal_window_ns]['efficiency'] * 100:.1f}%)"
        )

    def update_results_table(self, results):
        """Update results table with optimization data"""
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
        """Handle optimization completion"""
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
        """Save current coincidence settings to file"""
        settings = {
            "center_channel": self.center_channel,
            "coincidence_window_ns": self.coincidence_window_ns,
            "optimal_window_ns": self.optimal_window_ns,
            "optimization_results": self.optimization_results,
            "timestamp": time.time(),
        }

        settings_file = Path("coincidence_settings.json")
        with open(settings_file, "w") as f:
            json.dump(settings, f, indent=2)

        QMessageBox.information(
            self, "Settings Saved", f"Coincidence settings saved to {settings_file}"
        )

    def update_center_channel(self):
        """Update center channel for coincidence analysis"""
        self.center_channel = self.channels[self.center_channel_combo.currentIndex()]
        if self.coincidence_mode:
            self.coincidence_stats_label.setText(
                f"Coincidence: Ch{self.center_channel} ±{self.coincidence_window_ns}ns"
            )
            self.plot_widget.setTitle(
                f"Coincidence Analysis (Ch{self.center_channel} ±{self.coincidence_window_ns}ns)"
            )

    def update_coincidence_window(self):
        self.coincidence_window_ns = self.time_window_spin.value()
        if self.coincidence_mode:
            self.coincidence_stats_label.setText(
                f"Coincidence: Ch{self.center_channel} ±{self.coincidence_window_ns}ns"
            )
            self.plot_widget.setTitle(
                f"Coincidence Analysis (Ch{self.center_channel} ±{self.coincidence_window_ns}ns)"
            )

    def add_event_with_trace(self, event, trace_data):
        """Add an event with its trace data for coincidence analysis"""
        if not self.coincidence_mode:
            # Just add trace normally if not in coincidence mode
            self.add_trace(event.channel, trace_data)
            return

        # Store event in buffer for coincidence analysis
        self.event_buffer.append((event, trace_data))

        # If this is a center channel event, look for coincidences
        if event.channel == self.center_channel:
            self._find_and_store_coincidence(event, trace_data)

    def _find_and_store_coincidence(self, center_event, center_trace):
        """Find events coincident with the center event"""
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
        # timestamps are typically in 10ns clock ticks
        dt_ticks = timestamp1 - timestamp2
        dt_ns = dt_ticks * 10.0  # Convert to nanoseconds
        return dt_ns

    def update_timing_analysis(self):
        """Update timing analysis display"""
        if not self.coincidence_events:
            return

        # Collect all time differences
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
        """Add trace to channel buffer"""
        try:
            if channel not in self.channels:
                return

            if not isinstance(trace_data, np.ndarray):
                trace_data = np.array(trace_data)

            if len(trace_data) == 0:
                return

            if len(trace_data) > 10:
                amplitude = np.max(trace_data) - np.min(trace_data)
                if amplitude >= self.amplitude_threshold:
                    self.trace_data[channel].append(trace_data)
            else:
                self.trace_data[channel].append(trace_data)

        except Exception as e:
            print(f"Error adding trace to channel {channel}: {e}")

    def calculate_real_time_axis(self, trace_length, channel):
        """Calculate real-time axis for traces"""
        if not self.use_realtime_axis:
            return np.arange(trace_length)

        trace_delay = self.trace_delay_ns.get(channel, 200)
        sample_times = np.arange(trace_length) * self.sampling_period_ns
        real_times = sample_times - trace_delay

        return real_times

    def update_plots(self):
        try:
            total_traces = 0
            channel_stats = {}

            # Process all channels
            for channel in self.channels:
                has_data = (
                    channel in self.trace_data and len(self.trace_data[channel]) > 0
                )

                if has_data:
                    traces = list(self.trace_data[channel])
                    total_traces += len(traces)

                    if traces:
                        recent_trace = traces[-1]
                        amplitude = np.max(recent_trace) - np.min(recent_trace)
                        baseline = (
                            np.mean(recent_trace[:10]) if len(recent_trace) > 10 else 0
                        )

                        channel_stats[channel] = {
                            "count": len(traces),
                            "amplitude": amplitude,
                            "baseline": baseline,
                        }

                if channel not in self.display_channels:
                    self.curves[channel].setData([], [])
                    continue

                if not has_data:
                    self.curves[channel].setData([], [])
                    continue

                # Display traces
                traces = list(self.trace_data[channel])
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
                        self.curves[channel].setData(combined_x, combined_y)
                        self.last_traces[channel] = display_traces[-1]

            # Update statistics display
            if self.show_statistics:
                if self.display_channels:
                    mode_text = "Coincidence" if self.coincidence_mode else "Traces"
                    axis_mode = "Real-Time" if self.use_realtime_axis else "Sample"
                    stats_text = f"{mode_text} ({axis_mode}) | Total: {total_traces} | "

                    for ch in self.display_channels:
                        if ch in channel_stats:
                            stats = channel_stats[ch]
                            delay_info = (
                                f"({self.trace_delay_ns.get(ch, 0):.0f}ns)"
                                if self.use_realtime_axis
                                else ""
                            )
                            stats_text += f"Ch{ch}{delay_info}: {stats['count']} | "
                    self.stats_label.setText(stats_text.rstrip(" | "))
                else:
                    self.stats_label.setText("No channels selected for display")
            else:
                self.stats_label.setText("Statistics hidden")

            if self.coincidence_mode and self.show_timing_stats:
                num_coincidences = len(self.coincidence_events)
                if num_coincidences > 0:
                    # Calculate timing statistics from recent coincidences
                    recent_coincidences = list(self.coincidence_events)[-100:]
                    all_time_diffs = []
                    for coinc in recent_coincidences:
                        all_time_diffs.extend(coinc.time_differences)

                    if all_time_diffs:
                        mean_dt = np.mean(all_time_diffs)
                        std_dt = np.std(all_time_diffs)

                        # Calculate efficiency (events within window / total events)
                        events_in_window = len(
                            [
                                dt
                                for dt in all_time_diffs
                                if abs(dt) <= self.coincidence_window_ns
                            ]
                        )
                        efficiency = (
                            events_in_window / len(all_time_diffs) * 100
                            if all_time_diffs
                            else 0
                        )

                        self.coincidence_stats_label.setText(
                            f"Coincidences: {num_coincidences} | Δt: {mean_dt:.1f}±{std_dt:.1f}ns | Eff: {efficiency:.1f}%"
                        )

                        # Live validation mode - test multiple windows
                        if self.validation_window_optimization:
                            self.perform_live_validation(all_time_diffs)
                    else:
                        self.coincidence_stats_label.setText(
                            f"Coincidences: {num_coincidences} | No timing data"
                        )
                else:
                    self.coincidence_stats_label.setText(
                        f"Coincidence: Ch{self.center_channel} ±{self.coincidence_window_ns}ns | No events"
                    )

            # Auto scale if enabled
            if self.auto_scale and total_traces > 0:
                self.plot_widget.autoRange()

        except Exception as e:
            print(f"Error updating traces plots: {e}")
            import traceback

            traceback.print_exc()

    def perform_live_validation(self, time_diffs):
        """Perform live validation of different window sizes"""
        if not hasattr(self, "_last_validation_time"):
            self._last_validation_time = 0

        # Only validate every 5 seconds to avoid excessive computation
        current_time = time.time()
        if current_time - self._last_validation_time < 5.0:
            return

        self._last_validation_time = current_time

        # Test different window sizes
        test_windows = [10, 20, 30, 50, 75, 100, 150, 200]
        results = {}

        for window in test_windows:
            events_in_window = len([dt for dt in time_diffs if abs(dt) <= window])
            efficiency = events_in_window / len(time_diffs) * 100 if time_diffs else 0
            results[window] = efficiency

        # Find optimal window (knee point in efficiency curve)
        optimal_window = self.find_optimal_window(results)

        # Update status if significantly different from current
        if abs(optimal_window - self.coincidence_window_ns) > 10:
            print(
                f"Live validation suggests window: {optimal_window}ns (current: {self.coincidence_window_ns}ns)"
            )

    def find_optimal_window(self, efficiency_results):
        """Find optimal window size using knee detection"""
        windows = sorted(efficiency_results.keys())
        efficiencies = [efficiency_results[w] for w in windows]

        # Find the elbow/knee point where efficiency gain diminishes
        if len(windows) < 3:
            return windows[0]

        # Calculate second derivative to find inflection point
        second_derivatives = []
        for i in range(1, len(efficiencies) - 1):
            d2 = efficiencies[i + 1] - 2 * efficiencies[i] + efficiencies[i - 1]
            second_derivatives.append(abs(d2))

        # Find minimum second derivative (smoothest point)
        if second_derivatives:
            min_idx = np.argmin(second_derivatives)
            return windows[min_idx + 1]  # Adjust for offset

        return windows[len(windows) // 2]  # Fallback to middle value

    # Control update methods
    def update_max_traces(self):
        self.max_traces_display = self.max_traces_spin.value()

    def update_threshold(self):
        self.amplitude_threshold = self.threshold_spin.value()

    def toggle_auto_scale(self, enabled):
        self.auto_scale = enabled

    def start_live_updates(self):
        if not self.update_timer.isActive():
            self.update_timer.start(100)
            print("Traces Plotter: Started live updates")

    def stop_live_updates(self):
        if self.update_timer.isActive():
            self.update_timer.stop()
            print("Traces Plotter: Stopped live updates")

    def clear_data(self):
        """Clear all trace and coincidence data"""
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

        self.update_plots()

    def set_timing_settings(self, settings):
        """Set timing settings from configuration"""
        self.trace_delay_ns = settings.get("trace_delay_ns", {})
        self.sampling_period_ns = settings.get("sampling_period_ns", 2.0)
        self.alpha_channel = settings.get("alpha_channel", 9)

    def set_channels(self, channels):
        """Update the list of channels"""
        for channel in self.channels:
            if channel in self.curves:
                self.plot_widget.removeItem(self.curves[channel])

        self.channels = channels

        new_trace_data = {}
        for ch in self.channels:
            new_trace_data[ch] = self.trace_data.get(ch, deque(maxlen=1000))
        self.trace_data = new_trace_data

        self.curves = {}
        for i, channel in enumerate(self.channels):
            color = self.colors[i % len(self.colors)]
            self.curves[channel] = self.plot_widget.plot(
                pen=pg.mkPen(color=color, width=1.5), name=f"Ch {channel}"
            )

    def set_display_channels(self, channels):
        """Set which channels to display"""
        print(f"Traces Plotter: set_display_channels called with {channels}")
        self.display_channels = channels if channels else []

        for channel in self.channels:
            if channel not in self.display_channels:
                self.curves[channel].setData([], [])

        self.update_plots()

    def get_coincidence_statistics(self):
        stats = {
            "coincidence_mode": self.coincidence_mode,
            "center_channel": self.center_channel,
            "coincidence_window_ns": self.coincidence_window_ns,
            "optimal_window_ns": self.optimal_window_ns,
            "total_coincidences": len(self.coincidence_events),
            "events_in_buffer": len(self.event_buffer),
            "optimization_active": self.optimization_active,
            "validation_mode": self.validation_window_optimization,
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

    def load_coincidence_settings(self, filename="coincidence_settings.json"):
        """Load coincidence settings from file"""
        settings_file = Path(filename)
        if settings_file.exists():
            try:
                with open(settings_file) as f:
                    settings = json.load(f)

                self.center_channel = settings.get(
                    "center_channel", self.center_channel
                )
                self.coincidence_window_ns = settings.get(
                    "coincidence_window_ns", self.coincidence_window_ns
                )
                self.optimal_window_ns = settings.get(
                    "optimal_window_ns", self.optimal_window_ns
                )
                self.optimization_results = settings.get("optimization_results", {})

                # Update UI
                self.time_window_spin.setValue(self.coincidence_window_ns)
                if self.center_channel in self.channels:
                    self.center_channel_combo.setCurrentIndex(
                        self.channels.index(self.center_channel)
                    )

                print(f"Loaded coincidence settings from {settings_file}")
                return True

            except Exception as e:
                print(f"Error loading settings: {e}")
                return False
        return False

    def export_timing_data(self, filename="timing_data.csv"):
        """Export timing analysis data to CSV"""
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
            import pandas as pd

            df = pd.DataFrame(export_data)
            df.to_csv(filename, index=False)
            QMessageBox.information(
                self, "Export Complete", f"Timing data exported to {filename}"
            )
        except ImportError:
            # Fallback to manual CSV writing
            import csv

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

    def get_recommended_settings(self):
        """Get recommended settings based on current data"""
        recommendations = {
            "status": "No data available",
            "recommended_window": None,
            "confidence": "Low",
        }

        if not self.coincidence_events:
            return recommendations

        # Analyze current timing data
        all_time_diffs = []
        for coinc in self.coincidence_events:
            all_time_diffs.extend([abs(dt) for dt in coinc.time_differences])

        if len(all_time_diffs) < 10:
            recommendations["status"] = "Insufficient data (need >10 events)"
            return recommendations

        # Calculate statistics
        mean_dt = np.mean(all_time_diffs)
        std_dt = np.std(all_time_diffs)
        percentile_95 = np.percentile(all_time_diffs, 95)

        # Recommend window based on statistics
        # Use 2-sigma or 95th percentile, whichever is smaller
        recommended = min(mean_dt + 2 * std_dt, percentile_95)

        # Ensure minimum window of 10ns
        recommended = max(recommended, 10.0)

        # Determine confidence based on data quality
        if len(all_time_diffs) > 100 and std_dt < mean_dt:
            confidence = "High"
        elif len(all_time_diffs) > 50:
            confidence = "Medium"
        else:
            confidence = "Low"

        recommendations.update(
            {
                "status": f"Based on {len(all_time_diffs)} timing measurements",
                "recommended_window": recommended,
                "confidence": confidence,
                "mean_dt": mean_dt,
                "std_dt": std_dt,
                "percentile_95": percentile_95,
                "current_efficiency": len(
                    [dt for dt in all_time_diffs if dt <= self.coincidence_window_ns]
                )
                / len(all_time_diffs)
                * 100,
            }
        )

        return recommendations
