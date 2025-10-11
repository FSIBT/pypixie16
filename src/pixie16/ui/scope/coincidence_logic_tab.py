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
    QLabel, QDoubleSpinBox, QComboBox, QPushButton, QMessageBox, QSizePolicy,
)
from PyQt6.QtCore import QTimer, pyqtSignal, QMutex, QMutexLocker
import pyqtgraph as pg

from ...analyze import calculate_filter


class DualChannelBinaryData:    
    def __init__(self, maxlen=100):
        self.maxlen = maxlen
        self.mutex = QMutex()
        
        self.logic_steps = [
            "local_fast_trigger",
            "fast_trigger_bp",
            "chan_trig",
            "chan_validation_trig",
            "local_fast_for_processing",
            "validated_trig_for_processing"
        ]
        
        self.ch_a_data = {step: deque(maxlen=maxlen) for step in self.logic_steps}
        self.ch_b_data = {step: deque(maxlen=maxlen) for step in self.logic_steps}
        
        self.ch_a_time_axis = None
        self.ch_b_time_axis = None
        
    def add_channel_data(self, channel_id, binary_results):
        with QMutexLocker(self.mutex):
            if channel_id == 'A':
                storage = self.ch_a_data
                self.ch_a_time_axis = binary_results.get("time_axis")
            elif channel_id == 'B':
                storage = self.ch_b_data
                self.ch_b_time_axis = binary_results.get("time_axis")
            else:
                return
                
            for step in self.logic_steps:
                if step in binary_results:
                    storage[step].append(binary_results[step])
    
    def get_latest_data(self):
        with QMutexLocker(self.mutex):
            return {
                'ch_a': {step: list(data)[-1] if data else None 
                        for step, data in self.ch_a_data.items()},
                'ch_b': {step: list(data)[-1] if data else None 
                        for step, data in self.ch_b_data.items()},
                'ch_a_time_axis': self.ch_a_time_axis,
                'ch_b_time_axis': self.ch_b_time_axis,
            }
    
    def clear(self):
        with QMutexLocker(self.mutex):
            for step in self.logic_steps:
                self.ch_a_data[step].clear()
                self.ch_b_data[step].clear()
            self.ch_a_time_axis = None
            self.ch_b_time_axis = None


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
        
        # Channel selection - A and B
        self.channel_a = self.channels[0]
        self.channel_b = self.channels[1] if len(self.channels) > 1 else self.channels[0]
        
        # Always enabled
        self.binary_logic_enabled = True
        
        # Hardware timing parameters (all in nanoseconds)
        self.hardware_params = {
            # Fast trigger parameters
            "fast_L": 2,  # FPGA cycles
            "fast_G": 2,  # FPGA cycles  
            "fast_threshold": 100,
            
            # Backplane delays and stretches
            "fast_trig_backplane_delay": 0,  # ns (FastTrigBackplaneEna)
            "fast_trig_backplane_len": 200,  # ns (FASTTRIGBACKLEN)
            
            # Channel trigger stretch
            "chan_trig_stretch": 200,  # ns (ChanTrigStretch)
            
            # External delay (to coincidence trigger)
            "external_delay_len": 300,  # ns (ExternDelayLen)
            
            # Validation window
            "validation_window": 1000,  # ns
        }
        
        # PIXIE-16 timing
        self.sampling_period_ns = 2.0  # 500MHz = 2ns/sample
        self.fpga_period_ns = 10.0     # 10ns/FPGA cycle (5 samples)
        
        self.binary_data = DualChannelBinaryData(maxlen=100)
        
        # Update timer - 10Hz continuous
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(False)
        self.update_timer.timeout.connect(self.update_visualization)
        
        # Plot tracking
        self.plot_items = []
        self.reference_lines = []
        
        # Event counters
        self.ch_a_event_count = 0
        self.ch_b_event_count = 0
        self.coincidence_count = 0
        self.last_update_time = time.time()
        
        self.init_ui()
        
        # CRITICAL: Setup plot immediately on initialization
        self.setup_plot()
        
        if self.hardware_manager:
            try:
                self.update_hardware_params()
            except Exception as e:
                print(f"Hardware parameter update failed: {e}")
        
        # Start visualization immediately
        self.update_timer.start(100)
        
        print(f"PIXIE-16 Binary Logic initialized - Ch{self.channel_a}(A) vs Ch{self.channel_b}(B)")
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Channel selection (no enable/disable toggle)
        channel_group = self.create_channel_selection()
        layout.addWidget(channel_group)
        
        # Timing parameters
        timing_group = self.create_timing_controls()
        layout.addWidget(timing_group)
        
        # Binary visualization plot
        binary_group = self.create_binary_visualization()
        layout.addWidget(binary_group)
        
        # Control buttons
        control_layout = self.create_control_buttons()
        layout.addLayout(control_layout)
        
        self.setLayout(layout)
    
    def create_channel_selection(self):
        group = QGroupBox("Channel Selection")
        layout = QHBoxLayout()
        
        layout.addWidget(QLabel("Channel A:"))
        self.ch_a_combo = QComboBox()
        for ch in self.channels:
            self.ch_a_combo.addItem(f"Ch {ch}")
        self.ch_a_combo.currentIndexChanged.connect(self.update_channel_a)
        layout.addWidget(self.ch_a_combo)
        
        layout.addWidget(QLabel("Channel B:"))
        self.ch_b_combo = QComboBox()
        for ch in self.channels:
            self.ch_b_combo.addItem(f"Ch {ch}")
        if len(self.channels) > 1:
            self.ch_b_combo.setCurrentIndex(1)
        self.ch_b_combo.currentIndexChanged.connect(self.update_channel_b)
        layout.addWidget(self.ch_b_combo)
        
        layout.addWidget(QLabel("Time Ref:"))
        self.time_ref_combo = QComboBox()
        self.time_ref_combo.addItems(["Channel A", "Channel B", "Coincidence Trigger"])
        self.time_ref_combo.currentIndexChanged.connect(self.update_time_reference)
        layout.addWidget(self.time_ref_combo)
        
        layout.addStretch()
        
        group.setLayout(layout)
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        return group
    
    def create_timing_controls(self):
        group = QGroupBox("Hardware Timing Parameters (ns)")
        layout = QGridLayout()
        
        # Fast trigger backplane
        layout.addWidget(QLabel("FT BP Delay:"), 0, 0)
        self.ft_bp_delay_spin = QDoubleSpinBox()
        self.ft_bp_delay_spin.setRange(0, 1000)
        self.ft_bp_delay_spin.setValue(0)
        self.ft_bp_delay_spin.setSuffix(" ns")
        self.ft_bp_delay_spin.valueChanged.connect(self.update_timing_params)
        layout.addWidget(self.ft_bp_delay_spin, 0, 1)
        
        layout.addWidget(QLabel("FT BP Length:"), 0, 2)
        self.ft_bp_len_spin = QDoubleSpinBox()
        self.ft_bp_len_spin.setRange(10, 2000)
        self.ft_bp_len_spin.setValue(200)
        self.ft_bp_len_spin.setSuffix(" ns")
        self.ft_bp_len_spin.valueChanged.connect(self.update_timing_params)
        layout.addWidget(self.ft_bp_len_spin, 0, 3)
        
        # Channel trigger stretch
        layout.addWidget(QLabel("Chan Trig Stretch:"), 1, 0)
        self.chan_stretch_spin = QDoubleSpinBox()
        self.chan_stretch_spin.setRange(10, 2000)
        self.chan_stretch_spin.setValue(200)
        self.chan_stretch_spin.setSuffix(" ns")
        self.chan_stretch_spin.valueChanged.connect(self.update_timing_params)
        layout.addWidget(self.chan_stretch_spin, 1, 1)
        
        # External delay
        layout.addWidget(QLabel("External Delay:"), 1, 2)
        self.ext_delay_spin = QDoubleSpinBox()
        self.ext_delay_spin.setRange(0, 2000)
        self.ext_delay_spin.setValue(300)
        self.ext_delay_spin.setSuffix(" ns")
        self.ext_delay_spin.valueChanged.connect(self.update_timing_params)
        layout.addWidget(self.ext_delay_spin, 1, 3)
        
        # Validation window
        layout.addWidget(QLabel("Validation Window:"), 2, 0)
        self.validation_win_spin = QDoubleSpinBox()
        self.validation_win_spin.setRange(100, 5000)
        self.validation_win_spin.setValue(1000)
        self.validation_win_spin.setSuffix(" ns")
        self.validation_win_spin.valueChanged.connect(self.update_timing_params)
        layout.addWidget(self.validation_win_spin, 2, 1)
        
        group.setLayout(layout)
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        return group
    
    def create_binary_visualization(self):
        group = QGroupBox("PIXIE-16 Coincidence Logic Chain")
        layout = QVBoxLayout()
        
        # Binary logic plot
        self.binary_plot = pg.PlotWidget()
        self.binary_plot.setLabel("left", "Logic Signals")
        self.binary_plot.setLabel("bottom", "Time (ns)")
        self.binary_plot.setTitle(f"Ch{self.channel_a} (A) vs Ch{self.channel_b} (B)")
        self.binary_plot.setBackground("w")
        self.binary_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.binary_plot.setMinimumHeight(500)
        
        layout.addWidget(self.binary_plot, 1)
        
        # Status
        self.status_label = QLabel("Ready - Waiting for events...")
        layout.addWidget(self.status_label)
        
        group.setLayout(layout)
        return group
    
    def setup_plot(self):
        try:
            self.clear_plot_safely()
            
            self.binary_plot.showGrid(True, True, alpha=0.3)
            
            # Y-axis labels
            y_ticks = [
                [
                    (11, "Local Fast Trig A"),
                    (10, "Local Fast Trig BP A"),
                    (9, "Local Fast Trig B"),
                    (8, "Local Fast Trig BP B"),
                    (7, "ChanTrig A (A AND B)"),
                    (6, "ChanTrig B (A AND B)"),
                    (5, "Chan Valid Trig A"),
                    (4, "Local FT Proc A"),
                    (3, "Valid Trig Proc A"),
                    (2, "Chan Valid Trig B"),
                    (1, "Local FT Proc B"),
                    (0, "Valid Trig Proc B"),
                ],
                []  # Minor ticks (empty)
            ]
            
            # Force set the ticks
            left_axis = self.binary_plot.getAxis("left")
            left_axis.setTicks(y_ticks)
            left_axis.setStyle(tickTextOffset=10)
            left_axis.setWidth(200)
            
            # Set Y range with padding
            self.binary_plot.setYRange(-0.5, 11.5, padding=0)
            
            # Set labels
            self.binary_plot.setLabel("left", "")  # Clear default label
            self.binary_plot.setLabel("bottom", "Time (ns)")
            
            # Add reference lines at logical separation points
            # Between BP and ChanTrig
            ref_line1 = pg.InfiniteLine(
                pos=7.5, angle=0,
                pen=pg.mkPen(color='gray', width=1, style=pg.QtCore.Qt.PenStyle.DotLine)
            )
            self.binary_plot.addItem(ref_line1)
            self.reference_lines.append(ref_line1)
            
            # Between ChanTrig and Validation
            ref_line2 = pg.InfiniteLine(
                pos=5.5, angle=0,
                pen=pg.mkPen(color='gray', width=1, style=pg.QtCore.Qt.PenStyle.DotLine)
            )
            self.binary_plot.addItem(ref_line2)
            self.reference_lines.append(ref_line2)
            
            # Between A validation and B validation
            ref_line3 = pg.InfiniteLine(
                pos=2.5, angle=0,
                pen=pg.mkPen(color='gray', width=1, style=pg.QtCore.Qt.PenStyle.DotLine)
            )
            self.binary_plot.addItem(ref_line3)
            self.reference_lines.append(ref_line3)
            
            # Time = 0 line
            time_line = pg.InfiniteLine(
                pos=0, angle=90,
                pen=pg.mkPen(color='darkred', width=2, style=pg.QtCore.Qt.PenStyle.DotLine)
            )
            self.binary_plot.addItem(time_line)
            self.reference_lines.append(time_line)
            
            for val, label in sorted(y_ticks[0], key=lambda x: x[0], reverse=True):
                print(f"  Row {val}: {label}")
                
        except Exception as e:
            print(f"ERROR in setup_plot: {e}")
            import traceback
            traceback.print_exc()
    
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
        
        self.params_label = QLabel("")
        self.update_params_display()
        layout.addWidget(self.params_label)
        
        layout.addStretch()
        
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)
        
        export_btn = QPushButton("Export Timing")
        export_btn.clicked.connect(self.export_timing_data)
        layout.addWidget(export_btn)
        
        return layout
    
    def update_channel_a(self):
        self.channel_a = self.channels[self.ch_a_combo.currentIndex()]
        self.binary_data.clear()
        self.ch_a_event_count = 0
        self.binary_plot.setTitle(f"Ch{self.channel_a} (A) vs Ch{self.channel_b} (B)")
        print(f"Channel A set to Ch{self.channel_a}")
        self.update_params_display()
    
    def update_channel_b(self):
        self.channel_b = self.channels[self.ch_b_combo.currentIndex()]
        self.binary_data.clear()
        self.ch_b_event_count = 0
        self.binary_plot.setTitle(f"Ch{self.channel_a} (A) vs Ch{self.channel_b} (B)")
        print(f"Channel B set to Ch{self.channel_b}")
        self.update_params_display()
    
    def update_time_reference(self):
        ref = self.time_ref_combo.currentText()
        print(f"Time reference: {ref}")
        # Will be used in compute_binary_logic to adjust time axis
    
    def update_timing_params(self):
        self.hardware_params.update({
            "fast_trig_backplane_delay": self.ft_bp_delay_spin.value(),
            "fast_trig_backplane_len": self.ft_bp_len_spin.value(),
            "chan_trig_stretch": self.chan_stretch_spin.value(),
            "external_delay_len": self.ext_delay_spin.value(),
            "validation_window": self.validation_win_spin.value(),
        })
        self.update_params_display()
    
    def add_event_with_trace(self, event, trace_data):
        if not hasattr(event, "timestamp") or not hasattr(event, "channel"):
            return
        
        try:
            self.event_buffer.append((event, trace_data))
            
            # Process for Ch A
            if event.channel == self.channel_a:
                self.ch_a_event_count += 1
                binary_results = self.compute_binary_logic(
                    trace_data, event.channel, event.timestamp, 'A'
                )
                if binary_results:
                    self.binary_data.add_channel_data('A', binary_results)
            
            # Process for Ch B
            if event.channel == self.channel_b:
                self.ch_b_event_count += 1
                binary_results = self.compute_binary_logic(
                    trace_data, event.channel, event.timestamp, 'B'
                )
                if binary_results:
                    self.binary_data.add_channel_data('B', binary_results)
                
        except Exception as e:
            print(f"ERROR in add_event_with_trace: {e}")
            import traceback
            traceback.print_exc()
    
    def compute_binary_logic(self, raw_trace, channel, event_timestamp, channel_id):
        if len(raw_trace) < 20:
            return None
        
        try:
            raw_trace = np.asarray(raw_trace, dtype=np.uint16)
            trace_length = len(raw_trace)
            
            # Time axis
            trigger_position = int(trace_length * 0.3)
            trigger_time_ns = trigger_position * self.sampling_period_ns
            time_axis = np.arange(trace_length) * self.sampling_period_ns - trigger_time_ns
            
            # Baseline and threshold
            baseline_samples = min(100, trace_length // 3)
            baseline = np.mean(raw_trace[:baseline_samples])
            threshold = self.hardware_params.get("fast_threshold", 100)
            
            # STEP 1: Local Fast Trigger (10ns pulse)
            # Using analyze.py fast trigger
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
                
                # Resize
                if len(fast_filter) < trace_length:
                    fast_filter = np.pad(fast_filter, (0, trace_length - len(fast_filter)), mode='constant')
                elif len(fast_filter) > trace_length:
                    fast_filter = fast_filter[:trace_length]
                
                # Find first trigger point
                trigger_indices = np.where(fast_filter > threshold)[0]
                if len(trigger_indices) > 0:
                    first_trigger_idx = trigger_indices[0]
                    first_trigger_time_ns = time_axis[first_trigger_idx]
                    
                    # Create 10ns pulse
                    local_fast_trigger = np.zeros(trace_length, dtype=np.int8)
                    pulse_samples = int(10 / self.sampling_period_ns)  # 10ns pulse
                    pulse_end = min(first_trigger_idx + pulse_samples, trace_length)
                    local_fast_trigger[first_trigger_idx:pulse_end] = 1
                else:
                    local_fast_trigger = np.zeros(trace_length, dtype=np.int8)
                    first_trigger_time_ns = None
                    
            except Exception as e:
                print(f"Fast trigger calc failed: {e}")
                local_fast_trigger = np.zeros(trace_length, dtype=np.int8)
                first_trigger_time_ns = None
            
            if first_trigger_time_ns is None:
                # No trigger, return empty signals
                return {
                    "local_fast_trigger": local_fast_trigger,
                    "fast_trigger_bp": np.zeros(trace_length, dtype=np.int8),
                    "chan_trig": np.zeros(trace_length, dtype=np.int8),
                    "chan_validation_trig": np.zeros(trace_length, dtype=np.int8),
                    "local_fast_for_processing": np.zeros(trace_length, dtype=np.int8),
                    "validated_trig_for_processing": np.zeros(trace_length, dtype=np.int8),
                    "time_axis": time_axis,
                    "timestamp": event_timestamp,
                    "channel": channel,
                }
            
            # STEP 2: Fast Trigger Backplane (delayed and stretched)
            bp_delay_ns = self.hardware_params["fast_trig_backplane_delay"]
            bp_len_ns = self.hardware_params["fast_trig_backplane_len"]
            
            fast_trigger_bp = np.zeros(trace_length, dtype=np.int8)
            bp_start_time = first_trigger_time_ns + bp_delay_ns
            bp_end_time = bp_start_time + bp_len_ns
            
            bp_start_idx = np.searchsorted(time_axis, bp_start_time)
            bp_end_idx = np.searchsorted(time_axis, bp_end_time)
            if bp_start_idx < trace_length and bp_end_idx <= trace_length:
                fast_trigger_bp[bp_start_idx:bp_end_idx] = 1
            
            # STEP 3: Channel Trigger (AND of A and B backplane triggers)
            # For this channel, check if OTHER channel had a trigger in buffer
            other_channel = self.channel_b if channel_id == 'A' else self.channel_a
            other_had_trigger = self._check_other_channel_trigger(other_channel, event_timestamp, window_ns=500)
            
            chan_trig = np.zeros(trace_length, dtype=np.int8)
            if other_had_trigger:
                # Calculate when coincidence trigger fires (~110ns after both triggers)
                coinc_delay_ns = 110
                coinc_time = first_trigger_time_ns + bp_delay_ns + coinc_delay_ns
                coinc_idx = np.searchsorted(time_axis, coinc_time)
                
                # 10ns coincidence pulse
                coinc_pulse_samples = int(10 / self.sampling_period_ns)
                coinc_end_idx = min(coinc_idx + coinc_pulse_samples, trace_length)
                if coinc_idx < trace_length:
                    chan_trig[coinc_idx:coinc_end_idx] = 1
                    self.coincidence_count += 1
            
            # STEP 4: Channel Validation Trigger (stretched chan_trig)
            chan_stretch_ns = self.hardware_params["chan_trig_stretch"]
            chan_validation_trig = np.zeros(trace_length, dtype=np.int8)
            
            if np.any(chan_trig > 0):
                val_start_idx = np.where(chan_trig > 0)[0][0]
                val_end_time = time_axis[val_start_idx] + chan_stretch_ns
                val_end_idx = np.searchsorted(time_axis, val_end_time)
                if val_end_idx <= trace_length:
                    chan_validation_trig[val_start_idx:val_end_idx] = 1
            
            # STEP 5: Local Fast for Processing (original trigger + external delay)
            ext_delay_ns = self.hardware_params["external_delay_len"]
            local_fast_for_processing = np.zeros(trace_length, dtype=np.int8)
            
            proc_start_time = first_trigger_time_ns + ext_delay_ns
            proc_start_idx = np.searchsorted(time_axis, proc_start_time)
            proc_pulse_samples = int(10 / self.sampling_period_ns)
            proc_end_idx = min(proc_start_idx + proc_pulse_samples, trace_length)
            if proc_start_idx < trace_length:
                local_fast_for_processing[proc_start_idx:proc_end_idx] = 1
            
            # STEP 6: Validated Trigger for Processing (AND of processing trigger and validation)
            validated_trig_for_processing = local_fast_for_processing & chan_validation_trig
            
            return {
                "local_fast_trigger": local_fast_trigger,
                "fast_trigger_bp": fast_trigger_bp,
                "chan_trig": chan_trig,
                "chan_validation_trig": chan_validation_trig,
                "local_fast_for_processing": local_fast_for_processing,
                "validated_trig_for_processing": validated_trig_for_processing,
                "time_axis": time_axis,
                "timestamp": event_timestamp,
                "channel": channel,
            }
            
        except Exception as e:
            print(f"ERROR compute_binary_logic Ch{channel}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _check_other_channel_trigger(self, other_channel, event_timestamp, window_ns=500):
        window_ticks = window_ns / 10.0  # Convert to 10ns ticks
        
        for buffered_event, _ in list(self.event_buffer)[-200:]:
            if not hasattr(buffered_event, 'channel') or not hasattr(buffered_event, 'timestamp'):
                continue
            
            if buffered_event.channel == other_channel:
                time_diff_ticks = abs(buffered_event.timestamp - event_timestamp)
                if time_diff_ticks <= window_ticks:
                    return True
        
        return False
    
    def update_visualization(self):
        try:
            data = self.binary_data.get_latest_data()
            
            has_ch_a = data['ch_a']['local_fast_trigger'] is not None
            has_ch_b = data['ch_b']['local_fast_trigger'] is not None
            
            if not has_ch_a and not has_ch_b:
                elapsed = time.time() - self.last_update_time
                if elapsed > 2.0:
                    self.status_label.setText(
                        f"Waiting... A:{self.ch_a_event_count} B:{self.ch_b_event_count}"
                    )
                    self.last_update_time = time.time()
                return
            
            # Clear and redraw
            self.clear_plot_safely()
            self.setup_plot()
            
            # Colors for each signal type
            colors = {
                "local_fast_trigger": "#FF0000",            # Red
                "fast_trigger_bp": "#FF6600",               # Orange
                "chan_trig": "#FFAA00",                     # Yellow-Orange
                "chan_validation_trig": "#00AA00",          # Green
                "local_fast_for_processing": "#0066FF",     # Blue
                "validated_trig_for_processing": "#AA00FF"  # Purple
            }
            
            # Y-offsets matching the NEW EXACT ORDER (top to bottom)
            y_offsets = {
                # Row 11-10: A initial triggers
                ("A", "local_fast_trigger"): 11,
                ("A", "fast_trigger_bp"): 10,
                
                # Row 9-8: B initial triggers
                ("B", "local_fast_trigger"): 9,
                ("B", "fast_trigger_bp"): 8,
                
                # Row 7-6: ChanTrig (coincidence)
                ("A", "chan_trig"): 7,
                ("B", "chan_trig"): 6,
                
                # Row 5-3: A validation chain
                ("A", "chan_validation_trig"): 5,
                ("A", "local_fast_for_processing"): 4,
                ("A", "validated_trig_for_processing"): 3,
                
                # Row 2-0: B validation chain
                ("B", "chan_validation_trig"): 2,
                ("B", "local_fast_for_processing"): 1,
                ("B", "validated_trig_for_processing"): 0,
            }
            
            # Plot Channel A signals
            if has_ch_a:
                for step in ["local_fast_trigger", "fast_trigger_bp", "chan_trig",
                            "chan_validation_trig", "local_fast_for_processing", 
                            "validated_trig_for_processing"]:
                    if data['ch_a'][step] is not None:
                        y_offset = y_offsets[("A", step)]
                        self.plot_binary_step(
                            data['ch_a'][step],
                            data['ch_a_time_axis'],
                            y_offset,
                            colors[step],
                            f"A: {step}"
                        )
            
            # Plot Channel B signals
            if has_ch_b:
                for step in ["local_fast_trigger", "fast_trigger_bp", "chan_trig",
                            "chan_validation_trig", "local_fast_for_processing",
                            "validated_trig_for_processing"]:
                    if data['ch_b'][step] is not None:
                        y_offset = y_offsets[("B", step)]
                        self.plot_binary_step(
                            data['ch_b'][step],
                            data['ch_b_time_axis'],
                            y_offset,
                            colors[step],
                            f"B: {step}"
                        )
            
            # Update status
            self.status_label.setText(
                f"Ch{self.channel_a}(A):{self.ch_a_event_count} | "
                f"Ch{self.channel_b}(B):{self.ch_b_event_count} | "
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
            return
        
        try:
            for channel in [self.channel_a, self.channel_b]:
                hw_params = self.hardware_manager.get_hardware_timing_parameters(channel)
                if hw_params:
                    trigger_risetime_us = hw_params.get('TRIGGER_RISETIME', 0.02)
                    trigger_flattop_us = hw_params.get('TRIGGER_FLATTOP', 0.02)
                    
                    self.hardware_params.update({
                        'fast_L': int(trigger_risetime_us * 100),
                        'fast_G': int(trigger_flattop_us * 100),
                        'fast_threshold': int(hw_params.get('TRIGGER_THRESHOLD', 100)),
                    })
                    
                    # Try to get hardware timing values
                    if 'FastTrigBackplaneEna' in hw_params:
                        self.hardware_params['fast_trig_backplane_delay'] = hw_params['FastTrigBackplaneEna']
                        self.ft_bp_delay_spin.setValue(hw_params['FastTrigBackplaneEna'])
                    
                    if 'FASTTRIGBACKLEN' in hw_params:
                        self.hardware_params['fast_trig_backplane_len'] = hw_params['FASTTRIGBACKLEN']
                        self.ft_bp_len_spin.setValue(hw_params['FASTTRIGBACKLEN'])
                    
                    if 'ChanTrigStretch' in hw_params:
                        self.hardware_params['chan_trig_stretch'] = hw_params['ChanTrigStretch']
                        self.chan_stretch_spin.setValue(hw_params['ChanTrigStretch'])
                    
                    if 'ExternDelayLen' in hw_params:
                        self.hardware_params['external_delay_len'] = hw_params['ExternDelayLen']
                        self.ext_delay_spin.setValue(hw_params['ExternDelayLen'])
                    
                    break
            
            self.update_params_display()
            
        except Exception as e:
            print(f"Hardware param update failed: {e}")
    
    def update_params_display(self):
        params_text = (
            f"A=Ch{self.channel_a}, B=Ch{self.channel_b} | "
            f"BP Delay={self.hardware_params['fast_trig_backplane_delay']:.0f}ns, "
            f"BP Len={self.hardware_params['fast_trig_backplane_len']:.0f}ns, "
            f"Chan Stretch={self.hardware_params['chan_trig_stretch']:.0f}ns, "
            f"Ext Delay={self.hardware_params['external_delay_len']:.0f}ns, "
            f"Val Win={self.hardware_params['validation_window']:.0f}ns"
        )
        self.params_label.setText(params_text)
    
    def detect_coincidence(self, center_event, center_trace):
        try:
            coincident_events = []
            
            for buffered_event, buffered_trace in self.event_buffer:
                if buffered_event == center_event:
                    continue
                
                time_diff_ns = abs(self._calculate_time_difference(
                    buffered_event.timestamp, center_event.timestamp
                ))
                
                if time_diff_ns <= 500:  # 500ns window
                    coincident_events.append((buffered_event, buffered_trace))
            
            if coincident_events:
                from .traces_plotter import CoincidenceEvent
                coinc_event = CoincidenceEvent(center_event, center_trace, coincident_events)
                self.coincidence_events.append(coinc_event)
                
        except Exception as e:
            print(f"Coincidence detection error: {e}")
    
    def _calculate_time_difference(self, timestamp1, timestamp2):
        return (timestamp1 - timestamp2) * 10.0
    
    def clear_data(self):
        try:
            self.event_buffer.clear()
            self.coincidence_events.clear()
            self.binary_data.clear()
            self.ch_a_event_count = 0
            self.ch_b_event_count = 0
            self.coincidence_count = 0
            
            self.clear_plot_safely()
            self.setup_plot()
                
            self.status_label.setText("Data cleared")
            
        except Exception as e:
            print(f"Error clearing data: {e}")
    
    def save_settings(self):
        settings = {
            "channel_a": self.channel_a,
            "channel_b": self.channel_b,
            "hardware_params": self.hardware_params,
            "timestamp": time.time(),
        }
        
        try:
            settings_file = Path("pixie_binary_logic_settings.json")
            with open(settings_file, "w") as f:
                json.dump(settings, f, indent=2)
            QMessageBox.information(
                self, "Settings Saved", 
                f"Saved to {settings_file}\n\n"
                f"Ch A: {self.channel_a}, Ch B: {self.channel_b}"
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
            
            filename = f"pixie_timing_data_{int(time.time())}.csv"
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
        stats = {
            "total_coincidences": len(self.coincidence_events),
            "events_in_buffer": len(self.event_buffer),
            "channel_a": self.channel_a,
            "channel_b": self.channel_b,
            "ch_a_events": self.ch_a_event_count,
            "ch_b_events": self.ch_b_event_count,
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
        self.hardware_params.update(params)
        self.update_params_display()
    
    def set_channels(self, channels):
        old_channels = self.channels
        self.channels = channels
        
        if self.channel_a not in self.channels:
            self.channel_a = self.channels[0] if self.channels else 0
        if self.channel_b not in self.channels:
            self.channel_b = self.channels[1] if len(self.channels) > 1 else self.channels[0]
        
        self.ch_a_combo.clear()
        self.ch_b_combo.clear()
        
        for ch in self.channels:
            self.ch_a_combo.addItem(f"Ch {ch}")
            self.ch_b_combo.addItem(f"Ch {ch}")
        
        if self.channel_a in self.channels:
            self.ch_a_combo.setCurrentIndex(self.channels.index(self.channel_a))
        if self.channel_b in self.channels:
            self.ch_b_combo.setCurrentIndex(self.channels.index(self.channel_b))
        
        if old_channels != self.channels:
            self.binary_data.clear()
            self.ch_a_event_count = 0
            self.ch_b_event_count = 0
        
        self.update_params_display()
    
    def closeEvent(self, event):
        try:
            print("Closing PIXIE-16 binary logic tab...")
            
            if self.update_timer.isActive():
                self.update_timer.stop()
            
            self.binary_data.clear()
            self.event_buffer.clear()
            self.coincidence_events.clear()
            
            self.clear_plot_safely()
            
            print(f"Closed - A:{self.ch_a_event_count} B:{self.ch_b_event_count} Coinc:{self.coincidence_count}")
            
        except Exception as e:
            print(f"Error during close: {e}")
        finally:
            event.accept()