"""
CoincidenceApp with live data visualization.
This is your existing app with live mode capabilities added.
"""

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
import numpy as np

import pixie16
from ..widgets import BaseApp
from .main_widget import CoincidencePlot

# Import live functionality
try:
    from ...live.live_data_reader import LiveDataReader, LiveDataSourceInterface

    LIVE_MODE_AVAILABLE = True
except ImportError:
    LIVE_MODE_AVAILABLE = False
    print("Live mode not available")


class LiveCoincidenceApp(BaseApp):
    """Enhanced CoincidenceApp with live data visualization."""

    def __init__(self, app=None):
        super().__init__(name="Pixie16 Live Coincidence Visualizer", app=app)

        self.settings_filename = None
        self.settings = None
        self.channels = [0, 1, 2]

        # Live mode components
        self.live_reader = None
        self.live_data_source = None
        self.is_live_mode = False

        self._setup_file_menu()
        self._setup_main_widget()
        self._setup_live_controls()
        self._setup_timers()

        self.show()

    def _setup_file_menu(self):
        """Setup file menu."""
        FileButton = QAction(QIcon.fromTheme("document-open"), "Open", self)
        FileButton.setShortcut("Ctrl+O")
        FileButton.setStatusTip("Open settings file")
        FileButton.triggered.connect(lambda x: self.open_file())
        self.file_menu.insertAction(self.file_menu.actions()[0], FileButton)

    def _setup_main_widget(self):
        """Setup main widget layout."""
        self.main_widget = QWidget(self)
        self.vbox = QVBoxLayout()

        self.data = CoincidencePlot(main=self)

        self.info_bar.setText(
            "Load a settings file, then enable live mode to see real-time data."
        )

        self.vbox.addLayout(self.data)
        self.vbox.addWidget(self.info_bar)

        self.main_widget.setLayout(self.vbox)
        self.main_widget.setFocus()
        self.setCentralWidget(self.main_widget)

    def _setup_live_controls(self):
        """Add live mode controls."""
        if not LIVE_MODE_AVAILABLE:
            return

        # Live controls layout
        live_controls = QHBoxLayout()

        # Live mode checkbox
        self.live_checkbox = QCheckBox("Live Mode")
        self.live_checkbox.toggled.connect(self._toggle_live_mode)
        self.live_checkbox.setEnabled(False)
        live_controls.addWidget(self.live_checkbox)

        # Update rate control
        live_controls.addWidget(QLabel("Rate (Hz):"))
        self.update_rate_spinner = QSpinBox()
        self.update_rate_spinner.setRange(1, 50)
        self.update_rate_spinner.setValue(10)
        self.update_rate_spinner.valueChanged.connect(self._set_update_rate)
        live_controls.addWidget(self.update_rate_spinner)

        # Acquisition button
        self.acquisition_button = QPushButton("Start Live")
        self.acquisition_button.clicked.connect(self._toggle_acquisition)
        self.acquisition_button.setEnabled(False)
        live_controls.addWidget(self.acquisition_button)

        # Status label
        self.live_status_label = QLabel("Load settings first")
        live_controls.addWidget(self.live_status_label)

        live_controls.addStretch()

        # Insert at top of layout
        self.vbox.insertLayout(0, live_controls)

    def _setup_timers(self):
        """Setup timers for live updates."""
        self.live_update_timer = QTimer()
        self.live_update_timer.timeout.connect(self._update_live_display)

    def open_file(self, filename=None) -> None:
        """Open settings file and setup live mode."""
        if filename is None or not isinstance(filename, str | Path):
            self.settings_filename, _ = QFileDialog.getOpenFileName(
                self, "Open file", str(self.data_path), "Settings files (*.set)"
            )
        else:
            self.settings_filename = filename

        if self.settings_filename == "":
            self.settings_filename = None
            return

        self.settings_filename = Path(self.settings_filename)

        try:
            self.settings = pixie16.read.load_settings(self.settings_filename, 0)

            channels = [
                i for i, x in enumerate(self.settings.MultiplicityMaskL) if x != 0
            ]
            if len(channels) < 1:
                self.info_bar.setText("[Warning] No coincidence setup detected")
                return

            # Get all involved channels
            all_channels = []
            for c in channels:
                tmp = self.settings.MultiplicityMaskL[c]
                tmp = f"{tmp:016b}"
                for i, n in enumerate(reversed(tmp)):
                    if int(n):
                        all_channels.append(i)
            self.channels = list(set(all_channels))

            # Update UI components
            self.data.multiplicity = [
                self.settings.MultiplicityMaskL[c] for c in self.channels
            ]
            self.data.channels = self.channels
            self.data.update_channels()

            # Setup live mode if available
            if LIVE_MODE_AVAILABLE:
                self.live_reader = LiveDataReader()
                self.live_data_source = LiveDataSourceInterface(self.live_reader)

                # Add event callback for monitoring
                self.live_reader.add_event_callback(self._on_new_event)

                self.acquisition_button.setEnabled(True)
                self.live_status_label.setText("Ready for live mode")

            # Load settings into channel widgets
            for i, c in enumerate(self.channels):
                if hasattr(self.data, "channel_widgets") and i < len(
                    self.data.channel_widgets
                ):
                    values = {
                        "Trigger Delay": self.settings.FtrigoutDelay[c],
                        "Trigger Stretch": self.settings.FastTrigBackLen[c],
                        "Validation Delay": self.settings.ExternDelayLen[c],
                        "Validation Stretch": self.settings.ChanTrigStretch[c],
                    }
                    self.data.channel_widgets[i].vstack.value = values

            self.info_bar.setText(
                f"Settings loaded. Channels: {self.channels}. Ready for live mode!"
            )

        except Exception as e:
            self.info_bar.setText(f"Error loading settings: {str(e)}")

    def _toggle_acquisition(self):
        """Start or stop live data acquisition."""
        if not self.live_data_source:
            return

        if not self.live_data_source.is_active:
            # Start acquisition using your test file
            binary_file = "/home/jo/Downloads/RUN-2025-06-03-00006-20250604T220357Z-1-001/RUN-2025-06-03-00006/binary-data/RUN-2025-06-03-00006-mod0-1748991222-589297-00000.bin"

            if Path(binary_file).exists():
                self.live_data_source.simulate_from_file(
                    binary_file, chunk_size=500, delay_ms=50
                )
                self.acquisition_button.setText("Stop Live")
                self.live_checkbox.setEnabled(True)
                self.live_status_label.setText("Live acquisition active")
            else:
                self.live_status_label.setText("Error: Test file not found")
        else:
            self.live_data_source.stop_acquisition()
            self.acquisition_button.setText("Start Live")
            self.live_checkbox.setChecked(False)
            self.live_status_label.setText("Live acquisition stopped")

    def _toggle_live_mode(self, enabled):
        """Toggle live visualization."""
        if not LIVE_MODE_AVAILABLE or not self.live_reader:
            return

        self.is_live_mode = enabled

        if enabled:
            update_interval = int(1000 / self.update_rate_spinner.value())
            self.live_update_timer.start(update_interval)
            self.live_status_label.setText("Live visualization ON")
        else:
            self.live_update_timer.stop()
            self.live_status_label.setText("Live visualization OFF")

    def _set_update_rate(self, rate_hz):
        """Set the live update rate."""
        if self.live_update_timer.isActive():
            self.live_update_timer.setInterval(int(1000 / rate_hz))

    def _on_new_event(self, event):
        """Callback for new events (for monitoring)."""
        # This gets called for every event - you can add logging here
        pass

    def _update_live_display(self):
        """Update the display with live data."""
        if not self.is_live_mode or not self.live_reader:
            return

        try:
            # Get recent events
            live_events = self.live_reader.get_live_events(count=20)

            if live_events:
                # Get statistics
                stats = self.live_reader.get_statistics()

                # Update status
                total_events = stats.get("events_processed", 0)
                rate = stats.get("processing_rate", 0)
                channels_active = list(live_events.keys())

                self.live_status_label.setText(
                    f"Live: {total_events} events @ {rate:.1f} Hz, Ch: {channels_active}"
                )

                # Convert to display format
                display_data = self._convert_events_for_display(live_events)

                # Update plot if it supports live data
                if hasattr(self.data, "update_with_live_data"):
                    self.data.update_with_live_data(display_data)

        except Exception as e:
            print(f"Error updating live display: {e}")
            self._toggle_live_mode(False)

    def _convert_events_for_display(self, live_events):
        """Convert live events to display format."""
        display_data = {}

        for channel, events in live_events.items():
            if not events:
                continue

            # Get the most recent event
            latest_event = events[-1]

            # Create data format expected by visualizer
            display_data[f"channel_{channel}"] = {
                "fast_trigger": 1.0,  # Indicate trigger occurred
                "coincidence": self._check_coincidence(
                    channel, latest_event, live_events
                ),
                "validation": 0.8,  # Placeholder
                "energy": latest_event.energy,
                "timestamp": latest_event.timestamp,
                "trace": np.array(latest_event.trace)
                if len(latest_event.trace) > 0
                else np.array([]),
            }

        return display_data

    def _check_coincidence(self, channel, event, all_events):
        """Simple coincidence check."""
        # Look for events in other channels within time window
        time_window = 1000  # 1 microsecond

        for other_ch, other_events in all_events.items():
            if other_ch == channel:
                continue

            for other_event in other_events:
                if abs(other_event.timestamp - event.timestamp) <= time_window:
                    return 1.0  # Coincidence found

        return 0.0  # No coincidence

    def closeEvent(self, event):
        """Cleanup when closing."""
        if self.live_data_source:
            self.live_data_source.stop_acquisition()
        super().closeEvent(event)


# Convenience function to run the live app
def run_live_coincidence_app():
    """Run the live coincidence visualizer."""
    from PyQt6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    window = LiveCoincidenceApp()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_live_coincidence_app()
