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
    QMessageBox,
)
from PyQt6 import QtCore
import pyqtgraph as pg
import psutil

from .. import pipeline

# from ..pipeline.tasks import SetDefaults
from ..config import LocalSettings


class DataAcquisition(QWidget):
    """App to acquire data using Pixie 16."""

    def __init__(self, app):
        super().__init__()

        self.app = app
        self.taskid_to_row = {}
        self.pipeline = pipeline.Pipeline()
        self.local_settings = LocalSettings()

        self.create_layout()
        self.enable_ui_for_new_run()

        self.start_button.clicked.connect(self.start_run)
        self.stop_button.clicked.connect(self.stop_run)
        self.run_time_input.editingFinished.connect(self.set_runtime)

        # Timer to update table and plot
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(250)

        # select a default mode
        self.on_mode_change(self.settings_modes.currentIndex())

    @property
    def modes(self):
        return ["DummyData"]

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

        stop_icon = style.standardIcon(QStyle.StandardPixmap.SP_MediaStop)
        self.stop_button = QPushButton()
        self.stop_button.setIcon(stop_icon)
        self.stop_button.setIconSize(QtCore.QSize(24, 24))
        self.stop_button.setFixedSize(QtCore.QSize(40, 40))
        self.stop_button.setToolTip("Stop")

        self.traces_enabled = QCheckBox("Traces")
        # self.help_button = QPushButton("Help")
        self.settings_text = QLabel("Settings Mode:")
        self.settings_text.setFixedWidth(100)
        self.settings_modes = QComboBox(self)

        self.settings_modes.addItems(self.modes)
        self.settings_modes.currentIndexChanged.connect(self.on_mode_change)

        self.run_layout.addWidget(self.start_button)
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

        self.diagnostics_layout.addWidget(self.mca_group_box)
        self.diagnostics_layout.addWidget(self.traces_group_box)
        self.diagnostics_layout.addWidget(self.Pixie_reboot)
        self.add_extra_buttons()

        self.actions_layout.addLayout(self.run_layout)
        self.actions_layout.addLayout(self.diagnostics_layout)

        self.layout.addLayout(self.actions_layout)

        # Process Table
        self.task_table = QTableWidget(0, 0)
        self.layout.addWidget(QLabel("Task Status"))
        self.layout.addWidget(self.task_table)

        # Plot Area - make overridable
        self.create_plot_area()

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

    def add_extra_buttons(self):
        self.Pixie_default = QPushButton("Set Pixie default")
        self.Pixie_default.clicked.connect(self.set_pixie_default)
        self.diagnostics_layout.addWidget(self.Pixie_default)

    def set_pixie_default(self):
        """Sets reasonable defaults for all parameters in the pixie16"""
        # defaults_task = SetDefaults(self.pipeline.bind_address)
        # defaults_task.do_work(None)
        pass

    def create_plot_area(self):
        """Create plot area - override this method in subclasses."""
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setTitle("Neutron rate (n/s)")
        self.cpu_plot = self.plot_widget.plot(pen="g")
        self.cpu_data = []
        self.time_data = []
        self.time = 0
        self.layout.addWidget(self.plot_widget)

    def enable_ui_for_new_run(self):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.settings_modes.setEnabled(True)

    def enable_ui_for_stopping_run(self):
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.settings_modes.setEnabled(False)

    def get_acquisition_sequence(self):
        """Build acquisition sequence based on enabled checkboxes."""
        sequence = []

        # Add MCA if enabled
        if self.MCA_diagnostics.isChecked():
            sequence.append("mca")

        # Add traces if enabled
        if self.traces_diagnostics.isChecked():
            sequence.append("traces")

        # Always add listmode at the end
        sequence.append("listmode")

        return sequence

    def start_run(self):
        """Start run - enhanced to handle acquisition sequence."""
        # Build the acquisition sequence
        sequence = self.get_acquisition_sequence()
        print(f"Starting run with sequence: {sequence}")

        # Create configuration with sequence and timing
        config = {
            "acquisition_sequence": sequence,
            "runtime": int(self.run_time_input.text()),
        }

        # Add timing for enabled acquisitions
        if "mca" in sequence:
            config["mca_time"] = float(self.MCA_set_time.text())

        if "traces" in sequence:
            config["trace_time"] = float(self.traces_set_time.text())

        # Configure pipeline with acquisition settings
        self.pipeline.configure(config)

        # Start the pipeline
        self.pipeline.start()
        self.enable_ui_for_stopping_run()

    def stop_run(self):
        self.pipeline.stop()
        self.enable_ui_for_new_run()

    def on_mode_change(self, idx: int):
        # Clear table state
        self.task_table.clearContents()
        self.task_table.setRowCount(0)
        self.taskid_to_row.clear()

        text = self.modes[idx]
        print(f"selected {text}")
        match text:
            case "DummyData":
                self.pipeline.init(["DummyData", "PickSingleModule", "ConvertToEvents"])
            case _:
                print("Should not happen")

    def set_runtime(self):
        runtime = self.run_time_input.text()
        try:
            runtime = int(runtime)
        except ValueError:
            try:
                s = dateutil.parser.parse(runtime) - dateutil.parser.parse("0s")
                runtime = int(s.total_seconds())
            except dateutil.parser.ParserError as e:
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Icon.Warning)
                msg.setWindowTitle("Wrong time format")
                msg.setText("Wrong format, e.g. minutes cannot be larger than 59")
                msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                msg.exec()
                return
        self.run_time_input.setText(str(runtime))
        self.progress_bar.setMaximum(runtime)
        self.local_settings.runtime = runtime

        if self.pipeline.tasks_active:
            self.pipeline.configure({"runtime": runtime})

    def update_status(self):
        """Get information from processes."""

        for i in range(10):
            self.pipeline.poll()

        current_time = time.time()
        if not hasattr(self, "last_report_time"):
            self.last_report_time = {}

        ordered_keys = [
            "name",
            "status",
            "cpu",
            "memory",
            "queue length",
            "activity",
            "Extra Info",
        ]

        if self.task_table.columnCount() != len(ordered_keys):  # Add this check
            self.task_table.setColumnCount(len(ordered_keys))
            self.task_table.setHorizontalHeaderLabels(ordered_keys)

            self.key_to_pos = {
                k: i for i, k in enumerate(ordered_keys)
            }  # Store in self for access
            # Set header resize mode (only if header is new or changed)
            header = self.task_table.horizontalHeader()
            header.setSectionResizeMode(
                self.key_to_pos["Extra Info"], QHeaderView.ResizeMode.Stretch
            )
        for t in self.pipeline.tasks_active:
            if t not in self.taskid_to_row:
                row = self.task_table.rowCount()
                self.task_table.insertRow(row)
                self.taskid_to_row[t] = row

        # Update Task table
        for t, status in self.pipeline.reports.items():
            # Check if task is active
            self.last_report_time[t] = current_time

            extra_info = []
            row = self.taskid_to_row[t]  # Get row once per task

            # Handle 'name' and 'status'
            name_value = status.get("name", t)  # t is the task class name
            name_item = QTableWidgetItem(str(name_value))
            self.task_table.setItem(row, self.key_to_pos["name"], name_item)

            status_item = QTableWidgetItem(
                self.format_value("status", status.get("status", "N/A"))
            )
            self.task_table.setItem(row, self.key_to_pos["status"], status_item)

            # Set CPU Percent
            ps_data = status.get("ps", {})
            cpu_percent = ps_data.get("cpu_percent", "N/A")
            cpu_item = QTableWidgetItem(self.format_value("cpu percent", cpu_percent))
            self.task_table.setItem(row, self.key_to_pos["cpu percent"], cpu_item)

            # Extract and set Memory (RSS)
            memory_info = ps_data.get("memory_info", {})
            memory_rss = 0
            if hasattr(memory_info, "rss"):
                memory_rss = memory_info.rss
            memory_item = QTableWidgetItem(self.format_value("memory", memory_rss))
            self.task_table.setItem(row, self.key_to_pos["memory"], memory_item)

            # Set Queue Length
            queue_length = status.get("queue", 0)
            queue_item = QTableWidgetItem(
                self.format_value("queue length", queue_length)
            )
            self.task_table.setItem(row, self.key_to_pos["queue length"], queue_item)

            # Set Activity using tracked time
            activity_item = QTableWidgetItem(
                self.format_value("activity", current_time)
            )
            self.task_table.setItem(row, self.key_to_pos["activity"], activity_item)

            # Other keys for "Extra Info"
            for key, val in status.items():
                if key in ["name", "status", "ps", "queue", "activity", "time done"]:
                    if key == "time done":
                        self.progress_bar.setValue(int(val))
                    continue

                display_value = self.format_value(key, val)
                extra_info.append(f"{key}={display_value}")

            item = QTableWidgetItem(" ".join(extra_info))
            self.task_table.setItem(row, self.key_to_pos["Extra Info"], item)

    def format_value(self, key, value):
        if isinstance(value, Enum):
            return str(value.value)

        if key == "memory":
            if isinstance(value, float | int):
                mb = float(value) / (1024**2)
                return f"{mb:.1f} MB"
            # If it's ps data from task reports, extract memory info
            elif isinstance(value, dict) and "memory_info" in value:
                memory_info = value["memory_info"]
                if memory_info and "rss" in memory_info:
                    mb = memory_info["rss"] / (1024**2)
                    return f"{mb:.1f} MB"

        if key == "cpu percent":
            if isinstance(value, float | int):
                return f"{value:.1f} %"
            # If it's ps data from task reports, extract cpu percent
            elif isinstance(value, dict) and "cpu_percent" in value:
                cpu_val = value["cpu_percent"]
                if cpu_val is not None:
                    return f"{cpu_val:.1f} %"

        if key == "queue length":
            if isinstance(value, int | float):
                return str(int(value))

        if key == "activity":
            if isinstance(value, int | float):
                dt = time.time() - value
                if dt <= 5:
                    return "🟢"
                elif dt <= 60:
                    return "🟡"
                else:
                    return "⚪"

    def closeEvent(self, event: QtCore.QEvent):
        """Handle App shutdown."""
        self.pipeline.stop()
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
            if self.pipeline.tasks_active:
                self.pipeline.configure({"trace_time": value})
        except ValueError:
            pass

    def update_mca_time(self):
        """Update mca_time in LocalSettings when MCA_set_time QLineEdit is changed."""
        try:
            value = float(self.MCA_set_time.text())
            self.local_settings.mca_time = value
            if self.pipeline.tasks_active:
                self.pipeline.configure({"mca_time": value})
        except ValueError:
            pass
