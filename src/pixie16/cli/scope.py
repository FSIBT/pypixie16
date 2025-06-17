"""
Pixie16 Scope - Real-time visualization and parameter control for PIXIE-16 modules

Usage:
  pixie16-scope [--dummy] [--module <N>] [--channels <list>]

Options:
  --dummy           Use dummy data for testing without hardware
  --module <N>      Specify module number [default: 2]
  --channels <list> Specify channels to display [default: 0,1,2,3,4,5,6,7]
"""

import sys
import os
import time
import threading
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QMessageBox,
    QGroupBox,
    QScrollArea,
    QPushButton,
    QLabel,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QCheckBox,
)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

import numpy as np

try:
    import pyqtgraph as pg
except ImportError:
    print("Warning: pyqtgraph not found. Install with: pip install pyqtgraph")
    pg = None

try:
    from docopt import docopt
except ImportError:
    print("Error: docopt not found. Install with: pip install docopt")
    sys.exit(1)

try:
    import pixie16 as px
    from pixie16.live.live_data_reader import LiveDataReader, LiveDataSourceInterface
except ImportError as e:
    print(f"Error importing pixie16 modules: {e}")
    print("Make sure pypixie16 is properly installed")
    sys.exit(1)

from pixie16.ui.widgets import BaseApp
from pixie16.ui.spectrum_plotter import ContinuousSpectrumPlotter
from pixie16.ui.channel_controls import ChannelDisplayControls
from pixie16.ui.parameter_controls import ParameterControls

import logging

logger = logging.getLogger(__name__)


class PixieScopeApp(BaseApp):
    def __init__(self, dummy_mode=False, module_number=2, channels=[(0, 4), (0, 9)]):
        super().__init__()

        if hasattr(self, "setWindowTitle"):
            self.setWindowTitle("Pixie16 Scope")

        self.dummy_mode = dummy_mode
        self.module_number = 2
        self.channels = [(0, 4), (0, 9)]  # or list(range(8))
        print("I am printing channel type:", type(self.channels))
        self.live_reader = None
        self.data_source = None
        self.is_acquiring = False
        self.auto_started = False

        self.settings = {
            "channels": self.channels,
            "TRACE_LENGTH": 1.0,
            "TRIGGER_THRESHOLD": 100,
            "TRACE_DELAY": 0.2,
            "MultiplicityMaskL": 0.0,
            "MultiplicityMaskH": 0.0,
            "TRIGGER_RISETIME": 0.02,
            "TRIGGER_FLATTOP": 0.02,
            "FAST_FILTER_RANGE": 0,
            "MODULE_CSRB": 0,
            "BackplanePullup": True,
            "TrigConfig0": 0,
            "TrigConfig1": 0,
            "TrigConfig2": 0,
            "TrigConfig3": 0,
            "Polarity": "positive",
            "CaptureTrace": True,
            "EnableChannelVal": False,
            "EnableCFD": False,
        }

        self.raw_settings = {
            "channels": self.channels,
            "PeakSample": [
                4,
                8,
                61,
                110,
                113,
                105,
                105,
                4,
                4,
                4,
                4,
            ],  # Atlas 4 was 100 or 118
        }

        self.last_event_count = 0
        self.last_update_time = time.time()

        self.init_ui()
        self.init_pixie16()
        self.plot_mca()
        self.setup_timers()

    def plot_mca(self):
        """Using pixie control's tale_MCA_spectra to collect data."""
        print(self.raw_settings)
        px.control.change_raw_setting_from_dict(self.raw_settings, call_pixie=True)
        histogram = px.control.take_MCA_spectra(
            channels=self.channels, duration=10, verbose=True
        )
        print(histogram, type(histogram))

    def init_ui(self):
        self.setGeometry(100, 100, 1600, 1000)
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        main_layout = QHBoxLayout()

        left_layout = QVBoxLayout()

        control_panel = self.create_control_panel()
        left_layout.addWidget(control_panel)

        self.spectrum_tab = ContinuousSpectrumPlotter(
            app=None,
            instrument_name="pixie16",
            display_name="PIXIE-16 Energy Spectra",
            channels=self.channels,
            energy_range=(0, 3000),
            bins=1000,
        )

        left_layout.addWidget(self.spectrum_tab)

        right_layout = QVBoxLayout()

        self.channel_controls = ChannelDisplayControls(
            channels=self.channels, title="Channel Display"
        )
        self.channel_controls.channels_changed.connect(self.update_display_channels)
        right_layout.addWidget(self.channel_controls)

        self.parameter_controls = ParameterControls(
            initial_module=self.module_number, title="PIXIE-16 Parameters"
        )
        self.parameter_controls.parameter_changed.connect(self.handle_parameter_change)
        self.parameter_controls.apply_all_requested.connect(
            self.handle_apply_all_parameters
        )
        self.parameter_controls.status_message.connect(self.update_info_bar)

        right_layout.addWidget(self.parameter_controls)

        right_layout.addStretch()

        left_widget = QWidget()
        left_widget.setLayout(left_layout)

        right_widget = QWidget()
        right_widget.setLayout(right_layout)
        right_widget.setMaximumWidth(450)
        right_widget.setMinimumWidth(450)

        main_layout.addWidget(left_widget, stretch=1)
        main_layout.addWidget(right_widget)

        bottom_layout = QVBoxLayout()
        bottom_layout.addLayout(main_layout)

        self.info_bar = QLabel("Initializing scope...")
        bottom_layout.addWidget(self.info_bar)

        main_widget.setLayout(bottom_layout)

        QTimer.singleShot(1000, self.auto_start_acquisition)

    def update_display_channels(self, selected_channels):
        print(f"Scope: channels changed to {selected_channels}")

        if hasattr(self.spectrum_tab, "set_display_channels"):
            self.spectrum_tab.set_display_channels(selected_channels)
            print(f"Called set_display_channels with {selected_channels}")
        else:
            print("ERROR: spectrum_tab doesn't have set_display_channels method")

        if selected_channels:
            self.info_bar.setText(
                f"Displaying {len(selected_channels)} channels: {selected_channels}"
            )
        else:
            self.info_bar.setText("No channels selected for display")

    def create_control_panel(self):
        group = QGroupBox("Scope Controls")
        layout = QHBoxLayout()

        self.clear_btn = QPushButton("Clear Spectra")
        self.clear_btn.clicked.connect(self.clear_data)

        self.save_btn = QPushButton("Save Data")
        self.save_btn.clicked.connect(self.save_data)

        layout.addWidget(self.clear_btn)
        layout.addWidget(self.save_btn)

        self.status_label = QLabel("Status: Initializing...")
        self.rate_label = QLabel("Rate: 0 Hz")
        self.events_label = QLabel("Events: 0")

        layout.addWidget(self.status_label)
        layout.addWidget(self.rate_label)
        layout.addWidget(self.events_label)

        layout.addStretch()
        group.setLayout(layout)
        return group

    def handle_parameter_change(self, param_name, value, module, channel):
        print(
            f"DEBUG: Handling parameter change: {param_name} = {value} for M{module}:Ch{channel}"
        )
        try:
            if not self.dummy_mode:
                import pixie16 as px

                px.control.set_channel_parameter(param_name, value, module, channel)
                self.info_bar.setText(
                    f"Set {param_name} = {value} on M{module}:Ch{channel}"
                )
                print(f"SUCCESS: Set {param_name} = {value} on hardware")
            else:
                self.info_bar.setText(
                    f"Dummy: {param_name} = {value} on M{module}:Ch{channel}"
                )
                print(
                    f"DUMMY MODE: Would set {param_name} = {value} on M{module}:Ch{channel}"
                )
        except Exception as e:
            error_msg = f"Error setting {param_name}: {e}"
            self.info_bar.setText(error_msg)
            print(f"ERROR: {error_msg}")

    def handle_apply_all_parameters(self, params_dict, module, channel):
        try:
            if not self.dummy_mode:
                import pixie16 as px

                for param_name, value in params_dict.items():
                    px.control.set_channel_parameter(param_name, value, module, channel)

                success_msg = f"Applied all {len(params_dict)} parameters to Module {module}, Channel {channel}"
                self.info_bar.setText(success_msg)
                logger.info(success_msg)
            else:
                self.info_bar.setText(
                    f"Dummy: Applied {len(params_dict)} parameters to M{module}:Ch{channel}"
                )

        except Exception as e:
            error_msg = f"Error applying parameters: {e}"
            self.info_bar.setText(error_msg)
            logger.error(error_msg)

    def update_info_bar(self, message):
        self.info_bar.setText(message)

    def init_pixie16(self):
        try:
            if not self.dummy_mode:
                # for real hardware
                px.control.init_and_boot(modules=[self.module_number])

                px.control.change_setting_from_dict(
                    settings=self.settings, call_pixie=True
                )

                self.info_bar.setText(
                    f"Pixie16 Module {self.module_number} initialized - Ready to start"
                )
            else:
                self.info_bar.setText("Running in dummy mode - Ready to start")

            self.live_reader = LiveDataReader()
            self.data_source = LiveDataSourceInterface(self.live_reader)

            self.live_reader.add_event_callback(self.process_event)

        except Exception as e:
            QMessageBox.critical(
                self,
                "Pixie16 Initialization Error",
                f"Failed to initialize Pixie16 system:\n{str(e)}",
            )
            if not self.dummy_mode:
                self.info_bar.setText("Initialization failed - check hardware")
            else:
                self.info_bar.setText("Dummy mode initialization failed")

    def setup_timers(self):
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)  # 1s

        self.data_timer = QTimer()
        self.data_timer.timeout.connect(self.read_pixie_data)

    def auto_start_acquisition(self):
        if not self.auto_started:
            self.auto_started = True
            self.start_continuous_acquisition()

    def start_continuous_acquisition(self):
        try:
            self.info_bar.setText("Starting continuous acquisition...")

            if self.dummy_mode:
                self.start_dummy_data()
            else:
                px.control.start_list_mode_run()
                self.data_timer.start(50)  # ms

            self.data_source.start_acquisition()

            self.is_acquiring = True
            self.status_label.setText("Status: Live")
            self.info_bar.setText("Live acquisition - displaying real-time data")

        except Exception as e:
            error_msg = f"Failed to start continuous acquisition: {str(e)}"
            print(error_msg)
            self.info_bar.setText(f"Error: {error_msg}")
            QTimer.singleShot(5000, self.start_continuous_acquisition)  # 5s

    def stop_continuous_acquisition(self):
        try:
            if self.data_source:
                self.data_source.stop_acquisition()
            self.data_timer.stop()

            if not self.dummy_mode:
                px.control.end_run()

            self.is_acquiring = False
            self.status_label.setText("Status: Stopped")
            self.info_bar.setText("Acquisition stopped")

        except Exception as e:
            print(f"Error stopping acquisition: {e}")

    def clear_data(self):
        if hasattr(self.spectrum_tab, "clear_data"):
            self.spectrum_tab.clear_data()
        self.last_event_count = 0
        self.info_bar.setText("Data cleared")

    def save_data(self):
        try:
            from PyQt6.QtWidgets import QFileDialog
            import json

            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Spectrum Data",
                f"pixie_spectra_{int(time.time())}.json",
                "JSON Files (*.json);;All Files (*)",
            )

            if file_path:
                data_to_save = {}
                for channel in self.channels:
                    if (
                        hasattr(self.spectrum_tab, "energy_data")
                        and channel in self.spectrum_tab.energy_data
                    ):
                        data_to_save[f"channel_{channel}"] = list(
                            self.spectrum_tab.energy_data[channel]
                        )

                data_to_save["metadata"] = {
                    "timestamp": time.time(),
                    "channels": self.channels,
                    "dummy_mode": self.dummy_mode,
                    "total_events": sum(
                        len(data)
                        for data in data_to_save.values()
                        if isinstance(data, list)
                    ),
                }

                with open(file_path, "w") as f:
                    json.dump(data_to_save, f, indent=2)

                self.info_bar.setText(f"Data saved to {file_path}")

        except Exception as e:
            error_msg = f"Failed to save data: {str(e)}"
            QMessageBox.warning(self, "Save Error", error_msg)
            self.info_bar.setText(f"Save error: {error_msg}")

    def read_pixie_data(self):
        if not self.is_acquiring or not self.live_reader:
            return

        try:
            data_list = px.control.read_list_mode_fifo(check=True, threshold=32)

            for data in data_list:
                if len(data) > 0:
                    self.live_reader.add_data(data)

        except Exception as e:
            print(f"Error reading PIXIE data: {e}")

    def start_dummy_data(self):
        print("Starting dummy data generation...")

        real_data_file = Path(
            "/home/jo/Documents/work/data/RUN-2025-06-05-00001/binary-data/RUN-2025-06-05-00001-mod0-1749144651-168324-00000.bin"
        )
        if real_data_file.exists():
            print(f"Using real PIXIE data from: {real_data_file}")
            self.start_real_data_simulation(real_data_file)
        else:
            print("Using synthetic data generation")
            self.start_synthetic_data()

    def start_real_data_simulation(self, data_file):
        def real_data_generator():
            try:
                binary_data = np.fromfile(data_file, dtype=np.uint32)
                print(f"Loaded {len(binary_data)} words from real data file")

                chunk_size = 1000
                total_chunks = len(binary_data) // chunk_size

                for i in range(0, len(binary_data), chunk_size):
                    if not self.data_source.is_active:
                        break

                    chunk = binary_data[i : i + chunk_size]
                    self.live_reader.add_data(chunk)

                    if i // chunk_size % 10 == 0:
                        print(
                            f"Fed chunk {i // chunk_size + 1}/{total_chunks} to live reader"
                        )

                    time.sleep(0.1)  # 10 Hz chunk feeding

                print("Real data simulation completed")

            except Exception as e:
                print(f"Error with real data simulation: {e}")
                self.start_synthetic_data()

        self.real_data_thread = threading.Thread(
            target=real_data_generator, daemon=True
        )
        self.real_data_thread.start()

    def start_synthetic_data(self):  # TODO: fix and remove when tested.
        import random

        def event_generator():
            event_count = 0
            while self.data_source.is_active:
                for channel in self.channels:
                    if random.random() < 0.05:
                        if channel < 4:  # Channels 0-3
                            energy = max(0, int(random.gauss(500, 100)))
                        elif channel < 8:  # Channels 4-7
                            energy = max(0, int(random.gauss(1000, 150)))
                        elif channel < 12:  # Channels 8-11
                            energy = max(0, int(random.gauss(1500, 200)))
                        else:  # Channels 12-15
                            energy = max(0, int(random.gauss(2000, 250)))

                        energy = max(0, min(energy, 4095))  # Clamp to ADC range

                        # Create mock event object
                        event = type(
                            "Event",
                            (),
                            {
                                "channel": channel,
                                "energy": energy,
                                "timestamp": int(time.time() * 1e9),
                            },
                        )()

                        self.process_event(event)
                        event_count += 1

                time.sleep(0.02)  # 50 Hz base rate

        self.synthetic_thread = threading.Thread(target=event_generator, daemon=True)
        self.synthetic_thread.start()

    def process_event(self, event):
        try:
            channel = getattr(event, "channel", 0)
            energy = getattr(event, "energy", 0)

            if hasattr(self, "_event_count"):
                self._event_count += 1
            else:
                self._event_count = 1

            # if self._event_count % 100 == 0:  # Print every 100 events
            #     print(f"Processed {self._event_count} events. Latest: Ch{channel}, E={energy}")

            # Feed to spectrum plotter - ensure channel is in range
            if channel in self.channels and hasattr(self.spectrum_tab, "energy_data"):
                self.spectrum_tab.energy_data[channel].append(energy)

        except Exception as e:
            print(f"Error processing event: {e}")
            import traceback

            traceback.print_exc()

    def update_status(self):
        if not self.live_reader:
            return

        try:
            stats = self.live_reader.get_statistics()
            rate = stats.get("processing_rate", 0)
            events = stats.get("events_processed", 0)

            self.rate_label.setText(f"Rate: {rate:.1f} Hz")
            self.events_label.setText(f"Events: {events}")

            if self.is_acquiring and hasattr(self.spectrum_tab, "energy_data"):
                total_events = sum(
                    len(data) for data in self.spectrum_tab.energy_data.values()
                )
                self.info_bar.setText(
                    f"Acquiring - Rate: {rate:.1f} Hz, Total Events: {total_events}"
                )

                channel_stats = {}
                for ch in self.channels:
                    channel_stats[ch] = len(self.spectrum_tab.energy_data.get(ch, []))

                if hasattr(self, "channel_controls"):
                    self.channel_controls.update_channel_statistics(channel_stats)

        except Exception as e:
            print(f"Error updating status: {e}")

    def closeEvent(self, event):
        try:
            if self.is_acquiring:
                self.stop_continuous_acquisition()
            if not self.dummy_mode:
                px.control.exit_system()
        except:
            pass
        event.accept()


def main():
    args = docopt(__doc__)

    dummy_mode = args["--dummy"]
    module_number = 2

    # Parse channels
    channels_str = args["--channels"] or "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15"
    try:
        print("Are you failing1")
        channels = [int(ch.strip()) for ch in channels_str.split(",")]
    except ValueError:
        print(
            "Error: Invalid channel list format. Use comma-separated integers like '0,1,2,3'"
        )
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("Pixie16 Scope")

    app.setStyle("Fusion")

    try:
        print("fail before creating??")
        window = PixieScopeApp(
            dummy_mode=dummy_mode, module_number=module_number, channels=channels
        )
        window.show()

        sys.exit(app.exec())

    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
