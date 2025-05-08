from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QVBoxLayout,
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


class DataAcquisition(QWidget):
    """
    App to acquire data using Pixie 16
    """

    def __init__(
        self,
    ):
        super().__init__()
        self.setWindowTitle("Data Acquisition")

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

        modes = ["API", "API_TRIGGER_ALL", "ATLAS", "ATLAS_TRIGGER_ALL", "FLAT"]
        self.settings_modes.addItems(modes)

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
        self.process_table = QTableWidget(0, 4)
        self.process_table.setHorizontalHeaderLabels(
            ["PID", "CPU %", "Memory MB", "Class Info"]
        )
        self.layout.addWidget(QLabel("Process Status"))
        self.layout.addWidget(self.process_table)

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

        # Timer to update table and plot
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(1000)

    def update_status(self):
        """
        Get information from processes
        """
        self.process_table.setRowCount(0)
        for proc in psutil.process_iter(["pid", "cpu_percent", "memory_info", "name"]):
            row = self.process_table.rowCount()
            self.process_table.insertRow(row)
            self.process_table.setItem(row, 0, QTableWidgetItem(str(proc.info["pid"])))
            self.process_table.setItem(
                row, 1, QTableWidgetItem(str(proc.info["cpu_percent"]))
            )
            # mem_mb = proc.info['memory_info'].rss / (1024 * 1024)
            self.process_table.setItem(row, 2, QTableWidgetItem(f"Test"))
            # Dummy class info (replace with ZMQ query)
            self.process_table.setItem(row, 3, QTableWidgetItem(proc.info["name"]))
            # Simulate plot update
        cpu_total = psutil.cpu_percent()
        self.time += 1
        self.cpu_data.append(cpu_total)
        self.time_data.append(self.time)
        self.cpu_plot.setData(self.time_data[-100:], self.cpu_data[-100:])
