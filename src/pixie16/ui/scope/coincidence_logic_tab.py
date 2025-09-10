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

        # Two-channel support
        self.two_channel_mode = True  # Enable two-channel mode by default
        self.binary_second_channel = self.channels[1] if len(self.channels) > 1 else self.channels[0]
        self.time_alignment_offset_ns = 0.0  # User adjustable offset between channels
        
        # Binary states for second channel
        self.binary_states_ch2 = {
            step: deque(maxlen=5000) for step in self.binary_logic_steps
        }
        
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

        # ADD: Two-channel mode toggle
        self.two_channel_cb = QCheckBox("Two Channel Mode")
        self.two_channel_cb.setChecked(True)
        self.two_channel_cb.toggled.connect(self.toggle_two_channel_mode)
        binary_controls_layout.addWidget(self.two_channel_cb)

        # Channel 1 selection 
        binary_controls_layout.addWidget(QLabel("Ch1:"))
        self.binary_channel_combo = QComboBox()
        for ch in self.channels:
            self.binary_channel_combo.addItem(f"Ch {ch}")
        self.binary_channel_combo.currentIndexChanged.connect(self.update_binary_channel)
        binary_controls_layout.addWidget(self.binary_channel_combo)

        # ADD: Channel 2 selection
        self.ch2_label = QLabel("Ch2:")
        binary_controls_layout.addWidget(self.ch2_label)
        self.binary_channel2_combo = QComboBox()
        for ch in self.channels:
            self.binary_channel2_combo.addItem(f"Ch {ch}")
        if len(self.channels) > 1:
            self.binary_channel2_combo.setCurrentIndex(1)  # Default to second channel
        self.binary_channel2_combo.currentIndexChanged.connect(self.update_binary_channel2)
        binary_controls_layout.addWidget(self.binary_channel2_combo)

        # ADD: Time alignment offset control (as per TODO: "Ch 9 trigger somewhere and everything is right of the trigger")
        binary_controls_layout.addWidget(QLabel("Offset:"))
        self.time_offset_spin = QDoubleSpinBox()
        self.time_offset_spin.setRange(-500.0, 500.0)
        self.time_offset_spin.setValue(0.0)
        self.time_offset_spin.setSuffix(" ns")
        self.time_offset_spin.setDecimals(1)
        self.time_offset_spin.setSingleStep(0.1)
        self.time_offset_spin.valueChanged.connect(self.update_time_offset)
        binary_controls_layout.addWidget(self.time_offset_spin)

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

        # Binary logic plot - MODIFIED for two-channel display
        self.binary_plot = pg.PlotWidget()
        self.binary_plot.setLabel("left", "Logic Steps (±Ch Offset)")
        self.binary_plot.setLabel("bottom", "Time (ns) - Aligned to Trigger")
        self.binary_plot.setTitle("Coincidence Logic - Two Channel View")
        self.binary_plot.showGrid(True, True, alpha=0.3)
        self.binary_plot.setBackground("w")
        self.binary_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.binary_plot.setMinimumHeight(200)

        # MODIFIED Y-axis labels for two-channel display (as per TODO: "+- on the axis")
        y_labels_two_channel = [
            # Channel 1 (positive side)
            (4, "Ch1 Event Accepted"),
            (3, "Ch1 Validation Window"), 
            (2, "Ch1 Fast Trigger"),
            (1, "Ch1 Raw > Threshold"),
            # Reference line at y=0 (trigger reference)
            (0, "Trigger Reference (t=0)"),
            # Channel 2 (negative side)  
            (-1, "Ch2 Raw > Threshold"),
            (-2, "Ch2 Fast Trigger"),
            (-3, "Ch2 Validation Window"),
            (-4, "Ch2 Event Accepted"),
        ]
        self.binary_plot.getAxis("left").setTicks([y_labels_two_channel])
        self.binary_plot.setYRange(-5, 5)  # Expand range for two channels
        
        binary_layout.addWidget(self.binary_plot, 1)

        # Hardware parameter display
        self.binary_params_label = QLabel("Hardware Parameters: Not loaded")
        self.binary_params_label.setStyleSheet("font-family: monospace; font-size: 9pt;")
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

    def toggle_two_channel_mode(self, enabled):
        self.two_channel_mode = enabled
        
        # Show/hide second channel controls
        self.ch2_label.setVisible(enabled)
        self.binary_channel2_combo.setVisible(enabled)
        self.time_offset_spin.setVisible(enabled)
        
        if enabled:
            self.binary_plot.setTitle("Coincidence Logic - Two Channel View") 
            self.binary_plot.setYRange(-5, 5)
            # Update Y-axis for two channel mode
            y_labels_two_channel = [
                (4, "Ch1 Event Accepted"), (3, "Ch1 Validation Window"), 
                (2, "Ch1 Fast Trigger"), (1, "Ch1 Raw > Threshold"),
                (0, "Trigger Reference (t=0)"),
                (-1, "Ch2 Raw > Threshold"), (-2, "Ch2 Fast Trigger"),
                (-3, "Ch2 Validation Window"), (-4, "Ch2 Event Accepted"),
            ]
            self.binary_plot.getAxis("left").setTicks([y_labels_two_channel])
        else:
            self.binary_plot.setTitle(f"Coincidence Logic - Channel {self.binary_selected_channel}")
            self.binary_plot.setYRange(-0.5, 6.5)
            # Revert to single channel Y-axis
            y_labels_single = [
                (0, "Event Accepted"), (1, "Delayed Local"), (2, "Validation Window"),
                (3, "Multiplicity Logic"), (4, "Backplane Signal"), 
                (5, "Fast Trigger"), (6, "Raw > Threshold"),
            ]
            self.binary_plot.getAxis("left").setTicks([y_labels_single])
            
        self.clear_binary_data()
    
    def get_event_trigger_time(self, event):
        # Check if CFD is enabled for this channel
        cfd_enabled = getattr(event, 'cfd_enabled', False)
        
        if cfd_enabled and hasattr(event, 'cfd_time'):
            # CFD is on - use CFD timestamp  
            trigger_time = event.cfd_time
        else:
            # CFD is off - use fast trigger time (as per TODO: "if you dont do CFD then fast trigger is the time stamp")
            if hasattr(event, 'fast_trigger_time'):
                trigger_time = event.fast_trigger_time
            else:
                # Estimate from trace (fast trigger usually at ~30% of trace)
                trigger_time = len(getattr(event, 'trace', [])) * 0.3
                
        return trigger_time
    
    def set_hardware_params_from_parent(self, hardware_params):
        self.hardware_params.update(hardware_params)
        
        # Also update binary-specific parameters
        self.binary_hardware_params['fast_threshold'] = hardware_params.get('fast_threshold', 100)
        self._update_parameter_display()

    def update_binary_channel2(self):
        self.binary_second_channel = self.channels[self.binary_channel2_combo.currentIndex()]
        if self.two_channel_mode:
            self.clear_binary_data()

    def update_time_offset(self):
        self.time_alignment_offset_ns = self.time_offset_spin.value()

    def clear_binary_data(self):
        for step in self.binary_logic_steps:
            self.binary_states[step].clear()
            if hasattr(self, 'binary_states_ch2'):
                self.binary_states_ch2[step].clear()
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
        if not self.binary_logic_enabled:
            return None

        # Determine which channel we're processing
        is_channel1 = (channel == self.binary_selected_channel)
        is_channel2 = (channel == self.binary_second_channel and self.two_channel_mode)
        
        if not (is_channel1 or is_channel2):
            return None

        trace_length = len(raw_trace)
        
        # Create time axis aligned to trigger (as per TODO: "Ch 9 trigger somewhere and everything is right of the trigger")
        # Estimate trigger position (typically around 30% into trace)
        trigger_position_samples = int(trace_length * 0.3)
        trigger_time_ns = trigger_position_samples * self.sampling_period_ns
        
        # Time axis with trigger at t=0 
        time_axis = np.arange(trace_length) * self.sampling_period_ns - trigger_time_ns
        
        # Apply channel-specific time offset for alignment
        if is_channel2:
            time_axis += self.time_alignment_offset_ns

        # Compute binary logic steps
        binary_results = self._compute_channel_binary_logic(raw_trace, channel, event_timestamp, time_axis)
        
        # Store results for appropriate channel
        if is_channel1:
            self._store_binary_results_for_channel(binary_results, 'ch1')
        elif is_channel2:
            self._store_binary_results_for_channel(binary_results, 'ch2')
        
        # Update visualization
        if self.two_channel_mode:
            self.update_two_channel_binary_visualization()
        else:
            self.update_binary_visualization(binary_results)
            
        return binary_results
    
    def _compute_channel_binary_logic(self, raw_trace, channel, event_timestamp, time_axis):        
        trace_length = len(raw_trace)
        
        # Raw signal > threshold
        threshold = self.binary_hardware_params["fast_threshold"]
        baseline = np.mean(raw_trace[:100]) if len(raw_trace) > 100 else np.mean(raw_trace)
        raw_binary = (raw_trace > (baseline + threshold)).astype(int)

        # Fast trigger
        fast_trigger_binary = self.compute_fast_trigger_binary(raw_trace, channel)

        # Validation window
        # show multiplicity logic firing when coincidences are detected
        validation_binary = self.compute_validation_window(event_timestamp, trace_length, channel)
        event_accepted_binary = fast_trigger_binary & validation_binary

        return {
            "raw_threshold": raw_binary,
            "fast_trigger": fast_trigger_binary,
            "validation_window": validation_binary,
            "event_accepted": event_accepted_binary,
            "time_axis": time_axis,
            "timestamp": event_timestamp,
            "channel": channel
        }
    
    def compute_validation_window(self, event_timestamp, trace_length, channel):        
        validation_binary = np.zeros(trace_length, dtype=int)
        
        # Check for coincident events from other channels
        current_time_ticks = event_timestamp
        window_ticks = self.coincidence_window_ns / 10.0  # Convert ns to 10ns ticks
        
        coincident_found = False
        for buffered_event, buffered_trace in list(self.event_buffer)[-50:]:
            if not hasattr(buffered_event, 'channel') or not hasattr(buffered_event, 'timestamp'):
                continue
                
            if buffered_event.channel == channel:
                continue  # Skip same channel
                
            time_diff_ticks = abs(buffered_event.timestamp - current_time_ticks)
            
            if time_diff_ticks <= window_ticks:
                coincident_found = True
                break
        
        # If coincidence found, show validation window active
        if coincident_found:
            # Show validation pulse in middle portion of trace (where trigger typically occurs)
            pulse_start = trace_length // 3
            pulse_width = min(100, trace_length // 5)  # Reasonable pulse width
            pulse_end = min(pulse_start + pulse_width, trace_length)
            validation_binary[pulse_start:pulse_end] = 1
        
        return validation_binary

    def _store_binary_results_for_channel(self, binary_results, channel_id):        
        storage = self.binary_states if channel_id == 'ch1' else self.binary_states_ch2
        
        # Store only the key steps for two-channel display
        key_steps = ["raw_threshold", "fast_trigger", "validation_window", "event_accepted"]
        
        for step in key_steps:
            if step in binary_results:
                storage[step].append(binary_results[step])

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
    
    def update_two_channel_binary_visualization(self):
        if not self.two_channel_mode or not self.binary_logic_enabled:
            return
            
        self.binary_plot.clear()
        
        # Colors for different logic steps
        colors = ["red", "orange", "green", "blue"]
        key_steps = ["raw_threshold", "fast_trigger", "validation_window", "event_accepted"]
        
        # Plot Channel 1 (positive Y axis)
        if any(len(self.binary_states[step]) > 0 for step in key_steps):
            self._plot_channel_binary_traces('ch1', colors, y_offset_base=1)
            
        # Plot Channel 2 (negative Y axis) 
        if any(len(self.binary_states_ch2[step]) > 0 for step in key_steps):
            self._plot_channel_binary_traces('ch2', colors, y_offset_base=-1)
            
        # Add trigger reference line at y=0 (as per TODO: "Ch 9 trigger somewhere")
        trigger_ref_line = pg.InfiniteLine(pos=0, angle=0, 
                                         pen=pg.mkPen(color='black', width=2, style=pg.QtCore.Qt.PenStyle.DashLine))
        self.binary_plot.addItem(trigger_ref_line)
        
        # Add time reference line at x=0 (trigger time)
        time_ref_line = pg.InfiniteLine(pos=0, angle=90,
                                      pen=pg.mkPen(color='gray', width=1, style=pg.QtCore.Qt.PenStyle.DotLine))  
        self.binary_plot.addItem(time_ref_line)
    
    def _plot_channel_binary_traces(self, channel_id, colors, y_offset_base):        
        storage = self.binary_states if channel_id == 'ch1' else self.binary_states_ch2
        y_multiplier = 1 if channel_id == 'ch1' else -1  # Positive for ch1, negative for ch2
        
        key_steps = ["raw_threshold", "fast_trigger", "validation_window", "event_accepted"]
        
        for i, step in enumerate(key_steps):
            if step not in storage or len(storage[step]) == 0:
                continue
                
            # Get most recent trace for this step
            binary_data = storage[step][-1]  # Most recent
            
            if len(binary_data) == 0:
                continue
                
            # Create time axis aligned to trigger
            trace_length = len(binary_data)
            trigger_position_samples = int(trace_length * 0.3)
            trigger_time_ns = trigger_position_samples * self.sampling_period_ns
            time_axis = np.arange(trace_length) * self.sampling_period_ns - trigger_time_ns
            
            # Apply channel time offset
            if channel_id == 'ch2':
                time_axis += self.time_alignment_offset_ns
                
            # Y offset for this logic step (as per TODO: "+- on the axis")
            y_offset = y_offset_base + (i * y_multiplier)
            
            # Create step plot for clean digital display
            step_x, step_y = self._create_step_plot_data(time_axis, binary_data, y_offset)
            
            color = colors[i % len(colors)]
            channel_num = self.binary_selected_channel if channel_id == 'ch1' else self.binary_second_channel
            
            self.binary_plot.plot(
                step_x, step_y,
                pen=pg.mkPen(color=color, width=2),
                name=f"{step.replace('_', ' ').title()} (Ch{channel_num})"
            )

    def _create_step_plot_data(self, time_axis, binary_data, y_offset):
        step_x = []
        step_y = []
        
        for i in range(len(binary_data)):
            if i == 0:
                # Initial point
                step_x.extend([time_axis[i], time_axis[i]]) 
                step_y.extend([y_offset, y_offset + binary_data[i]])
            else:
                # Horizontal line from previous point
                step_x.append(time_axis[i])
                step_y.append(y_offset + binary_data[i-1])
                # Vertical transition 
                step_x.append(time_axis[i])
                step_y.append(y_offset + binary_data[i])
        
        return step_x, step_y

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
