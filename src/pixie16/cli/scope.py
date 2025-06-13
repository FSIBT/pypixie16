"""
Pixie16 Scope - Real-time visualization and parameter control for PIXIE-16 modules

Usage:
  pixie16-scope [--dummy] [--module <N>] [--channels <list>]

Options:
  --dummy           Use dummy data for testing without hardware
  --module <N>      Specify module number [default: 0]
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
    QGridLayout,
    QTabWidget,
    QMessageBox,
    QGroupBox,
    QScrollArea,
    QPushButton,
    QLabel,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QCheckBox,
    QButtonGroup,
    QRadioButton,
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


class PixieScopeApp(BaseApp):
    def __init__(self, dummy_mode=False, module_number=0, channels=None):
        super().__init__()

        # Set window title
        if hasattr(self, "setWindowTitle"):
            self.setWindowTitle("Pixie16 Scope")

        self.dummy_mode = dummy_mode
        self.module_number = module_number
        self.channels = channels or list(range(8))
        self.live_reader = None
        self.data_source = None
        self.is_acquiring = False

        # Auto-start flag
        self.auto_started = False

        # stats tracking
        self.last_event_count = 0
        self.last_update_time = time.time()

        self.init_ui()
        self.init_pixie16()
        self.setup_timers()

    def init_ui(self):
        self.setGeometry(100, 100, 1400, 900)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout()

        control_panel = self.create_control_panel()  # top
        layout.addWidget(control_panel)

        self.spectrum_tab = ContinuousSpectrumPlotter(
            app=None,
            instrument_name="pixie16",
            display_name="PIXIE-16 Energy Spectra",
            channels=self.channels,
            energy_range=(0, 3000),
            bins=1000,
        )

        layout.addWidget(self.spectrum_tab)

        self.info_bar = QLabel("Initializing scope...")  # bottom
        layout.addWidget(self.info_bar)

        main_widget.setLayout(layout)

        QTimer.singleShot(1000, self.auto_start_acquisition)

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

    def init_pixie16(self):
        try:
            if not self.dummy_mode:
                # Initialize real hardware
                px.control.init_and_boot(modules=[self.module_number])
                self.info_bar.setText(
                    f"Pixie16 Module {self.module_number} initialized - Ready to start"
                )
            else:
                self.info_bar.setText("Running in dummy mode - Ready to start")

            # Create live data reader
            self.live_reader = LiveDataReader()
            self.data_source = LiveDataSourceInterface(self.live_reader)

            # Connect event processing
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
                # Start dummy data simulation
                self.start_dummy_data()
            else:
                # Start real hardware acquisition
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

            # Get save location
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Spectrum Data",
                f"pixie_spectra_{int(time.time())}.json",
                "JSON Files (*.json);;All Files (*)",
            )

            if file_path:
                # Collect data from all channels
                data_to_save = {}
                for channel in self.channels:
                    if (
                        hasattr(self.spectrum_tab, "energy_data")
                        and channel in self.spectrum_tab.energy_data
                    ):
                        data_to_save[f"channel_{channel}"] = list(
                            self.spectrum_tab.energy_data[channel]
                        )

                # Add metadata
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

                # Save to file
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
            # Read data from PIXIE FIFO
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

                # Feed chunks of data to the live reader
                chunk_size = 1000
                total_chunks = len(binary_data) // chunk_size

                for i in range(0, len(binary_data), chunk_size):
                    if not self.data_source.is_active:
                        break

                    chunk = binary_data[i : i + chunk_size]
                    self.live_reader.add_data(chunk)

                    if i // chunk_size % 10 == 0:  # Print every 10th chunk
                        print(
                            f"Fed chunk {i // chunk_size + 1}/{total_chunks} to live reader"
                        )

                    time.sleep(0.1)  # 10 Hz chunk feeding

                print("Real data simulation completed")

            except Exception as e:
                print(f"Error with real data simulation: {e}")
                # Fallback to synthetic data
                self.start_synthetic_data()

        self.real_data_thread = threading.Thread(
            target=real_data_generator, daemon=True
        )
        self.real_data_thread.start()

    def start_synthetic_data(self):
        import random

        def event_generator():
            event_count = 0
            while self.data_source.is_active:
                # Generate random events for the ACTUAL channels we're using
                for channel in self.channels:
                    if random.random() < 0.05:  # 5% chance per channel per cycle
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

                        # Process event
                        self.process_event(event)
                        event_count += 1

                time.sleep(0.02)  # 50 Hz base rate

        self.synthetic_thread = threading.Thread(target=event_generator, daemon=True)
        self.synthetic_thread.start()

    def process_event(self, event):
        try:
            channel = getattr(event, "channel", 0)
            energy = getattr(event, "energy", 0)

            # Debug output
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

    def handle_parameter_change(self, parameter, value):
        try:
            if not self.dummy_mode:
                # The parameter widget already handles setting the hardware parameter
                # This is just for logging/status updates
                module = getattr(self.parameter_tab, "module", 0)
                channel = getattr(self.parameter_tab, "channel", 0)
                print(
                    f"Parameter {parameter} = {value} applied to Module {module}, Channel {channel}"
                )
                self.info_bar.setText(f"Updated {parameter} = {value} for Ch{channel}")
            else:
                self.info_bar.setText(f"Dummy mode: {parameter} = {value}")

        except Exception as e:
            error_msg = f"Error handling parameter change: {str(e)}"
            print(error_msg)

    def change_display_mode(self, mode):
        if mode == "Single Channel":
            self.focus_channel_combo.setEnabled(True)
            # Update spectrum plotter to show only selected channel
            selected_channel = int(self.focus_channel_combo.currentText().split()[1])
            self.spectrum_tab.set_display_channels([selected_channel])
        else:
            self.focus_channel_combo.setEnabled(False)
            # Show all channels
            self.spectrum_tab.set_display_channels(self.channels)

    def change_focus_channel(self, channel_text):
        if self.display_mode_combo.currentText() == "Single Channel":
            channel = int(channel_text.split()[1])
            self.spectrum_tab.set_display_channels([channel])
            # Also update parameter controls to this channel
            self.param_channel_spin.setValue(channel)

    def update_energy_range(self):
        min_energy = self.energy_min_spin.value()
        max_energy = self.energy_max_spin.value()
        if min_energy >= max_energy:
            max_energy = min_energy + 100
            self.energy_max_spin.setValue(max_energy)
        self.spectrum_tab.set_energy_range(min_energy, max_energy)

    def toggle_log_scale(self, checked):
        if hasattr(self.spectrum_tab, "set_log_scale"):
            self.spectrum_tab.set_log_scale(checked)

    # Parameter update methods
    def update_threshold(self):
        value = self.threshold_spin.value()
        self.set_pixie_parameter("TRIGGER_THRESHOLD", value)

    def update_energy_rise(self):
        value = self.energy_rise_spin.value()
        self.set_pixie_parameter("ENERGY_RISETIME", value)

    def update_energy_flat(self):
        value = self.energy_flat_spin.value()
        self.set_pixie_parameter("ENERGY_FLATTOP", value)

    def update_trigger_rise(self):
        value = self.trigger_rise_spin.value()
        self.set_pixie_parameter("TRIGGER_RISETIME", value)

    def update_gain(self):
        value = float(self.gain_combo.currentText())
        self.set_pixie_parameter("Gain", value)

    def update_polarity(self):
        value = self.polarity_combo.currentText()
        self.set_pixie_parameter("Polarity", value)

    def update_channel_enable(self):
        value = self.channel_enable_check.isChecked()
        self.set_pixie_parameter("GoodChannel", value)

    def set_pixie_parameter(self, param_name, value):
        try:
            if not self.dummy_mode:
                module = self.param_module_spin.value()
                channel = self.param_channel_spin.value()
                px.control.set_channel_parameter(param_name, value, module, channel)
                self.info_bar.setText(
                    f"Set {param_name} = {value} on M{module}:Ch{channel}"
                )
            else:
                self.info_bar.setText(f"Dummy: {param_name} = {value}")
        except Exception as e:
            self.info_bar.setText(f"Error setting {param_name}: {e}")

    def apply_current_settings(self):
        try:
            if not self.dummy_mode:
                module = self.param_module_spin.value()
                channel = self.param_channel_spin.value()

                # Apply all parameters
                px.control.set_channel_parameter(
                    "TRIGGER_THRESHOLD", self.threshold_spin.value(), module, channel
                )
                px.control.set_channel_parameter(
                    "ENERGY_RISETIME", self.energy_rise_spin.value(), module, channel
                )
                px.control.set_channel_parameter(
                    "ENERGY_FLATTOP", self.energy_flat_spin.value(), module, channel
                )
                px.control.set_channel_parameter(
                    "TRIGGER_RISETIME", self.trigger_rise_spin.value(), module, channel
                )
                px.control.set_channel_parameter(
                    "Gain", float(self.gain_combo.currentText()), module, channel
                )
                px.control.set_channel_parameter(
                    "Polarity", self.polarity_combo.currentText(), module, channel
                )
                px.control.set_channel_parameter(
                    "GoodChannel",
                    self.channel_enable_check.isChecked(),
                    module,
                    channel,
                )

                self.info_bar.setText(
                    f"Applied all settings to Module {module}, Channel {channel}"
                )
            else:
                self.info_bar.setText("Dummy mode: All settings applied")
        except Exception as e:
            self.info_bar.setText(f"Error applying settings: {e}")

    def update_status(self):
        if not self.live_reader:
            return

        try:
            stats = self.live_reader.get_statistics()

            # Update rate and event count
            rate = stats.get("processing_rate", 0)
            events = stats.get("events_processed", 0)

            self.rate_label.setText(f"Rate: {rate:.1f} Hz")
            self.events_label.setText(f"Events: {events}")

            # Update info bar with more detailed statistics
            if self.is_acquiring:
                if hasattr(self.spectrum_tab, "energy_data"):
                    total_events = sum(
                        len(data) for data in self.spectrum_tab.energy_data.values()
                    )
                    self.info_bar.setText(
                        f"Acquiring - Rate: {rate:.1f} Hz, Total Events: {total_events}"
                    )

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
    module_number = int(args["--module"] or 0)

    # Parse channels
    channels_str = args["--channels"] or "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15"
    try:
        channels = [int(ch.strip()) for ch in channels_str.split(",")]
    except ValueError:
        print(
            "Error: Invalid channel list format. Use comma-separated integers like '0,1,2,3'"
        )
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("Pixie16 Scope")

    # Set application style
    app.setStyle("Fusion")

    try:
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
