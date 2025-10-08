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
from PyQt6.QtCore import QTimer, pyqtSignal, QMutex, QMutexLocker
import pyqtgraph as pg


class DualChannelBinaryData:    
    def __init__(self, maxlen=1000):
        self.maxlen = maxlen
        self.mutex = QMutex()  # Qt thread-safe mutex
        
        self.logic_steps = [
            "raw_threshold",
            "fast_trigger", 
            "validation_window",
            "event_accepted"
        ]
        
        self.ch1_data = {step: deque(maxlen=maxlen) for step in self.logic_steps}
        self.ch2_data = {step: deque(maxlen=maxlen) for step in self.logic_steps}
        
    def add_channel_data(self, channel_id, binary_results):
        """Thread-safe data addition"""
        with QMutexLocker(self.mutex):
            if channel_id == 1:
                storage = self.ch1_data
            elif channel_id == 2:
                storage = self.ch2_data
            else:
                return
                
            for step in self.logic_steps:
                if step in binary_results:
                    storage[step].append(binary_results[step])
    
    def get_latest_data(self):
        """Thread-safe data retrieval"""
        with QMutexLocker(self.mutex):
            return {
                'ch1': {step: list(data)[-1] if data else None 
                       for step, data in self.ch1_data.items()},
                'ch2': {step: list(data)[-1] if data else None 
                       for step, data in self.ch2_data.items()},
            }
    
    def clear(self):
        """Thread-safe data clearing"""
        with QMutexLocker(self.mutex):
            for step in self.logic_steps:
                self.ch1_data[step].clear()
                self.ch2_data[step].clear()


class CoincidenceLogicTab(QWidget):    
    parameter_changed = pyqtSignal(str, object, int, int)
    
    def __init__(self, channels=None, hardware_manager=None, parent=None):
        super().__init__(parent)
        
        self.channels = channels or list(range(16))
        self.hardware_manager = hardware_manager
        
        if len(self.channels) < 2:
            self.channels = list(range(2))
            
        # Event storage
        self.event_buffer = deque(maxlen=50000)
        self.coincidence_events = deque(maxlen=10000)
        
        # Settings
        self.center_channel = self.channels[0]
        self.coincidence_window_ns = 20.0
        self.coincidence_mode = False
        
        # Dual-channel binary logic
        self.binary_logic_enabled = False  # Start disabled
        self.channel1 = self.channels[0]
        self.channel2 = self.channels[1] if len(self.channels) > 1 else self.channels[0]
        self.time_alignment_offset_ns = 0.0
        self.display_time_window_us = 2.0
        
        self.binary_data = DualChannelBinaryData(maxlen=1000)
        
        # Hardware parameters with defaults
        self.hardware_params = {
            "fast_L": 2,
            "fast_G": 2,
            "fast_threshold": 100,
            "cfd_threshold": 100,
        }
        
        # PIXIE-16 timing
        self.sampling_period_ns = 2.0
        
        # Update timer - IMPORTANT: set parent to self
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.update_visualization)
        
        # Plot items storage
        self.plot_items = []
        self.reference_lines = []
        
        self.init_ui()
        
        if self.hardware_manager:
            try:
                self.update_hardware_params()
            except Exception as e:
                print(f"Hardware parameter update failed: {e}")
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        settings_group = self.create_coincidence_settings()
        layout.addWidget(settings_group)
        
        binary_group = self.create_binary_visualization()
        layout.addWidget(binary_group)
        
        control_layout = self.create_control_buttons()
        layout.addLayout(control_layout)
        
        self.setLayout(layout)
    
    def create_coincidence_settings(self):
        group = QGroupBox("Coincidence Analysis Settings")
        layout = QGridLayout()
        
        layout.addWidget(QLabel("Center Channel:"), 0, 0)
        self.center_channel_combo = QComboBox()
        for ch in self.channels:
            self.center_channel_combo.addItem(f"Ch {ch}")
        if self.center_channel in self.channels:
            self.center_channel_combo.setCurrentIndex(self.channels.index(self.center_channel))
        self.center_channel_combo.currentIndexChanged.connect(self.update_center_channel)
        layout.addWidget(self.center_channel_combo, 0, 1)
        
        layout.addWidget(QLabel("Time Window:"), 0, 2)
        self.time_window_spin = QDoubleSpinBox()
        self.time_window_spin.setRange(5.0, 1000.0)
        self.time_window_spin.setValue(self.coincidence_window_ns)
        self.time_window_spin.setSuffix(" ns")
        self.time_window_spin.valueChanged.connect(self.update_coincidence_window)
        layout.addWidget(self.time_window_spin, 0, 3)
        
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
        
        self.enable_checkbox = QCheckBox("Enable Binary Logic View")
        self.enable_checkbox.setChecked(False)  # Start disabled
        self.enable_checkbox.toggled.connect(self.toggle_binary_logic)
        controls_layout.addWidget(self.enable_checkbox)
        
        controls_layout.addWidget(QLabel("Channel 1:"))
        self.ch1_combo = QComboBox()
        for ch in self.channels:
            self.ch1_combo.addItem(f"Ch {ch}")
        self.ch1_combo.currentIndexChanged.connect(self.update_channel1)
        controls_layout.addWidget(self.ch1_combo)
        
        controls_layout.addWidget(QLabel("Channel 2:"))
        self.ch2_combo = QComboBox()
        for ch in self.channels:
            self.ch2_combo.addItem(f"Ch {ch}")
        if len(self.channels) > 1:
            self.ch2_combo.setCurrentIndex(1)
        self.ch2_combo.currentIndexChanged.connect(self.update_channel2)
        controls_layout.addWidget(self.ch2_combo)
        
        controls_layout.addWidget(QLabel("Ch2 Offset:"))
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-500.0, 500.0)
        self.offset_spin.setValue(0.0)
        self.offset_spin.setSuffix(" ns")
        self.offset_spin.setDecimals(1)
        self.offset_spin.setSingleStep(0.1)
        self.offset_spin.valueChanged.connect(self.update_time_offset)
        controls_layout.addWidget(self.offset_spin)
        
        controls_layout.addWidget(QLabel("Display Window:"))
        self.display_time_spin = QDoubleSpinBox()
        self.display_time_spin.setRange(0.5, 10.0)
        self.display_time_spin.setValue(2.0)
        self.display_time_spin.setSuffix(" μs")
        self.display_time_spin.valueChanged.connect(self.update_display_time_window)
        controls_layout.addWidget(self.display_time_spin)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # Binary logic plot - IMPORTANT: Create but don't populate yet
        self.binary_plot = pg.PlotWidget()
        self.binary_plot.setLabel("left", "Logic Steps")
        self.binary_plot.setLabel("bottom", "Time (ns)")
        self.binary_plot.setTitle("Dual-Channel Coincidence Logic (Disabled)")
        self.binary_plot.setBackground("w")
        self.binary_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.binary_plot.setMinimumHeight(300)
        
        layout.addWidget(self.binary_plot, 1)
        
        self.params_label = QLabel("Hardware Parameters: Not loaded")
        self.params_label.setStyleSheet("font-family: monospace; font-size: 9pt;")
        layout.addWidget(self.params_label)
        
        group.setLayout(layout)
        return group
    
    def setup_plot(self):
        """Setup plot with proper initialization"""
        try:
            # Clear existing items safely
            self.clear_plot_safely()
            
            self.binary_plot.showGrid(True, True, alpha=0.3)
            
            # Y-axis labels
            y_labels = [
                (4, "Ch1 Event"), (3, "Ch1 Validation"), 
                (2, "Ch1 Fast Trigger"), (1, "Ch1 Raw>Thresh"),
                (0, "Trigger Ref (t=0)"),
                (-1, "Ch2 Raw>Thresh"), (-2, "Ch2 Fast Trigger"),
                (-3, "Ch2 Validation"), (-4, "Ch2 Event"),
            ]
            self.binary_plot.getAxis("left").setTicks([y_labels])
            self.binary_plot.setYRange(-5, 5)
            
            # Add reference lines ONLY if enabled
            if self.binary_logic_enabled:
                trigger_line = pg.InfiniteLine(
                    pos=0, angle=0, 
                    pen=pg.mkPen(color='black', width=2, style=pg.QtCore.Qt.PenStyle.DashLine)
                )
                time_line = pg.InfiniteLine(
                    pos=0, angle=90,
                    pen=pg.mkPen(color='gray', width=1, style=pg.QtCore.Qt.PenStyle.DotLine)
                )
                
                self.binary_plot.addItem(trigger_line)
                self.binary_plot.addItem(time_line)
                self.reference_lines = [trigger_line, time_line]
                
        except Exception as e:
            print(f"Error in setup_plot: {e}")
    
    def clear_plot_safely(self):
        """Safely clear all plot items"""
        try:
            # Remove tracked items
            for item in self.plot_items:
                try:
                    self.binary_plot.removeItem(item)
                except:
                    pass
            self.plot_items.clear()
            
            # Remove reference lines
            for line in self.reference_lines:
                try:
                    self.binary_plot.removeItem(line)
                except:
                    pass
            self.reference_lines.clear()
            
            # Final clear
            self.binary_plot.clear()
            
        except Exception as e:
            print(f"Error clearing plot: {e}")
    
    def create_control_buttons(self):
        layout = QHBoxLayout()
        
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)
        
        export_btn = QPushButton("Export Timing Data")
        export_btn.clicked.connect(self.export_timing_data)
        layout.addWidget(export_btn)
        
        return layout
    
    def update_center_channel(self):
        self.center_channel = self.channels[self.center_channel_combo.currentIndex()]
    
    def update_coincidence_window(self):
        self.coincidence_window_ns = self.time_window_spin.value()
    
    def set_quick_preset(self, preset_text):
        window_ns = float(preset_text.replace("ns", ""))
        self.time_window_spin.setValue(window_ns)
    
    def update_channel1(self):
        new_ch1 = self.channels[self.ch1_combo.currentIndex()]
        if new_ch1 != self.channel2:
            self.channel1 = new_ch1
            self.binary_data.clear()
            self.status_label.setText(f"Channel 1 changed to Ch{new_ch1}")
    
    def update_channel2(self):
        new_ch2 = self.channels[self.ch2_combo.currentIndex()]
        if new_ch2 != self.channel1:
            self.channel2 = new_ch2
            self.binary_data.clear()
            self.status_label.setText(f"Channel 2 changed to Ch{new_ch2}")
    
    def update_time_offset(self):
        self.time_alignment_offset_ns = self.offset_spin.value()
    
    def update_display_time_window(self):
        self.display_time_window_us = self.display_time_spin.value()
    
    def toggle_binary_logic(self, enabled):
        try:
            self.binary_logic_enabled = enabled
            
            if enabled:
                print(f"Enabling binary logic for Ch{self.channel1} and Ch{self.channel2}")
                self.setup_plot()
                self.update_hardware_params()
                self.binary_plot.setTitle(
                    f"Binary Logic: Ch{self.channel1} vs Ch{self.channel2}"
                )
                self.status_label.setText("Binary logic enabled")
            else:
                print("Disabling binary logic")
                # Stop timer FIRST
                if self.update_timer.isActive():
                    self.update_timer.stop()
                
                # Clear data
                self.binary_data.clear()
                
                # Clear plot
                self.clear_plot_safely()
                
                self.binary_plot.setTitle("Binary Logic (Disabled)")
                self.status_label.setText("Binary logic disabled")
                
        except Exception as e:
            print(f"Error toggling binary logic: {e}")
            self.binary_logic_enabled = False
            self.enable_checkbox.setChecked(False)
    
    def add_event_with_trace(self, event, trace_data):
        """Main entry point for event processing"""
        if not hasattr(event, "timestamp") or not hasattr(event, "channel"):
            return
        
        try:
            # Always store for coincidence analysis
            self.event_buffer.append((event, trace_data))
            
            # Process binary logic ONLY if enabled
            if self.binary_logic_enabled:
                if event.channel == self.channel1:
                    binary_results = self.compute_binary_logic(
                        trace_data, event.channel, event.timestamp, 1
                    )
                    if binary_results:
                        self.binary_data.add_channel_data(1, binary_results)
                        
                elif event.channel == self.channel2:
                    binary_results = self.compute_binary_logic(
                        trace_data, event.channel, event.timestamp, 2
                    )
                    if binary_results:
                        self.binary_data.add_channel_data(2, binary_results)
                
                # Schedule visualization update (debounced)
                if not self.update_timer.isActive():
                    self.update_timer.start(100)  # 100ms debounce
            
            # Coincidence detection
            if event.channel == self.center_channel:
                self.detect_coincidence(event, trace_data)
                
        except Exception as e:
            print(f"Error processing event: {e}")
            import traceback
            traceback.print_exc()
    
    def compute_binary_logic(self, raw_trace, channel, event_timestamp, channel_id):
        """Compute binary logic representation - SAFE version"""
        if not self.binary_logic_enabled or len(raw_trace) < 10:
            return None
        
        try:
            trace_length = len(raw_trace)
            
            # Time axis
            trigger_position = int(trace_length * 0.3)
            trigger_time_ns = trigger_position * self.sampling_period_ns
            time_axis = np.arange(trace_length) * self.sampling_period_ns - trigger_time_ns
            
            if channel_id == 2:
                time_axis += self.time_alignment_offset_ns
            
            # Raw threshold
            baseline = np.mean(raw_trace[:min(100, len(raw_trace))])
            threshold = self.hardware_params.get("fast_threshold", 100)
            raw_binary = (raw_trace > (baseline + threshold)).astype(np.int8)
            
            # Fast trigger (simplified - no hardware calls during acquisition)
            fast_binary = raw_binary.copy()  # Placeholder
            
            # Validation window
            validation_binary = np.zeros(trace_length, dtype=np.int8)
            pulse_start = trace_length // 3
            pulse_width = min(100, trace_length // 5)
            pulse_end = min(pulse_start + pulse_width, trace_length)
            validation_binary[pulse_start:pulse_end] = 1
            
            # Event accepted
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
            print(f"Binary logic error for Ch{channel}: {e}")
            return None
    
    def detect_coincidence(self, center_event, center_trace):
        try:
            coincident_events = []
            
            for buffered_event, buffered_trace in self.event_buffer:
                if buffered_event == center_event:
                    continue
                
                time_diff_ns = abs(self._calculate_time_difference(
                    buffered_event.timestamp, center_event.timestamp
                ))
                
                if time_diff_ns <= self.coincidence_window_ns:
                    coincident_events.append((buffered_event, buffered_trace))
            
            if coincident_events:
                from .traces_plotter import CoincidenceEvent
                coinc_event = CoincidenceEvent(center_event, center_trace, coincident_events)
                self.coincidence_events.append(coinc_event)
                
        except Exception as e:
            print(f"Coincidence detection error: {e}")
    
    def _calculate_time_difference(self, timestamp1, timestamp2):
        return (timestamp1 - timestamp2) * 10.0
    
    def update_visualization(self):
        if not self.binary_logic_enabled:
            return
        
        try:
            # Get data (thread-safe)
            data = self.binary_data.get_latest_data()
            
            # Clear plot safely
            self.clear_plot_safely()
            self.setup_plot()
            
            # Plot colors
            colors = ["red", "orange", "green", "blue"]
            steps = ["raw_threshold", "fast_trigger", "validation_window", "event_accepted"]
            
            # Plot Ch1 (positive Y)
            for i, step in enumerate(steps):
                if data['ch1'][step] is not None:
                    self.plot_binary_step(data['ch1'][step], i + 1, colors[i], f"Ch1 {step}")
            
            # Plot Ch2 (negative Y)
            for i, step in enumerate(steps):
                if data['ch2'][step] is not None:
                    self.plot_binary_step(data['ch2'][step], -(i + 1), colors[i], f"Ch2 {step}")
            
            self.status_label.setText("Visualization updated")
            
        except Exception as e:
            print(f"Visualization update error: {e}")
            self.status_label.setText(f"Viz error: {str(e)[:30]}")
    
    def plot_binary_step(self, binary_data, y_offset, color, name):
        """Plot a binary step - safe version"""
        try:
            if not isinstance(binary_data, np.ndarray) or len(binary_data) == 0:
                return
            
            trace_length = len(binary_data)
            trigger_position = int(trace_length * 0.3)
            trigger_time_ns = trigger_position * self.sampling_period_ns
            time_axis = np.arange(trace_length) * self.sampling_period_ns - trigger_time_ns
            
            # Create step plot
            step_x, step_y = [], []
            
            for j in range(min(len(binary_data), len(time_axis))):
                if j == 0:
                    step_x.extend([time_axis[j], time_axis[j]])
                    step_y.extend([y_offset, y_offset + binary_data[j]])
                else:
                    step_x.append(time_axis[j])
                    step_y.append(y_offset + binary_data[j-1])
                    step_x.append(time_axis[j])
                    step_y.append(y_offset + binary_data[j])
            
            # Plot and track
            if len(step_x) > 0 and len(step_y) > 0:
                plot_item = self.binary_plot.plot(
                    step_x, step_y,
                    pen=pg.mkPen(color=color, width=2),
                    name=name
                )
                self.plot_items.append(plot_item)
                
        except Exception as e:
            print(f"Error plotting {name}: {e}")
    
    def update_hardware_params(self):
        """Update hardware parameters"""
        if not self.hardware_manager:
            return
        
        try:
            for channel in [self.channel1, self.channel2]:
                hw_params = self.hardware_manager.get_hardware_timing_parameters(channel)
                if hw_params:
                    self.hardware_params.update({
                        'fast_L': self._convert_time_to_fpga_cycles(
                            hw_params.get('TRIGGER_RISETIME', 0.02)
                        ),
                        'fast_G': self._convert_time_to_fpga_cycles(
                            hw_params.get('TRIGGER_FLATTOP', 0.02)
                        ),
                        'fast_threshold': hw_params.get('TRIGGER_THRESHOLD', 100),
                    })
                    break
            
            self.update_params_display()
            
        except Exception as e:
            print(f"Hardware param update failed: {e}")
    
    def _convert_time_to_fpga_cycles(self, time_us):
        return int(time_us * 100)
    
    def update_params_display(self):
        params_text = (
            f"Ch1={self.channel1}, Ch2={self.channel2} | "
            f"FastL/G: {self.hardware_params.get('fast_L', 2)}/{self.hardware_params.get('fast_G', 2)} | "
            f"Threshold: {self.hardware_params.get('fast_threshold', 100)} | "
            f"Window: {self.coincidence_window_ns}ns"
        )
        self.params_label.setText(params_text)
    
    def clear_data(self):
        try:
            # Stop timer first
            if self.update_timer.isActive():
                self.update_timer.stop()
            
            self.event_buffer.clear()
            self.coincidence_events.clear()
            self.binary_data.clear()
            
            if self.binary_logic_enabled:
                self.clear_plot_safely()
                self.setup_plot()
                
            self.status_label.setText("Data cleared")
            
        except Exception as e:
            print(f"Error clearing data: {e}")
    
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
            "timestamp": time.time(),
        }
        
        try:
            settings_file = Path("coincidence_settings.json")
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
        
        try:
            export_data = []
            for i, coinc_event in enumerate(self.coincidence_events):
                center_timestamp = coinc_event.center_event.timestamp
                center_channel = coinc_event.center_event.channel
                center_energy = getattr(coinc_event.center_event, "energy", 0)
                
                for event, time_diff in zip(
                    coinc_event.associated_events, coinc_event.time_differences
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
                    })
            
            filename = f"timing_data_{int(time.time())}.csv"
            with open(filename, "w", newline="") as csvfile:
                if export_data:
                    writer = csv.DictWriter(csvfile, fieldnames=export_data[0].keys())
                    writer.writeheader()
                    writer.writerows(export_data)
            
            QMessageBox.information(
                self, "Export Complete", f"Exported {len(export_data)} events to {filename}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Failed to export: {e}")
    
    def get_coincidence_statistics(self):
        """Get statistics"""
        stats = {
            "total_coincidences": len(self.coincidence_events),
            "events_in_buffer": len(self.event_buffer),
            "binary_logic_enabled": self.binary_logic_enabled,
            "center_channel": self.center_channel,
            "coincidence_window_ns": self.coincidence_window_ns,
        }
        
        if self.coincidence_events:
            recent = list(self.coincidence_events)[-100:]
            all_diffs = []
            for coinc in recent:
                all_diffs.extend(coinc.time_differences)
            
            if all_diffs:
                abs_diffs = [abs(dt) for dt in all_diffs]
                stats.update({
                    "mean_time_diff_ns": np.mean(all_diffs),
                    "std_time_diff_ns": np.std(all_diffs),
                    "min_time_diff_ns": np.min(abs_diffs),
                    "max_time_diff_ns": np.max(abs_diffs),
                })
        
        return stats
    
    def set_hardware_params(self, params):
        self.hardware_params.update(params)
        self.update_params_display()
    
    def set_channels(self, channels):
        old_channels = self.channels
        self.channels = channels
        
        # Ensure valid channel selections
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
    
    def closeEvent(self, event):
        try:
            print("Closing coincidence logic tab...")
            
            # Stop timer
            if self.update_timer.isActive():
                self.update_timer.stop()
            
            # Clear data
            self.binary_data.clear()
            self.event_buffer.clear()
            self.coincidence_events.clear()
            
            # Clear plot
            self.clear_plot_safely()
            
            print("Coincidence logic tab closed cleanly")
            
        except Exception as e:
            print(f"Error during coincidence tab close: {e}")
        finally:
            event.accept()