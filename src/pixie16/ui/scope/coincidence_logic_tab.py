"""
Coincidence logic tab with binary waveform visualization for coincidence analysis, optimization, and binary logic display.
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


class CoincidenceLogicTab(QWidget):
    """
    Coincidence Logic Tab with binary waveform visualization.
    """

    # Signals
    parameter_changed = pyqtSignal(
        str, object, int, int
    )  # param_name, value, module, channel

    def __init__(self, channels=None, hardware_manager=None, parent=None):
        super().__init__(parent)

        self.channels = channels or list(range(16))
        self.hardware_manager = hardware_manager

        # Event storage for coincidence analysis
        self.event_buffer = deque(maxlen=50000)
        self.coincidence_events = deque(maxlen=10000)

        # Coincidence analysis settings
        self.coincidence_mode = False
        self.center_channel = 9 if 9 in self.channels else self.channels[0]
        self.coincidence_window_ns = 20.0
        self.validation_window_optimization = False
        self.optimization_active = False
        self.optimization_results = {}
        self.optimal_window_ns = 20.0

        # Binary logic visualization settings
        self.binary_logic_enabled = False
        self.binary_selected_channel = self.channels[0]
        self.binary_time_window_us = 2.0  # microseconds to display
        self.binary_logic_steps = [
            "raw_threshold",
            "fast_trigger",
            "backplane_signal",
            "multiplicity_logic",
            "validation_window",
            "delayed_local",
            "event_accepted",
        ]

        # Binary state storage for visualization
        self.binary_states = {
            step: deque(maxlen=5000) for step in self.binary_logic_steps
        }
        self.binary_timestamps = deque(maxlen=5000)

        # Hardware parameters for timing calculations
        self.binary_hardware_params = {
            "fast_trigger_backplane_delay_ns": 0,
            "fast_trigger_backplane_length_ns": 100,
            "channel_trigger_stretch_ns": 200,
            "external_delay_length_ns": 300,
            "multiplicity_mask_l": 0,
            "multiplicity_mask_h": 0,
            "fast_threshold": 100,
        }

        # For hardware trace computation (should be overridden by parent)
        self.hardware_params = {
            "fast_L": 2,
            "fast_G": 2,
            "fast_threshold": 100,
            "cfd_threshold": 100,
        }

        self.sampling_period_ns = 2.0  # 500MHz module

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Coincidence settings
        settings_group = self.create_coincidence_settings_group()
        layout.addWidget(settings_group)

        # Binary Logic Visualization Group
        binary_group = self.create_binary_logic_group()
        layout.addWidget(binary_group)

        # Window optimization controls
        optimization_group = self.create_optimization_group()
        layout.addWidget(optimization_group)

        # Results display in tabbed format
        results_tabs = self.create_results_tabs()
        layout.addWidget(results_tabs)

        # Status and control buttons
        control_layout = self.create_control_buttons()
        layout.addLayout(control_layout)

        self.setLayout(layout)

    def create_coincidence_settings_group(self):
        settings_group = QGroupBox("Coincidence Settings")
        settings_layout = QGridLayout()

        # Center channel selection
        settings_layout.addWidget(QLabel("Center Channel:"), 0, 0)
        self.center_channel_combo = QComboBox()
        for ch in self.channels:
            self.center_channel_combo.addItem(f"Ch {ch}")
        self.center_channel_combo.setCurrentIndex(
            self.channels.index(self.center_channel)
            if self.center_channel in self.channels
            else 0
        )
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
        return settings_group

    def create_binary_logic_group(self):
        binary_group = QGroupBox("Binary Coincidence Logic Visualization")
        binary_layout = QVBoxLayout()

        # Binary controls
        binary_controls_layout = QHBoxLayout()

        # Enable binary visualization
        self.binary_enable_cb = QCheckBox("Enable Binary Logic View")
        self.binary_enable_cb.toggled.connect(self.toggle_binary_logic)
        binary_controls_layout.addWidget(self.binary_enable_cb)

        # Channel selection for binary view
        binary_controls_layout.addWidget(QLabel("Channel:"))
        self.binary_channel_combo = QComboBox()
        for ch in self.channels:
            self.binary_channel_combo.addItem(f"Ch {ch}")
        self.binary_channel_combo.currentIndexChanged.connect(
            self.update_binary_channel
        )
        binary_controls_layout.addWidget(self.binary_channel_combo)

        # Time window control
        binary_controls_layout.addWidget(QLabel("Time Window:"))
        self.binary_time_spin = QDoubleSpinBox()
        self.binary_time_spin.setRange(0.5, 10.0)
        self.binary_time_spin.setValue(2.0)
        self.binary_time_spin.setSuffix(" μs")
        self.binary_time_spin.valueChanged.connect(self.update_binary_time_window)
        binary_controls_layout.addWidget(self.binary_time_spin)

        binary_controls_layout.addStretch()
        binary_layout.addLayout(binary_controls_layout)

        # Binary logic plot
        self.binary_plot = pg.PlotWidget()
        self.binary_plot.setLabel("left", "Logic Steps")
        self.binary_plot.setLabel("bottom", "Time (ns)")
        self.binary_plot.setTitle("Coincidence Logic Steps - Channel 0")
        self.binary_plot.showGrid(True, True, alpha=0.3)
        self.binary_plot.setBackground("w")
        self.binary_plot.setMinimumHeight(300)

        # Set up Y-axis for logic steps
        y_labels = [
            (0, "Event Accepted"),
            (1, "Delayed Local"),
            (2, "Validation Window"),
            (3, "Multiplicity Logic"),
            (4, "Backplane Signal"),
            (5, "Fast Trigger"),
            (6, "Raw > Threshold"),
        ]
        self.binary_plot.getAxis("left").setTicks([y_labels])
        self.binary_plot.setYRange(-0.5, 6.5)

        binary_layout.addWidget(self.binary_plot)

        # Hardware parameter display
        self.binary_params_label = QLabel("Hardware Parameters: Not loaded")
        self.binary_params_label.setStyleSheet(
            "font-family: monospace; font-size: 9pt;"
        )
        binary_layout.addWidget(self.binary_params_label)

        binary_group.setLayout(binary_layout)
        return binary_group

    def create_optimization_group(self):
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
        return optimization_group

    def create_results_tabs(self):
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

        return results_tabs

    def create_control_buttons(self):
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

        return control_layout

    # ==================== BINARY LOGIC METHODS ====================

    def toggle_binary_logic(self, enabled):
        self.binary_logic_enabled = enabled
        if enabled:
            self.update_binary_hardware_params()
            self.binary_plot.setTitle(
                f"Coincidence Logic Steps - Channel {self.binary_selected_channel}"
            )
        else:
            self.binary_plot.clear()

    def update_binary_channel(self):
        self.binary_selected_channel = self.channels[
            self.binary_channel_combo.currentIndex()
        ]
        if self.binary_logic_enabled:
            self.binary_plot.setTitle(
                f"Coincidence Logic Steps - Channel {self.binary_selected_channel}"
            )
            self.clear_binary_data()

    def update_binary_time_window(self):
        self.binary_time_window_us = self.binary_time_spin.value()

    def clear_binary_data(self):
        for step in self.binary_logic_steps:
            self.binary_states[step].clear()
        self.binary_timestamps.clear()
        self.binary_plot.clear()

    def update_binary_hardware_params(self):
        if not self.hardware_manager:
            return

        try:
            # Read actual hardware parameters if available
            if hasattr(self.hardware_manager, "get_channel_parameter"):
                channel = self.binary_selected_channel
                self.binary_hardware_params.update(
                    {
                        "fast_trigger_backplane_length_ns": self.hardware_manager.get_channel_parameter(
                            "FASTTRIGBACKLEN", 0, channel
                        )
                        * 1000,
                        "channel_trigger_stretch_ns": self.hardware_manager.get_channel_parameter(
                            "CHANTRIGSTRETCH", 0, channel
                        )
                        * 1000,
                        "external_delay_length_ns": self.hardware_manager.get_channel_parameter(
                            "EXTERNDELAYLEN", 0, channel
                        )
                        * 1000,
                        "multiplicity_mask_l": self.hardware_manager.get_channel_parameter(
                            "MULTIPLICITYMASKL", 0, channel
                        ),
                        "multiplicity_mask_h": self.hardware_manager.get_channel_parameter(
                            "MULTIPLICITYMASKH", 0, channel
                        ),
                    }
                )
        except Exception as e:
            print(f"Could not read hardware parameters: {e}")

        # Update display
        params_text = (
            f"FastTrigBackLen: {self.binary_hardware_params['fast_trigger_backplane_length_ns']:.0f}ns | "
            f"ChanTrigStretch: {self.binary_hardware_params['channel_trigger_stretch_ns']:.0f}ns | "
            f"ExtDelayLen: {self.binary_hardware_params['external_delay_length_ns']:.0f}ns | "
            f"MultMask: 0x{self.binary_hardware_params['multiplicity_mask_l']:08X}"
        )
        self.binary_params_label.setText(params_text)

    def compute_binary_logic_steps(self, raw_trace, channel, event_timestamp):
        if not self.binary_logic_enabled or channel != self.binary_selected_channel:
            return None

        trace_length = len(raw_trace)
        time_axis = np.arange(trace_length) * self.sampling_period_ns

        # Step 1: Raw signal > threshold
        threshold = self.binary_hardware_params["fast_threshold"]
        baseline = (
            np.mean(raw_trace[:100]) if len(raw_trace) > 100 else np.mean(raw_trace)
        )
        raw_binary = (raw_trace > (baseline + threshold)).astype(int)

        # Step 2: Fast trigger (FO0) - needs parent implementation
        fast_trigger_binary = self.compute_fast_trigger_binary(raw_trace, channel)

        # Step 3: Backplane signal (delayed version of fast trigger)
        backplane_delay_samples = int(
            self.binary_hardware_params["fast_trigger_backplane_delay_ns"]
            / self.sampling_period_ns
        )
        backplane_binary = np.roll(fast_trigger_binary, backplane_delay_samples)
        if backplane_delay_samples > 0:
            backplane_binary[:backplane_delay_samples] = 0

        # Step 4: Multiplicity logic
        multiplicity_binary = self.compute_multiplicity_logic(
            event_timestamp, trace_length
        )

        # Step 5: Validation window (stretched multiplicity result)
        stretch_samples = int(
            self.binary_hardware_params["channel_trigger_stretch_ns"]
            / self.sampling_period_ns
        )
        validation_binary = np.convolve(
            multiplicity_binary, np.ones(stretch_samples), mode="same"
        )
        validation_binary = (validation_binary > 0).astype(int)

        # Step 6: Delayed local trigger
        ext_delay_samples = int(
            self.binary_hardware_params["external_delay_length_ns"]
            / self.sampling_period_ns
        )
        delayed_local_binary = np.roll(fast_trigger_binary, ext_delay_samples)
        if ext_delay_samples > 0:
            delayed_local_binary[:ext_delay_samples] = 0

        # Step 7: Final event validation (AND of delayed local and validation window)
        event_accepted_binary = delayed_local_binary & validation_binary

        # Store results
        binary_results = {
            "raw_threshold": raw_binary,
            "fast_trigger": fast_trigger_binary,
            "backplane_signal": backplane_binary,
            "multiplicity_logic": multiplicity_binary,
            "validation_window": validation_binary,
            "delayed_local": delayed_local_binary,
            "event_accepted": event_accepted_binary,
            "time_axis": time_axis,
            "timestamp": event_timestamp,
        }

        # Update visualization
        self.update_binary_visualization(binary_results)

        return binary_results

    def compute_multiplicity_logic(self, event_timestamp, trace_length):
        """
        Returns binary array showing when System FPGA coincidence logic fires.
        """
        multiplicity_binary = np.zeros(trace_length, dtype=int)

        # Only show multiplicity logic if we actually found coincidences
        if not self.coincidence_events:
            return multiplicity_binary

        # Check if current event is part of any stored coincidence
        current_time = event_timestamp
        window_ticks = self.coincidence_window_ns / 10.0

        for coinc_event in self.coincidence_events:
            # Check if this trace's timestamp matches a coincidence event
            center_time = coinc_event.center_event.timestamp
            time_diff = abs(current_time - center_time)

            if time_diff <= window_ticks:
                # This trace is part of a real coincidence
                # Show multiplicity logic firing during the coincidence window

                # Calculate where in the trace the coincidence logic would fire
                pulse_start = trace_length // 3  # Middle of trace
                pulse_width = min(50, trace_length // 10)  # 50 samples or 10% of trace
                pulse_end = min(pulse_start + pulse_width, trace_length)

                multiplicity_binary[pulse_start:pulse_end] = 1
                break  # Only need to find one matching coincidence

        return multiplicity_binary

    def compute_fast_trigger_binary(self, raw_trace, channel):
        """
        Override in parent class
        """
        if len(raw_trace) < 10:
            return np.zeros(len(raw_trace), dtype=int)  # fallback

        # Simple derivative-based fast trigger simulation
        diff = np.diff(raw_trace)
        fast_trigger = np.zeros(len(raw_trace))
        fast_trigger[1:] = diff

        threshold = self.binary_hardware_params["fast_threshold"]
        return (fast_trigger > threshold).astype(int)

    def update_binary_visualization(self, binary_results):
        if not self.binary_logic_enabled:
            return

        self.binary_plot.clear()

        time_axis = binary_results["time_axis"]
        colors = ["red", "orange", "yellow", "green", "blue", "purple", "brown"]

        # Plot each logic step as a binary waveform
        for i, step in enumerate(self.binary_logic_steps):
            if step in binary_results:
                binary_data = binary_results[step]
                # Offset each trace vertically
                y_offset = i
                y_data = binary_data + y_offset

                # Create step plot for binary data
                step_x = []
                step_y = []
                for j in range(len(binary_data)):
                    step_x.extend([time_axis[j], time_axis[j]])
                    step_y.extend([y_offset, y_offset + binary_data[j]])
                    if j < len(binary_data) - 1:
                        step_x.append(time_axis[j + 1])
                        step_y.append(y_offset + binary_data[j])

                color = colors[i % len(colors)]
                self.binary_plot.plot(
                    step_x, step_y, pen=pg.mkPen(color=color, width=2)
                )

        # Add timing histogram in background if we have coincidence data
        self.add_timing_histogram_background()

    def add_timing_histogram_background(self):
        if not self.coincidence_events:
            return

        # Get timing differences
        all_time_diffs = []
        for coinc_event in self.coincidence_events:
            all_time_diffs.extend([abs(dt) for dt in coinc_event.time_differences])

        if not all_time_diffs:
            return

        # Create histogram
        hist, bins = np.histogram(
            all_time_diffs, bins=50, range=(0, self.binary_time_window_us * 1000)
        )

        # Normalize and scale for background display
        if np.max(hist) > 0:
            hist_normalized = hist / np.max(hist) * 6.5  # Scale to fit plot height

            # Create histogram background
            hist_item = pg.PlotCurveItem(
                bins[:-1],
                hist_normalized,
                stepMode=True,
                fillLevel=0,
                brush=pg.mkBrush(color=(128, 128, 255, 50)),  # Semi-transparent blue
            )
            self.binary_plot.addItem(hist_item)

    # ==================== COINCIDENCE ANALYSIS METHODS ====================

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
        efficiencies = [results[w]["efficiency"] * 100 for w in windows]

        self.optimization_plot.clear()
        self.optimization_plot.plot(
            windows, efficiencies, pen="b", symbol="o", name="Efficiency"
        )

        # Find optimal window
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
            "binary_logic_enabled": self.binary_logic_enabled,
            "binary_selected_channel": self.binary_selected_channel,
            "binary_hardware_params": self.binary_hardware_params,
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

    # ==================== DATA PROCESSING METHODS ====================

    def add_event_with_trace(self, event, trace_data):
        """
        Add event with trace data for coincidence analysis.
        This is the main entry point for processing events.
        """
        event_timestamp = getattr(event, "timestamp", None)

        # Store in event buffer
        self.event_buffer.append((event, trace_data))

        # Process binary logic if enabled for this channel
        if hasattr(event, "channel") and event.channel == self.binary_selected_channel:
            self.compute_binary_logic_steps(trace_data, event.channel, event_timestamp)

        # If this is a center channel event, look for coincidences
        if hasattr(event, "channel") and event.channel == self.center_channel:
            self._find_and_store_coincidence(event, trace_data)

    def _find_and_store_coincidence(self, center_event, center_trace):
        coincident_events_with_traces = []

        # Look through recent events for coincidences
        for buffered_event, buffered_trace in self.event_buffer:
            if buffered_event == center_event:
                continue  # Skip the center event itself

            # Calculate time difference
            time_diff_ns = abs(
                self._calculate_pixie_time_difference(
                    buffered_event.timestamp, center_event.timestamp
                )
            )

            # Check if within coincidence window
            if time_diff_ns <= self.coincidence_window_ns:
                coincident_events_with_traces.append((buffered_event, buffered_trace))

        # Create and store coincidence event
        if coincident_events_with_traces:
            coinc_event = CoincidenceEvent(
                center_event, center_trace, coincident_events_with_traces
            )
            self.coincidence_events.append(coinc_event)

            # Update timing analysis
            self.update_timing_analysis()

    def _calculate_pixie_time_difference(self, timestamp1, timestamp2):
        dt_ticks = timestamp1 - timestamp2
        dt_ns = dt_ticks * 10.0  # Convert to nanoseconds
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

    # ==================== UTILITY METHODS ====================

    def clear_data(self):
        self.event_buffer.clear()
        self.coincidence_events.clear()
        self.clear_binary_data()

        # Clear plots
        self.optimization_plot.clear()
        self.timing_plot.clear()
        self.timing_stats_text.clear()
        self.results_table.setRowCount(0)
        self.binary_plot.clear()

    def get_coincidence_statistics(self):
        stats = {
            "coincidence_mode": self.coincidence_mode,
            "center_channel": self.center_channel,
            "coincidence_window_ns": self.coincidence_window_ns,
            "optimal_window_ns": self.optimal_window_ns,
            "total_coincidences": len(self.coincidence_events),
            "events_in_buffer": len(self.event_buffer),
            "optimization_active": self.optimization_active,
            "binary_logic_enabled": self.binary_logic_enabled,
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

    # ==================== INTERFACE METHODS FOR PARENT CLASS ====================

    def set_hardware_params(self, params):
        self.hardware_params.update(params)
        self.binary_hardware_params["fast_threshold"] = params.get(
            "fast_threshold", 100
        )

    def set_channels(self, channels):
        self.channels = channels

        # Update combo boxes
        self.center_channel_combo.clear()
        self.binary_channel_combo.clear()

        for ch in self.channels:
            self.center_channel_combo.addItem(f"Ch {ch}")
            self.binary_channel_combo.addItem(f"Ch {ch}")

        # Reset to valid channels
        if self.center_channel not in self.channels:
            self.center_channel = self.channels[0] if self.channels else 0
        if self.binary_selected_channel not in self.channels:
            self.binary_selected_channel = self.channels[0] if self.channels else 0
