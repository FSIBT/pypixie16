"""
Parameter control widgets for PIXIE-16 scope interface.
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
)
from PyQt6.QtCore import pyqtSignal, Qt

logger = logging.getLogger(__name__)


class ParameterControls(QGroupBox):
    parameter_changed = pyqtSignal(str, object, int, int)
    apply_all_requested = pyqtSignal(dict, int, int)  # (all_params, module, channel)
    status_message = pyqtSignal(str)  # For status bar updates

    def __init__(self, initial_module=0, title="PIXIE-16 Parameters"):
        super().__init__(title)

        self.current_module = initial_module
        self.current_channel = 0

        self.setup_ui()
        self.connect_signals()
        self.set_default_values()

    def setup_ui(self):
        main_layout = QVBoxLayout()

        module_channel_group = self.create_module_channel_selector()
        main_layout.addWidget(module_channel_group)

        param_tabs = self.create_parameter_tabs()
        main_layout.addWidget(param_tabs)

        # at bottom
        button_group = self.create_action_buttons()
        main_layout.addWidget(button_group)

        self.setLayout(main_layout)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def create_module_channel_selector(self):
        group = QGroupBox("Target Module/Channel")
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

        layout.addStretch()
        group.setLayout(layout)
        return group

    def create_parameter_tabs(self):
        tabs = QTabWidget()

        trigger_tab = self.create_trigger_tab()
        tabs.addTab(trigger_tab, "Trigger")

        energy_tab = self.create_energy_tab()
        tabs.addTab(energy_tab, "Energy")
        hardware_tab = self.create_hardware_tab()
        tabs.addTab(hardware_tab, "Hardware")

        return tabs

    def create_trigger_tab(self):
        tab = QWidget()
        layout = QGridLayout()

        layout.addWidget(QLabel("Trigger Threshold:"), 0, 0)
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(0, 65535)
        self.threshold_spin.setValue(1000)
        self.threshold_spin.setSuffix(" ADC")
        self.threshold_spin.setToolTip("ADC threshold for event detection (0-65535)")
        layout.addWidget(self.threshold_spin, 0, 1)
        layout.addWidget(QLabel("Trigger Rise Time:"), 1, 0)
        self.trigger_rise_spin = QDoubleSpinBox()
        self.trigger_rise_spin.setRange(0.01, 10.0)
        self.trigger_rise_spin.setValue(0.1)
        self.trigger_rise_spin.setSuffix(" μs")
        self.trigger_rise_spin.setDecimals(3)
        self.trigger_rise_spin.setToolTip(
            "Fast filter rise time for trigger (0.01-10.0 μs)"
        )
        layout.addWidget(self.trigger_rise_spin, 1, 1)

        layout.addWidget(QLabel("Trigger Flat Top:"), 2, 0)
        self.trigger_flat_spin = QDoubleSpinBox()
        self.trigger_flat_spin.setRange(0.01, 5.0)
        self.trigger_flat_spin.setValue(0.1)
        self.trigger_flat_spin.setSuffix(" μs")
        self.trigger_flat_spin.setDecimals(3)
        self.trigger_flat_spin.setToolTip(
            "Fast filter flat top for trigger timing (0.01-5.0 μs)"
        )
        layout.addWidget(self.trigger_flat_spin, 2, 1)

        layout.setRowStretch(3, 1)
        tab.setLayout(layout)
        return tab

    def create_energy_tab(self):
        tab = QWidget()
        layout = QGridLayout()

        layout.addWidget(QLabel("Energy Rise Time:"), 0, 0)
        self.energy_rise_spin = QDoubleSpinBox()
        self.energy_rise_spin.setRange(0.1, 100.0)
        self.energy_rise_spin.setValue(2.0)
        self.energy_rise_spin.setSuffix(" μs")
        self.energy_rise_spin.setDecimals(3)
        self.energy_rise_spin.setToolTip(
            "Slow filter rise time for energy (0.1-100.0 μs)"
        )
        layout.addWidget(self.energy_rise_spin, 0, 1)

        layout.addWidget(QLabel("Energy Flat Top:"), 1, 0)
        self.energy_flat_spin = QDoubleSpinBox()
        self.energy_flat_spin.setRange(0.01, 10.0)
        self.energy_flat_spin.setValue(0.5)
        self.energy_flat_spin.setSuffix(" μs")
        self.energy_flat_spin.setDecimals(3)
        self.energy_flat_spin.setToolTip(
            "Slow filter flat top for energy resolution (0.01-10.0 μs)"
        )
        layout.addWidget(self.energy_flat_spin, 1, 1)

        layout.setRowStretch(2, 1)  # Add stretch
        tab.setLayout(layout)
        return tab

    def create_hardware_tab(self):
        tab = QWidget()
        layout = QGridLayout()

        layout.addWidget(QLabel("Gain:"), 0, 0)
        self.gain_combo = QComboBox()
        self.gain_combo.addItems(["0.625", "2.5"])
        self.gain_combo.setCurrentText("2.5")
        self.gain_combo.setToolTip(
            "Analog gain setting (0.625 = low gain, 2.5 = high gain)"
        )
        layout.addWidget(self.gain_combo, 0, 1)

        layout.addWidget(QLabel("Polarity:"), 1, 0)
        self.polarity_combo = QComboBox()
        self.polarity_combo.addItems(["negative", "positive"])
        self.polarity_combo.setCurrentText("negative")
        self.polarity_combo.setToolTip("Signal polarity (must match detector output)")
        layout.addWidget(self.polarity_combo, 1, 1)

        self.channel_enable_check = QCheckBox("Channel Enabled")
        self.channel_enable_check.setChecked(True)
        self.channel_enable_check.setToolTip(
            "Enable/disable channel for data processing"
        )
        layout.addWidget(self.channel_enable_check, 2, 0, 1, 2)

        self.trace_capture_check = QCheckBox("Capture Traces")
        self.trace_capture_check.setChecked(False)
        self.trace_capture_check.setToolTip(
            "Enable ADC trace recording (increases data volume)"
        )
        layout.addWidget(self.trace_capture_check, 3, 0, 1, 2)

        layout.setRowStretch(4, 1)
        tab.setLayout(layout)
        return tab

    def create_action_buttons(self):
        group = QGroupBox("Actions")
        layout = QHBoxLayout()

        self.apply_all_btn = QPushButton("Apply All Settings")
        self.apply_all_btn.setToolTip(
            "Apply all current parameter values to selected module/channel"
        )
        self.apply_all_btn.setStyleSheet("""
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
        """)
        layout.addWidget(self.apply_all_btn)

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
        print("DEBUG: Connecting parameter control signals...")

        self.module_spin.valueChanged.connect(self.on_module_changed)
        self.channel_spin.valueChanged.connect(self.on_channel_changed)

        self.threshold_spin.valueChanged.connect(
            lambda val: self.debug_emit_parameter_change("TRIGGER_THRESHOLD", val)
        )
        self.trigger_rise_spin.valueChanged.connect(
            lambda val: self.debug_emit_parameter_change("TRIGGER_RISETIME", val)
        )
        self.trigger_flat_spin.valueChanged.connect(
            lambda val: self.debug_emit_parameter_change("TRIGGER_FLATTOP", val)
        )
        self.energy_rise_spin.valueChanged.connect(
            lambda val: self.debug_emit_parameter_change("ENERGY_RISETIME", val)
        )
        self.energy_flat_spin.valueChanged.connect(
            lambda val: self.debug_emit_parameter_change("ENERGY_FLATTOP", val)
        )
        self.gain_combo.currentTextChanged.connect(
            lambda text: self.debug_emit_parameter_change("Gain", float(text))
        )
        self.polarity_combo.currentTextChanged.connect(
            lambda text: self.debug_emit_parameter_change("Polarity", text)
        )
        self.channel_enable_check.toggled.connect(
            lambda checked: self.debug_emit_parameter_change("GoodChannel", checked)
        )
        self.trace_capture_check.toggled.connect(
            lambda checked: self.debug_emit_parameter_change("CaptureTrace", checked)
        )

        self.apply_all_btn.clicked.connect(self.apply_all_settings)
        self.load_preset_btn.clicked.connect(self.load_preset)
        self.save_preset_btn.clicked.connect(self.save_preset)

        print("DEBUG: All parameter control signals connected")

    def debug_emit_parameter_change(self, param_name, value):
        print(f"DEBUG: Parameter widget changed: {param_name} = {value}")
        module = self.module_spin.value()
        channel = self.channel_spin.value()
        print(f"DEBUG: Emitting parameter_changed signal for M{module}:Ch{channel}")
        self.parameter_changed.emit(param_name, value, module, channel)
        print(f"DEBUG: Signal emitted successfully")

    def set_default_values(self):
        self.threshold_spin.setValue(1000)
        self.trigger_rise_spin.setValue(0.1)
        self.trigger_flat_spin.setValue(0.1)
        self.energy_rise_spin.setValue(2.0)
        self.energy_flat_spin.setValue(0.5)
        self.gain_combo.setCurrentText("2.5")
        self.polarity_combo.setCurrentText("negative")
        self.channel_enable_check.setChecked(True)
        self.trace_capture_check.setChecked(False)

    def emit_parameter_change(self, param_name, value):
        module = self.module_spin.value()
        channel = self.channel_spin.value()
        self.parameter_changed.emit(param_name, value, module, channel)

    def on_module_changed(self, module):
        self.current_module = module
        self.status_message.emit(f"Selected Module {module}")

    def on_channel_changed(self, channel):
        self.current_channel = channel
        self.status_message.emit(f"Selected Channel {channel}")

    def apply_all_settings(self):
        params = self.get_all_parameters()
        module = self.module_spin.value()
        channel = self.channel_spin.value()

        self.apply_all_requested.emit(params, module, channel)
        self.status_message.emit(
            f"Applied all settings to Module {module}, Channel {channel}"
        )

    def get_all_parameters(self):
        return {
            "TRIGGER_THRESHOLD": self.threshold_spin.value(),
            "TRIGGER_RISETIME": self.trigger_rise_spin.value(),
            "TRIGGER_FLATTOP": self.trigger_flat_spin.value(),
            "ENERGY_RISETIME": self.energy_rise_spin.value(),
            "ENERGY_FLATTOP": self.energy_flat_spin.value(),
            "Gain": float(self.gain_combo.currentText()),
            "Polarity": self.polarity_combo.currentText(),
            "GoodChannel": self.channel_enable_check.isChecked(),
            "CaptureTrace": self.trace_capture_check.isChecked(),
        }

    def set_all_parameters(self, params):
        if "TRIGGER_THRESHOLD" in params:
            self.threshold_spin.setValue(params["TRIGGER_THRESHOLD"])
        if "TRIGGER_RISETIME" in params:
            self.trigger_rise_spin.setValue(params["TRIGGER_RISETIME"])
        if "TRIGGER_FLATTOP" in params:
            self.trigger_flat_spin.setValue(params["TRIGGER_FLATTOP"])
        if "ENERGY_RISETIME" in params:
            self.energy_rise_spin.setValue(params["ENERGY_RISETIME"])
        if "ENERGY_FLATTOP" in params:
            self.energy_flat_spin.setValue(params["ENERGY_FLATTOP"])
        if "Gain" in params:
            self.gain_combo.setCurrentText(str(params["Gain"]))
        if "Polarity" in params:
            self.polarity_combo.setCurrentText(params["Polarity"])
        if "GoodChannel" in params:
            self.channel_enable_check.setChecked(params["GoodChannel"])
        if "CaptureTrace" in params:
            self.trace_capture_check.setChecked(params["CaptureTrace"])

    def load_preset(self):
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Load Parameter Preset", "", "JSON Files (*.json);;All Files (*)"
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
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Parameter Preset",
                f"pixie_preset_{int(time.time())}.json",
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

    def set_module_channel(self, module, channel):
        self.module_spin.setValue(module)
        self.channel_spin.setValue(channel)
