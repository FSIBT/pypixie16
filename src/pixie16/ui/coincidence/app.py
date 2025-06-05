from pathlib import Path
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import (
    QFileDialog,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QPushButton,
)

import pixie16

from ..widgets import BaseApp
from .main_widget import CoincidencePlot

try:
    from ...live.live_data_reader import LiveDataReader, LiveDataSourceInterface

    LIVE_MODE_AVAILABLE = True
except ImportError:
    LIVE_MODE_AVAILABLE = False
    print("Live mode not available - install live dependencies")


class CoincidenceApp(BaseApp):
    """An app that display arbitrary fast trigger positions and all coincidence signals that result.

    It also includes the internal delay from the calculation of the coincidences (added to the validation window).
    """

    def __init__(self, app=None):
        super().__init__(name="Pixie16 Coincidence Visualizer", app=app)

        self.settings_filename = None
        self.settings = None
        self.channels = [0, 1, 2]

        FileButton = QAction(QIcon.fromTheme("document-open"), "Open", self)
        FileButton.setShortcut("Ctrl+O")
        FileButton.setStatusTip("Open settings file")
        FileButton.triggered.connect(lambda x: self.open_file())
        self.file_menu.insertAction(self.file_menu.actions()[0], FileButton)

        self.main_widget = QWidget(self)
        self.vbox = QVBoxLayout()

        self.data = CoincidencePlot(main=self)

        self.info_bar.setText(
            "Change values on the right or click on the graph to change the position of the fast trigger location."
        )

        self.vbox.addLayout(self.data)
        self.vbox.addWidget(self.info_bar)

        self.main_widget.setLayout(self.vbox)
        self.main_widget.setFocus()

        self.setCentralWidget(self.main_widget)

        self.show()

        self.live_reader = None
        self.live_data_source = None
        self.is_live_mode = False

        self._setup_live_controls()

        self.live_update_timer = QTimer()
        self.live_update_timer.timeout.connect(self._update_live_display)

    def _setup_live_controls(self):
        """Add live mode controls to the UI."""
        if not LIVE_MODE_AVAILABLE:
            return

        live_controls = QHBoxLayout()

        self.live_checkbox = QCheckBox("Live Mode")
        self.live_checkbox.toggled.connect(self._toggle_live_mode)
        self.live_checkbox.setEnabled(False)  # Enable after loading settings
        live_controls.addWidget(self.live_checkbox)

        # Update rate spinner
        live_controls.addWidget(QLabel("Update Rate (Hz):"))
        self.update_rate_spinner = QSpinBox()
        self.update_rate_spinner.setRange(1, 50)
        self.update_rate_spinner.setValue(10)
        self.update_rate_spinner.valueChanged.connect(self._set_update_rate)
        live_controls.addWidget(self.update_rate_spinner)

        # Start/Stop acquisition button
        self.acquisition_button = QPushButton("Start Live Acquisition")
        self.acquisition_button.clicked.connect(self._toggle_acquisition)
        self.acquisition_button.setEnabled(False)
        live_controls.addWidget(self.acquisition_button)

        # Status label
        self.live_status_label = QLabel("Live mode not active")
        live_controls.addWidget(self.live_status_label)

        self.vbox.insertLayout(0, live_controls)  # At Top  of layout

    def _toggle_live_mode(self, enabled):
        """Toggle live visualization mode."""
        if not LIVE_MODE_AVAILABLE or not self.live_reader:
            return

        self.is_live_mode = enabled

        if enabled:
            # Start live visualization updates
            update_interval = int(1000 / self.update_rate_spinner.value())
            self.live_update_timer.start(update_interval)
            self.live_status_label.setText("Live visualization active")
        else:
            # Stop live visualization
            self.live_update_timer.stop()
            self.live_status_label.setText("Live visualization stopped")

    def _toggle_acquisition(self):
        """Start or stop live data acquisition."""
        if not self.live_data_source:
            return

        if not self.live_data_source.is_active:
            # Start acquisition - you can modify this to use real hardware
            # For now, we'll simulate with a file
            binary_file = "/home/jo/Downloads/RUN-2025-06-03-00006-20250604T220357Z-1-001/RUN-2025-06-03-00006/binary-data/RUN-2025-06-03-00006-mod0-1748991222-589297-00000.bin"

            if Path(binary_file).exists():
                self.live_data_source.simulate_from_file(
                    binary_file, chunk_size=500, delay_ms=100
                )
                self.acquisition_button.setText("Stop Live Acquisition")
                self.live_checkbox.setEnabled(True)
                self.live_status_label.setText(
                    "Live acquisition started (file simulation)"
                )
            else:
                self.live_status_label.setText("Error: Binary file not found")
        else:
            # Stop acquisition
            self.live_data_source.stop_acquisition()
            self.acquisition_button.setText("Start Live Acquisition")
            self.live_checkbox.setChecked(False)
            self.live_status_label.setText("Live acquisition stopped")

    def _set_update_rate(self, rate_hz):
        """Set the live update rate."""
        if self.live_update_timer.isActive():
            self.live_update_timer.setInterval(int(1000 / rate_hz))

    def _update_live_display(self):
        """Update the display with live data."""
        if not self.is_live_mode or not self.live_reader:
            return

        try:
            # Get live events
            live_events = self.live_reader.get_live_events(count=50)

            if live_events:
                # Convert events to display format
                display_data = self._convert_events_for_display(live_events)

                # Update your existing plot with live data
                if hasattr(self.data, "update_with_live_data"):
                    self.data.update_with_live_data(display_data)

                # Update status
                total_events = sum(len(events) for events in live_events.values())
                channels_active = list(live_events.keys())
                self.live_status_label.setText(
                    f"Live: {total_events} events, channels {channels_active}"
                )

        except Exception as e:
            print(f"Error updating live display: {e}")
            self._toggle_live_mode(False)

    def _convert_events_for_display(self, live_events):
        """Convert live events to format expected by visualizer."""
        display_data = {}

        for channel, events in live_events.items():
            if not events:
                continue

            # Extract the data your visualizer needs
            display_data[f"channel_{channel}"] = {
                "fast_trigger": 1.0 if events else 0.0,  # Simplified - modify as needed
                "coincidence": 0.5,  # You'll need to implement coincidence detection
                "validation": 0.8,  # And validation logic
                "energy": events[-1].energy if events else 0,
                "timestamp": events[-1].timestamp if events else 0,
                "trace": events[-1].trace
                if events and len(events[-1].trace) > 0
                else np.array([]),
            }

        return display_data

    def open_file(self, filename=None) -> None:
        if filename is None or not isinstance(filename, str | Path):
            self.settings_filename, _ = QFileDialog.getOpenFileName(
                self, "Open file", str(self.data_path), "Settings files (*.set)"
            )
        else:
            self.settings_filename = filename

        # check if cancel was hit in QFileDialog
        if self.settings_filename == "":
            self.settings_filename = None
            return

        self.settings_filename = Path(self.settings_filename)
        self.settings = pixie16.read.load_settings(self.settings_filename, 0)

        channels = [i for i, x in enumerate(self.settings.MultiplicityMaskL) if x != 0]
        if len(channels) < 1:
            print("[Warning] no coincidence setup detected, not loading settings")
            return

        # get all channels that are involved
        all_channels = []
        for c in channels:
            tmp = self.settings.MultiplicityMaskL[c]
            tmp = f"{tmp:016b}"
            for i, n in enumerate(reversed(tmp)):
                if int(n):
                    all_channels.append(i)
        self.channels = list(set(all_channels))
        self.data.multiplicity = [
            self.settings.MultiplicityMaskL[c] for c in self.channels
        ]

        self.data.channels = self.channels

        self.data.update_channels()

        for i, c in enumerate(self.channels):
            values = {
                "Trigger Delay": self.settings.FtrigoutDelay[c],
                "Trigger Stretch": self.settings.FastTrigBackLen[c],
                "Validation Delay": self.settings.ExternDelayLen[c],
                "Validation Stretch": self.settings.ChanTrigStretch[c],
            }
            self.data.channel_widgets[i].vstack.value = values

        if LIVE_MODE_AVAILABLE and self.settings is not None:
            # Setup live data reader
            self.live_reader = LiveDataReader()
            self.live_data_source = LiveDataSourceInterface(self.live_reader)

            # Enable live controls
            self.acquisition_button.setEnabled(True)
            self.live_status_label.setText(
                "Live mode ready - click Start Live Acquisition"
            )
