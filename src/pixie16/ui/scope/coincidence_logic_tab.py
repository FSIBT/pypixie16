"""
Coincidence logic tab with binary waveform visualization
"""

import numpy as np
from collections import deque
import time
import json
from pathlib import Path
import csv

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QComboBox, QMessageBox, QSizePolicy,
)
from PyQt6.QtCore import QTimer, pyqtSignal, QMutex, QMutexLocker
import pyqtgraph as pg

from ...analyze import (
    compute_fast_trigger_validation,
    convert_trace_to_FPGA,
    calculate_filter,
    get_fast_trigger_index,
)


class DualChannelBinaryData:    
    def __init__(self, maxlen=100):  # Keep only recent traces
        self.maxlen = maxlen
        self.mutex = QMutex()
        
        self.logic_steps = [
            "raw_threshold",
            "fast_trigger", 
            "validation_window",
            "event_accepted"
        ]
        
        self.ch1_data = {step: deque(maxlen=maxlen) for step in self.logic_steps}
        self.ch2_data = {step: deque(maxlen=maxlen) for step in self.logic_steps}
        
        self.ch1_time_axis = None
        self.ch2_time_axis = None
        
    def add_channel_data(self, channel_id, binary_results):
        with QMutexLocker(self.mutex):
            if channel_id == 1:
                storage = self.ch1_data
                self.ch1_time_axis = binary_results.get("time_axis")
            elif channel_id == 2:
                storage = self.ch2_data
                self.ch2_time_axis = binary_results.get("time_axis")
            else:
                return
                
            for step in self.logic_steps:
                if step in binary_results:
                    storage[step].append(binary_results[step])
    
    def get_latest_data(self):
        with QMutexLocker(self.mutex):
            return {
                'ch1': {step: list(data)[-1] if data else None 
                       for step, data in self.ch1_data.items()},
                'ch2': {step: list(data)[-1] if data else None 
                       for step, data in self.ch2_data.items()},
                'ch1_time_axis': self.ch1_time_axis,
                'ch2_time_axis': self.ch2_time_axis,
            }
    
    def clear(self):
        """Thread-safe data clearing"""
        with QMutexLocker(self.mutex):
            for step in self.logic_steps:
                self.ch1_data[step].clear()
                self.ch2_data[step].clear()
            self.ch1_time_axis = None
            self.ch2_time_axis = None


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
        self.binary_logic_enabled = False
        self.channel1 = self.channels[0]
        self.channel2 = self.channels[1] if len(self.channels) > 1 else self.channels[0]
        self.time_alignment_offset_ns = 0.0
        self.display_time_window_us = 2.0
        
        self.binary_data = DualChannelBinaryData(maxlen=100)
        
        # Hardware parameters
        self.hardware_params = {
            "fast_L": 2,
            "fast_G": 2,
            "fast_threshold": 100,
            "cfd_threshold": 100,
        }
        
        # PIXIE-16 timing (500MHz module)
        self.sampling_period_ns = 2.0
        self.fpga_period_ns = 10.0
        
        # Update timer - MORE AGGRESSIVE
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(False)  # CONTINUOUS updates
        self.update_timer.timeout.connect(self.update_visualization)
        
        # Plot tracking
        self.plot_items = []
        self.reference_lines = []
        
        # Event counters
        self.ch1_event_count = 0
        self.ch2_event_count = 0
        self.coincidence_count = 0
        self.last_update_time = time.time()
        
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
        self.enable_checkbox.setChecked(False)
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
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # Binary logic plot
        self.binary_plot = pg.PlotWidget()
        self.binary_plot.setLabel("left", "Logic Steps")
        self.binary_plot.setLabel("bottom", "Time (ns) - Aligned to Trigger")
        self.binary_plot.setTitle("Dual-Channel Coincidence Logic (Disabled)")
        self.binary_plot.setBackground("w")
        self.binary_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.binary_plot.setMinimumHeight(400)
        
        layout.addWidget(self.binary_plot, 1)
        
        # Status
        self.params_label = QLabel("Hardware Parameters: Not loaded")
        self.params_label.setStyleSheet("font-family: monospace; font-size: 9pt;")
        layout.addWidget(self.params_label)
        
        group.setLayout(layout)
        return group
    
    def setup_plot(self):
        """Setup plot"""
        try:
            self.clear_plot_safely()
            
            self.binary_plot.showGrid(True, True, alpha=0.3)
            
            # Y-axis labels
            y_labels = [
                (4, "Ch1: Event Valid"), 
                (3, "Ch1: Coinc Window"), 
                (2, "Ch1: Fast Trigger"), 
                (1, "Ch1: Raw > Thresh"),
                (0, "═══ Trigger (t=0) ═══"),
                (-1, "Ch2: Raw > Thresh"), 
                (-2, "Ch2: Fast Trigger"),
                (-3, "Ch2: Coinc Window"), 
                (-4, "Ch2: Event Valid"),
            ]
            self.binary_plot.getAxis("left").setTicks([y_labels])
            self.binary_plot.setYRange(-5, 5)
            
            if self.binary_logic_enabled:
                trigger_line = pg.InfiniteLine(
                    pos=0, angle=0, 
                    pen=pg.mkPen(color='black', width=3, style=pg.QtCore.Qt.PenStyle.DashLine)
                )
                time_line = pg.InfiniteLine(
                    pos=0, angle=90,
                    pen=pg.mkPen(color='darkred', width=2, style=pg.QtCore.Qt.PenStyle.DotLine)
                )
                
                self.binary_plot.addItem(trigger_line)
                self.binary_plot.addItem(time_line)
                self.reference_lines = [trigger_line, time_line]
                
        except Exception as e:
            print(f"Error in setup_plot: {e}")
    
    def clear_plot_safely(self):
        try:
            for item in self.plot_items:
                try:
                    self.binary_plot.removeItem(item)
                except:
                    pass
            self.plot_items.clear()
            
            for line in self.reference_lines:
                try:
                    self.binary_plot.removeItem(line)
                except:
                    pass
            self.reference_lines.clear()
            
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
        
        export_btn = QPushButton("Export Timing")
        export_btn.clicked.connect(self.export_timing_data)
        layout.addWidget(export_btn)
        
        return layout
    
    def update_center_channel(self):
        self.center_channel = self.channels[self.center_channel_combo.currentIndex()]
    
    def update_coincidence_window(self):
        self.coincidence_window_ns = self.time_window_spin.value()
        self.update_params_display()
    
    def set_quick_preset(self, preset_text):
        window_ns = float(preset_text.replace("ns", ""))
        self.time_window_spin.setValue(window_ns)
    
    def update_channel1(self):
        new_ch1 = self.channels[self.ch1_combo.currentIndex()]
        self.channel1 = new_ch1
        self.binary_data.clear()
        self.ch1_event_count = 0
        print(f"Channel 1 set to Ch{new_ch1}")
        if new_ch1 == self.channel2:
            print(f"  WARNING: Ch1 and Ch2 are both Ch{new_ch1} - will show duplicate traces")
        self.update_params_display()
    
    def update_channel2(self):
        new_ch2 = self.channels[self.ch2_combo.currentIndex()]
        self.channel2 = new_ch2
        self.binary_data.clear()
        self.ch2_event_count = 0
        print(f"Channel 2 set to Ch{new_ch2}")
        if new_ch2 == self.channel1:
            print(f"  WARNING: Ch1 and Ch2 are both Ch{new_ch2} - will show duplicate traces")
        self.update_params_display()
    
    def update_time_offset(self):
        self.time_alignment_offset_ns = self.offset_spin.value()
    
    def update_display_time_window(self):
        self.display_time_window_us = self.display_time_spin.value()
    
    def toggle_binary_logic(self, enabled):
        """Enable/disable binary logic"""
        try:
            self.binary_logic_enabled = enabled
            
            if enabled:
                print(f"\n{'='*60}")
                print(f"BINARY LOGIC ENABLED")
                print(f"  Channel 1: Ch{self.channel1}")
                print(f"  Channel 2: Ch{self.channel2}")
                print(f"  Fast L: {self.hardware_params['fast_L']} FPGA")
                print(f"  Fast G: {self.hardware_params['fast_G']} FPGA")
                print(f"  Threshold: {self.hardware_params['fast_threshold']} ADC")
                print(f"  Coinc Window: {self.coincidence_window_ns} ns")
                print(f"{'='*60}\n")
                
                self.setup_plot()
                self.update_hardware_params()
                self.binary_plot.setTitle(
                    f"Binary Logic: Ch{self.channel1} vs Ch{self.channel2}"
                )
                
                # Start continuous updates at 10 Hz
                self.update_timer.start(100)
                
                self.status_label.setText("ACTIVE - Waiting for events...")
            else:
                print("Binary logic disabled")
                self.update_timer.stop()
                self.binary_data.clear()
                self.clear_plot_safely()
                
                self.binary_plot.setTitle("Binary Logic (Disabled)")
                self.status_label.setText(
                    f"Disabled - Ch1:{self.ch1_event_count} Ch2:{self.ch2_event_count} Coinc:{self.coincidence_count}"
                )
                
        except Exception as e:
            print(f"Error toggling: {e}")
            import traceback
            traceback.print_exc()
            self.binary_logic_enabled = False
            self.enable_checkbox.setChecked(False)
    
    def add_event_with_trace(self, event, trace_data):
        if not hasattr(event, "timestamp") or not hasattr(event, "channel"):
            return
        
        try:
            # Always store
            self.event_buffer.append((event, trace_data))
            
            # Process if binary logic enabled
            if self.binary_logic_enabled:
                if event.channel == self.channel1:
                    self.ch1_event_count += 1
                    binary_results = self.compute_binary_logic(
                        trace_data, event.channel, event.timestamp, 1
                    )
                    if binary_results:
                        self.binary_data.add_channel_data(1, binary_results)
                        
                        # Debug every 10 events
                        if self.ch1_event_count % 10 == 0:
                            print(f"Ch{self.channel1}: {self.ch1_event_count} events, "
                                  f"raw={np.sum(binary_results['raw_threshold'])}, "
                                  f"fast={np.sum(binary_results['fast_trigger'])}, "
                                  f"valid={np.sum(binary_results['validation_window'])}")
                
                # Process for Ch2 if matches (separate check, not elif!)
                if event.channel == self.channel2:
                    self.ch2_event_count += 1
                    binary_results = self.compute_binary_logic(
                        trace_data, event.channel, event.timestamp, 2
                    )
                    if binary_results:
                        self.binary_data.add_channel_data(2, binary_results)
            
            # Coincidence detection
            if event.channel == self.center_channel:
                self.detect_coincidence(event, trace_data)
                
        except Exception as e:
            print(f"ERROR in add_event_with_trace: {e}")
            import traceback
            traceback.print_exc()
    
    def compute_binary_logic(self, raw_trace, channel, event_timestamp, channel_id):
        """Compute binary logic - ALWAYS returns data even without coincidence"""
        if not self.binary_logic_enabled or len(raw_trace) < 20:
            return None
        
        try:
            raw_trace = np.asarray(raw_trace, dtype=np.uint16)
            trace_length = len(raw_trace)
            
            # Time axis
            trigger_position = int(trace_length * 0.3)
            trigger_time_ns = trigger_position * self.sampling_period_ns
            time_axis = np.arange(trace_length) * self.sampling_period_ns - trigger_time_ns
            
            if channel_id == 2:
                time_axis += self.time_alignment_offset_ns
            
            # STEP 1: Raw threshold
            baseline_samples = min(100, trace_length // 3)
            baseline = np.mean(raw_trace[:baseline_samples])
            threshold = self.hardware_params.get("fast_threshold", 100)
            raw_binary = (raw_trace > (baseline + threshold)).astype(np.int8)
            
            # STEP 2: Fast trigger calc
            try:
                fast_L_us = self.hardware_params.get("fast_L", 2) * 0.01
                fast_G_us = self.hardware_params.get("fast_G", 2) * 0.01
                
                fast_result = calculate_filter(
                    raw_trace[np.newaxis, :],
                    L=fast_L_us,
                    G=fast_G_us,
                    filter_range=0
                )
                
                fast_filter = fast_result[0]
                
                # Match lengths
                if len(fast_filter) < trace_length:
                    fast_filter = np.pad(fast_filter, (0, trace_length - len(fast_filter)), mode='constant')
                elif len(fast_filter) > trace_length:
                    fast_filter = fast_filter[:trace_length]
                
                fast_binary = (fast_filter > threshold).astype(np.int8)
                
            except Exception as e:
                print(f"Fast trigger calc failed: {e}")
                fast_binary = raw_binary.copy()
            
            # STEP 3: Validation window
            validation_binary = np.zeros(trace_length, dtype=np.int8)
            
            window_ticks = self.coincidence_window_ns / 10.0
            coincidence_found = False
            
            # Check event buffer for paired channel
            paired_channel = self.channel2 if channel_id == 1 else self.channel1
            
            for buffered_event, _ in list(self.event_buffer)[-200:]:
                if not hasattr(buffered_event, 'channel') or not hasattr(buffered_event, 'timestamp'):
                    continue
                
                if buffered_event.channel == paired_channel:
                    time_diff_ticks = abs(buffered_event.timestamp - event_timestamp)
                    
                    if time_diff_ticks <= window_ticks:
                        coincidence_found = True
                        self.coincidence_count += 1
                        break
            
            # Show validation window if coincidence detected
            if coincidence_found:
                pulse_start = max(0, trigger_position - 50)
                pulse_end = min(trace_length, trigger_position + 150)
                validation_binary[pulse_start:pulse_end] = 1
            
            # STEP 4: Event accepted = fast AND validation
            event_accepted_binary = fast_binary & validation_binary
            
            return {
                "raw_threshold": raw_binary,
                "fast_trigger": fast_binary,
                "validation_window": validation_binary,
                "event_accepted": event_accepted_binary,
                "time_axis": time_axis,
                "timestamp": event_timestamp,
                "channel": channel,
                "coincidence_found": coincidence_found,
            }
            
        except Exception as e:
            print(f"ERROR compute_binary_logic Ch{channel}: {e}")
            import traceback
            traceback.print_exc()
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
            # Get latest data
            data = self.binary_data.get_latest_data()
            
            # Check if we have data
            has_ch1 = data['ch1']['raw_threshold'] is not None
            has_ch2 = data['ch2']['raw_threshold'] is not None
            
            if not has_ch1 and not has_ch2:
                # Update status
                elapsed = time.time() - self.last_update_time
                if elapsed > 2.0:
                    self.status_label.setText(
                        f"Waiting... Ch1:{self.ch1_event_count} Ch2:{self.ch2_event_count}"
                    )
                    self.last_update_time = time.time()
                return
            
            # Clear and redraw
            self.clear_plot_safely()
            self.setup_plot()
            
            # Plot colors
            colors = {
                "raw_threshold": "#FF4444",
                "fast_trigger": "#FF8800",
                "validation_window": "#00AA00",
                "event_accepted": "#0066CC"
            }
            
            steps = ["raw_threshold", "fast_trigger", "validation_window", "event_accepted"]
            
            # Plot Ch1
            if has_ch1:
                for i, step in enumerate(steps):
                    if data['ch1'][step] is not None:
                        self.plot_binary_step(
                            data['ch1'][step],
                            data['ch1_time_axis'],
                            i + 1,
                            colors[step],
                            f"Ch{self.channel1}: {step.replace('_', ' ').title()}"
                        )
            
            # Plot Ch2
            if has_ch2:
                for i, step in enumerate(steps):
                    if data['ch2'][step] is not None:
                        time_axis = data['ch2_time_axis']
                        if time_axis is not None:
                            time_axis = time_axis + self.time_alignment_offset_ns
                        self.plot_binary_step(
                            data['ch2'][step],
                            time_axis,
                            -(i + 1),
                            colors[step],
                            f"Ch{self.channel2}: {step.replace('_', ' ').title()}"
                        )
            
            # Update status
            self.status_label.setText(
                f"Ch1:{self.ch1_event_count} Ch2:{self.ch2_event_count} | "
                f"Coinc:{self.coincidence_count} | "
                f"{time.strftime('%H:%M:%S')}"
            )
            self.last_update_time = time.time()
            
        except Exception as e:
            print(f"ERROR update_visualization: {e}")
            import traceback
            traceback.print_exc()
    
    def plot_binary_step(self, binary_data, time_axis, y_offset, color, name):
        try:
            if not isinstance(binary_data, np.ndarray) or len(binary_data) == 0:
                return
            
            if time_axis is None or len(time_axis) != len(binary_data):
                return
            
            # Create step plot
            step_x, step_y = [], []
            
            for j in range(len(binary_data)):
                if j == 0:
                    step_x.extend([time_axis[j], time_axis[j]])
                    step_y.extend([y_offset, y_offset + float(binary_data[j])])
                else:
                    step_x.append(time_axis[j])
                    step_y.append(y_offset + float(binary_data[j-1]))
                    step_x.append(time_axis[j])
                    step_y.append(y_offset + float(binary_data[j]))
            
            if len(step_x) > 0:
                step_x.append(time_axis[-1])
                step_y.append(step_y[-1])
                
                plot_item = self.binary_plot.plot(
                    step_x, step_y,
                    pen=pg.mkPen(color=color, width=2.5),
                    name=name
                )
                self.plot_items.append(plot_item)
                
        except Exception as e:
            print(f"ERROR plotting {name}: {e}")
    
    def update_hardware_params(self):
        if not self.hardware_manager:
            self.update_params_display()
            return
        
        try:
            for channel in [self.channel1, self.channel2]:
                hw_params = self.hardware_manager.get_hardware_timing_parameters(channel)
                if hw_params:
                    trigger_risetime_us = hw_params.get('TRIGGER_RISETIME', 0.02)
                    trigger_flattop_us = hw_params.get('TRIGGER_FLATTOP', 0.02)
                    
                    self.hardware_params.update({
                        'fast_L': int(trigger_risetime_us * 100),
                        'fast_G': int(trigger_flattop_us * 100),
                        'fast_threshold': int(hw_params.get('TRIGGER_THRESHOLD', 100)),
                    })
                    break
            
            self.update_params_display()
            
        except Exception as e:
            print(f"Hardware param update failed: {e}")
    
    def update_params_display(self):
        params_text = (
            f"Ch1={self.channel1}, Ch2={self.channel2} | "
            f"Fast L={self.hardware_params.get('fast_L', 2)}, "
            f"G={self.hardware_params.get('fast_G', 2)} | "
            f"Thresh={self.hardware_params.get('fast_threshold', 100)} | "
            f"Window={self.coincidence_window_ns:.1f}ns"
        )
        self.params_label.setText(params_text)
    
    def clear_data(self):
        """Clear all data"""
        try:
            self.update_timer.stop()
            
            self.event_buffer.clear()
            self.coincidence_events.clear()
            self.binary_data.clear()
            self.ch1_event_count = 0
            self.ch2_event_count = 0
            self.coincidence_count = 0
            
            if self.binary_logic_enabled:
                self.clear_plot_safely()
                self.setup_plot()
                self.update_timer.start(100)
                
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
                self, "Settings Saved", 
                f"Saved to {settings_file}\n\n"
                f"Ch1: {self.channel1}, Ch2: {self.channel2}\n"
                f"Window: {self.coincidence_window_ns}ns"
            )
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Error: {e}")
    
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
                        "abs_time_difference_ns": abs(time_diff),
                    })
            
            filename = f"timing_data_{int(time.time())}.csv"
            with open(filename, "w", newline="") as csvfile:
                if export_data:
                    writer = csv.DictWriter(csvfile, fieldnames=export_data[0].keys())
                    writer.writeheader()
                    writer.writerows(export_data)
            
            QMessageBox.information(
                self, "Export Complete", 
                f"Exported {len(export_data)} events to:\n{filename}\n\n"
                f"Total coincidences: {len(self.coincidence_events)}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Error: {e}")
    
    def get_coincidence_statistics(self):
        """Get statistics"""
        stats = {
            "total_coincidences": len(self.coincidence_events),
            "events_in_buffer": len(self.event_buffer),
            "binary_logic_enabled": self.binary_logic_enabled,
            "center_channel": self.center_channel,
            "coincidence_window_ns": self.coincidence_window_ns,
            "channel1": self.channel1,
            "channel2": self.channel2,
            "ch1_events": self.ch1_event_count,
            "ch2_events": self.ch2_event_count,
            "coincidences_detected": self.coincidence_count,
        }
        
        if self.coincidence_events:
            recent = list(self.coincidence_events)[-100:]
            all_diffs = []
            for coinc in recent:
                all_diffs.extend(coinc.time_differences)
            
            if all_diffs:
                abs_diffs = [abs(dt) for dt in all_diffs]
                stats.update({
                    "mean_time_diff_ns": float(np.mean(all_diffs)),
                    "std_time_diff_ns": float(np.std(all_diffs)),
                    "min_time_diff_ns": float(np.min(abs_diffs)),
                    "max_time_diff_ns": float(np.max(abs_diffs)),
                })
        
        return stats
    
    def set_hardware_params(self, params):
        """Update params from parent"""
        self.hardware_params.update(params)
        self.update_params_display()
        
        if self.binary_logic_enabled:
            print(f"Hardware params updated:")
            print(f"  Fast L: {params.get('fast_L')} cycles")
            print(f"  Fast G: {params.get('fast_G')} cycles")
            print(f"  Threshold: {params.get('fast_threshold')} ADC")
    
    def set_channels(self, channels):
        """Update channels list"""
        old_channels = self.channels
        self.channels = channels
        
        if self.channel1 not in self.channels:
            self.channel1 = self.channels[0] if self.channels else 0
        if self.channel2 not in self.channels:
            self.channel2 = self.channels[1] if len(self.channels) > 1 else self.channels[0]
        if self.center_channel not in self.channels:
            self.center_channel = self.channels[0] if self.channels else 0
        
        self.center_channel_combo.clear()
        self.ch1_combo.clear()
        self.ch2_combo.clear()
        
        for ch in self.channels:
            self.center_channel_combo.addItem(f"Ch {ch}")
            self.ch1_combo.addItem(f"Ch {ch}")
            self.ch2_combo.addItem(f"Ch {ch}")
        
        if self.center_channel in self.channels:
            self.center_channel_combo.setCurrentIndex(self.channels.index(self.center_channel))
        if self.channel1 in self.channels:
            self.ch1_combo.setCurrentIndex(self.channels.index(self.channel1))
        if self.channel2 in self.channels:
            self.ch2_combo.setCurrentIndex(self.channels.index(self.channel2))
        
        if old_channels != self.channels:
            self.binary_data.clear()
            self.ch1_event_count = 0
            self.ch2_event_count = 0
        
        self.update_params_display()
    
    def closeEvent(self, event):
        """Clean shutdown"""
        try:
            print("Closing coincidence logic tab...")
            
            if self.update_timer.isActive():
                self.update_timer.stop()
            
            self.binary_data.clear()
            self.event_buffer.clear()
            self.coincidence_events.clear()
            
            self.clear_plot_safely()
            
            print(f"Closed - Ch1:{self.ch1_event_count} Ch2:{self.ch2_event_count} Coinc:{self.coincidence_count}")
            
        except Exception as e:
            print(f"Error during close: {e}")
        finally:
            event.accept()