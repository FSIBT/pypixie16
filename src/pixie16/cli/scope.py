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
        self.live_reader = None
        self.data_source = None
        self.is_acquiring = False
        self.auto_started = False

        self.settings = {
            "channels": self.channels,
            "TRACE_LENGTH": 1.0,
            "TRIGGER_THRESHOLD": 1,
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

        self.mca_data = {}  # Store MCA histogram data
        self.current_mode = "mca_mode"  # Default mode
        self.acquisition_timer = None
        self.last_event_count = 0
        self.last_update_time = time.time()

        self.init_ui()
        self.init_pixie16()
        # self.plot_mca()
        self.setup_timers()

    def plot_mca(self):
        """Using pixie control's tale_MCA_spectra to collect data."""
        print(self.raw_settings)
        px.control.change_raw_setting_from_dict(self.raw_settings, call_pixie=True)
        histogram = px.control.take_MCA_spectra(
            channels=self.channels, duration=10, verbose=True
        )
        print(histogram, type(histogram))

    def on_mode_changed(self, mode_text):
        """Handle acquisition mode changes"""
        self.current_mode = mode_text.lower().replace(" ", "_")

        # Stop current acquisition if running
        if self.is_acquiring:
            self.stop_acquisition()

        # Switch spectrum plotter based on mode
        if self.current_mode == "mca_mode":
            from pixie16.ui.mca_spectrum_plotter import MCASpectrumPlotter

            # Get channels from settings
            active_channels = []
            for module, channel in self.settings.get("channels", [(0, 4), (0, 9)]):
                active_channels.append(channel)

            # Replace spectrum tab
            old_spectrum_tab = self.spectrum_tab
            self.spectrum_tab = MCASpectrumPlotter(
                channels=active_channels, title="PIXIE-16 MCA Spectra"
            )
        if self.current_mode == "list_mode":
            print("Mode changed to List Mode")

        self.info_bar.setText(f"Mode changed to: {mode_text} - MCA plotter ready")
        print(f"Switched to {self.current_mode} mode with MCA plotter")

    def start_mca_mode(self):
        """Start MCA histogram acquisition using real PIXIE functions"""
        try:
            if not self.dummy_mode:
                # Apply current settings before starting
                settings = self.parameter_controls.get_current_settings()
                import pixie16 as px

                px.control.change_setting_from_dict(settings, call_pixie=True)

                # Start PIXIE histogram run
                px.control.start_histogram_run()
                print("Started PIXIE histogram run")

            # Set up timer to read MCA data periodically
            if self.acquisition_timer:
                self.acquisition_timer.stop()

            self.acquisition_timer = QTimer()
            self.acquisition_timer.timeout.connect(self.read_mca_data)
            self.acquisition_timer.start(1000)  # Read every 1 second for MCA

            # Initialize MCA data storage for active channels - FLEXIBLE SIZE
            active_channels = []
            for module, channel in self.settings.get("channels", [(0, 4), (0, 9)]):
                active_channels.append(channel)
                # Don't pre-allocate fixed size!
                self.mca_data[channel] = np.array([])

            # Update spectrum plotter channels
            if hasattr(self.spectrum_tab, "set_channels"):
                self.spectrum_tab.set_channels(active_channels)

            runtime = (
                self.parameter_controls.get_runtime()
                if hasattr(self.parameter_controls, "get_runtime")
                else 10
            )
            self.info_bar.setText(
                f"MCA mode: Histogram accumulation for {runtime} seconds"
            )

        except Exception as e:
            error_msg = f"Error starting MCA mode: {str(e)}"
            print(error_msg)
            self.info_bar.setText(error_msg)
            raise

    def start_mca_acquisition(self):
        """Start MCA mode with UI updates - UNIFIED METHOD"""
        try:
            if not self.dummy_mode:
                # Apply current settings before starting
                settings = (
                    self.parameter_controls.get_current_settings()
                    if hasattr(self.parameter_controls, "get_current_settings")
                    else self.settings
                )
                px.control.change_setting_from_dict(settings, call_pixie=True)

                # Start PIXIE histogram run
                px.control.start_histogram_run()
                print("Started PIXIE histogram run")

            # Initialize MCA data for active channels - use flexible size
            for module, channel in self.channels:
                # Don't pre-allocate a fixed size - let the hardware determine it
                self.mca_data[channel] = np.array([])

            # Start the MCA plotter's update timer
            if hasattr(self.spectrum_tab, "start_live_updates"):
                self.spectrum_tab.start_live_updates()

            # Set up timer to read MCA data
            self.acquisition_timer = QTimer()
            self.acquisition_timer.timeout.connect(self.read_mca_data)
            self.acquisition_timer.start(2000)  # Read every 2 seconds

            self.info_bar.setText("MCA mode: Collecting histogram data...")

        except Exception as e:
            error_msg = f"Error starting MCA: {str(e)}"
            print(error_msg)
            self.info_bar.setText(error_msg)
            raise

    def read_mca_data(self):
        """Read MCA histogram data from PIXIE modules - FIXED API CALLS"""
        try:
            if self.dummy_mode:
                self.generate_dummy_mca_data()
                return

            # Use the CORRECT PIXIE API call
            try:
                print("Reading MCA data using take_MCA_spectra...")
                histogram_result = px.control.take_MCA_spectra(
                    channels=self.channels,  # [(0,4), (0,9)]
                    duration=1.0,  # Short duration for frequent updates
                    verbose=False,
                )

                print(f"MCA result type: {type(histogram_result)}")
                if hasattr(histogram_result, "__len__"):
                    print(f"MCA result length: {len(histogram_result)}")

                if isinstance(histogram_result, list) and len(histogram_result) >= 2:
                    # Map list results to channel numbers
                    channel_numbers = [ch for _, ch in self.channels]  # [4, 9]

                    for i, channel_num in enumerate(channel_numbers):
                        if i < len(histogram_result):
                            raw_data = np.array(histogram_result[i])

                            # DON'T TRUNCATE - Keep full data!
                            self.mca_data[channel_num] = raw_data

                            print(
                                f"Channel {channel_num}: {len(raw_data)} bins, "
                                f"max={np.max(raw_data)}, sum={np.sum(raw_data)}"
                            )

                            # Update the spectrum plotter with FULL histogram data
                            if hasattr(self.spectrum_tab, "update_mca_histogram"):
                                self.spectrum_tab.update_mca_histogram(
                                    channel_num, raw_data
                                )

                else:
                    print(f"Unexpected histogram_result format: {histogram_result}")

            except Exception as e:
                print(f"Error in take_MCA_spectra: {e}")
                import traceback

                traceback.print_exc()
                return

            total_counts = sum(np.sum(hist) for hist in self.mca_data.values())
            self.info_bar.setText(f"MCA: Read histograms, total counts: {total_counts}")

        except Exception as e:
            print(f"Error in read_mca_data: {e}")
            import traceback

            traceback.print_exc()

    def generate_dummy_mca_data(self):
        """Generate dummy MCA data for testing - FIXED TO MATCH REAL DATA"""
        import random

        channel_numbers = [ch for _, ch in self.channels]  # [4, 9]

        for channel in channel_numbers:
            # Create 32768 bins to match real hardware
            if channel not in self.mca_data or len(self.mca_data[channel]) != 32768:
                self.mca_data[channel] = np.zeros(32768, dtype=np.int32)

            # Add some random counts in realistic ranges
            for _ in range(200):  # More counts for visibility
                if channel == 4:
                    # Put data in higher bins like real data
                    bin_idx = int(random.gauss(25000, 2000))
                elif channel == 9:
                    bin_idx = int(random.gauss(28000, 1500))
                else:
                    bin_idx = int(random.gauss(26000, 1000))

                bin_idx = max(0, min(bin_idx, 32767))  # Clamp to full range
                self.mca_data[channel][bin_idx] += random.randint(1, 5)

            print(
                f"Generated dummy data for channel {channel}: "
                f"{len(self.mca_data[channel])} bins, "
                f"sum={np.sum(self.mca_data[channel])}"
            )

            # Update the MCA plotter with full data
            if hasattr(self.spectrum_tab, "update_mca_histogram"):
                self.spectrum_tab.update_mca_histogram(channel, self.mca_data[channel])
                print(f"Updated MCA plotter for channel {channel}")

    def update_mca_histogram(self, channel, histogram_data):
        """Update histogram for a specific channel"""
        if len(histogram_data) > 0:
            x_data = np.arange(len(histogram_data))  # Bin numbers
            y_data = histogram_data  # Counts

            # Update the plot with full data
            self.plot_widget.plot(x_data, y_data, pen=self.channel_colors[channel])

    def init_ui(self):
        self.setGeometry(100, 100, 1600, 1000)
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        main_layout = QHBoxLayout()

        left_layout = QVBoxLayout()

        control_panel = self.create_control_panel()
        left_layout.addWidget(control_panel)

        if self.current_mode == "mca_mode":
            from pixie16.ui.mca_spectrum_plotter import MCASpectrumPlotter

            # Extract just the channel numbers for MCA plotter
            channel_numbers = [ch for _, ch in self.channels]  # [4, 9]
            self.spectrum_tab = MCASpectrumPlotter(
                channels=channel_numbers, title="PIXIE-16 MCA Spectra"
            )
        else:
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

        self.info_bar.setText("Ready - Select mode and click Start Acquisition")

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
        layout = QVBoxLayout()

        # Mode selection
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Acquisition Mode:"))

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(
            ["MCA Mode", "List Mode"]
        )  # TODO: added list_mode and traces mode
        self.mode_combo.currentTextChanged.connect(self.on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()

        layout.addLayout(mode_layout)

        # Acquisition controls
        acq_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Acquisition")
        self.start_btn.clicked.connect(self.start_acquisition)
        self.stop_btn = QPushButton("Stop Acquisition")
        self.stop_btn.clicked.connect(self.stop_acquisition)
        self.stop_btn.setEnabled(False)

        acq_layout.addWidget(self.start_btn)
        acq_layout.addWidget(self.stop_btn)

        # Data controls
        self.clear_btn = QPushButton("Clear Spectra")
        self.clear_btn.clicked.connect(self.clear_data)

        self.save_btn = QPushButton("Save Data")
        self.save_btn.clicked.connect(self.save_data)

        acq_layout.addWidget(self.clear_btn)
        acq_layout.addWidget(self.save_btn)

        layout.addLayout(acq_layout)

        # Status display
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Status: Ready")
        self.rate_label = QLabel("Rate: 0 Hz")
        self.events_label = QLabel("Events: 0")

        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.rate_label)
        status_layout.addWidget(self.events_label)

        layout.addLayout(status_layout)

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

    def start_acquisition(self):
        """Start acquisition based on selected mode"""
        try:
            mode_text = self.mode_combo.currentText()
            self.current_mode = mode_text.lower().replace(" ", "_")

            self.info_bar.setText(f"Starting {mode_text} acquisition...")

            if self.current_mode == "mca_mode":
                self.start_mca_acquisition()
            elif self.current_mode == "list_mode":
                self.start_list_mode_acquisition()
            else:
                self.info_bar.setText("Mode not implemented yet")
                return

            self.is_acquiring = True
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.status_label.setText(f"Status: Acquiring ({mode_text})")

        except Exception as e:
            error_msg = f"Failed to start acquisition: {str(e)}"
            print(error_msg)
            self.info_bar.setText(error_msg)

    def stop_acquisition(self):
        """Stop current acquisition"""
        try:
            if self.acquisition_timer:
                self.acquisition_timer.stop()

            # Stop the MCA plotter's update timer
            if hasattr(self.spectrum_tab, "stop_live_updates"):
                self.spectrum_tab.stop_live_updates()

            if self.data_source:
                self.data_source.stop_acquisition()

            if hasattr(self, "data_timer"):
                self.data_timer.stop()

            # Only call end_run for list mode, not MCA mode
            if not self.dummy_mode and self.current_mode == "list_mode":
                px.control.end_run()

            self.is_acquiring = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.status_label.setText("Status: Stopped")
            self.info_bar.setText("Acquisition stopped")

        except Exception as e:
            print(f"Error stopping acquisition: {e}")

    def start_list_mode_acquisition(self):
        """Start list mode acquisition"""
        try:
            if self.dummy_mode:
                self.start_dummy_data()
            else:
                px.control.change_setting_from_dict(self.settings, call_pixie=True)
                px.control.start_list_mode_run()
                self.data_timer.start(50)

            self.data_source.start_acquisition()
            self.info_bar.setText("List mode: Real-time event processing")

        except Exception as e:
            error_msg = f"Error starting list mode: {str(e)}"
            print(error_msg)
            self.info_bar.setText(error_msg)
            raise

    def init_pixie16(self):
        try:
            if not self.dummy_mode:
                print("Booting PIXIE-16...")
                px.control.init_and_boot(modules=[self.module_number])
                self.info_bar.setText(
                    f"PIXIE-16 Module {self.module_number} initialized - Ready to start"
                )
            else:
                self.info_bar.setText("Running in dummy mode - Ready to start")

            self.live_reader = LiveDataReader()
            self.data_source = LiveDataSourceInterface(self.live_reader)
            self.live_reader.add_event_callback(self.process_event)

        except Exception as e:
            QMessageBox.critical(
                self,
                "PIXIE-16 Initialization Error",
                f"Failed to initialize PIXIE-16 system:\n{str(e)}",
            )
            self.info_bar.setText("Initialization failed - check hardware")

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
