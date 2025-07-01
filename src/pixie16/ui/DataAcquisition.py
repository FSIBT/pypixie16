from enum import Enum
import time

import dateutil
from PyQt6.QtWidgets import (
    QWidget,
    QCheckBox,
    QLabel,
    QVBoxLayout,
    QHeaderView,
    QHBoxLayout,
    QGroupBox,
    QSizePolicy,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QLineEdit,
    QStyle,
    QProgressBar,
)
from PyQt6 import QtCore
# import pyqtgraph as pg
# import psutil

from .. import pipeline
from ..config import LocalSettings


class DataAcquisition(QWidget):
    """App to acquire data using Pixie 16."""

    def __init__(self, app):
        super().__init__()

        self.app = app
        self.taskid_to_row = {}
        self.pipeline = pipeline.Pipeline()
        self.local_settings = LocalSettings()
        
        # Current pipeline configuration state
        self.current_pipeline_config = {}
        self.current_run_number = 1

        self.create_layout()

        self.start_button.clicked.connect(self.start_run)
        self.pause_button.clicked.connect(self.pipeline.pause)
        self.stop_button.clicked.connect(self.pipeline.stop)
        self.run_time_input.editingFinished.connect(self.set_runtime)

        # Timer to update table and plot
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(100)

        # select a default mode
        self.on_mode_change(self.settings_modes.currentIndex())

    @property
    def modes(self):
        """Override this in subclasses to provide different modes."""
        return ["DummyData"]
    
    def get_default_pipeline_for_mode(self, mode_name):
        """Override this in subclasses to provide mode-specific pipelines."""
        return ["DummyData", "PickSingleModule", "ConvertToEvents"]
    
    def get_default_config_for_mode(self, mode_name):
        """Override this in subclasses to provide mode-specific configuration."""
        return {
            "mode": mode_name,
            "detector_mode": mode_name,
            "runtime": int(self.run_time_input.text()),
            "modules": [2],
            "channels": [(0, i) for i in range(16)],
        }
    
    def configure_pipeline_for_mode(self, mode_name):
        """Configure pipeline for the selected mode. Override in subclasses."""
        pipeline_tasks = self.get_default_pipeline_for_mode(mode_name)
        self.pipeline.init(pipeline_tasks)
        
        # Get base configuration
        config = self.get_default_config_for_mode(mode_name)
        
        # Update with current settings
        config.update(self.local_settings.to_dict())
        
        # Store current config and configure pipeline
        self.current_pipeline_config = config
        self.pipeline.configure(config)
    
    def get_acquisition_sequence(self):
        """Get the sequence of acquisition types to run. Override in subclasses."""
        sequence = []
        
        # Check if MCA is enabled
        if hasattr(self, 'MCA_diagnostics') and self.MCA_diagnostics.isChecked():
            sequence.append("mca")
        elif hasattr(self, 'mca_enabled') and self.mca_enabled.isChecked():
            sequence.append("mca")
            
        # Check if traces are enabled  
        if self.traces_enabled.isChecked():
            sequence.append("traces")
            
        # Always include listmode
        sequence.append("listmode")
        
        return sequence

    def create_layout(self):
        style = self.app.style()

        # Main Layout
        self.layout = QVBoxLayout()

        # Actions Layout: should contain buttons and diagnostics
        self.actions_layout = QVBoxLayout()

        # Run Buttons
        self.run_layout = QHBoxLayout()

        play_icon = style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        self.start_button = QPushButton()
        self.start_button.setIcon(play_icon)
        self.start_button.setIconSize(QtCore.QSize(24, 24))
        self.start_button.setFixedSize(QtCore.QSize(40, 40))
        self.start_button.setToolTip("Play")

        self.run_time_text = QLabel("Run time :")
        self.run_time_text.setFixedWidth(70)
        self.run_time_input = QLineEdit()
        self.run_time_input.setText("60")
        self.run_time_input.setFixedWidth(60)

        pause_icon = style.standardIcon(QStyle.StandardPixmap.SP_MediaPause)
        self.pause_button = QPushButton()
        self.pause_button.setIcon(pause_icon)
        self.pause_button.setIconSize(QtCore.QSize(24, 24))
        self.pause_button.setFixedSize(QtCore.QSize(40, 40))
        self.pause_button.setToolTip("Pause")

        stop_icon = style.standardIcon(QStyle.StandardPixmap.SP_MediaStop)
        self.stop_button = QPushButton()
        self.stop_button.setIcon(stop_icon)
        self.stop_button.setIconSize(QtCore.QSize(24, 24))
        self.stop_button.setFixedSize(QtCore.QSize(40, 40))
        self.stop_button.setToolTip("Stop")

        self.traces_enabled = QCheckBox("Traces")
        self.settings_text = QLabel("Settings Mode:")
        self.settings_text.setFixedWidth(100)
        self.settings_modes = QComboBox(self)

        self.settings_modes.addItems(self.modes)
        self.settings_modes.currentIndexChanged.connect(self.on_mode_change)

        self.run_layout.addWidget(self.start_button)
        self.run_layout.addWidget(self.pause_button)
        self.run_layout.addWidget(self.stop_button)
        self.run_layout.addWidget(self.run_time_text)
        self.run_layout.addWidget(self.run_time_input)
        self.run_layout.addWidget(self.traces_enabled)
        self.run_layout.addWidget(self.settings_text)
        self.run_layout.addWidget(self.settings_modes)

        # Diagnostics tools
        self.mca_group_box = QGroupBox("MCA Diagnostics")
        self.mca_layout = QHBoxLayout()
        self.mca_group_box.setLayout(self.mca_layout)
        self.mca_group_box.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum
        )

        self.diagnostics_layout = QHBoxLayout()
        self.MCA_diagnostics = QCheckBox("Enable")
        self.MCA_set_time_text = QLabel("Time [s]:")
        self.MCA_set_time = QLineEdit()
        self.MCA_set_time.setText("30")

        self.MCA_diagnostics.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )

        self.MCA_set_time_text.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )

        self.MCA_set_time.setFixedWidth(60)
        self.MCA_set_time.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )

        self.mca_layout.addWidget(self.MCA_diagnostics)
        self.mca_layout.addWidget(self.MCA_set_time_text)
        self.mca_layout.addWidget(self.MCA_set_time)

        self.traces_group_box = QGroupBox("Traces Diagnostics")
        self.traces_layout = QHBoxLayout()
        self.traces_group_box.setLayout(self.traces_layout)
        self.traces_group_box.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum
        )

        self.traces_diagnostics = QCheckBox("Enable")
        self.traces_set_time_text = QLabel("Time[s]:")
        self.traces_set_time = QLineEdit()
        self.traces_set_time.setText("5")

        self.traces_diagnostics.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )

        self.traces_set_time_text.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )

        self.traces_set_time.setFixedWidth(60)
        self.traces_set_time.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )

        self.traces_layout.addWidget(self.traces_diagnostics)
        self.traces_layout.addWidget(self.traces_set_time_text)
        self.traces_layout.addWidget(self.traces_set_time)

        self.Pixie_reboot = QPushButton("Reboot Pixie")
        self.Pixie_default = QPushButton("Set Pixie default")
        self.Pixie_default.clicked.connect(self.set_pixie_default)

        self.diagnostics_layout.addWidget(self.mca_group_box)
        self.diagnostics_layout.addWidget(self.traces_group_box)
        self.diagnostics_layout.addWidget(self.Pixie_reboot)
        self.diagnostics_layout.addWidget(self.Pixie_default)

        self.actions_layout.addLayout(self.run_layout)
        self.actions_layout.addLayout(self.diagnostics_layout)

        self.layout.addLayout(self.actions_layout)

        # Process Table
        self.task_table = QTableWidget(0, 0)
        self.layout.addWidget(QLabel("Task Status"))
        self.layout.addWidget(self.task_table)

        # # Plot Area
        # self.plot_widget = pg.PlotWidget()
        # self.plot_widget.setTitle("Neutron rate (n/s)")
        # self.cpu_plot = self.plot_widget.plot(pen="g")
        # self.cpu_data = []
        # self.time_data = []
        # self.time = 0
        # self.layout.addWidget(self.plot_widget)

        # Run status
        self.status_layout = QHBoxLayout()
        self.task_running = QLabel('<span style="color:green;">TRACES</span>')
        self.task_running.setFixedWidth(50)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(800)
        self.run_time_progress_text = QLabel(
            '<span style="color:yellow;">0:00:10</span>'
        )
        self.run_time_progress_text.setFixedWidth(50)
        self.run_time_left_text = QLabel('<span style="color:purple;">0:02:10</span>')
        self.run_time_left_text.setFixedWidth(50)
        self.current_task_status = QLabel(
            "Current task status (i.e. Setting up process pipeline)"
        )

        self.status_layout.addWidget(self.task_running)
        self.status_layout.addWidget(self.progress_bar)
        self.status_layout.addWidget(self.run_time_progress_text)
        self.status_layout.addWidget(self.run_time_left_text)
        self.status_layout.addWidget(self.current_task_status)

        self.layout.addLayout(self.status_layout)

        self.setLayout(self.layout)

        self.MCA_diagnostics.stateChanged.connect(self.update_skip_mca)
        self.traces_enabled.stateChanged.connect(self.update_traces_setting)
        self.traces_set_time.editingFinished.connect(self.update_trace_time)
        self.MCA_set_time.editingFinished.connect(self.update_mca_time)

    def start_run(self):
        """Start a run with the configured acquisition sequence."""
        # Get the acquisition sequence
        sequence = self.get_acquisition_sequence()
        
        # Build run configuration
        run_config = self.current_pipeline_config.copy()
        run_config.update({
            "runtime": int(self.run_time_input.text()),
            "run_nr": self.get_next_run_number(),
            "acquisition_sequence": sequence,
        })
        
        # Add acquisition-specific settings
        if "mca" in sequence:
            try:
                run_config["mca_time"] = float(self.MCA_set_time.text())
            except (ValueError, AttributeError):
                run_config["mca_time"] = 30
        
        if "traces" in sequence:
            try:
                run_config["trace_time"] = float(self.traces_set_time.text())
            except (ValueError, AttributeError):
                run_config["trace_time"] = 5
        
        print(f"Starting run with config: {run_config}")
        
        # Configure and start pipeline
        self.pipeline.configure(run_config)
        self.pipeline.start()

    def set_pixie_default(self):
        """Sets reasonable defaults for all parameters in the pixie16"""
        # Override in subclasses to provide actual implementation
        pass

    def on_mode_change(self, idx: int):
        """Handle mode changes - calls configure_pipeline_for_mode."""
        if idx < 0 or idx >= len(self.modes):
            return
            
        mode_name = self.modes[idx]
        print(f"Selected mode: {mode_name}")
        
        try:
            self.configure_pipeline_for_mode(mode_name)
            print(f"Successfully configured pipeline for {mode_name}")
        except Exception as e:
            print(f"Error configuring pipeline for {mode_name}: {e}")
            # Could fall back to DummyData or show error message

    def get_next_run_number(self):
        """Get the next run number and increment."""
        current = self.current_run_number
        self.current_run_number += 1
        return current

    def set_runtime(self):
        runtime = self.run_time_input.text()
        try:
            runtime = int(runtime)
        except ValueError:
            try:
                s = dateutil.parser.parse(runtime) - dateutil.parser.parse("0s")
                runtime = int(s.total_seconds())
            except dateutil.parser.ParserError as e:
                msg = QMessageBox(parent)
                msg.setIcon(QMessageBox.Icon.Warning)
                msg.setWindowTitle("Wrong time format")
                msg.setText("Wrong format, e.g. minutes cannot be larger than 59")
                msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                msg.exec()
                return
        self.run_time_input.setText(str(runtime))
        self.progress_bar.setMaximum(runtime)
        self.local_settings.runtime = runtime

        if self.pipeline.current_pipeline:
            task_id = self.pipeline.current_pipeline[0]
            conf = {"runtime": runtime}
            msg = {"type": pipeline.MessageType.CONFIGURE, "config": conf}
            self.pipeline.send_command(task_id, msg)

    def update_status(self):
        """Get information from processes."""

        for i in range(10):
            self.pipeline.poll()

        keys = set()
        for t, status in self.pipeline.reports.items():
            keys.update(status.keys())

        ordered_keys = [
            "name",
            "status",
            "cpu percent",
            "memory",
            "queue length",
            "activity",
            "Extra Info",
        ]

        self.task_table.setColumnCount(len(ordered_keys))
        self.task_table.setHorizontalHeaderLabels(ordered_keys)

        key_to_pos = {k: i for i, k in enumerate(ordered_keys)}
        header = self.task_table.horizontalHeader()
        header.setSectionResizeMode(
            key_to_pos["Extra Info"], QHeaderView.ResizeMode.Stretch
        )

        for t in self.pipeline.tasks_active:
            if t in self.taskid_to_row:
                continue
            row = self.task_table.rowCount()
            self.task_table.insertRow(row)
            self.taskid_to_row[t] = row

        for t, status in self.pipeline.reports.items():
            extra_info = []
            for key, val in status.items():
                if key == "time done":
                    self.progress_bar.setValue(int(val))
                    continue
                display_value = self.format_value(key, val)
                if key in ordered_keys:
                    item = QTableWidgetItem(display_value)
                    row = self.taskid_to_row[t]
                    self.task_table.setItem(row, key_to_pos[key], item)
                else:
                    extra_info.append(f"{key}={display_value}")
            item = QTableWidgetItem(" ".join(extra_info))
            row = self.taskid_to_row[t]
            self.task_table.setItem(row, key_to_pos["Extra Info"], item)

    def format_value(self, key, value):
        if isinstance(value, Enum):
            return str(value.value)

        if key == "memory" and isinstance(value, float | int):
            mb = float(value) / (1024**2)
            return f"{mb:.1f} MB"

        if key == "cpu percent" and isinstance(value, float | int):
            return f"{value:.1f} %"

        if key == "activity":
            dt = time.time() - value
            if dt <= 5:
                return "🟢"
            elif dt <= 60:
                return "🟡"
            else:
                return "⚪"

        return str(value)

    def closeEvent(self, event: QtCore.QEvent):
        """Handle App shutdown."""
        self.pipeline.end_tasks()
        self.pipeline.close()
        event.accept()

    def update_skip_mca(self, state):
        """Update skip_mca in LocalSettings when MCA_diagnostics checkbox is toggled."""
        self.local_settings.skip_mca = not bool(self.MCA_diagnostics.isChecked())

    def update_traces_setting(self, state):
        """Update traces in LocalSettings when traces_enabled checkbox is toggled."""
        self.local_settings.traces = bool(self.traces_enabled.isChecked())

    def update_trace_time(self):
        """Update trace_time in LocalSettings when traces_set_time QLineEdit is changed."""
        try:
            value = float(self.traces_set_time.text())
            self.local_settings.trace_time = value
            if self.pipeline.current_pipeline and len(self.pipeline.current_pipeline) > 0:
                task_id = self.pipeline.current_pipeline[0]
                conf = {"trace_time": value}
                msg = {"type": pipeline.MessageType.CONFIGURE, "config": conf}
                self.pipeline.send_command(task_id, msg)
        except ValueError:
            pass

    def update_mca_time(self):
        """Update mca_time in LocalSettings when MCA_set_time QLineEdit is changed."""
        try:
            value = float(self.MCA_set_time.text())
            self.local_settings.mca_time = value
            if self.pipeline.current_pipeline and len(self.pipeline.current_pipeline) > 0:
                task_id = self.pipeline.current_pipeline[0]
                conf = {"mca_time": value}
                msg = {"type": pipeline.MessageType.CONFIGURE, "config": conf}
                self.pipeline.send_command(task_id, msg)
        except ValueError:
            pass