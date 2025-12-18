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
    QLabel, QDoubleSpinBox, QComboBox, QPushButton, QMessageBox, 
    QSizePolicy, QCheckBox, QSpinBox,
)
from PyQt6.QtCore import QTimer, pyqtSignal, QMutex, QMutexLocker
import pyqtgraph as pg

from ...analyze import calculate_filter


class BinaryHistogramData:
    def __init__(self, time_bins=2000, time_range_ns=4000):
        self.time_bins = time_bins
        self.time_range_ns = time_range_ns
        self.bin_edges = np.linspace(-time_range_ns/2, time_range_ns/2, time_bins+1)
        
        # Histogram for each logic step
        self.histograms = {
            "local_fast_trigger": np.zeros(time_bins),
            "fast_trigger_bp": np.zeros(time_bins),
            "chan_trig": np.zeros(time_bins),
            "chan_validation_trig": np.zeros(time_bins),
            "local_fast_for_processing": np.zeros(time_bins),
            "validated_trig_for_processing": np.zeros(time_bins),
        }
        
        self.total_events = 0
    
    def add_binary_trace(self, time_axis, binary_data, step_name):
        if step_name not in self.histograms:
            return
        
        # Find where signal is HIGH (value = 1)
        high_indices = np.where(binary_data > 0)[0]
        
        if len(high_indices) > 0:
            high_times = time_axis[high_indices]
            hist, _ = np.histogram(high_times, bins=self.bin_edges)
            self.histograms[step_name] += hist
            
        self.total_events += 1
    
    def get_histogram(self, step_name, normalize=False):
        if step_name not in self.histograms:
            return None, None
        
        hist = self.histograms[step_name].copy()
        
        if normalize and self.total_events > 0:
            hist = hist / self.total_events
        
        # Return histogram and bin centers
        bin_centers = (self.bin_edges[:-1] + self.bin_edges[1:]) / 2
        return bin_centers, hist
    
    def clear(self):
        for key in self.histograms:
            self.histograms[key].fill(0)
        self.total_events = 0


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
        
        # Histogram persistence data
        self.ch_a_histogram = BinaryHistogramData()
        self.ch_b_histogram = BinaryHistogramData()
        
    def add_channel_data(self, channel_id, binary_results):
        with QMutexLocker(self.mutex):
            if channel_id == 'A':
                storage = self.ch_a_data
                histogram = self.ch_a_histogram
                self.ch_a_time_axis = binary_results.get("time_axis")
            elif channel_id == 'B':
                storage = self.ch_b_data
                histogram = self.ch_b_histogram
                self.ch_b_time_axis = binary_results.get("time_axis")
            else:
                return
            
            time_axis = binary_results.get("time_axis")
            
            for step in self.logic_steps:
                if step in binary_results:
                    storage[step].append(binary_results[step])
                    # Add to histogram
                    if time_axis is not None:
                        histogram.add_binary_trace(time_axis, binary_results[step], step)
    
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
    
    def get_histogram_data(self, channel_id, normalize=False):
        with QMutexLocker(self.mutex):
            if channel_id == 'A':
                histogram = self.ch_a_histogram
            elif channel_id == 'B':
                histogram = self.ch_b_histogram
            else:
                return {}
            
            histograms = {}
            for step in self.logic_steps:
                bin_centers, hist = histogram.get_histogram(step, normalize)
                if hist is not None:
                    histograms[step] = (bin_centers, hist)
            
            return histograms, histogram.total_events
    
    def clear(self):
        with QMutexLocker(self.mutex):
            for step in self.logic_steps:
                self.ch_a_data[step].clear()
                self.ch_b_data[step].clear()
            self.ch_a_time_axis = None
            self.ch_b_time_axis = None
            self.ch_a_histogram.clear()
            self.ch_b_histogram.clear()


class CoincidenceLogicTab(QWidget):    
    parameter_changed = pyqtSignal(str, object, int, int)
    request_controls_widget = pyqtSignal(object)
    
    def __init__(self, channels=None, hardware_manager=None, parent=None):
        super().__init__(parent)
        
        self.channels = channels or list(range(16))
        self.hardware_manager = hardware_manager
        
        # Channel A timing reference for alignment
        self.reference_timestamp = None
        self.reference_time_axis_offset = 200.0  # Default offset
        
        if len(self.channels) < 2:
            self.channels = list(range(2))
            
        # Event storage
        self.event_buffer = deque(maxlen=50000)
        self.coincidence_events = deque(maxlen=10000)

        self.coincidence_mode = False
        
        # Channel selection
        self.channel_a = self.channels[0]
        self.channel_b = self.channels[1] if len(self.channels) > 1 else self.channels[0]
        
        # Always enabled
        self.binary_logic_enabled = True
        
        # Histogram settings
        self.show_histograms = True
        self.histogram_normalize = False
        self.histogram_alpha = 0.3  # Transparency
        
        # Hardware timing parameters (ns)
        # These are read from hardware or can be adjusted manually
        self.hardware_params = {
            "fast_L": 2,
            "fast_G": 2,
            "fast_threshold": 100,
            "fast_trig_backplane_delay": 0,
            "fast_trig_backplane_len": 200,
            "chan_trig_stretch": 50,   # Further decreased for tighter validation window
            "external_delay_len": 300,
            "validation_window": 1000,
        }
        
        self.sampling_period_ns = 2.0
        self.fpga_period_ns = 10.0
        
        self.binary_data = DualChannelBinaryData(maxlen=100)
        
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(False)
        self.update_timer.timeout.connect(self.update_visualization)
        
        self.plot_items = []
        self.reference_lines = []
        self.histogram_items = []
        
        self.ch_a_event_count = 0
        self.ch_b_event_count = 0
        self.coincidence_count = 0
        
        # Validation statistics
        self.ch_a_validation_stats = {
            "blue_in_green_count": 0,
            "yellow_valid_count": 0,
            "total_events": 0,
            "cross_channel_events": 0,
            "cross_channel_aligned": 0
        }
        self.ch_b_validation_stats = {
            "blue_in_green_count": 0,
            "yellow_valid_count": 0,
            "total_events": 0,
            "cross_channel_events": 0,
            "cross_channel_aligned": 0
        }
        self.last_update_time = time.time()
        
        self.controls_widget = None
        
        self.init_ui()
        self.setup_plot()
        
        self.update_timer.start(100)
        print(f"PIXIE-16 Binary Logic initialized - Ch{self.channel_a}(A) vs Ch{self.channel_b}(B)")
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        histogram_group = self.create_histogram_controls()
        layout.addWidget(histogram_group)
        
        binary_group = self.create_binary_visualization()
        layout.addWidget(binary_group)
        
        control_layout = self.create_control_buttons()
        layout.addLayout(control_layout)
        
        self.setLayout(layout)
    
    def create_coincidence_controls_widget(self):
        if self.controls_widget is not None:
            return self.controls_widget
        
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Channel Selection
        channel_group = QGroupBox("Channel Selection")
        channel_layout = QGridLayout()
        
        channel_layout.addWidget(QLabel("Channel A:"), 0, 0)
        self.ch_a_combo = QComboBox()
        for ch in self.channels:
            self.ch_a_combo.addItem(f"Ch {ch}")
        self.ch_a_combo.currentIndexChanged.connect(self.update_channel_a)
        channel_layout.addWidget(self.ch_a_combo, 0, 1)
        
        channel_layout.addWidget(QLabel("Channel B:"), 1, 0)
        self.ch_b_combo = QComboBox()
        for ch in self.channels:
            self.ch_b_combo.addItem(f"Ch {ch}")
        if len(self.channels) > 1:
            self.ch_b_combo.setCurrentIndex(1)
        self.ch_b_combo.currentIndexChanged.connect(self.update_channel_b)
        channel_layout.addWidget(self.ch_b_combo, 1, 1)
        
        channel_layout.addWidget(QLabel("Time Ref:"), 2, 0)
        self.time_ref_combo = QComboBox()
        self.time_ref_combo.addItems(["Channel A", "Channel B", "Coincidence Trigger"])
        channel_layout.addWidget(self.time_ref_combo, 2, 1)
        
        channel_group.setLayout(channel_layout)
        channel_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout.addWidget(channel_group)
        
        # Hardware Timing Parameters
        timing_group = QGroupBox("Hardware Timing Parameters (ns)")
        timing_layout = QGridLayout()
        
        row = 0
        timing_layout.addWidget(QLabel("FT BP Delay:"), row, 0)
        self.ft_bp_delay_spin = QDoubleSpinBox()
        self.ft_bp_delay_spin.setRange(0, 1000)
        self.ft_bp_delay_spin.setValue(0)
        self.ft_bp_delay_spin.setSuffix(" ns")
        self.ft_bp_delay_spin.valueChanged.connect(self.update_timing_params)
        timing_layout.addWidget(self.ft_bp_delay_spin, row, 1)
        
        row += 1
        timing_layout.addWidget(QLabel("FT BP Length:"), row, 0)
        self.ft_bp_len_spin = QDoubleSpinBox()
        self.ft_bp_len_spin.setRange(10, 10000)
        self.ft_bp_len_spin.setValue(200)
        self.ft_bp_len_spin.setSuffix(" ns")
        self.ft_bp_len_spin.valueChanged.connect(self.update_timing_params)
        timing_layout.addWidget(self.ft_bp_len_spin, row, 1)
        
        row += 1
        timing_layout.addWidget(QLabel("Chan Trig Stretch:"), row, 0)
        self.chan_stretch_spin = QDoubleSpinBox()
        self.chan_stretch_spin.setRange(10, 10000)
        self.chan_stretch_spin.setValue(50)   # Further decreased for tighter validation
        self.chan_stretch_spin.setSuffix(" ns")
        self.chan_stretch_spin.valueChanged.connect(self.update_timing_params)
        timing_layout.addWidget(self.chan_stretch_spin, row, 1)
        
        row += 1
        timing_layout.addWidget(QLabel("External Delay:"), row, 0)
        self.ext_delay_spin = QDoubleSpinBox()
        self.ext_delay_spin.setRange(0, 10000)
        self.ext_delay_spin.setValue(300)
        self.ext_delay_spin.setSuffix(" ns")
        self.ext_delay_spin.valueChanged.connect(self.update_timing_params)
        timing_layout.addWidget(self.ext_delay_spin, row, 1)
        
        row += 1
        timing_layout.addWidget(QLabel("Validation Window:"), row, 0)
        self.validation_win_spin = QDoubleSpinBox()
        self.validation_win_spin.setRange(100, 10000)
        self.validation_win_spin.setValue(1000)
        self.validation_win_spin.setSuffix(" ns")
        self.validation_win_spin.valueChanged.connect(self.update_timing_params)
        timing_layout.addWidget(self.validation_win_spin, row, 1)
        
        row += 1
        apply_hw_btn = QPushButton("Apply to Hardware")
        apply_hw_btn.clicked.connect(self.apply_timing_to_hardware)
        timing_layout.addWidget(apply_hw_btn, row, 0, 1, 2)
        
        timing_group.setLayout(timing_layout)
        timing_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout.addWidget(timing_group)
        
        # Info display
        info_group = QGroupBox("Current Settings")
        info_layout = QVBoxLayout()
        self.params_label = QLabel("")
        self.params_label.setWordWrap(True)
        self.params_label.setStyleSheet("QLabel { font-size: 9pt; padding: 5px; }")
        self.update_params_display()
        info_layout.addWidget(self.params_label)
        info_group.setLayout(info_layout)
        info_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout.addWidget(info_group)
        
        layout.addStretch()
        
        widget.setLayout(layout)
        self.controls_widget = widget
        return widget
    
    def on_tab_activated(self):
        # Resume computations when tab becomes active
        if not self.update_timer.isActive():
            self.update_timer.start(100)
            print("CoincidenceLogicTab: Resumed compute-intensive timer updates")
        
        controls = self.create_coincidence_controls_widget()
        self.request_controls_widget.emit(controls)
        print("CoincidenceLogicTab: Requested custom controls widget for right panel")
    
    def on_tab_deactivated(self):
        # pause computations when tab is not visible to save CPU
        if self.update_timer.isActive():
            self.update_timer.stop()
            print("CoincidenceLogicTab: Paused compute-intensive timer updates to save CPU")
        
        self.request_controls_widget.emit(None)  # None = restore default
        print("CoincidenceLogicTab: Requested restore default controls")
    
    def create_histogram_controls(self):
        group = QGroupBox("Histogram Persistence (Shows Timing Jitter)")
        layout = QHBoxLayout()
        
        self.hist_enable_cb = QCheckBox("Show Histograms")
        self.hist_enable_cb.setChecked(True)
        self.hist_enable_cb.toggled.connect(self.toggle_histograms)
        layout.addWidget(self.hist_enable_cb)
        
        self.hist_normalize_cb = QCheckBox("Normalize")
        self.hist_normalize_cb.setChecked(False)
        self.hist_normalize_cb.toggled.connect(self.toggle_normalize)
        layout.addWidget(self.hist_normalize_cb)
        
        layout.addWidget(QLabel("Alpha:"))
        self.hist_alpha_spin = QDoubleSpinBox()
        self.hist_alpha_spin.setRange(0.1, 0.9)
        self.hist_alpha_spin.setValue(0.3)
        self.hist_alpha_spin.setSingleStep(0.1)
        self.hist_alpha_spin.valueChanged.connect(self.update_histogram_alpha)
        layout.addWidget(self.hist_alpha_spin)
        
        clear_hist_btn = QPushButton("Clear Histograms")
        clear_hist_btn.clicked.connect(self.clear_histograms)
        layout.addWidget(clear_hist_btn)
        
        self.hist_stats_label = QLabel("Events: 0")
        layout.addWidget(self.hist_stats_label)
        
        layout.addStretch()
        
        group.setLayout(layout)
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        return group
    
    def create_binary_visualization(self):
        group = QGroupBox("PIXIE-16 Coincidence Logic Chain")
        layout = QVBoxLayout()
        
        self.binary_plot = pg.PlotWidget()
        self.binary_plot.setLabel("left", "Logic Signals")
        self.binary_plot.setLabel("bottom", "Time (ns)")
        self.binary_plot.setTitle(f"Ch{self.channel_a} (A) vs Ch{self.channel_b} (B)")
        self.binary_plot.setBackground("w")
        self.binary_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.binary_plot.setMinimumHeight(600)
        
        layout.addWidget(self.binary_plot, 1)
        
        self.status_label = QLabel("Ready - Waiting for events...")
        layout.addWidget(self.status_label)
        
        group.setLayout(layout)
        return group
    
    def setup_plot(self):
        try:
            self.clear_plot_safely()
            
            self.binary_plot.showGrid(True, True, alpha=0.3)
            
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
                []
            ]
            
            left_axis = self.binary_plot.getAxis("left")
            left_axis.setTicks(y_ticks)
            left_axis.setStyle(tickTextOffset=10)
            left_axis.setWidth(200)
            
            self.binary_plot.setYRange(-0.5, 11.5, padding=0)
            self.binary_plot.setLabel("left", "")
            self.binary_plot.setLabel("bottom", "Time (ns)")
            
            for y_pos in [7.5, 5.5, 2.5]:
                ref_line = pg.InfiniteLine(
                    pos=y_pos, angle=0,
                    pen=pg.mkPen(color='gray', width=1, style=pg.QtCore.Qt.PenStyle.DotLine)
                )
                self.binary_plot.addItem(ref_line)
                self.reference_lines.append(ref_line)
            
            time_line = pg.InfiniteLine(
                pos=0, angle=90,
                pen=pg.mkPen(color='darkred', width=2, style=pg.QtCore.Qt.PenStyle.DotLine)
            )
            self.binary_plot.addItem(time_line)
            self.reference_lines.append(time_line)
                
        except Exception as e:
            print(f"ERROR in setup_plot: {e}")
            import traceback
            traceback.print_exc()

    def set_coincidence_mode(self, enabled):
        self.coincidence_mode = enabled
        print(f"CoincidenceLogicTab: coincidence_mode set to {enabled}")
    
    def clear_plot_safely(self):
        try:
            for item in self.plot_items + self.histogram_items:
                try:
                    self.binary_plot.removeItem(item)
                except:
                    pass
            self.plot_items.clear()
            self.histogram_items.clear()
            
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
        self.update_params_display()
    
    def update_channel_b(self):
        self.channel_b = self.channels[self.ch_b_combo.currentIndex()]
        self.binary_data.clear()
        self.ch_b_event_count = 0
        self.binary_plot.setTitle(f"Ch{self.channel_a} (A) vs Ch{self.channel_b} (B)")
        self.update_params_display()
    
    def update_timing_params(self):
        """Update internal parameters from spinboxes"""
        self.hardware_params.update({
            "fast_trig_backplane_delay": self.ft_bp_delay_spin.value(),
            "fast_trig_backplane_len": self.ft_bp_len_spin.value(),
            "chan_trig_stretch": self.chan_stretch_spin.value(),
            "external_delay_len": self.ext_delay_spin.value(),
            "validation_window": self.validation_win_spin.value(),
        })
        self.update_params_display()
    
    def apply_timing_to_hardware(self):
        if not self.hardware_manager:
            QMessageBox.warning(self, "No Hardware", "Hardware manager not available")
            return
        
        try:
            # Convert ns to appropriate units and emit parameter changes
            bp_delay_cycles = int(self.hardware_params["fast_trig_backplane_delay"] / self.fpga_period_ns)
            bp_len_us = self.hardware_params["fast_trig_backplane_len"] / 1000.0
            chan_stretch_us = self.hardware_params["chan_trig_stretch"] / 1000.0
            ext_delay_us = self.hardware_params["external_delay_len"] / 1000.0
            
            # Emit parameter changes for both channels
            for channel in [self.channel_a, self.channel_b]:
                self.parameter_changed.emit("FastTrigBackplaneEna", bp_delay_cycles, 0, channel)
                self.parameter_changed.emit("FASTTRIGBACKLEN", bp_len_us, 0, channel)
                self.parameter_changed.emit("ChanTrigStretch", chan_stretch_us, 0, channel)
                self.parameter_changed.emit("ExternDelayLen", ext_delay_us, 0, channel)
            
            QMessageBox.information(
                self, "Parameters Applied",
                f"Timing parameters applied to Ch{self.channel_a} and Ch{self.channel_b}"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to apply parameters: {e}")
    
    def toggle_histograms(self, enabled):
        self.show_histograms = enabled
    
    def toggle_normalize(self, enabled):
        self.histogram_normalize = enabled
    
    def update_histogram_alpha(self, value):
        self.histogram_alpha = value
    
    def clear_histograms(self):
        self.binary_data.ch_a_histogram.clear()
        self.binary_data.ch_b_histogram.clear()
        self.ch_a_event_count = 0
        self.ch_b_event_count = 0
        
        # Clear validation statistics
        self.ch_a_validation_stats = {
            "blue_in_green_count": 0,
            "yellow_valid_count": 0,
            "total_events": 0,
            "cross_channel_events": 0,
            "cross_channel_aligned": 0
        }
        self.ch_b_validation_stats = {
            "blue_in_green_count": 0,
            "yellow_valid_count": 0,
            "total_events": 0,
            "cross_channel_events": 0,
            "cross_channel_aligned": 0
        }
        print("Histograms and validation statistics cleared")
    
    def add_event_with_trace(self, event, trace_data):
        if not hasattr(event, "timestamp") or not hasattr(event, "channel"):
            return
        
        try:
            self.event_buffer.append((event, trace_data))
            
            if event.channel == self.channel_a:
                self.ch_a_event_count += 1
                binary_results = self.compute_binary_logic(
                    trace_data, event.channel, event.timestamp, 'A'
                )
                if binary_results:
                    self.binary_data.add_channel_data('A', binary_results)
            
            if event.channel == self.channel_b:
                self.ch_b_event_count += 1
                binary_results = self.compute_binary_logic(
                    trace_data, event.channel, event.timestamp, 'B'
                )
                if binary_results:
                    self.binary_data.add_channel_data('B', binary_results)
                
        except Exception as e:
            print(f"ERROR in add_event_with_trace: {e}")
    
    def compute_binary_logic(self, raw_trace, channel, event_timestamp, channel_id):
        if len(raw_trace) < 20:
            return None
        
        if not self.update_timer.isActive():
            return None
        
        try:
            raw_trace = np.asarray(raw_trace, dtype=np.uint16)
            trace_length = len(raw_trace)
            
            # Use Channel A as time reference for Channel B alignment
            if channel_id == 'A':
                # Channel A sets the time reference
                FIXED_TRIGGER_POSITION = 100  # Fixed sample position for consistent time axis
                trigger_time_ns = FIXED_TRIGGER_POSITION * self.sampling_period_ns
                time_axis = np.arange(trace_length) * self.sampling_period_ns - trigger_time_ns
                
                if self.reference_timestamp is None:
                    self.reference_timestamp = event_timestamp
                    self.reference_time_axis_offset = trigger_time_ns
                    print(f"DEBUG: Set FIXED reference timestamp = {self.reference_timestamp}")
                
                time_axis = np.arange(trace_length) * self.sampling_period_ns - trigger_time_ns
            
            elif channel_id == 'B':
                FIXED_TRIGGER_POSITION = 100  # Same as Channel A
                trigger_time_ns = FIXED_TRIGGER_POSITION * self.sampling_period_ns
                time_axis = np.arange(trace_length) * self.sampling_period_ns - trigger_time_ns
            else:
                # Unknown channel ID fallback
                FIXED_TRIGGER_POSITION = 100
                trigger_time_ns = FIXED_TRIGGER_POSITION * self.sampling_period_ns
                time_axis = np.arange(trace_length) * self.sampling_period_ns - trigger_time_ns
            
            baseline_samples = min(100, trace_length // 3)
            baseline = np.mean(raw_trace[:baseline_samples])
            threshold = self.hardware_params.get("fast_threshold", 100)
            
            # STEP 1: Local Fast Trigger
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
                
                if len(fast_filter) < trace_length:
                    fast_filter = np.pad(fast_filter, (0, trace_length - len(fast_filter)), mode='constant')
                elif len(fast_filter) > trace_length:
                    fast_filter = fast_filter[:trace_length]
                
                trigger_indices = np.where(fast_filter > threshold)[0]
                if len(trigger_indices) > 0:
                    first_trigger_idx = trigger_indices[0]
                    first_trigger_time_ns = time_axis[first_trigger_idx]
                    
                    local_fast_trigger = np.zeros(trace_length, dtype=np.int8)
                    pulse_samples = int(10 / self.sampling_period_ns)
                    pulse_end = min(first_trigger_idx + pulse_samples, trace_length)
                    local_fast_trigger[first_trigger_idx:pulse_end] = 1
                else:
                    local_fast_trigger = np.zeros(trace_length, dtype=np.int8)
                    first_trigger_time_ns = None
                    
            except Exception as e:
                local_fast_trigger = np.zeros(trace_length, dtype=np.int8)
                first_trigger_time_ns = None
            
            if first_trigger_time_ns is None:
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
            
            # STEP 2: Fast Trigger Backplane
            bp_delay_ns = self.hardware_params["fast_trig_backplane_delay"]
            bp_len_ns = self.hardware_params["fast_trig_backplane_len"]
            
            fast_trigger_bp = np.zeros(trace_length, dtype=np.int8)
            bp_start_time = first_trigger_time_ns + bp_delay_ns
            bp_end_time = bp_start_time + bp_len_ns
            
            bp_start_idx = np.searchsorted(time_axis, bp_start_time)
            bp_end_idx = np.searchsorted(time_axis, bp_end_time)
            if bp_start_idx < trace_length and bp_end_idx <= trace_length:
                fast_trigger_bp[bp_start_idx:bp_end_idx] = 1
            
            # STEP 3: Channel Trigger (AND of A and B)
            other_channel = self.channel_b if channel_id == 'A' else self.channel_a
            other_had_trigger = self._check_other_channel_trigger(other_channel, event_timestamp, window_ns=500)
            
            chan_trig = np.zeros(trace_length, dtype=np.int8)
            if other_had_trigger:
                coinc_delay_ns = 110
                coinc_time = first_trigger_time_ns + bp_delay_ns + coinc_delay_ns
                coinc_idx = np.searchsorted(time_axis, coinc_time)
                
                coinc_pulse_samples = int(10 / self.sampling_period_ns)
                coinc_end_idx = min(coinc_idx + coinc_pulse_samples, trace_length)
                if coinc_idx < trace_length:
                    chan_trig[coinc_idx:coinc_end_idx] = 1
                    self.coincidence_count += 1
            
            # STEP 4: Channel Validation Trigger
            # For cross-channel validation: Channel Valid Trig A should be centered in the other channel's stretch
            chan_stretch_ns = self.hardware_params["chan_trig_stretch"]
            chan_validation_trig = np.zeros(trace_length, dtype=np.int8)
            
            if np.any(chan_trig > 0):
                val_start_idx = np.where(chan_trig > 0)[0][0]
                
                if other_had_trigger:
                    # Cross-channel validation: align validation window to be stable
                    # Remove random cross-channel delay that causes jittering
                    # Use direct timing alignment based on trigger position
                    val_end_time = time_axis[val_start_idx] + chan_stretch_ns
                    val_end_idx = np.searchsorted(time_axis, val_end_time)
                    
                    if val_end_idx <= trace_length:
                        chan_validation_trig[val_start_idx:val_end_idx] = 1
                else:
                    # Single channel validation: use standard timing
                    val_end_time = time_axis[val_start_idx] + chan_stretch_ns
                    val_end_idx = np.searchsorted(time_axis, val_end_time)
                    if val_end_idx <= trace_length:
                        chan_validation_trig[val_start_idx:val_end_idx] = 1
            
            # STEP 5: Local Fast for Processing
            # Adjust timing to center blue signal in middle of green (chan_validation_trig)
            local_fast_for_processing = np.zeros(trace_length, dtype=np.int8)
            
            if np.any(chan_validation_trig > 0):
                # Find the green signal boundaries
                green_start_idx = np.where(chan_validation_trig > 0)[0][0]
                green_end_idx = np.where(chan_validation_trig > 0)[0][-1]
                green_duration_samples = green_end_idx - green_start_idx + 1
                
                # Center the blue signal in the green signal
                blue_pulse_samples = int(10 / self.sampling_period_ns)  # 10ns pulse
                blue_center_idx = green_start_idx + green_duration_samples // 2
                blue_start_idx = max(0, blue_center_idx - blue_pulse_samples // 2)
                blue_end_idx = min(trace_length, blue_start_idx + blue_pulse_samples)
                
                if blue_start_idx < trace_length:
                    local_fast_for_processing[blue_start_idx:blue_end_idx] = 1
                    
                # Update validation statistics
                stats_key = "ch_a_validation_stats" if channel_id == 'A' else "ch_b_validation_stats"
                stats = getattr(self, stats_key)
                stats["total_events"] += 1
                
                # Track cross-channel events and alignment
                if other_had_trigger:
                    stats["cross_channel_events"] += 1
                    # Check if the cross-channel alignment is good (validation window overlaps properly)
                    if np.any(chan_validation_trig > 0):
                        stats["cross_channel_aligned"] += 1
                
                # Check if blue is inside green (should always be true now with centering)
                blue_in_green = np.any(local_fast_for_processing & chan_validation_trig)
                if blue_in_green:
                    stats["blue_in_green_count"] += 1
            
            # STEP 6: Validated Trigger for Processing
            validated_trig_for_processing = local_fast_for_processing & chan_validation_trig
            
            # Update yellow validation statistics
            stats_key = "ch_a_validation_stats" if channel_id == 'A' else "ch_b_validation_stats"
            stats = getattr(self, stats_key)
            if np.any(validated_trig_for_processing > 0):
                stats["yellow_valid_count"] += 1
            
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
            return None
    
    def _check_other_channel_trigger(self, other_channel, event_timestamp, window_ns=500):
        window_ticks = window_ns / 10.0
        
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
            
            # Colors for signals
            colors = {
                "local_fast_trigger": "#FF0000",
                "fast_trigger_bp": "#FF6600",
                "chan_trig": "#FFAA00",
                "chan_validation_trig": "#00AA00",
                "local_fast_for_processing": "#0066FF",
                "validated_trig_for_processing": "#AA00FF"
            }
            
            # Y-offsets
            y_offsets = {
                ("A", "local_fast_trigger"): 11,
                ("A", "fast_trigger_bp"): 10,
                ("B", "local_fast_trigger"): 9,
                ("B", "fast_trigger_bp"): 8,
                ("A", "chan_trig"): 7,
                ("B", "chan_trig"): 6,
                ("A", "chan_validation_trig"): 5,
                ("A", "local_fast_for_processing"): 4,
                ("A", "validated_trig_for_processing"): 3,
                ("B", "chan_validation_trig"): 2,
                ("B", "local_fast_for_processing"): 1,
                ("B", "validated_trig_for_processing"): 0,
            }
            
            # Plot histograms FIRST (behind binary traces)
            if self.show_histograms:
                self.plot_histograms(y_offsets, colors)
            
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
            
            # Update status with histogram info
            hist_a, total_a = self.binary_data.get_histogram_data('A', self.histogram_normalize)
            hist_b, total_b = self.binary_data.get_histogram_data('B', self.histogram_normalize)
            
            self.status_label.setText(
                f"Ch{self.channel_a}(A):{self.ch_a_event_count} | "
                f"Ch{self.channel_b}(B):{self.ch_b_event_count} | "
                f"Coinc:{self.coincidence_count} | "
                f"{time.strftime('%H:%M:%S')}"
            )
            
            # Calculate validation percentages
            ch_a_blue_pct = (
                100 * self.ch_a_validation_stats["blue_in_green_count"] / max(1, self.ch_a_validation_stats["total_events"])
            )
            ch_a_yellow_pct = (
                100 * self.ch_a_validation_stats["yellow_valid_count"] / max(1, self.ch_a_validation_stats["total_events"])
            )
            ch_a_cross_pct = (
                100 * self.ch_a_validation_stats["cross_channel_aligned"] / max(1, self.ch_a_validation_stats["cross_channel_events"])
            )
            
            ch_b_blue_pct = (
                100 * self.ch_b_validation_stats["blue_in_green_count"] / max(1, self.ch_b_validation_stats["total_events"])
            )
            ch_b_yellow_pct = (
                100 * self.ch_b_validation_stats["yellow_valid_count"] / max(1, self.ch_b_validation_stats["total_events"])
            )
            ch_b_cross_pct = (
                100 * self.ch_b_validation_stats["cross_channel_aligned"] / max(1, self.ch_b_validation_stats["cross_channel_events"])
            )
            
            self.hist_stats_label.setText(
                f"Events: A={total_a}, B={total_b} | "
                f"A: Blue@Green={ch_a_blue_pct:.0f}%, Yellow={ch_a_yellow_pct:.0f}%, CrossAlign={ch_a_cross_pct:.0f}% | "
                f"B: Blue@Green={ch_b_blue_pct:.0f}%, Yellow={ch_b_yellow_pct:.0f}%, CrossAlign={ch_b_cross_pct:.0f}%"
            )
            
            self.last_update_time = time.time()
            
        except Exception as e:
            print(f"ERROR update_visualization: {e}")
            import traceback
            traceback.print_exc()
    
    def plot_histograms(self, y_offsets, colors):
        try:
            # Get histogram data
            hist_a, total_a = self.binary_data.get_histogram_data('A', self.histogram_normalize)
            hist_b, total_b = self.binary_data.get_histogram_data('B', self.histogram_normalize)
            
            if not hist_a and not hist_b:
                return
            
            # Plot histograms for each signal
            for channel_id, histograms, total_events in [('A', hist_a, total_a), ('B', hist_b, total_b)]:
                if not histograms:
                    continue
                
                for step, (bin_centers, hist_data) in histograms.items():
                    if hist_data is None or len(hist_data) == 0:
                        continue
                    
                    if np.sum(hist_data) == 0:
                        continue
                    
                    y_offset = y_offsets.get((channel_id, step))
                    if y_offset is None:
                        continue
                    
                    # Normalize histogram to 0-0.8 range
                    max_val = np.max(hist_data)
                    if max_val > 0:
                        normalized_hist = (hist_data / max_val) * 0.5  # limit height
                    else:
                        normalized_hist = hist_data
                    
                    # filled area plot
                    y_bottom = np.full_like(bin_centers, y_offset)
                    y_top = y_bottom + normalized_hist
                    
                    gray_color = "#808080"  # Medium gray
                    
                    # Create filled curve with gray and transparency
                    fill_item = pg.FillBetweenItem(
                        pg.PlotDataItem(bin_centers, y_bottom),
                        pg.PlotDataItem(bin_centers, y_top),
                        brush=pg.mkBrush(color=gray_color, alpha=int(self.histogram_alpha * 255))
                    )
                    
                    self.binary_plot.addItem(fill_item)
                    self.histogram_items.append(fill_item)
                    
        except Exception as e:
            print(f"ERROR plotting histograms: {e}")
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
                    # Read trigger parameters
                    trigger_risetime_us = hw_params.get('TRIGGER_RISETIME', 0.02)
                    trigger_flattop_us = hw_params.get('TRIGGER_FLATTOP', 0.02)
                    
                    self.hardware_params.update({
                        'fast_L': int(trigger_risetime_us * 100),  # Convert to FPGA cycles
                        'fast_G': int(trigger_flattop_us * 100),
                        'fast_threshold': int(hw_params.get('TRIGGER_THRESHOLD', 100)),
                    })
                    
                    # Try to read timing parameters from hardware
                    # These come from DSP variables (see variables.py)
                    all_params = self.hardware_manager.get_all_parameters(0, channel)
                    
                    if 'FastTrigBackplaneEna' in all_params:
                        # This is in FPGA cycles, convert to ns
                        self.hardware_params['fast_trig_backplane_delay'] = all_params['FastTrigBackplaneEna'] * self.fpga_period_ns
                        self.ft_bp_delay_spin.setValue(self.hardware_params['fast_trig_backplane_delay'])
                    
                    if 'FastTrigBackLen' in all_params:
                        # In microseconds, convert to ns
                        self.hardware_params['fast_trig_backplane_len'] = all_params['FastTrigBackLen'] * 1000
                        self.ft_bp_len_spin.setValue(self.hardware_params['fast_trig_backplane_len'])
                    
                    if 'ChanTrigStretch' in all_params:
                        # In microseconds, convert to ns
                        self.hardware_params['chan_trig_stretch'] = all_params['ChanTrigStretch'] * 1000
                        self.chan_stretch_spin.setValue(self.hardware_params['chan_trig_stretch'])
                    
                    if 'ExternDelayLen' in all_params:
                        # In microseconds, convert to ns
                        self.hardware_params['external_delay_len'] = all_params['ExternDelayLen'] * 1000
                        self.ext_delay_spin.setValue(self.hardware_params['external_delay_len'])
                    
                    print(f"Loaded hardware parameters from Ch{channel}:")
                    print(f"  Fast L/G: {self.hardware_params['fast_L']}/{self.hardware_params['fast_G']} FPGA cycles")
                    print(f"  BP Delay: {self.hardware_params['fast_trig_backplane_delay']:.1f} ns")
                    print(f"  BP Length: {self.hardware_params['fast_trig_backplane_len']:.1f} ns")
                    print(f"  Chan Stretch: {self.hardware_params['chan_trig_stretch']:.1f} ns")
                    print(f"  Ext Delay: {self.hardware_params['external_delay_len']:.1f} ns")
                    
                    break  # Use first channel's parameters
            
            self.update_params_display()
            
        except Exception as e:
            print(f"Hardware param update failed: {e}")
            import traceback
            traceback.print_exc()
    
    def update_params_display(self):
        params_text = (
            f"<b>Channels:</b> A=Ch{self.channel_a}, B=Ch{self.channel_b}<br>"
            f"<b>BP Delay:</b> {self.hardware_params['fast_trig_backplane_delay']:.0f} ns<br>"
            f"<b>BP Length:</b> {self.hardware_params['fast_trig_backplane_len']:.0f} ns<br>"
            f"<b>Chan Stretch:</b> {self.hardware_params['chan_trig_stretch']:.0f} ns<br>"
            f"<b>Ext Delay:</b> {self.hardware_params['external_delay_len']:.0f} ns<br>"
            f"<b>Validation:</b> {self.hardware_params['validation_window']:.0f} ns"
        )
        if hasattr(self, 'params_label'):
            self.params_label.setText(params_text)
    
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
            "show_histograms": self.show_histograms,
            "histogram_normalize": self.histogram_normalize,
            "histogram_alpha": self.histogram_alpha,
            "timestamp": time.time(),
        }
        
        try:
            # Get unified data directory path
            if hasattr(self.parent(), 'data_storage_manager'):
                data_manager = self.parent().data_storage_manager
            else:
                from .data_manager import DataSettingsManager
                data_manager = DataSettingsManager()
            settings_path = data_manager.get_save_path('sessions', 'coincidence_logic_settings.json')
            
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=2)
            QMessageBox.information(
                self, "Settings Saved", 
                f"Saved to {settings_path}"
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
                
                for event, time_diff in zip(
                    coinc_event.associated_events, coinc_event.time_differences
                ):
                    export_data.append({
                        "coincidence_id": i,
                        "center_channel": center_channel,
                        "center_timestamp": center_timestamp,
                        "associated_channel": event[0].channel,
                        "associated_timestamp": event[0].timestamp,
                        "time_difference_ns": time_diff,
                    })
            
            # Get unified data directory path
            if hasattr(self.parent(), 'data_storage_manager'):
                data_manager = self.parent().data_storage_manager
            else:
                from .data_manager import DataSettingsManager
                data_manager = DataSettingsManager()
            export_path = data_manager.get_save_path('exports', f"timing_data_{int(time.time())}.csv")
            
            with open(export_path, "w", newline="") as csvfile:
                if export_data:
                    writer = csv.DictWriter(csvfile, fieldnames=export_data[0].keys())
                    writer.writeheader()
                    writer.writerows(export_data)
            
            QMessageBox.information(
                self, "Export Complete", 
                f"Exported {len(export_data)} events to {export_path}"
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
        
        # Recreate controls widget with new channels
        if hasattr(self, 'controls_widget') and self.controls_widget:
            self.controls_widget.setParent(None)
            self.controls_widget = None
        
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