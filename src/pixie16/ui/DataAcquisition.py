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

    def _enable_mock_mode(self):
        """Enable pixie16 mock mode - add this method to DataAcquisition class"""
        try:
            # Import here to avoid circular imports
            from .. import enable_mock_mode

            enable_mock_mode()
            print("INFO: pixie16.control successfully mocked")
            return True
        except Exception as e:
            print(f"WARNING: Failed to enable mock mode: {e}")
            print("INFO: Continuing without mock - some functions may fail")
            return False

    def _check_dummy_mode(self, app):
        """Check if dummy mode is enabled - add this method to DataAcquisition class"""
        import sys

        return getattr(app, "dummy", False) or "--dummy" in sys.argv

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

        stop_icon = style.standardIcon(QStyle.StandardPixmap.SP_MediaStop)
        self.stop_button = QPushButton()
        self.stop_button.setIcon(stop_icon)
        self.stop_button.setIconSize(QtCore.QSize(24, 24))
        self.stop_button.setFixedSize(QtCore.QSize(40, 40))
        self.stop_button.setToolTip("Stop")

        self.run_time_text = QLabel("Run time (s):")
        self.run_time_text.setFixedWidth(100)
        self.run_time_input = QLineEdit()
        self.run_time_input.setText("60")
        self.run_time_input.setFixedWidth(80)

        self.MCA_set_time_text = QLabel("MCA Time (s):")
        self.MCA_set_time_text.setFixedWidth(100)
        self.MCA_set_time = QLineEdit()
        self.MCA_set_time.setText("0")
        self.MCA_set_time.setFixedWidth(80)

        self.traces_set_time_text = QLabel("Traces Time (s):")
        self.traces_set_time_text.setFixedWidth(100)
        self.traces_set_time = QLineEdit()
        self.traces_set_time.setText("0")
        self.traces_set_time.setFixedWidth(80)

        # self.help_button = QPushButton("Help")
        self.settings_text = QLabel("Settings Mode:")
        self.settings_text.setFixedWidth(100)
        self.settings_modes = QComboBox(self)
        self.settings_modes.addItems(self.modes)
        self.settings_modes.setFixedWidth(100)
        self.settings_modes.currentIndexChanged.connect(self.on_mode_change)

        self.Pixie_reboot = QPushButton("Reboot Pixie")
        self.Pixie_reboot.setFixedWidth(100)

        self.add_main_controls()

        self.actions_layout.addLayout(self.run_layout)
        # self.actions_layout.addLayout(self.diagnostics_layout)

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
            '<span style="color:black;">0:00:10</span>'
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

        if self._check_dummy_mode(self.app):
            self.mock_status_label = QLabel("Mock Status: Ready")
            self.mock_status_label.setStyleSheet(
                "color: blue; font-family: monospace; background-color: #f0f0f0; padding: 5px;"
            )
            self.layout.addWidget(self.mock_status_label)

        self.setLayout(self.layout)

        self.traces_set_time.editingFinished.connect(self.update_trace_time)
        self.MCA_set_time.editingFinished.connect(self.update_mca_time)

    def add_main_controls(self):
        """Add main control widgets to run_layout - override this to customize UI."""
        self.run_layout.addWidget(self.start_button)
        self.run_layout.addWidget(self.stop_button)
        self.run_layout.addWidget(self.run_time_text)
        self.run_layout.addWidget(self.run_time_input)
        self.run_layout.addWidget(self.MCA_set_time_text)
        self.run_layout.addWidget(self.MCA_set_time)
        self.run_layout.addWidget(self.traces_set_time_text)
        self.run_layout.addWidget(self.traces_set_time)
        self.run_layout.addWidget(self.settings_text)
        self.run_layout.addWidget(self.settings_modes)
        self.run_layout.addWidget(self.Pixie_reboot)

        # Add stretch to push everything to the left
        self.run_layout.addStretch()

    def add_extra_buttons(self):
        # self.Pixie_default = QPushButton("Set Pixie default")
        # self.Pixie_default.clicked.connect(self.set_pixie_default)
        # self.diagnostics_layout.addWidget(self.Pixie_default)
        pass

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

        try:
            mca_time = float(self.MCA_set_time.text())
            if mca_time > 0:  # Add MCA if time > 0
                sequence.append("mca")
        except ValueError:
            pass

        try:
            trace_time = float(self.traces_set_time.text())
            if trace_time > 0:  # Add traces if time > 0
                sequence.append("traces")
        except ValueError:
            pass

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

    def clear_table(self):
        self.task_table.clearContents()
        self.task_table.setRowCount(0)
        self.taskid_to_row.clear()

    def on_mode_change(self, idx: int):
        # Clear table state
        self.clear_table()

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
            "cpu percent",
            "memory",
            "queue length",
            "activity",
            "Extra Info",
        ]

        if self.task_table.columnCount() != len(ordered_keys):
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
            cpu_percent = status.get("cpu", "N/A")
            cpu_item = QTableWidgetItem(self.format_value("cpu percent", cpu_percent))
            self.task_table.setItem(row, self.key_to_pos["cpu percent"], cpu_item)

            # Extract and set Memory (Percentage)
            memory_percent = status.get("memory", 0)
            memory_item = QTableWidgetItem(self.format_value("memory", memory_percent))
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
                if key in [
                    "name",
                    "status",
                    "ps",
                    "queue",
                    "activity",
                    "time done",
                    "address_push",
                    "address_pull",
                    "is_start",
                    "is_end",
                    "is_final",
                ]:
                    if key == "time done":
                        self.progress_bar.setValue(int(val))
                    continue

                display_value = self.format_value(key, val)
                extra_info.append(f"{key}={display_value}")

            item = QTableWidgetItem(" ".join(extra_info))
            self.task_table.setItem(row, self.key_to_pos["Extra Info"], item)

        self.update_mock_status()

    def update_mock_status(self):
        """Update mock status display with function calls and call count"""
        if hasattr(self, "mock_status_label"):
            try:
                import pixie16 as px

                if hasattr(px, "is_mock_enabled") and px.is_mock_enabled():
                    mock_instance = px.mock_control.get_mock_instance()
                    call_count = len(mock_instance.call_log)

                    if call_count == 0:
                        status_text = "Mock Status: Active - No calls yet"
                        color = "blue"
                    else:
                        # Get recent function calls (last 3) and their names only
                        recent_calls = (
                            mock_instance.call_log[-3:]
                            if mock_instance.call_log
                            else []
                        )
                        recent_functions = []
                        for call in recent_calls:
                            # Extract just the function name from "pixie16.control.function_name(args)"
                            func_name = call.split(".")[-1].split("(")[0]
                            recent_functions.append(func_name)

                        # Get function call counts for summary
                        call_counts = {}
                        for call in mock_instance.call_log:
                            func_name = call.split(".")[-1].split("(")[0]
                            call_counts[func_name] = call_counts.get(func_name, 0) + 1

                        # Show both total count and recent function calls
                        recent_str = (
                            " → ".join(recent_functions) if recent_functions else "none"
                        )

                        # Show top 2 most called functions with counts
                        top_calls = sorted(
                            call_counts.items(), key=lambda x: x[1], reverse=True
                        )[:2]
                        top_summary = ", ".join(
                            [f"{name}({count})" for name, count in top_calls]
                        )

                        status_text = f"Mock Status: {call_count} calls | Recent: {recent_str} | Top: {top_summary}"
                        color = "green"

                    self.mock_status_label.setText(status_text)
                    self.mock_status_label.setStyleSheet(
                        f"color: {color}; font-family: monospace; background-color: #f0f0f0; padding: 5px; border: 1px solid #ccc;"
                    )
                else:
                    self.mock_status_label.setText("Mock Status: Disabled")
                    self.mock_status_label.setStyleSheet(
                        "color: gray; font-family: monospace; background-color: #f0f0f0; padding: 5px;"
                    )

            except Exception as e:
                self.mock_status_label.setText(f"Mock Status: Error - {str(e)[:50]}")
                self.mock_status_label.setStyleSheet(
                    "color: red; font-family: monospace; background-color: #f0f0f0; padding: 5px;"
                )

    def format_value(self, key, value):
        if isinstance(value, Enum):
            return str(value.value)

        if key == "memory":
            if isinstance(value, float | int):
                mb = float(value) / (1024**2)
                return f"{mb:.1f} MB"

        if key == "cpu percent":
            if isinstance(value, float | int):
                return f"{value:.1f} %"

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

        return str(value)

    def closeEvent(self, event: QtCore.QEvent):
        """Handle App shutdown."""
        self.pipeline.stop()
        event.accept()

    def update_trace_time(self):
        """Update trace_time in LocalSettings when traces_set_time QLineEdit is changed."""
        try:
            value = float(self.traces_set_time.text())
            self.local_settings.trace_time = value
            self.local_settings.traces = value > 0
            if self.pipeline.tasks_active:
                self.pipeline.configure({"trace_time": value, "traces": value > 0})
        except ValueError:
            pass

    def update_mca_time(self):
        """Update mca_time in LocalSettings when MCA_set_time QLineEdit is changed."""
        try:
            value = float(self.MCA_set_time.text())
            self.local_settings.mca_time = value
            self.local_settings.skip_mca = value <= 0
            if self.pipeline.tasks_active:
                self.pipeline.configure({"mca_time": value, "skip_mca": value <= 0})
        except ValueError:
            pass
