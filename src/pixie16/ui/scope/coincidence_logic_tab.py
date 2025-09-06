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
    QSizePolicy,
)
from PyQt6.QtCore import QTimer, QThread, pyqtSignal
import pyqtgraph as pg

from ...analyze import (
    compute_fast_trigger_validation,
    compute_energy_filter,
    convert_trace_to_FPGA,
    calculate_CFD,
    calculate_filter,
    get_fast_trigger_index,
)


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

        # Binary logic visualization settings
        self.binary_logic_enabled = True
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

        if self.hardware_manager:
            self.update_binary_hardware_params()

    def init_ui(self):
        layout = QVBoxLayout()

        settings_group = self.create_coincidence_settings_group()
        layout.addWidget(settings_group, 0)

        binary_group = self.create_binary_logic_group()
        layout.addWidget(binary_group, 1)

        control_layout = self.create_control_buttons()
        layout.addLayout(control_layout, 0)
        
        self.setLayout(layout)

    def create_coincidence_settings_group(self):
        settings_group = QGroupBox("Coincidence Settings")
        settings_layout = QGridLayout()

        settings_layout.setContentsMargins(5, 5, 5, 5)
        settings_layout.setSpacing(5)

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

        settings_group.setLayout(settings_layout)
        settings_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        
        return settings_group

    def create_binary_logic_group(self):
        binary_group = QGroupBox("Binary Coincidence Logic Visualization")
        binary_layout = QVBoxLayout()

        # Binary controls
        binary_controls_layout = QHBoxLayout()

        # Enable binary visualization
        self.binary_enable_cb = QCheckBox("Enable Binary Logic View")
        self.binary_enable_cb.setChecked(True)
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
        self.binary_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.binary_plot.setMinimumHeight(200)

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

        binary_layout.addWidget(self.binary_plot, 1)

        # Hardware parameter display
        self.binary_params_label = QLabel("Hardware Parameters: Not loaded")
        self.binary_params_label.setStyleSheet(
            "font-family: monospace; font-size: 9pt;"
        )
        binary_layout.addWidget(self.binary_params_label, 0)

        binary_group.setLayout(binary_layout)
        return binary_group

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
            channel = self.binary_selected_channel
            # Use the correct method name
            hw_params = self.hardware_manager.get_hardware_timing_parameters(channel)
            
            # Map the parameters correctly
            if hw_params:
                self.hardware_params.update({
                    'fast_L': self._convert_time_to_fpga_cycles(hw_params.get('TRIGGER_RISETIME', 0.1)),
                    'fast_G': self._convert_time_to_fpga_cycles(hw_params.get('TRIGGER_FLATTOP', 0.1)),
                    'fast_threshold': hw_params.get('TRIGGER_THRESHOLD', 100),
                })
                
                # Also update binary hardware params for timing
                self.binary_hardware_params.update({
                    'channel_trigger_stretch_ns': hw_params.get('ChanTrigStretch', 0) * 1000,
                    'external_delay_length_ns': hw_params.get('ExternDelayLen', 0) * 1000,
                    'fast_trigger_backplane_length_ns': hw_params.get('FastTrigBackLen', 0) * 1000,
                    'multiplicity_mask_l': hw_params.get('MultiplicityMaskL', 0),
                    'multiplicity_mask_h': hw_params.get('MultiplicityMaskH', 0),
                })
        except Exception as e:
            print(f"Could not read hardware parameters: {e}")
        
        self._update_parameter_display()
    
    def _update_parameter_display(self):
        params_text = (
            f"FastL/G: {self.hardware_params.get('fast_L', 2)}/{self.hardware_params.get('fast_G', 2)} | "
            f"Threshold: {self.hardware_params.get('fast_threshold', 100)} | "
            f"TrigStretch: {self.binary_hardware_params['channel_trigger_stretch_ns']:.0f}ns | "
            f"MultMask: 0x{self.binary_hardware_params['multiplicity_mask_l']:08X}"
        )
        self.binary_params_label.setText(params_text)

    def _convert_time_to_fpga_cycles(self, time_us):
        # For 500MHz module: 2ns per ADC sample, 10ns per FPGA cycle
        # time_us * 1000ns/us * 1cycle/10ns = time_us * 100 cycles/us
        return int(time_us * 100)

    def compute_binary_logic_steps(self, raw_trace, channel, event_timestamp):
        if not self.binary_logic_enabled or channel != self.binary_selected_channel:
            return None

        trace_length = len(raw_trace)
        time_axis = np.arange(trace_length) * self.sampling_period_ns

        # Raw signal > threshold
        threshold = self.binary_hardware_params["fast_threshold"]
        baseline = (
            np.mean(raw_trace[:100]) if len(raw_trace) > 100 else np.mean(raw_trace)
        )
        raw_binary = (raw_trace > (baseline + threshold)).astype(int)

        # Fast trigger (FO0) - needs parent implementation
        fast_trigger_binary = self.compute_fast_trigger_binary(raw_trace, channel)

        # Backplane signal (delayed version of fast trigger)
        backplane_delay_samples = int(
            self.binary_hardware_params["fast_trigger_backplane_delay_ns"]
            / self.sampling_period_ns
        )
        backplane_binary = np.roll(fast_trigger_binary, backplane_delay_samples)
        if backplane_delay_samples > 0:
            backplane_binary[:backplane_delay_samples] = 0

        # Multiplicity logic
        multiplicity_binary = self.compute_multiplicity_logic(
            event_timestamp, trace_length
        )

        # Validation window (stretched multiplicity result)
        stretch_samples = int(
            self.binary_hardware_params["channel_trigger_stretch_ns"]
            / self.sampling_period_ns
        )
        validation_binary = np.convolve(
            multiplicity_binary, np.ones(stretch_samples), mode="same"
        )
        validation_binary = (validation_binary > 0).astype(int)

        # Delayed local trigger
        ext_delay_samples = int(
            self.binary_hardware_params["external_delay_length_ns"]
            / self.sampling_period_ns
        )
        delayed_local_binary = np.roll(fast_trigger_binary, ext_delay_samples)
        if ext_delay_samples > 0:
            delayed_local_binary[:ext_delay_samples] = 0

        # Final event validation (AND of delayed local and validation window)
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
        Simulate System FPGA multiplicity logic based on actual hardware masks
        """
        multiplicity_binary = np.zeros(trace_length, dtype=int)
        
        mult_mask_l = self.binary_hardware_params.get('multiplicity_mask_l', 0)
        mult_mask_h = self.binary_hardware_params.get('multiplicity_mask_h', 0)
        
        if mult_mask_l == 0 and mult_mask_h == 0:
            return multiplicity_binary
        
        # checking other channels within timing window
        current_channel = self.binary_selected_channel
        coincident_channels = []
        
        # Check recent events from other channels in the buffer
        current_time_ticks = event_timestamp
        window_ticks = self.coincidence_window_ns / 10.0  # Convert ns to 10ns ticks
        
        for buffered_event, buffered_trace in list(self.event_buffer)[-50:]:  # Check last 50 events
            if not hasattr(buffered_event, 'channel') or not hasattr(buffered_event, 'timestamp'):
                continue
                
            if buffered_event.channel == current_channel:
                continue  # Skip same channel
                
            time_diff_ticks = abs(buffered_event.timestamp - current_time_ticks)
            
            if time_diff_ticks <= window_ticks:
                # This channel fired within the coincidence window
                channel_bit = 1 << buffered_event.channel
                
                # Check if this channel is enabled in multiplicity mask
                if (channel_bit & mult_mask_l) or (channel_bit & mult_mask_h):
                    coincident_channels.append(buffered_event.channel)
        
        # If we found coincident channels, show multiplicity logic firing
        if coincident_channels:
            # Simulate multiplicity logic pulse in middle of trace
            pulse_start = trace_length // 3
            pulse_width = min(50, trace_length // 10)
            pulse_end = min(pulse_start + pulse_width, trace_length)
            multiplicity_binary[pulse_start:pulse_end] = 1
        
        return multiplicity_binary

    def compute_fast_trigger_binary(self, raw_trace, channel):
        if len(raw_trace) < 10:
            return np.zeros(len(raw_trace), dtype=int)
        
        # Get hardware parameters for this channel
        fast_L = self.hardware_params.get('fast_L', 2)
        fast_G = self.hardware_params.get('fast_G', 2) 
        fast_threshold = self.hardware_params.get('fast_threshold', 100)
        
        try:
            result = compute_fast_trigger_validation(
                raw_trace.reshape(1, -1),  # Ensure 2D array
                L=fast_L,
                G=fast_G, 
                threshold=fast_threshold
            )
            
            if result['validation_passed'] and result['fast_triggers'] is not None:
                # Convert fast filter output to binary trigger
                fast_filter = result['fast_triggers'][0]  # Get first trace result
                
                # Pad to match original trace length
                if len(fast_filter) < len(raw_trace):
                    pad_length = len(raw_trace) - len(fast_filter)
                    fast_filter = np.pad(fast_filter, (pad_length, 0), mode='constant', constant_values=0)
                elif len(fast_filter) > len(raw_trace):
                    fast_filter = fast_filter[:len(raw_trace)]
                    
                # Create binary output based on threshold crossing
                binary_output = (fast_filter > fast_threshold).astype(int)
                return binary_output
                
        except Exception as e:
            print(f"Fast trigger calculation failed: {e}")
            # return average of first 100 samples
            baseline = np.mean(raw_trace[:100]) if len(raw_trace) > 100 else np.mean(raw_trace)
            threshold = self.binary_hardware_params.get('fast_threshold', 100)
            return (raw_trace > (baseline + threshold)).astype(int)

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

                # Create step plot for binary data
                step_x = []
                step_y = []
                for j in range(len(binary_data)):
                    if j == 0:
                        step_x.extend([time_axis[j], time_axis[j]])
                        step_y.extend([y_offset, y_offset + binary_data[j]])
                    else:
                        # Add horizontal line from previous point
                        step_x.append(time_axis[j])
                        step_y.append(y_offset + binary_data[j - 1])
                        # Add vertical transition
                        step_x.append(time_axis[j])
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

    def update_center_channel(self):
        self.center_channel = self.channels[self.center_channel_combo.currentIndex()]

    def update_coincidence_window(self):
        self.coincidence_window_ns = self.time_window_spin.value()

    def set_quick_window(self, window_text):
        window_ns = float(window_text.replace("ns", ""))
        self.time_window_spin.setValue(window_ns)
        self.update_coincidence_window()

    def save_coincidence_settings(self):
        settings = {
            "center_channel": self.center_channel,
            "coincidence_window_ns": self.coincidence_window_ns,
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

    def _calculate_pixie_time_difference(self, timestamp1, timestamp2):
        dt_ticks = timestamp1 - timestamp2
        dt_ns = dt_ticks * 10.0  # Convert to nanoseconds
        return dt_ns

    def clear_data(self):
        self.event_buffer.clear()
        self.coincidence_events.clear()
        self.clear_binary_data()

        # Clear plots
        self.binary_plot.clear()

    def get_coincidence_statistics(self):
        stats = {
            "coincidence_mode": self.coincidence_mode,
            "center_channel": self.center_channel,
            "coincidence_window_ns": self.coincidence_window_ns,
            "total_coincidences": len(self.coincidence_events),
            "events_in_buffer": len(self.event_buffer),
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
