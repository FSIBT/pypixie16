"""
Parameter control widgets for PIXIE-16 scope interface
"""

import json
import time
import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QCheckBox,
    QPushButton,
    QLabel,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QTabWidget,
    QSizePolicy,
    QFileDialog,
    QMessageBox,
    QScrollArea,
    QFrame,
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QFont, QPalette

from .parameter_validation import PixieParameterValidator, ParameterChangeManager

logger = logging.getLogger(__name__)


class ValidatedSpinBox(QSpinBox):
    def __init__(self, param_name: str, validator: PixieParameterValidator):
        super().__init__()
        self.param_name = param_name
        self.validator = validator
        self.spec = validator.get_parameter_info(param_name)

        if self.spec:
            self.setRange(int(self.spec.min_value), int(self.spec.max_value))
            self.setSuffix(f" {self.spec.unit}")
            self.setToolTip(
                f"{self.spec.description}\nRange: {self.spec.min_value}-{self.spec.max_value} {self.spec.unit}"
            )


class ValidatedDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, param_name: str, validator: PixieParameterValidator):
        super().__init__()
        self.param_name = param_name
        self.validator = validator
        self.spec = validator.get_parameter_info(param_name)

        if self.spec:
            self.setRange(self.spec.min_value, self.spec.max_value)
            self.setSuffix(f" {self.spec.unit}")
            self.setDecimals(3)
            self.setToolTip(
                f"{self.spec.description}\nRange: {self.spec.min_value}-{self.spec.max_value} {self.spec.unit}"
            )


class ParameterControls(QGroupBox):
    parameter_changed = pyqtSignal(str, object, int, int)
    apply_all_requested = pyqtSignal(dict, int, int)
    status_message = pyqtSignal(str)
    validation_error = pyqtSignal(
        str, str, object
    )  # param_name, error_msg, attempted_value

    def __init__(
        self, initial_module=0, title="PIXIE-16 Parameters", module_type="100MHz"
    ):
        super().__init__(title)

        self.current_module = initial_module
        self.current_channel = 0

        # Initialize validation system
        self.validator = PixieParameterValidator(module_type)
        self.change_manager = ParameterChangeManager(
            self.validator, self._hardware_update_callback
        )

        # Widget storage for dynamic access
        self.parameter_widgets = {}
        self.real_time_updates_enabled = True

        self.setup_ui()
        self.connect_signals()
        self.set_default_values()

    def setup_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(2)

        # Create collapsible container
        main_container = self.create_collapsible_parameter_section()
        main_layout.addWidget(main_container)

        self.setLayout(main_layout)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def create_collapsible_parameter_section(self):
        main_container = QWidget()
        main_container_layout = QVBoxLayout()
        main_container_layout.setContentsMargins(0, 0, 0, 0)
        main_container_layout.setSpacing(0)

        self.param_header_btn = QPushButton("▶ Parameter Controls")
        self.param_header_btn.setCheckable(True)
        self.param_header_btn.setChecked(False)
        self.param_header_btn.clicked.connect(self.toggle_parameter_section)
        self.param_header_btn.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 5px;
                font-weight: bold;
                border: 1px solid gray;
                background-color: #f0f0f0;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)

        self.param_content_widget = QWidget()
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(5, 5, 5, 5)
        content_layout.setSpacing(5)

        # Module/Channel selector
        module_channel_group = self.create_module_channel_selector()
        content_layout.addWidget(module_channel_group)

        # Real-time update toggle
        update_controls = self.create_update_controls()
        content_layout.addWidget(update_controls)

        # Parameter tabs
        param_tabs = self.create_parameter_tabs()
        content_layout.addWidget(param_tabs)

        # Action buttons
        button_group = self.create_action_buttons()
        content_layout.addWidget(button_group)

        self.param_content_widget.setLayout(content_layout)
        self.param_content_widget.setVisible(False)

        main_container_layout.addWidget(self.param_header_btn)
        main_container_layout.addWidget(self.param_content_widget)
        main_container.setLayout(main_container_layout)
        main_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )

        return main_container

    def toggle_parameter_section(self, checked):
        self.param_content_widget.setVisible(checked)
        if checked:
            self.param_header_btn.setText("▼ Parameter Controls")
        else:
            self.param_header_btn.setText("▶ Parameter Controls")

    def create_module_channel_selector(self):
        group = QGroupBox("Target Module/Channel")
        group.setCheckable(True)  # Makes the group box collapsible
        group.setChecked(True)  # Start expanded
        layout = QHBoxLayout()

        layout.addWidget(QLabel("Module:"))
        self.module_spin = QSpinBox()
        self.module_spin.setRange(0, 15)
        self.module_spin.setValue(self.current_module)
        layout.addWidget(self.module_spin)

        layout.addWidget(QLabel("Channel:"))
        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(0, 15)
        self.channel_spin.setValue(self.current_channel)
        layout.addWidget(self.channel_spin)

        # Add "Select All" toggle button
        self.select_all_btn = QPushButton("All Channels")
        self.select_all_btn.setCheckable(True)
        self.select_all_btn.setChecked(False)
        self.select_all_btn.clicked.connect(self.toggle_all_channels)
        self.select_all_btn.setToolTip("Toggle between single channel and all channels")
        layout.addWidget(self.select_all_btn)

        layout.addStretch()
        group.setLayout(layout)
        return group

    def create_update_controls(self):
        group = QGroupBox("Update Settings")
        layout = QHBoxLayout()

        self.realtime_check = QCheckBox("Real-time Updates")
        self.realtime_check.setChecked(True)
        self.realtime_check.setToolTip(
            "Apply parameter changes immediately to hardware"
        )
        layout.addWidget(self.realtime_check)

        layout.addWidget(QLabel("Debounce:"))
        self.debounce_spin = QDoubleSpinBox()
        self.debounce_spin.setRange(0.1, 5.0)
        self.debounce_spin.setValue(0.5)
        self.debounce_spin.setSuffix(" s")
        self.debounce_spin.setDecimals(1)
        self.debounce_spin.setToolTip("Delay before applying rapid parameter changes")
        layout.addWidget(self.debounce_spin)

        layout.addStretch()
        group.setLayout(layout)
        return group

    def toggle_all_channels(self, checked):
        if checked:
            self.select_all_btn.setText("Single Channel")
            self.channel_spin.setEnabled(False)
            self.status_message.emit(
                "All channels mode - parameters apply to all channels"
            )
            # You can emit a signal here to notify parent about all-channel mode
        else:
            self.select_all_btn.setText("All Channels")
            self.channel_spin.setEnabled(True)
            self.status_message.emit(
                f"Single channel mode - parameters apply to Channel {self.channel_spin.value()}"
            )

    def create_parameter_tabs(self):
        tabs = QTabWidget()
        tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        # Core acquisition parameters
        trigger_tab = self.create_trigger_tab()
        tabs.addTab(trigger_tab, "Trigger")

        energy_tab = self.create_energy_tab()
        tabs.addTab(energy_tab, "Energy")

        # Advanced timing parameters
        timing_tab = self.create_timing_tab()
        tabs.addTab(timing_tab, "Timing")

        # Split advanced into three tabs
        trace_tab = self.create_trace_tab()
        tabs.addTab(trace_tab, "Traces")

        cfd_tab = self.create_cfd_tab()
        tabs.addTab(cfd_tab, "CFD")

        qdc_tab = self.create_qdc_tab()
        tabs.addTab(qdc_tab, "QDC")

        # Hardware configuration
        hardware_tab = self.create_hardware_tab()
        tabs.addTab(hardware_tab, "Hardware")

        return tabs

    def create_trigger_tab(self):
        tab = QWidget()
        layout = QGridLayout()
        layout.setVerticalSpacing(10)
        layout.setHorizontalSpacing(20)

        row = 0

        # Trigger Threshold
        layout.addWidget(QLabel("Threshold:"), row, 0)
        self.threshold_spin = ValidatedSpinBox("TRIGGER_THRESHOLD", self.validator)
        self.threshold_spin.setValue(1000)
        self.parameter_widgets["TRIGGER_THRESHOLD"] = self.threshold_spin
        layout.addWidget(self.threshold_spin, row, 1)
        row += 1

        # Trigger Rise Time
        layout.addWidget(QLabel("Rise Time:"), row, 0)
        self.trigger_rise_spin = ValidatedDoubleSpinBox(
            "TRIGGER_RISETIME", self.validator
        )
        self.trigger_rise_spin.setValue(0.1)
        self.parameter_widgets["TRIGGER_RISETIME"] = self.trigger_rise_spin
        layout.addWidget(self.trigger_rise_spin, row, 1)
        row += 1

        # Trigger Flat Top
        layout.addWidget(QLabel("Flat Top:"), row, 0)
        self.trigger_flat_spin = ValidatedDoubleSpinBox(
            "TRIGGER_FLATTOP", self.validator
        )
        self.trigger_flat_spin.setValue(0.1)
        self.parameter_widgets["TRIGGER_FLATTOP"] = self.trigger_flat_spin
        layout.addWidget(self.trigger_flat_spin, row, 1)
        row += 1

        tab.setLayout(layout)
        return tab

    def create_energy_tab(self):
        tab = QWidget()
        layout = QGridLayout()
        layout.setVerticalSpacing(10)

        row = 0

        # Energy Rise Time
        layout.addWidget(QLabel("Rise Time:"), row, 0)
        self.energy_rise_spin = ValidatedDoubleSpinBox(
            "ENERGY_RISETIME", self.validator
        )
        self.energy_rise_spin.setValue(2.0)
        self.parameter_widgets["ENERGY_RISETIME"] = self.energy_rise_spin
        layout.addWidget(self.energy_rise_spin, row, 1)
        row += 1

        # Energy Flat Top
        layout.addWidget(QLabel("Flat Top:"), row, 0)
        self.energy_flat_spin = ValidatedDoubleSpinBox("ENERGY_FLATTOP", self.validator)
        self.energy_flat_spin.setValue(0.5)
        self.parameter_widgets["ENERGY_FLATTOP"] = self.energy_flat_spin
        layout.addWidget(self.energy_flat_spin, row, 1)
        row += 1

        # Energy Minimum
        layout.addWidget(QLabel("Energy Min:"), row, 0)
        self.emin_spin = ValidatedSpinBox("EMIN", self.validator)
        self.emin_spin.setValue(0)
        self.parameter_widgets["EMIN"] = self.emin_spin
        layout.addWidget(self.emin_spin, row, 1)
        row += 1

        # Energy Filter Taps (for debugging and live calibration)
        layout.addWidget(QLabel("Energy L:"), row, 0)
        self.energy_L_spin = ValidatedSpinBox("ENERGY_L", self.validator)
        self.energy_L_spin.setValue(40)
        self.parameter_widgets["ENERGY_L"] = self.energy_L_spin
        layout.addWidget(self.energy_L_spin, row, 1)
        row += 1
        
        layout.addWidget(QLabel("Energy G:"), row, 0)
        self.energy_G_spin = ValidatedSpinBox("ENERGY_G", self.validator)
        self.energy_G_spin.setValue(10)
        self.parameter_widgets["ENERGY_G"] = self.energy_G_spin
        layout.addWidget(self.energy_G_spin, row, 1)
        row += 1

        tab.setLayout(layout)
        return tab

    def create_timing_tab(self):
        tab = QWidget()
        layout = QGridLayout()
        layout.setVerticalSpacing(10)

        row = 0

        # Preamplifier Tau
        layout.addWidget(QLabel("Preamp Tau:"), row, 0)
        self.tau_spin = ValidatedDoubleSpinBox("TAU", self.validator)
        self.tau_spin.setValue(50.0)
        self.parameter_widgets["TAU"] = self.tau_spin
        layout.addWidget(self.tau_spin, row, 1)
        row += 1

        # External Deadtime
        layout.addWidget(QLabel("Ext Deadtime:"), row, 0)
        self.xdt_spin = ValidatedDoubleSpinBox("XDT", self.validator)
        self.xdt_spin.setValue(0.0)
        self.parameter_widgets["XDT"] = self.xdt_spin
        layout.addWidget(self.xdt_spin, row, 1)
        row += 1

        # Baseline Percentage
        layout.addWidget(QLabel("Baseline %:"), row, 0)
        self.baseline_percent_spin = ValidatedDoubleSpinBox(
            "BASELINE_PERCENT", self.validator
        )
        self.baseline_percent_spin.setValue(10.0)
        self.parameter_widgets["BASELINE_PERCENT"] = self.baseline_percent_spin
        layout.addWidget(self.baseline_percent_spin, row, 1)
        row += 1

        # Baseline Average
        layout.addWidget(QLabel("Baseline Avg:"), row, 0)
        self.baseline_avg_spin = ValidatedSpinBox("BASELINE_AVERAGE", self.validator)
        self.baseline_avg_spin.setValue(4)
        self.parameter_widgets["BASELINE_AVERAGE"] = self.baseline_avg_spin
        layout.addWidget(self.baseline_avg_spin, row, 1)
        row += 1

        # Baseline Cut (BLCUT)
        layout.addWidget(QLabel("Baseline Cut:"), row, 0)
        self.blcut_spin = ValidatedSpinBox("BLCUT", self.validator)
        self.blcut_spin.setValue(200)
        self.parameter_widgets["BLCUT"] = self.blcut_spin
        layout.addWidget(self.blcut_spin, row, 1)
        row += 1

        tab.setLayout(layout)
        return tab

    def create_trace_tab(self):
        tab = QWidget()
        layout = QGridLayout()
        layout.setVerticalSpacing(10)

        row = 0

        # Trace Length
        layout.addWidget(QLabel("Trace Length:"), row, 0)
        self.trace_length_spin = ValidatedDoubleSpinBox("TRACE_LENGTH", self.validator)
        self.trace_length_spin.setValue(2.0)
        self.parameter_widgets["TRACE_LENGTH"] = self.trace_length_spin
        layout.addWidget(self.trace_length_spin, row, 1)
        row += 1

        # Trace Delay
        layout.addWidget(QLabel("Trace Delay:"), row, 0)
        self.trace_delay_spin = ValidatedDoubleSpinBox("TRACE_DELAY", self.validator)
        self.trace_delay_spin.setValue(0.5)
        self.parameter_widgets["TRACE_DELAY"] = self.trace_delay_spin
        layout.addWidget(self.trace_delay_spin, row, 1)
        row += 1

        tab.setLayout(layout)
        return tab

    def create_cfd_tab(self):
        tab = QWidget()
        layout = QGridLayout()
        layout.setVerticalSpacing(10)

        row = 0

        layout.addWidget(QLabel("CFD Delay:"), row, 0)
        self.cfd_delay_spin = ValidatedDoubleSpinBox("CFDDelay", self.validator)
        self.cfd_delay_spin.setValue(0.1)
        self.parameter_widgets["CFDDelay"] = self.cfd_delay_spin
        layout.addWidget(self.cfd_delay_spin, row, 1)
        row += 1

        layout.addWidget(QLabel("CFD Scale:"), row, 0)
        self.cfd_scale_spin = ValidatedDoubleSpinBox("CFDScale", self.validator)
        self.cfd_scale_spin.setValue(1.0)
        self.parameter_widgets["CFDScale"] = self.cfd_scale_spin
        layout.addWidget(self.cfd_scale_spin, row, 1)
        row += 1

        layout.addWidget(QLabel("CFD Threshold:"), row, 0)
        self.cfd_thresh_spin = ValidatedSpinBox("CFDThresh", self.validator)
        self.cfd_thresh_spin.setValue(500)
        self.parameter_widgets["CFDThresh"] = self.cfd_thresh_spin
        layout.addWidget(self.cfd_thresh_spin, row, 1)
        row += 1

        tab.setLayout(layout)
        return tab

    def create_qdc_tab(self):
        tab = QWidget()
        layout = QGridLayout()
        layout.setVerticalSpacing(10)

        row = 0

        for i in range(8):  # Show all 8 QDC channels
            layout.addWidget(QLabel(f"QDC Len {i}:"), row, 0)
            qdc_spin = ValidatedDoubleSpinBox(f"QDCLen{i}", self.validator)
            qdc_spin.setValue(1.0)
            self.parameter_widgets[f"QDCLen{i}"] = qdc_spin
            layout.addWidget(qdc_spin, row, 1)
            row += 1

        tab.setLayout(layout)
        return tab

    def create_hardware_tab(self):
        tab = QWidget()
        layout = QGridLayout()
        layout.setVerticalSpacing(10)

        row = 0

        # Voltage Offset
        layout.addWidget(QLabel("DC Offset:"), row, 0)
        self.voffset_spin = ValidatedDoubleSpinBox("VOFFSET", self.validator)
        self.voffset_spin.setValue(0.0)
        self.parameter_widgets["VOFFSET"] = self.voffset_spin
        layout.addWidget(self.voffset_spin, row, 1)
        row += 1

        # Gain
        layout.addWidget(QLabel("Gain:"), row, 0)
        self.gain_combo = QComboBox()
        self.gain_combo.addItems(["0.625", "2.5"])
        self.gain_combo.setCurrentText("2.5")
        self.gain_combo.setToolTip(
            "Analog gain setting (0.625 = low gain, 2.5 = high gain)"
        )
        self.parameter_widgets["Gain"] = self.gain_combo
        layout.addWidget(self.gain_combo, row, 1)
        row += 1

        # Polarity
        layout.addWidget(QLabel("Polarity:"), row, 0)
        self.polarity_combo = QComboBox()
        self.polarity_combo.addItems(["negative", "positive"])
        self.polarity_combo.setCurrentText("negative")
        self.polarity_combo.setToolTip("Signal polarity (must match detector output)")
        self.parameter_widgets["Polarity"] = self.polarity_combo
        layout.addWidget(self.polarity_combo, row, 1)
        row += 1

        # Channel Enable
        self.channel_enable_check = QCheckBox("Channel Enabled")
        self.channel_enable_check.setChecked(True)
        self.channel_enable_check.setToolTip(
            "Enable/disable channel for data processing"
        )
        self.parameter_widgets["GoodChannel"] = self.channel_enable_check
        layout.addWidget(self.channel_enable_check, row, 0, 1, 2)
        row += 1

        # Trace Capture
        self.trace_capture_check = QCheckBox("Capture Traces")
        self.trace_capture_check.setChecked(False)
        self.trace_capture_check.setToolTip(
            "Enable ADC trace recording (increases data volume)"
        )
        self.parameter_widgets["CaptureTrace"] = self.trace_capture_check
        layout.addWidget(self.trace_capture_check, row, 0, 1, 2)
        row += 1

        tab.setLayout(layout)
        return tab

    def create_action_buttons(self):
        group = QGroupBox("Settings Actions")
        layout = QHBoxLayout()

        self.apply_all_btn = QPushButton("Apply All")
        self.apply_all_btn.setToolTip(
            "Apply all current parameter values to selected module/channel"
        )
        self.apply_all_btn.setStyleSheet(
            """
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    font-weight: bold;
                    padding: 8px 16px;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
                QPushButton:pressed {
                    background-color: #3d8b40;
                }
            """
        )
        layout.addWidget(self.apply_all_btn)

        self.read_hw_btn = QPushButton("Read from Hardware")
        self.read_hw_btn.setToolTip("Read current parameter values from hardware")
        layout.addWidget(self.read_hw_btn)

        self.load_preset_btn = QPushButton("Load Preset")
        self.load_preset_btn.setToolTip("Load parameter values from file")
        layout.addWidget(self.load_preset_btn)

        self.save_preset_btn = QPushButton("Save Preset")
        self.save_preset_btn.setToolTip("Save current parameter values to file")
        layout.addWidget(self.save_preset_btn)

        layout.addStretch()
        group.setLayout(layout)
        return group

    def connect_signals(self):
        # Module/Channel selection
        self.module_spin.valueChanged.connect(self.on_module_changed)
        self.channel_spin.valueChanged.connect(self.on_channel_changed)

        # Real-time update controls
        self.realtime_check.toggled.connect(self.on_realtime_toggled)
        self.debounce_spin.valueChanged.connect(self.on_debounce_changed)

        # Connect all parameter widgets
        for param_name, widget in self.parameter_widgets.items():
            self._connect_parameter_widget(param_name, widget)

        # Action buttons
        self.apply_all_btn.clicked.connect(self.apply_all_settings)
        self.read_hw_btn.clicked.connect(self.read_from_hardware)
        self.load_preset_btn.clicked.connect(self.load_preset)
        self.save_preset_btn.clicked.connect(self.save_preset)

    def _connect_parameter_widget(self, param_name: str, widget):
        if isinstance(widget, QSpinBox | QDoubleSpinBox):
            widget.valueChanged.connect(
                lambda value, name=param_name: self.on_parameter_changed(name, value)
            )
        elif isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(
                lambda text, name=param_name: self.on_parameter_changed(name, text)
            )
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(
                lambda checked, name=param_name: self.on_parameter_changed(
                    name, checked
                )
            )

    def on_parameter_changed(self, param_name: str, value):
        module = self.module_spin.value()
        channel = self.channel_spin.value()

        self.parameter_changed.emit(param_name, value, module, channel)
        self.status_message.emit(
            f"Parameter {param_name} changed to {value} (pending apply)"
        )

    def on_realtime_toggled(self, enabled: bool):
        self.real_time_updates_enabled = False
        if enabled:
            self.realtime_check.setChecked(False)  # Force disabled
            self.status_message.emit(
                "Real-time parameter updates disabled (use 'Apply All' button - PIXIE-16 hardware limitation)"
            )
        else:
            self.status_message.emit(
                "Parameter updates: Use 'Apply All' button to update hardware"
            )

    def on_debounce_changed(self, delay: float):
        self.change_manager.debounce_delay = delay
        self.status_message.emit(f"Debounce delay set to {delay} seconds")

    def on_module_changed(self, module: int):
        self.current_module = module
        self.status_message.emit(f"Selected Module {module}")
        # Read parameters from new module if real-time updates enabled
        if self.real_time_updates_enabled:
            QTimer.singleShot(100, self.read_from_hardware)

    def on_channel_changed(self, channel: int):
        self.current_channel = channel
        self.status_message.emit(f"Selected Channel {channel}")
        # Read parameters from new channel if real-time updates enabled
        if self.real_time_updates_enabled:
            QTimer.singleShot(100, self.read_from_hardware)

    def apply_all_settings(self):
        params = self.get_all_parameters()
        module = self.module_spin.value()
        channel = self.channel_spin.value()

        # Validate all parameters
        validated_params = self.validator.validate_parameter_set(
            params, module, channel
        )

        self.apply_all_requested.emit(validated_params, module, channel)
        self.status_message.emit(
            f"Applied all settings to Module {module}, Channel {channel}"
        )

    def read_from_hardware(self):  # Implemented by the parent scope application
        self.status_message.emit("Reading parameters from hardware...")

    def get_all_parameters(self) -> dict[str, any]:
        params = {}

        for param_name, widget in self.parameter_widgets.items():
            if isinstance(widget, QSpinBox):
                params[param_name] = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                params[param_name] = widget.value()
            elif isinstance(widget, QComboBox):
                if param_name == "Gain":
                    params[param_name] = float(widget.currentText())
                else:
                    params[param_name] = widget.currentText()
            elif isinstance(widget, QCheckBox):
                params[param_name] = widget.isChecked()

        return params

    def set_all_parameters(self, params: dict[str, any]):
        for param_name, value in params.items():
            if param_name in self.parameter_widgets:
                widget = self.parameter_widgets[param_name]

                # Temporarily disconnect signals to avoid recursive updates
                self._disconnect_widget_signals(widget)

                try:
                    if isinstance(widget, QSpinBox | QDoubleSpinBox):
                        widget.setValue(value)
                    elif isinstance(widget, QComboBox):
                        widget.setCurrentText(str(value))
                    elif isinstance(widget, QCheckBox):
                        widget.setChecked(bool(value))
                finally:
                    # Reconnect signals
                    self._connect_parameter_widget(param_name, widget)

    def _disconnect_widget_signals(self, widget):
        if isinstance(widget | (QSpinBox | QDoubleSpinBox)):
            widget.valueChanged.disconnect()
        elif isinstance(widget, QComboBox):
            widget.currentTextChanged.disconnect()
        elif isinstance(widget, QCheckBox):
            widget.toggled.disconnect()

    def set_default_values(self):
        # Core trigger parameters
        if "TRIGGER_THRESHOLD" in self.parameter_widgets:
            self.parameter_widgets["TRIGGER_THRESHOLD"].setValue(1000)
        if "TRIGGER_RISETIME" in self.parameter_widgets:
            self.parameter_widgets["TRIGGER_RISETIME"].setValue(0.1)
        if "TRIGGER_FLATTOP" in self.parameter_widgets:
            self.parameter_widgets["TRIGGER_FLATTOP"].setValue(0.1)

        # Energy filter parameters
        if "ENERGY_RISETIME" in self.parameter_widgets:
            self.parameter_widgets["ENERGY_RISETIME"].setValue(2.0)
        if "ENERGY_FLATTOP" in self.parameter_widgets:
            self.parameter_widgets["ENERGY_FLATTOP"].setValue(0.5)

        # Hardware settings
        if "Gain" in self.parameter_widgets:
            self.parameter_widgets["Gain"].setCurrentText("2.5")
        if "Polarity" in self.parameter_widgets:
            self.parameter_widgets["Polarity"].setCurrentText("negative")
        if "GoodChannel" in self.parameter_widgets:
            self.parameter_widgets["GoodChannel"].setChecked(True)
        if "CaptureTrace" in self.parameter_widgets:
            self.parameter_widgets["CaptureTrace"].setChecked(False)

    def load_preset(self):
        try:
            if hasattr(self.parent(), 'data_storage_manager'):
                data_manager = self.parent().data_storage_manager
                default_dir = data_manager.get_data_directory() / "sessions"
                default_dir.mkdir(parents=True, exist_ok=True)
            else:
                default_dir = Path.home() / "PIXIE16_settings"
                
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Load Parameter Preset", str(default_dir), "JSON Files (*.json);;All Files (*)"
            )

            if file_path:
                with open(file_path) as f:
                    preset = json.load(f)

                self.set_all_parameters(preset)
                self.status_message.emit(f"Loaded preset from {Path(file_path).name}")

        except Exception as e:
            error_msg = f"Error loading preset: {e}"
            logger.error(error_msg)
            self.status_message.emit(error_msg)
            QMessageBox.warning(self, "Load Error", error_msg)

    def save_preset(self):
        try:
            # Get unified data directory as default location
            if hasattr(self.parent(), 'data_storage_manager'):
                data_manager = self.parent().data_storage_manager
            else:
                from .data_manager import DataSettingsManager
                data_manager = DataSettingsManager()
            default_dir = data_manager.get_data_directory() / "sessions"
            default_dir.mkdir(parents=True, exist_ok=True)
            default_path = default_dir / f"pixie_preset_{int(time.time())}.json"
            
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Parameter Preset",
                str(default_path),
                "JSON Files (*.json);;All Files (*)",
            )

            if file_path:
                preset = self.get_all_parameters()
                preset.update(
                    {
                        "timestamp": time.time(),
                        "module": self.module_spin.value(),
                        "channel": self.channel_spin.value(),
                        "description": f"PIXIE-16 parameters for Module {self.current_module}, Channel {self.current_channel}",
                        "module_type": self.validator.module_type,
                    }
                )

                with open(file_path, "w") as f:
                    json.dump(preset, f, indent=2)

                self.status_message.emit(f"Saved preset to {Path(file_path).name}")

        except Exception as e:
            error_msg = f"Error saving preset: {e}"
            logger.error(error_msg)
            self.status_message.emit(error_msg)
            QMessageBox.warning(self, "Save Error", error_msg)

    def _hardware_update_callback(
        self, params: dict[str, any], module: int, channel: int
    ):
        # This will be connected by the parent scope application
        self.apply_all_requested.emit(params, module, channel)

    def set_module_channel(self, module: int, channel: int):
        self.module_spin.setValue(module)
        self.channel_spin.setValue(channel)
