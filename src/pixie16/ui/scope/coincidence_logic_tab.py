"""
Coincidence logic tab with binary waveform visualization for coincidence analysis, optimization, and binary logic display.
"""

import numpy as np
from collections import deque
import time
import json
from pathlib import Path
import csv
from threading import Lock

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
    QMessageBox,
    QSizePolicy,
)
from PyQt6.QtCore import QTimer, pyqtSignal
import pyqtgraph as pg

from ...analyze import (
    compute_fast_trigger_validation,
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
            dt_ns = self._calculate_time_difference(
                event.timestamp, center_event.timestamp
            )
            self.time_differences.append(dt_ns)

    def _calculate_time_difference(self, timestamp1, timestamp2):
        dt_ticks = timestamp1 - timestamp2
        dt_ns = dt_ticks * 10.0  # Convert 10ns ticks to nanoseconds
        return dt_ns


class DualChannelBinaryData:    
    def __init__(self, maxlen=1000):
        self.maxlen = maxlen
        
        # Binary logic steps for visualization  
        self.logic_steps = [
            "raw_threshold",
            "fast_trigger", 
            "validation_window",
            "event_accepted"
        ]
        
        # Simple storage without threading locks
        self.ch1_data = {step: deque(maxlen=maxlen) for step in self.logic_steps}
        self.ch2_data = {step: deque(maxlen=maxlen) for step in self.logic_steps}
        
    def add_channel_data(self, channel_id, binary_results):
        if channel_id == 1:
            storage = self.ch1_data
        elif channel_id == 2:
            storage = self.ch2_data
        else:
            return
            
        # Store results for each logic step
        for step in self.logic_steps:
            if step in binary_results:
                storage[step].append(binary_results[step])
    
    def get_latest_data(self):
        return {
            'ch1': {step: list(data)[-1] if data else None 
                   for step, data in self.ch1_data.items()},
            'ch2': {step: list(data)[-1] if data else None 
                   for step, data in self.ch2_data.items()},
        }
    
    def clear(self):
        for step in self.logic_steps:
            self.ch1_data[step].clear()
            self.ch2_data[step].clear()

class CoincidenceLogicTab(QWidget):    
    # Signals
    parameter_changed = pyqtSignal(str, object, int, int)
    
    def __init__(self, channels=None, hardware_manager=None, parent=None):
        super().__init__(parent)
        
        self.channels = channels or list(range(16))
        self.hardware_manager = hardware_manager
        
        if len(self.channels) < 2:
            self.channels = list(range(2))  # Default to Ch0, Ch1
            
        # Event storage for coincidence analysis
        self.event_buffer = deque(maxlen=50000)
        self.coincidence_events = deque(maxlen=10000)
        
        # Coincidence settings
        self.center_channel = self.channels[0]
        self.coincidence_window_ns = 20.0
        self.coincidence_mode = False
        
        # Dual-channel binary logic settings
        self.binary_logic_enabled = True
        self.channel1 = self.channels[0]
        self.channel2 = self.channels[1] if len(self.channels) > 1 else self.channels[0]
        self.time_alignment_offset_ns = 0.0
        self.display_time_window_us = 2.0
        
        self.binary_data = DualChannelBinaryData(maxlen=1000)
        
        # Hardware parameters
        self.hardware_params = {
            "fast_L": 2,
            "fast_G": 2,
            "fast_threshold": 100,
            "cfd_threshold": 100,
        }
        
        self.binary_hardware_params = {
            "channel_trigger_stretch_ns": 200,
            "external_delay_length_ns": 300,
            "fast_threshold": 100,
        }
        
        # PIXIE-16 timing constants
        self.sampling_period_ns = 2.0  # 500MHz module
        
        self.init_ui()
        
        if self.hardware_manager:
            try:
                self.update_hardware_params()
            except Exception as e:
                print(f"Hardware parameter update failed: {e}")
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Coincidence settings group
        settings_group = self.create_coincidence_settings()
        layout.addWidget(settings_group)
        
        # Binary logic visualization group
        binary_group = self.create_binary_visualization()
        layout.addWidget(binary_group)
        
        # Control buttons
        control_layout = self.create_control_buttons()
        layout.addLayout(control_layout)
        
        self.setLayout(layout)
    
    def create_coincidence_settings(self):
        group = QGroupBox("Coincidence Analysis Settings")
        layout = QGridLayout()
        
        # Center channel
        layout.addWidget(QLabel("Center Channel:"), 0, 0)
        self.center_channel_combo = QComboBox()
        for ch in self.channels:
            self.center_channel_combo.addItem(f"Ch {ch}")
        if self.center_channel in self.channels:
            self.center_channel_combo.setCurrentIndex(self.channels.index(self.center_channel))
        self.center_channel_combo.currentIndexChanged.connect(self.update_center_channel)
        layout.addWidget(self.center_channel_combo, 0, 1)
        
        # Time window
        layout.addWidget(QLabel("Time Window:"), 0, 2)
        self.time_window_spin = QDoubleSpinBox()
        self.time_window_spin.setRange(5.0, 1000.0)
        self.time_window_spin.setValue(self.coincidence_window_ns)
        self.time_window_spin.setSuffix(" ns")
        self.time_window_spin.valueChanged.connect(self.update_coincidence_window)
        layout.addWidget(self.time_window_spin, 0, 3)
        
        # Quick presets
        layout.addWidget(QLabel("Quick Presets:"), 1, 0)
        self.quick_preset_combo = QComboBox()
        self.quick_preset_combo.addItems(["10ns", "20ns", "50ns", "100ns", "200ns", "500ns"])
        self.quick_preset_combo.setCurrentText("20ns")
        self.quick_preset_combo.currentTextChanged.connect(self.set_quick_preset)
        layout.addWidget(self.quick_preset_combo, 1, 1)
        
        group.setLayout(layout)
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        return group
    
    def create_binary_visualization(self):
        group = QGroupBox("Dual-Channel Binary Logic Visualization")
        layout = QVBoxLayout()
        
        # Controls
        controls_layout = QHBoxLayout()
        
        # Enable checkbox
        self.enable_checkbox = QCheckBox("Enable Binary Logic View")
        self.enable_checkbox.setChecked(True)
        self.enable_checkbox.toggled.connect(self.toggle_binary_logic)
        controls_layout.addWidget(self.enable_checkbox)
        
        # Channel 1 selection
        controls_layout.addWidget(QLabel("Channel 1:"))
        self.ch1_combo = QComboBox()
        for ch in self.channels:
            self.ch1_combo.addItem(f"Ch {ch}")
        self.ch1_combo.currentIndexChanged.connect(self.update_channel1)
        controls_layout.addWidget(self.ch1_combo)
        
        # Channel 2 selection
        controls_layout.addWidget(QLabel("Channel 2:"))
        self.ch2_combo = QComboBox()
        for ch in self.channels:
            self.ch2_combo.addItem(f"Ch {ch}")
        if len(self.channels) > 1:
            self.ch2_combo.setCurrentIndex(1)
        self.ch2_combo.currentIndexChanged.connect(self.update_channel2)
        controls_layout.addWidget(self.ch2_combo)
        
        # Time alignment offset
        controls_layout.addWidget(QLabel("Ch2 Offset:"))
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-500.0, 500.0)
        self.offset_spin.setValue(0.0)
        self.offset_spin.setSuffix(" ns")
        self.offset_spin.setDecimals(1)
        self.offset_spin.setSingleStep(0.1)
        self.offset_spin.valueChanged.connect(self.update_time_offset)
        controls_layout.addWidget(self.offset_spin)
        
        # Display time window
        controls_layout.addWidget(QLabel("Display Window:"))
        self.display_time_spin = QDoubleSpinBox()
        self.display_time_spin.setRange(0.5, 10.0)
        self.display_time_spin.setValue(2.0)
        self.display_time_spin.setSuffix(" μs")
        self.display_time_spin.valueChanged.connect(self.update_display_time_window)
        controls_layout.addWidget(self.display_time_spin)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # Binary logic plot
        self.binary_plot = pg.PlotWidget()
        self.setup_plot()
        layout.addWidget(self.binary_plot, 1)
        
        # Hardware parameters display
        self.params_label = QLabel("Hardware Parameters: Loading...")
        self.params_label.setStyleSheet("font-family: monospace; font-size: 9pt;")
        layout.addWidget(self.params_label)
        
        group.setLayout(layout)
        return group
    
    def setup_plot(self):
        self.binary_plot.setLabel("left", "Logic Steps (Ch1: +, Ch2: -)")
        self.binary_plot.setLabel("bottom", "Time (ns) - Aligned to Trigger")
        self.binary_plot.setTitle("Dual-Channel Coincidence Logic")
        self.binary_plot.showGrid(True, True, alpha=0.3)
        self.binary_plot.setBackground("w")
        self.binary_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.binary_plot.setMinimumHeight(300)
        
        # Y-axis labels for dual-channel display
        y_labels = [
            (4, "Ch1 Event Accepted"), (3, "Ch1 Validation Window"), 
            (2, "Ch1 Fast Trigger"), (1, "Ch1 Raw > Threshold"),
            (0, "Trigger Reference (t=0)"),
            (-1, "Ch2 Raw > Threshold"), (-2, "Ch2 Fast Trigger"),
            (-3, "Ch2 Validation Window"), (-4, "Ch2 Event Accepted"),
        ]
        self.binary_plot.getAxis("left").setTicks([y_labels])
        self.binary_plot.setYRange(-5, 5)
        
        # Add reference lines
        trigger_line = pg.InfiniteLine(pos=0, angle=0, 
                                     pen=pg.mkPen(color='black', width=2, style=pg.QtCore.Qt.PenStyle.DashLine))
        time_line = pg.InfiniteLine(pos=0, angle=90,
                                  pen=pg.mkPen(color='gray', width=1, style=pg.QtCore.Qt.PenStyle.DotLine))
        self.binary_plot.addItem(trigger_line)
        self.binary_plot.addItem(time_line)
    
    def create_control_buttons(self):
        layout = QHBoxLayout()
        
        self.status_label = QLabel("Ready for coincidence analysis")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        
        # Save settings
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)
        
        # Export data
        export_btn = QPushButton("Export Timing Data")
        export_btn.clicked.connect(self.export_timing_data)
        layout.addWidget(export_btn)
        
        return layout
    
    # Event handlers
    def update_center_channel(self):
        self.center_channel = self.channels[self.center_channel_combo.currentIndex()]
    
    def update_coincidence_window(self):
        self.coincidence_window_ns = self.time_window_spin.value()
    
    def set_quick_preset(self, preset_text):
        window_ns = float(preset_text.replace("ns", ""))
        self.time_window_spin.setValue(window_ns)
    
    def update_channel1(self):
        new_ch1 = self.channels[self.ch1_combo.currentIndex()]
        if new_ch1 != self.channel2:  # Prevent same channel selection
            self.channel1 = new_ch1
            self.binary_data.clear()
    
    def update_channel2(self):
        new_ch2 = self.channels[self.ch2_combo.currentIndex()]
        if new_ch2 != self.channel1:  # Prevent same channel selection
            self.channel2 = new_ch2
            self.binary_data.clear()
    
    def update_time_offset(self):
        self.time_alignment_offset_ns = self.offset_spin.value()
    
    def update_display_time_window(self):
        self.display_time_window_us = self.display_time_spin.value()
    
    def toggle_binary_logic(self, enabled):
        self.binary_logic_enabled = enabled
        if enabled:
            self.update_hardware_params()
        else:
            self.binary_plot.clear()
            self.setup_plot()  # Restore reference lines
    
    # Core functionality
    def add_event_with_trace(self, event, trace_data):
        if not hasattr(event, "timestamp") or not hasattr(event, "channel"):
            return
        
        try:
            # Store in event buffer for coincidence analysis
            self.event_buffer.append((event, trace_data))
            
            # Process binary logic for relevant channels
            if event.channel == self.channel1:
                binary_results = self.compute_binary_logic(trace_data, event.channel, event.timestamp, 1)
                if binary_results:
                    self.binary_data.add_channel_data(1, binary_results)
                    
            elif event.channel == self.channel2:
                binary_results = self.compute_binary_logic(trace_data, event.channel, event.timestamp, 2)
                if binary_results:
                    self.binary_data.add_channel_data(2, binary_results)
            
            # Handle coincidence detection
            if event.channel == self.center_channel:
                self.detect_coincidence(event, trace_data)
                
            # Update visualization
            if self.binary_logic_enabled:
                self.update_visualization()
                
        except Exception as e:
            print(f"Error processing event: {e}")
    
    def compute_binary_logic(self, raw_trace, channel, event_timestamp, channel_id):
        if not self.binary_logic_enabled or len(raw_trace) < 10:
            return None
        
        trace_length = len(raw_trace)
        
        # Create time axis aligned to trigger (30% into trace)
        trigger_position = int(trace_length * 0.3)
        trigger_time_ns = trigger_position * self.sampling_period_ns
        time_axis = np.arange(trace_length) * self.sampling_period_ns - trigger_time_ns
        
        # Apply channel 2 time offset
        if channel_id == 2:
            time_axis += self.time_alignment_offset_ns
        
        try:
            # Raw threshold crossing
            baseline = np.mean(raw_trace[:100]) if len(raw_trace) > 100 else np.mean(raw_trace)
            threshold = self.hardware_params["fast_threshold"]
            raw_binary = (raw_trace > (baseline + threshold)).astype(int)
            
            # Fast trigger using analyze.py functions
            fast_binary = self.compute_fast_trigger_binary(raw_trace)
            
            # Validation window (based on coincidence detection)
            validation_binary = self.compute_validation_window(event_timestamp, trace_length)
            
            # Event accepted (fast trigger AND validation)
            event_accepted_binary = fast_binary & validation_binary
            
            return {
                "raw_threshold": raw_binary,
                "fast_trigger": fast_binary,
                "validation_window": validation_binary,
                "event_accepted": event_accepted_binary,
                "time_axis": time_axis,
                "timestamp": event_timestamp,
                "channel": channel
            }
            
        except Exception as e:
            print(f"Binary logic computation failed for channel {channel}: {e}")
            return None
    
    def compute_fast_trigger_binary(self, raw_trace):
        try:
            # Use the hardware parameters
            fast_L = self.hardware_params.get('fast_L', 2)
            fast_G = self.hardware_params.get('fast_G', 2)
            fast_threshold = self.hardware_params.get('fast_threshold', 100)
            
            # Use compute_fast_trigger_validation from analyze.py
            result = compute_fast_trigger_validation(
                raw_trace.reshape(1, -1),
                L=fast_L,
                G=fast_G,
                threshold=fast_threshold
            )
            
            if result['validation_passed'] and result['fast_triggers'] is not None:
                fast_filter = result['fast_triggers'][0]
                
                # Match trace length
                if len(fast_filter) < len(raw_trace):
                    pad_length = len(raw_trace) - len(fast_filter)
                    fast_filter = np.pad(fast_filter, (pad_length, 0), mode='constant')
                elif len(fast_filter) > len(raw_trace):
                    fast_filter = fast_filter[:len(raw_trace)]
                
                return (fast_filter > fast_threshold).astype(int)
            else:
                # Fallback to simple threshold
                baseline = np.mean(raw_trace[:100]) if len(raw_trace) > 100 else np.mean(raw_trace)
                return (raw_trace > (baseline + fast_threshold)).astype(int)
                
        except Exception as e:
            print(f"Fast trigger computation failed: {e}")
            # Simple fallback
            baseline = np.mean(raw_trace[:100]) if len(raw_trace) > 100 else np.mean(raw_trace)
            threshold = self.hardware_params.get('fast_threshold', 100)
            return (raw_trace > (baseline + threshold)).astype(int)
    
    def compute_validation_window(self, event_timestamp, trace_length):
        validation_binary = np.zeros(trace_length, dtype=int)
        
        # Check for coincident events within the window
        current_time_ticks = event_timestamp
        window_ticks = self.coincidence_window_ns / 10.0  # Convert ns to 10ns ticks
        
        coincident_found = False
        for buffered_event, _ in list(self.event_buffer)[-50:]:  # Check recent events
            if not hasattr(buffered_event, 'channel') or not hasattr(buffered_event, 'timestamp'):
                continue
            
            # Skip same channel events
            if buffered_event.channel == (self.channel1 if event_timestamp == current_time_ticks else self.channel2):
                continue
            
            time_diff_ticks = abs(buffered_event.timestamp - current_time_ticks)
            
            if time_diff_ticks <= window_ticks:
                coincident_found = True
                break
        
        # Show validation pulse if coincidence found
        if coincident_found:
            pulse_start = trace_length // 3
            pulse_width = min(100, trace_length // 5)
            pulse_end = min(pulse_start + pulse_width, trace_length)
            validation_binary[pulse_start:pulse_end] = 1
        
        return validation_binary
    
    def detect_coincidence(self, center_event, center_trace):
        coincident_events = []
        
        # Look for events within the coincidence window
        for buffered_event, buffered_trace in self.event_buffer:
            if buffered_event == center_event:
                continue
            
            time_diff_ns = abs(self._calculate_time_difference(
                buffered_event.timestamp, center_event.timestamp
            ))
            
            if time_diff_ns <= self.coincidence_window_ns:
                coincident_events.append((buffered_event, buffered_trace))
        
        # Store coincidence event if found
        if coincident_events:
            coinc_event = CoincidenceEvent(center_event, center_trace, coincident_events)
            self.coincidence_events.append(coinc_event)
    
    def _calculate_time_difference(self, timestamp1, timestamp2):
        dt_ticks = timestamp1 - timestamp2
        return dt_ticks * 10.0  # Convert to nanoseconds
    
    def update_visualization(self):
        if not self.binary_logic_enabled:
            return
        
        # Get latest data
        data = self.binary_data.get_latest_data()
        
        # Clear plot but preserve reference lines
        self.binary_plot.clear()
        self.setup_plot()
        
        # Plot colors for logic steps
        colors = ["red", "orange", "green", "blue"]
        steps = ["raw_threshold", "fast_trigger", "validation_window", "event_accepted"]
        
        # Plot Channel 1 (positive Y axis)
        for i, step in enumerate(steps):
            if data['ch1'][step] is not None:
                binary_trace = data['ch1'][step]
                y_offset = i + 1
                self.plot_binary_step(binary_trace, y_offset, colors[i], f"Ch1 {step}")
        
        # Plot Channel 2 (negative Y axis) 
        for i, step in enumerate(steps):
            if data['ch2'][step] is not None:
                binary_trace = data['ch2'][step]
                y_offset = -(i + 1)
                self.plot_binary_step(binary_trace, y_offset, colors[i], f"Ch2 {step}")
    
    def plot_binary_step(self, binary_data, y_offset, color, name):
        if len(binary_data) == 0:
            return
        
        # Create time axis
        trace_length = len(binary_data)
        trigger_position = int(trace_length * 0.3)
        trigger_time_ns = trigger_position * self.sampling_period_ns
        time_axis = np.arange(trace_length) * self.sampling_period_ns - trigger_time_ns
        
        # Create step plot data
        step_x, step_y = [], []
        
        for j in range(len(binary_data)):
            if j == 0:
                step_x.extend([time_axis[j], time_axis[j]])
                step_y.extend([y_offset, y_offset + binary_data[j]])
            else:
                # Horizontal line
                step_x.append(time_axis[j])
                step_y.append(y_offset + binary_data[j-1])
                # Vertical transition
                step_x.append(time_axis[j])
                step_y.append(y_offset + binary_data[j])
        
        # Plot the step
        self.binary_plot.plot(
            step_x, step_y,
            pen=pg.mkPen(color=color, width=2),
            name=name
        )
    
    # Hardware integration
    def update_hardware_params(self):
        if not self.hardware_manager:
            return
        
        try:
            # Get parameters for the selected channels
            for channel in [self.channel1, self.channel2]:
                hw_params = self.hardware_manager.get_hardware_timing_parameters(channel)
                if hw_params:
                    self.hardware_params.update({
                        'fast_L': self._convert_time_to_fpga_cycles(hw_params.get('TRIGGER_RISETIME', 0.02)),
                        'fast_G': self._convert_time_to_fpga_cycles(hw_params.get('TRIGGER_FLATTOP', 0.02)),
                        'fast_threshold': hw_params.get('TRIGGER_THRESHOLD', 100),
                    })
                    
                    self.binary_hardware_params.update({
                        'channel_trigger_stretch_ns': hw_params.get('ChanTrigStretch', 0) * 1000,
                        'external_delay_length_ns': hw_params.get('ExternDelayLen', 0) * 1000,
                    })
                    break  # Use first available channel's parameters
            
            self.update_params_display()
            
        except Exception as e:
            print(f"Hardware parameter update failed: {e}")
    
    def _convert_time_to_fpga_cycles(self, time_us):
        return int(time_us * 100)  # 500MHz module: time_us * 100 cycles/us
    
    def update_params_display(self):
        params_text = (
            f"Ch1={self.channel1}, Ch2={self.channel2} | "
            f"FastL/G: {self.hardware_params.get('fast_L', 2)}/{self.hardware_params.get('fast_G', 2)} | "
            f"Threshold: {self.hardware_params.get('fast_threshold', 100)} | "
            f"Window: {self.coincidence_window_ns}ns"
        )
        self.params_label.setText(params_text)
    
    # Data management
    def clear_data(self):
        self.event_buffer.clear()
        self.coincidence_events.clear()
        self.binary_data.clear()
        
        if self.binary_logic_enabled:
            self.binary_plot.clear()
            self.setup_plot()
    
    def save_settings(self):
        settings = {
            "center_channel": self.center_channel,
            "coincidence_window_ns": self.coincidence_window_ns,
            "channel1": self.channel1,
            "channel2": self.channel2,
            "time_alignment_offset_ns": self.time_alignment_offset_ns,
            "display_time_window_us": self.display_time_window_us,
            "binary_logic_enabled": self.binary_logic_enabled,
            "hardware_params": self.hardware_params,
            "binary_hardware_params": self.binary_hardware_params,
            "timestamp": time.time(),
        }
        
        settings_file = Path("coincidence_settings.json")
        try:
            with open(settings_file, "w") as f:
                json.dump(settings, f, indent=2)
            QMessageBox.information(
                self, "Settings Saved", f"Settings saved to {settings_file}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Failed to save: {e}")
    
    def export_timing_data(self):
        if not self.coincidence_events:
            QMessageBox.warning(self, "No Data", "No coincidence data to export.")
            return
        
        # Collect timing data
        export_data = []
        for i, coinc_event in enumerate(self.coincidence_events):
            center_timestamp = coinc_event.center_event.timestamp
            center_channel = coinc_event.center_event.channel
            center_energy = getattr(coinc_event.center_event, "energy", 0)
            
            for j, (event, time_diff) in enumerate(
                zip(coinc_event.associated_events, coinc_event.time_differences)
            ):
                export_data.append({
                    "coincidence_id": i,
                    "center_channel": center_channel,
                    "center_timestamp": center_timestamp,
                    "center_energy": center_energy,
                    "associated_channel": event[0].channel,
                    "associated_timestamp": event[0].timestamp,
                    "associated_energy": getattr(event[0], "energy", 0),
                    "time_difference_ns": time_diff,
                    "abs_time_difference_ns": abs(time_diff),
                })
        
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
            QMessageBox.critical(self, "Export Failed", f"Failed to export: {e}")
    
    # Utility methods
    def get_coincidence_statistics(self):
        """Get coincidence analysis statistics."""
        stats = {
            "center_channel": self.center_channel,
            "coincidence_window_ns": self.coincidence_window_ns,
            "channel1": self.channel1,
            "channel2": self.channel2,
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
                abs_diffs = [abs(dt) for dt in all_time_diffs]
                stats.update({
                    "mean_time_difference_ns": np.mean(all_time_diffs),
                    "std_time_difference_ns": np.std(all_time_diffs),
                    "min_time_difference_ns": np.min(abs_diffs),
                    "max_time_difference_ns": np.max(abs_diffs),
                    "events_in_window": len([dt for dt in abs_diffs if dt <= self.coincidence_window_ns]),
                    "window_efficiency": len([dt for dt in abs_diffs if dt <= self.coincidence_window_ns]) / len(abs_diffs) * 100,
                })
        
        return stats
    
    def set_hardware_params(self, params):
        self.hardware_params.update(params)
        self.binary_hardware_params["fast_threshold"] = params.get("fast_threshold", 100)
        self.update_params_display()
    
    def set_channels(self, channels):
        old_channels = self.channels
        self.channels = channels
        
        # Ensure we still have valid channels selected
        if self.channel1 not in self.channels:
            self.channel1 = self.channels[0] if self.channels else 0
        if self.channel2 not in self.channels:
            self.channel2 = self.channels[1] if len(self.channels) > 1 else self.channels[0]
        if self.center_channel not in self.channels:
            self.center_channel = self.channels[0] if self.channels else 0
        
        # Update combo boxes
        self.center_channel_combo.clear()
        self.ch1_combo.clear()
        self.ch2_combo.clear()
        
        for ch in self.channels:
            self.center_channel_combo.addItem(f"Ch {ch}")
            self.ch1_combo.addItem(f"Ch {ch}")
            self.ch2_combo.addItem(f"Ch {ch}")
        
        # Set current selections
        if self.center_channel in self.channels:
            self.center_channel_combo.setCurrentIndex(self.channels.index(self.center_channel))
        if self.channel1 in self.channels:
            self.ch1_combo.setCurrentIndex(self.channels.index(self.channel1))
        if self.channel2 in self.channels:
            self.ch2_combo.setCurrentIndex(self.channels.index(self.channel2))
        
        # Clear data if channels changed
        if old_channels != self.channels:
            self.binary_data.clear()
        
        self.update_params_display()