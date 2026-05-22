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
    QFormLayout,
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

from .parameter_validation import PixieParameterValidator

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
    status_message = pyqtSignal(str)
    request_read_hardware = pyqtSignal()
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

        # Widget storage for dynamic access
        self.parameter_widgets = {}

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

        # Create scroll area for parameter content
        self.param_scroll_area = QScrollArea()
        self.param_scroll_area.setWidgetResizable(True)
        self.param_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.param_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.param_scroll_area.setMaximumHeight(400)  # Limit height to prevent panel from becoming too tall
        
        # Create widget to hold scrollable content
        self.param_content_widget = QWidget()
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(5, 5, 5, 5)
        content_layout.setSpacing(5)

        # Module/Channel selector
        module_channel_group = self.create_module_channel_selector()
        content_layout.addWidget(module_channel_group)

        # Parameter tabs
        param_tabs = self.create_parameter_tabs()
        content_layout.addWidget(param_tabs)

        # Action buttons
        button_group = self.create_action_buttons()
        content_layout.addWidget(button_group)

        self.param_content_widget.setLayout(content_layout)
        
        # Set the scrollable widget
        self.param_scroll_area.setWidget(self.param_content_widget)
        self.param_scroll_area.setVisible(False)

        main_container_layout.addWidget(self.param_header_btn)
        main_container_layout.addWidget(self.param_scroll_area)
        main_container.setLayout(main_container_layout)
        main_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )

        return main_container

    def toggle_parameter_section(self, checked):
        self.param_scroll_area.setVisible(checked)
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

        layout.addStretch()
        group.setLayout(layout)
        return group

    # Which parameter names belong to which tab
    _TAB_PARAMS = {
        "Trigger": ["TRIGGER_THRESHOLD", "TRIGGER_RISETIME", "TRIGGER_FLATTOP"],
        "Energy": ["ENERGY_RISETIME", "ENERGY_FLATTOP", "EMIN", "ENERGY_L", "ENERGY_G"],
        "Timing": ["TAU", "XDT", "BASELINE_PERCENT", "BASELINE_AVERAGE", "BLCUT"],
        "Traces": ["TRACE_LENGTH", "TRACE_DELAY"],
        "CFD": ["CFDDelay", "CFDScale", "CFDThresh"],
        "QDC": [f"QDCLen{i}" for i in range(8)],
        "Hardware": ["VOFFSET", "Gain", "Polarity", "GoodChannel", "CaptureTrace"],
    }

    def create_parameter_tabs(self):
        self.param_tabs = QTabWidget()
        self.param_tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        # Core acquisition parameters
        trigger_tab = self.create_trigger_tab()
        self.param_tabs.addTab(trigger_tab, "Trigger")

        energy_tab = self.create_energy_tab()
        self.param_tabs.addTab(energy_tab, "Energy")

        # Advanced timing parameters
        timing_tab = self.create_timing_tab()
        self.param_tabs.addTab(timing_tab, "Timing")

        # Split advanced into three tabs
        trace_tab = self.create_trace_tab()
        self.param_tabs.addTab(trace_tab, "Traces")

        cfd_tab = self.create_cfd_tab()
        self.param_tabs.addTab(cfd_tab, "CFD")

        qdc_tab = self.create_qdc_tab()
        self.param_tabs.addTab(qdc_tab, "QDC")

        # Hardware configuration
        hardware_tab = self.create_hardware_tab()
        self.param_tabs.addTab(hardware_tab, "Hardware")

        return self.param_tabs

    def create_trigger_tab(self):
        tab = QWidget()
        layout = QFormLayout()
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        layout.setVerticalSpacing(6)
        layout.setHorizontalSpacing(8)

        self.threshold_spin = ValidatedSpinBox("TRIGGER_THRESHOLD", self.validator)
        self.threshold_spin.setValue(1000)
        self.parameter_widgets["TRIGGER_THRESHOLD"] = self.threshold_spin
        layout.addRow("Threshold:", self.threshold_spin)

        self.trigger_rise_spin = ValidatedDoubleSpinBox(
            "TRIGGER_RISETIME", self.validator
        )
        self.trigger_rise_spin.setValue(0.1)
        self.parameter_widgets["TRIGGER_RISETIME"] = self.trigger_rise_spin
        layout.addRow("Rise Time:", self.trigger_rise_spin)

        self.trigger_flat_spin = ValidatedDoubleSpinBox(
            "TRIGGER_FLATTOP", self.validator
        )
        self.trigger_flat_spin.setValue(0.1)
        self.parameter_widgets["TRIGGER_FLATTOP"] = self.trigger_flat_spin
        layout.addRow("Flat Top:", self.trigger_flat_spin)

        tab.setLayout(layout)
        return tab

    def create_energy_tab(self):
        tab = QWidget()
        layout = QFormLayout()
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        layout.setVerticalSpacing(6)
        layout.setHorizontalSpacing(8)

        self.energy_rise_spin = ValidatedDoubleSpinBox(
            "ENERGY_RISETIME", self.validator
        )
        self.energy_rise_spin.setValue(2.0)
        self.parameter_widgets["ENERGY_RISETIME"] = self.energy_rise_spin
        layout.addRow("Rise Time:", self.energy_rise_spin)

        self.energy_flat_spin = ValidatedDoubleSpinBox("ENERGY_FLATTOP", self.validator)
        self.energy_flat_spin.setValue(0.5)
        self.parameter_widgets["ENERGY_FLATTOP"] = self.energy_flat_spin
        layout.addRow("Flat Top:", self.energy_flat_spin)

        self.emin_spin = ValidatedSpinBox("EMIN", self.validator)
        self.emin_spin.setValue(0)
        self.parameter_widgets["EMIN"] = self.emin_spin
        layout.addRow("Energy Min:", self.emin_spin)

        self.energy_L_spin = ValidatedSpinBox("ENERGY_L", self.validator)
        self.energy_L_spin.setValue(40)
        self.parameter_widgets["ENERGY_L"] = self.energy_L_spin
        layout.addRow("Energy L:", self.energy_L_spin)

        self.energy_G_spin = ValidatedSpinBox("ENERGY_G", self.validator)
        self.energy_G_spin.setValue(10)
        self.parameter_widgets["ENERGY_G"] = self.energy_G_spin
        layout.addRow("Energy G:", self.energy_G_spin)

        tab.setLayout(layout)
        return tab

    def create_timing_tab(self):
        tab = QWidget()
        layout = QFormLayout()
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        layout.setVerticalSpacing(6)
        layout.setHorizontalSpacing(8)

        self.tau_spin = ValidatedDoubleSpinBox("TAU", self.validator)
        self.tau_spin.setValue(50.0)
        self.parameter_widgets["TAU"] = self.tau_spin
        layout.addRow("Preamp Tau:", self.tau_spin)

        self.xdt_spin = ValidatedDoubleSpinBox("XDT", self.validator)
        self.xdt_spin.setValue(0.0)
        self.parameter_widgets["XDT"] = self.xdt_spin
        layout.addRow("Ext Deadtime:", self.xdt_spin)

        self.baseline_percent_spin = ValidatedDoubleSpinBox(
            "BASELINE_PERCENT", self.validator
        )
        self.baseline_percent_spin.setValue(10.0)
        self.parameter_widgets["BASELINE_PERCENT"] = self.baseline_percent_spin
        layout.addRow("Baseline %:", self.baseline_percent_spin)

        self.baseline_avg_spin = ValidatedSpinBox("BASELINE_AVERAGE", self.validator)
        self.baseline_avg_spin.setValue(4)
        self.parameter_widgets["BASELINE_AVERAGE"] = self.baseline_avg_spin
        layout.addRow("Baseline Avg:", self.baseline_avg_spin)

        self.blcut_spin = ValidatedSpinBox("BLCUT", self.validator)
        self.blcut_spin.setValue(200)
        self.parameter_widgets["BLCUT"] = self.blcut_spin
        layout.addRow("Baseline Cut:", self.blcut_spin)

        tab.setLayout(layout)
        return tab

    def create_trace_tab(self):
        tab = QWidget()
        layout = QFormLayout()
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        layout.setVerticalSpacing(6)
        layout.setHorizontalSpacing(8)

        self.trace_length_spin = ValidatedDoubleSpinBox("TRACE_LENGTH", self.validator)
        self.trace_length_spin.setValue(2.0)
        self.parameter_widgets["TRACE_LENGTH"] = self.trace_length_spin
        layout.addRow("Trace Length:", self.trace_length_spin)

        self.trace_delay_spin = ValidatedDoubleSpinBox("TRACE_DELAY", self.validator)
        self.trace_delay_spin.setValue(0.5)
        self.parameter_widgets["TRACE_DELAY"] = self.trace_delay_spin
        layout.addRow("Trace Delay:", self.trace_delay_spin)

        tab.setLayout(layout)
        return tab

    def create_cfd_tab(self):
        tab = QWidget()
        layout = QFormLayout()
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        layout.setVerticalSpacing(6)
        layout.setHorizontalSpacing(8)

        self.cfd_delay_spin = ValidatedDoubleSpinBox("CFDDelay", self.validator)
        self.cfd_delay_spin.setValue(0.1)
        self.parameter_widgets["CFDDelay"] = self.cfd_delay_spin
        layout.addRow("CFD Delay:", self.cfd_delay_spin)

        self.cfd_scale_spin = ValidatedDoubleSpinBox("CFDScale", self.validator)
        self.cfd_scale_spin.setValue(1.0)
        self.parameter_widgets["CFDScale"] = self.cfd_scale_spin
        layout.addRow("CFD Scale:", self.cfd_scale_spin)

        self.cfd_thresh_spin = ValidatedSpinBox("CFDThresh", self.validator)
        self.cfd_thresh_spin.setValue(500)
        self.parameter_widgets["CFDThresh"] = self.cfd_thresh_spin
        layout.addRow("CFD Threshold:", self.cfd_thresh_spin)

        tab.setLayout(layout)
        return tab

    def create_qdc_tab(self):
        tab = QWidget()
        layout = QGridLayout()
        layout.setVerticalSpacing(6)
        layout.setHorizontalSpacing(8)
        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 0)
        layout.setColumnStretch(2, 0)
        layout.setColumnStretch(3, 0)
        layout.setColumnStretch(4, 1)  # absorb extra space at the right

        for i in range(8):
            row = i % 4
            col = (i // 4) * 2
            layout.addWidget(QLabel(f"QDC Len {i}:"), row, col)
            qdc_spin = ValidatedDoubleSpinBox(f"QDCLen{i}", self.validator)
            qdc_spin.setValue(1.0)
            self.parameter_widgets[f"QDCLen{i}"] = qdc_spin
            layout.addWidget(qdc_spin, row, col + 1)

        tab.setLayout(layout)
        return tab

    def create_hardware_tab(self):
        tab = QWidget()
        layout = QFormLayout()
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        layout.setVerticalSpacing(6)
        layout.setHorizontalSpacing(8)

        self.voffset_spin = ValidatedDoubleSpinBox("VOFFSET", self.validator)
        self.voffset_spin.setValue(0.0)
        self.parameter_widgets["VOFFSET"] = self.voffset_spin
        layout.addRow("DC Offset:", self.voffset_spin)

        self.gain_combo = QComboBox()
        self.gain_combo.addItems(["0.625", "2.5"])
        self.gain_combo.setCurrentText("2.5")
        self.gain_combo.setToolTip(
            "Analog gain setting (0.625 = low gain, 2.5 = high gain)"
        )
        self.parameter_widgets["Gain"] = self.gain_combo
        layout.addRow("Gain:", self.gain_combo)

        self.polarity_combo = QComboBox()
        self.polarity_combo.addItems(["negative", "positive"])
        self.polarity_combo.setCurrentText("negative")
        self.polarity_combo.setToolTip("Signal polarity (must match detector output)")
        self.parameter_widgets["Polarity"] = self.polarity_combo
        layout.addRow("Polarity:", self.polarity_combo)

        self.channel_enable_check = QCheckBox("Channel Enabled")
        self.channel_enable_check.setChecked(True)
        self.channel_enable_check.setToolTip(
            "Enable/disable channel for data processing"
        )
        self.parameter_widgets["GoodChannel"] = self.channel_enable_check
        layout.addRow("", self.channel_enable_check)

        self.trace_capture_check = QCheckBox("Capture Traces")
        self.trace_capture_check.setChecked(False)
        self.trace_capture_check.setToolTip(
            "Enable ADC trace recording (increases data volume)"
        )
        self.parameter_widgets["CaptureTrace"] = self.trace_capture_check
        layout.addRow("", self.trace_capture_check)

        tab.setLayout(layout)
        return tab

    def create_action_buttons(self):
        group = QGroupBox("Settings Actions")
        layout = QGridLayout()
        layout.setSpacing(4)

        self.apply_channel_btn = QPushButton("Apply to Channel")
        self.apply_channel_btn.setToolTip(
            "Write all parameter values to the selected module/channel"
        )
        self.apply_channel_btn.setStyleSheet(
            "QPushButton { font-weight: bold; background-color: #d0f0d0; }"
        )
        layout.addWidget(self.apply_channel_btn, 0, 0, 1, 2)

        self.read_hw_btn = QPushButton("Read HW")
        self.read_hw_btn.setToolTip("Read current parameter values from hardware")
        layout.addWidget(self.read_hw_btn, 0, 2)

        self.load_preset_btn = QPushButton("Load Preset")
        self.load_preset_btn.setToolTip("Load parameter values from file")
        layout.addWidget(self.load_preset_btn, 1, 0)

        self.save_preset_btn = QPushButton("Save Preset")
        self.save_preset_btn.setToolTip("Save current parameter values to file")
        layout.addWidget(self.save_preset_btn, 1, 1)

        self.load_default_btn = QPushButton("Defaults")
        self.load_default_btn.setToolTip("Load default parameter values from built-in defaults")
        layout.addWidget(self.load_default_btn, 1, 2)

        self.load_dict_btn = QPushButton("From File")
        self.load_dict_btn.setToolTip("Load parameter values from a JSON settings file")
        layout.addWidget(self.load_dict_btn, 2, 0)

        group.setLayout(layout)
        return group

    def connect_signals(self):
        # Module/Channel selection
        self.module_spin.valueChanged.connect(self.on_module_changed)
        self.channel_spin.valueChanged.connect(self.on_channel_changed)

        # Action buttons
        self.apply_channel_btn.clicked.connect(self.apply_to_channel)
        self.read_hw_btn.clicked.connect(self.read_from_hardware)
        self.load_preset_btn.clicked.connect(self.load_preset)
        self.save_preset_btn.clicked.connect(self.save_preset)

    def apply_to_channel(self):
        """Apply only the parameters from the currently visible tab."""
        module = self.module_spin.value()
        channel = self.channel_spin.value()

        # Get the active tab name
        active_tab_name = self.param_tabs.tabText(self.param_tabs.currentIndex())
        active_param_names = self._TAB_PARAMS.get(active_tab_name, [])

        # Only emit params from the visible tab
        all_params = self.get_all_parameters()
        count = 0
        for param_name in active_param_names:
            if param_name in all_params:
                self.parameter_changed.emit(param_name, all_params[param_name], module, channel)
                count += 1

        self.status_message.emit(
            f"Applied {count} params ({active_tab_name}) to M{module}:Ch{channel}"
        )

    def on_module_changed(self, module: int):
        self.current_module = module
        self.status_message.emit(f"Selected Module {module}")
        QTimer.singleShot(100, self._request_hw_read)

    def on_channel_changed(self, channel: int):
        self.current_channel = channel
        self.status_message.emit(f"Selected Channel {channel}")
        QTimer.singleShot(100, self._request_hw_read)

    def _request_hw_read(self):
        """Request the app to read hardware params for current module/channel."""
        self.request_read_hardware.emit()

    def read_from_hardware(self):  # Kept for manual "Read HW" button
        self.request_read_hardware.emit()

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
                try:
                    if isinstance(widget, QSpinBox):
                        widget.setValue(int(round(value)))
                    elif isinstance(widget, QDoubleSpinBox):
                        widget.setValue(float(value))
                    elif isinstance(widget, QComboBox):
                        widget.setCurrentText(str(value))
                    elif isinstance(widget, QCheckBox):
                        widget.setChecked(bool(value))
                except (ValueError, TypeError) as e:
                    logger.warning(f"Could not set {param_name}={value}: {e}")

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

                # Load settings to GUI first
                self.set_all_parameters(preset)
                
                # Apply to hardware using parent's hardware manager (if available)
                if hasattr(self.parent(), 'pixie_hw') and self.parent().pixie_hw:
                    try:
                        success = self.parent().pixie_hw.read_from_dictionary(preset)
                        if success:
                            self.status_message.emit(f"Loaded preset from {Path(file_path).name} and applied to hardware")
                        else:
                            self.status_message.emit(f"Loaded preset from {Path(file_path).name} to GUI only (hardware apply failed)")
                    except Exception as hw_error:
                        logger.warning(f"Failed to apply preset to hardware: {hw_error}")
                        self.status_message.emit(f"Loaded preset from {Path(file_path).name} to GUI only (hardware error)")
                else:
                    self.status_message.emit(f"Loaded preset from {Path(file_path).name} to GUI only (no hardware access)")

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

