from enum import Enum
import time

import dateutil
from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QVBoxLayout,
    QHeaderView,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QLineEdit,
    QProgressBar,
)
from PyQt6 import QtCore
import pyqtgraph as pg
import psutil

import pixie16 as px


class DataAcquisition(QWidget):
    """App to acquire data using Pixie 16."""

    def __init__(
        self,
    ):
        super().__init__()

        self.taskid_to_row = {}
        self.pipeline = px.pipeline.Pipeline()

        self.create_layout()

        self.on_mode_change(self.settings_modes.currentText())
        self.run_time_input.editingFinished.connect(self.set_runtime)

        # Timer to update table and plot
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(100)

    @property
    def modes(self):
        return ["DummyData"]

    def create_layout(self):
        # Main Layout
        self.layout = QVBoxLayout()

        # Actions Layout: should contain buttons and diagnostics
        self.actions_layout = QVBoxLayout()

        # Run Buttons
        self.run_layout = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.run_time_text = QLabel("Run time :")
        self.run_time_text.setFixedWidth(70)
        self.run_time_input = QLineEdit()
        self.run_time_input.setText("60")
        self.run_time_input.setFixedWidth(60)
        self.pause_button = QPushButton("Pause")
        self.stop_button = QPushButton("Stop")
        self.traces_enabled = QPushButton("Enable Traces")
        # self.help_button = QPushButton("Help")
        self.settings_text = QLabel("Settings Mode:")
        self.settings_text.setFixedWidth(100)
        self.settings_modes = QComboBox(self)

        self.settings_modes.addItems(self.modes)
        self.settings_modes.currentIndexChanged.connect(self.on_mode_change)

        self.run_layout.addWidget(self.start_button)
        self.run_layout.addWidget(self.run_time_text)
        self.run_layout.addWidget(self.run_time_input)
        self.run_layout.addWidget(self.pause_button)
        self.run_layout.addWidget(self.stop_button)
        self.run_layout.addWidget(self.traces_enabled)
        self.run_layout.addWidget(self.settings_text)
        self.run_layout.addWidget(self.settings_modes)

        # Diagnostics tools
        self.diagnostics_layout = QHBoxLayout()
        self.MCA_diagnostics = QPushButton("Diagnostics MCA")
        self.MCA_set_time_text = QLabel("SetMtime :")
        self.MCA_set_time_text.setFixedWidth(60)
        self.MCA_set_time = QLineEdit()
        self.MCA_set_time.setText("30")
        self.MCA_set_time.setFixedWidth(60)

        self.traces_diagnostics = QPushButton("Diagnostics Traces")
        self.traces_set_time_text = QLabel("setTtime :")
        self.traces_set_time_text.setFixedWidth(60)
        self.traces_set_time = QLineEdit()
        self.traces_set_time.setText("5")
        self.traces_set_time.setFixedWidth(60)

        self.Pixie_reboot = QPushButton("Reboot Pixie")
        self.Pixie_default = QPushButton("Set Pixie default")

        self.diagnostics_layout.addWidget(self.MCA_diagnostics)
        self.diagnostics_layout.addWidget(self.MCA_set_time_text)
        self.diagnostics_layout.addWidget(self.MCA_set_time)
        self.diagnostics_layout.addWidget(self.traces_diagnostics)
        self.diagnostics_layout.addWidget(self.traces_set_time_text)
        self.diagnostics_layout.addWidget(self.traces_set_time)
        self.diagnostics_layout.addWidget(self.Pixie_reboot)
        self.diagnostics_layout.addWidget(self.Pixie_default)

        self.actions_layout.addLayout(self.run_layout)
        self.actions_layout.addLayout(self.diagnostics_layout)

        self.layout.addLayout(self.actions_layout)

        # Process Table
        self.task_table = QTableWidget(0, 0)
        self.layout.addWidget(QLabel("Task Status"))
        self.layout.addWidget(self.task_table)

        # Plot Area
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setTitle("Neutron rate (n/s)")  # "Resource Usage Over Time")
        # self.plot_widget.setLabel('left', 'CPU %')
        # self.plot_widget.setLabel('bottom', 'Time (s)')
        self.cpu_plot = self.plot_widget.plot(pen="g")
        self.cpu_data = []
        self.time_data = []
        self.time = 0
        self.layout.addWidget(self.plot_widget)

        # Run status
        self.status_layout = QHBoxLayout()
        self.task_running = QLabel('<span style="color:green;">TRACES</span>')
        self.task_running.setFixedWidth(50)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(20)
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
        # self.layout.addWidget(self.progress_bar)

        self.setLayout(self.layout)

    def on_mode_change(self, text: str):
        print(f"selected {text}")
        match text:
            case "DummyData":
                self.pipeline.create_pipeline(["DummyData", "ConvertToEvents"])
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
                msg = QMessageBox(parent)
                msg.setIcon(QMessageBox.Icon.Warning)
                msg.setWindowTitle("Wrong time format")
                msg.setText("Wrong format, e.g. minutes cannot be larger than 59")
                msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                msg.exec()
                return
        self.run_time_input.setText(str(runtime))
        if self.pipeline.current_pipeline:
            task_id = self.pipeline.current_pipeline[0]
            conf = {"runtime": runtime}
            msg = {"type": px.pipeline.MessageType.CONFIGURE, "config": conf}
            self.pipeline.send_command(task_id, msg)

    def update_status(self):
        """Get information from processes."""

        self.pipeline.poll_once()

        keys = set()
        for t, status in self.pipeline.status.items():
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

        for t in self.pipeline._tasks:
            if t in self.taskid_to_row:
                continue
            row = self.task_table.rowCount()
            self.task_table.insertRow(row)
            self.taskid_to_row[t] = row

        for t, status in self.pipeline.status.items():
            extra_info = []
            for key, val in status.items():
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

        if key == "memory_rss" and isinstance(value, float | int):
            mb = float(value) / (1024**2)
            return f"{mb:.1f} MB"

        if key == "cpu_percent" and isinstance(value, float | int):
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
