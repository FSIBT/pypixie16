"""
Pixie16 Scope - Real-time visualization and parameter control for PIXIE-16 modules

Usage:
  pixie16-scope [--dummy] [--module <N>] [--channels <list>]

Options:
  --dummy           Use dummy data for testing without hardware
  --module <N>      Specify module number [default: 2]
  --channels <list> Specify channels to display [default: 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15]
"""

import sys
import os
import time
import threading
from pathlib import Path
import json

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QMessageBox,
    QGroupBox,
    QSplitter,
    QPushButton,
    QLabel,
    QComboBox,
    QCheckBox,
)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

import numpy as np

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

# Import the plotting modules
from pixie16.ui.mca_spectrum_plotter import MCASpectrumPlotter
from pixie16.ui.spectrum_plotter import ContinuousSpectrumPlotter
from pixie16.ui.traces_plotter import TracesPlotter
from pixie16.ui.channel_controls import ChannelDisplayControls
from pixie16.ui.parameter_controls import ParameterControls

import logging

logger = logging.getLogger(__name__)

# Hardcoded paths for testing
DUMMY_BINARY_FILE = "/home/jo/Documents/work/data/RUN-2025-06-05-00001/binary-data/RUN-2025-06-05-00001-mod0-1749144651-168324-00000.bin"
DUMMY_NUMPY_FILE = "/home/jo/Downloads/RUN-2025-06-17-00000-mca-2025-06-17-09-21-48.npy"


class PixieScopeApp(QMainWindow):
    def __init__(self, dummy_mode=False, module_number=2, channels=None):
        super().__init__()

        self.setWindowTitle("Pixie16 Scope")
        self.setGeometry(100, 100, 1600, 1000)

        self.dummy_mode = dummy_mode
        self.module_number = module_number

        # Default to all 16 channels if none specified
        if channels is None:
            channels = list(range(16))
        self.channels = [
            (module_number, ch) for ch in channels
        ]  # Convert to (module, channel) tuples
        self.channel_numbers = channels  # Keep just the channel numbers for convenience

        self.live_reader = None
        self.data_source = None
        self.is_acquiring = False
        self.current_mode = "mca_mode"  # Default mode
        self.acquisition_timer = None

        # Data storage for MCA mode
        self.mca_data = {}
        self.cumulative_mca_data = {}

        # PIXIE-16 settings
        self.settings = {
            "channels": self.channels,
            "TRACE_LENGTH": 1.0,
            "TRIGGER_THRESHOLD": 100,
            "TRACE_DELAY": 0.2,
            "TRIGGER_RISETIME": 0.02,
            "TRIGGER_FLATTOP": 0.02,
            "ENERGY_RISETIME": 0.5,
            "ENERGY_FLATTOP": 0.1,
            "Polarity": "positive",
            "CaptureTrace": True,
            "EnableChannelVal": True,
        }

        self.use_realtime_axis = True  # ON by default
        self.trace_delay_ns = {}  # Per-channel delays from default.json
        self.sampling_period_ns = 2.0  # 500 MSPS = 2ns per sample
        self.alpha_channel = 9  # Alpha detector channel

        self.load_pixie16_timing_settings()

        self.init_ui()
        self.init_pixie16()
        self.setup_timers()

    def setup_dummy_timing(self):
        """Fallback timing settings for dummy mode"""
        self.sampling_period_ns = 2.0
        # Use realistic values based on your default.json
        dummy_delays = [
            108,
            108,
            16,
            176,
            64,
            324,
            108,
            108,
            408,
            24,
            48,
            16,
            64,
            64,
            64,
            64,
        ]
        for i in range(16):
            self.trace_delay_ns[i] = dummy_delays[i]
        print("Using dummy timing settings")

    def load_pixie16_timing_settings(self):
        """Load timing settings from your default.json file"""
        try:
            config_paths = [
                Path("default.json"),
                Path("data/default.json"),
                Path(__file__).parent / "default.json",
                Path(__file__).parent.parent / "default.json",
                Path(__file__).parent.parent / "data" / "default.json",
            ]

            config_path = None
            for path in config_paths:
                if path.exists():
                    config_path = path
                    break

            if not config_path:
                print("default.json not found, using dummy timing settings")
                self.setup_dummy_timing()
                return

            print(f"Loading PIXIE-16 timing from: {config_path}")

            with open(config_path) as f:
                config = json.load(f)

            module_data = config[0]

            channel_input = module_data["channel"]["input"]

            # Hardware specs are in metadata.config[0]
            adc_msps = module_data["metadata"]["config"][0]["adc_msps"]
            self.sampling_period_ns = 1000.0 / adc_msps  # 500 MSPS -> 2ns

            # Get per-channel trigger delays (in samples)
            trigger_delays = channel_input["TriggerDelay"]

            # Convert to ns
            for channel in range(16):
                self.trace_delay_ns[channel] = (
                    trigger_delays[channel] * self.sampling_period_ns
                )

            print(f"Loaded PIXIE-16 timing: {self.sampling_period_ns}ns/sample")
            print(
                f"    Alpha Ch{self.alpha_channel}: {self.trace_delay_ns[self.alpha_channel]:.1f}ns delay"
            )

            # Print key channels for your alpha-gamma analysis
            key_channels = [1, 4, 9]  # Based on your setup
            for ch in key_channels:
                if ch < len(trigger_delays):
                    print(f"   Ch{ch}: {self.trace_delay_ns[ch]:.1f}ns delay")

            self.analyze_alpha_gamma_timing()

        except Exception as e:
            print(f"Error loading default.json: {e}")
            self.setup_dummy_timing()

    def analyze_alpha_gamma_timing(self):
        alpha_ch = self.alpha_channel
        gamma_channels = [1, 4]  # Your gamma detectors

        alpha_delay = self.trace_delay_ns[alpha_ch]
        expected_gamma_delay = 20

        print(f"\n=== Alpha-Gamma Timing Analysis ===")
        print(f"Expected: Gamma {expected_gamma_delay}ns after alpha")
        print(f"Alpha Ch{alpha_ch}: {alpha_delay:.1f}ns recording delay")

        for gamma_ch in gamma_channels:
            gamma_delay = self.trace_delay_ns[gamma_ch]
            recording_diff = gamma_delay - alpha_delay

            # True timing accounting for different recording delays
            apparent_delay = expected_gamma_delay - recording_diff

            print(f"Gamma Ch{gamma_ch}: {gamma_delay:.1f}ns recording delay")
            print(
                f"  -> Records {abs(recording_diff):.1f}ns {'earlier' if recording_diff > 0 else 'later'} than alpha"
            )

            if apparent_delay < 0:
                print(
                    f"  -> Gamma timestamp will appear {abs(apparent_delay):.1f}ns BEFORE alpha!"
                )
            else:
                print(
                    f"  -> Gamma timestamp will appear {apparent_delay:.1f}ns after alpha"
                )

    def init_ui(self):
        # Set responsive window size
        screen = QApplication.primaryScreen().geometry()
        window_width = min(1200, int(screen.width() * 0.85))
        window_height = min(800, int(screen.height() * 0.8))
        self.setGeometry(100, 100, window_width, window_height)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        # Create layout with splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left side - plotting area
        left_widget = QWidget()
        self.left_layout = QVBoxLayout(left_widget)
        self.left_layout.setContentsMargins(5, 5, 5, 5)

        # Control panel
        control_panel = self.create_control_panel()
        self.left_layout.addWidget(control_panel)

        # Initialize with MCA plotter by default
        self.spectrum_tab = MCASpectrumPlotter(
            channels=self.channel_numbers, title="PIXIE-16 MCA Spectra"
        )
        self.left_layout.addWidget(self.spectrum_tab)

        # Right side - controls
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5, 5, 5, 5)

        self.channel_controls = ChannelDisplayControls(
            channels=self.channels, title="Channels"
        )
        self.channel_controls.channels_changed.connect(self.update_display_channels)
        right_layout.addWidget(self.channel_controls)

        self.parameter_controls = ParameterControls(
            initial_module=self.module_number, title="Parameters"
        )
        self.parameter_controls.parameter_changed.connect(self.handle_parameter_change)
        self.parameter_controls.apply_all_requested.connect(
            self.handle_apply_all_parameters
        )
        self.parameter_controls.status_message.connect(self.update_info_bar)

        # The Parameters Box hw
        self.parameter_controls.setMaximumHeight(450)
        self.parameter_controls.setMinimumHeight(350)
        right_layout.addWidget(self.parameter_controls)

        right_layout.addStretch()

        # Set sizes
        left_widget.setMinimumWidth(400)
        right_widget.setMinimumWidth(200)
        right_widget.setMaximumWidth(350)

        # Add to splitter
        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(right_widget)

        main_splitter.setSizes([int(window_width * 0.75), int(window_width * 0.25)])
        main_splitter.setCollapsible(0, False)
        main_splitter.setCollapsible(1, True)

        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.addWidget(main_splitter)

        # Info bar
        self.info_bar = QLabel("Ready - Select mode and click 'Start Acquisition'")
        self.info_bar.setMaximumHeight(25)
        self.info_bar.setStyleSheet("QLabel { padding: 2px; font-size: 11px; }")
        main_layout.addWidget(self.info_bar)

        main_widget.setLayout(main_layout)

        # Show dummy mode status
        if self.dummy_mode:
            self.info_bar.setText("DUMMY MODE - Using test data files")

    def create_control_panel(self):
        group = QGroupBox("Controls")
        group.setMaximumHeight(100)
        layout = QVBoxLayout()
        layout.setSpacing(5)

        top_layout = QHBoxLayout()

        # Mode selection
        top_layout.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["MCA Mode", "List Mode", "Traces Mode"])
        self.mode_combo.currentTextChanged.connect(self.on_mode_changed)
        self.mode_combo.setMaximumWidth(120)
        top_layout.addWidget(self.mode_combo)

        # Add some spacing between mode and buttons
        top_layout.addSpacing(20)

        # Acquisition control buttons
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.start_acquisition)
        self.start_btn.setMaximumWidth(60)  # Made slightly smaller
        top_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_acquisition)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMaximumWidth(60)
        top_layout.addWidget(self.stop_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_data)
        self.clear_btn.setMaximumWidth(60)
        top_layout.addWidget(self.clear_btn)

        top_layout.addStretch()

        # Status display (second row)
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Status: Ready")
        self.status_label.setMinimumWidth(100)
        self.rate_label = QLabel("Rate: 0 Hz")
        self.rate_label.setMinimumWidth(80)
        self.events_label = QLabel("Events: 0")
        self.events_label.setMinimumWidth(80)

        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.rate_label)
        status_layout.addWidget(self.events_label)
        status_layout.addStretch()

        # Add both layouts
        layout.addLayout(top_layout)
        layout.addLayout(status_layout)

        group.setLayout(layout)
        return group

    def on_mode_changed(self, mode_text):
        """Handle acquisition mode changes with proper cleanup"""
        print(
            f"Mode change requested: {self.current_mode} -> {mode_text.lower().replace(' ', '_')}"
        )

        # Stop current acquisition if running
        if self.is_acquiring:
            print("Stopping current acquisition before mode change...")
            self.stop_acquisition()
            time.sleep(0.1)  # Give cleanup time to complete

        old_mode = self.current_mode
        self.current_mode = mode_text.lower().replace(" ", "_")

        # Remove old spectrum tab
        old_spectrum_tab = self.spectrum_tab
        if old_spectrum_tab:
            print(f"Removing old {old_mode} spectrum tab...")
            try:
                if hasattr(old_spectrum_tab, "stop_live_updates"):
                    old_spectrum_tab.stop_live_updates()
                self.left_layout.removeWidget(old_spectrum_tab)
                old_spectrum_tab.setParent(None)
                old_spectrum_tab.deleteLater()
            except Exception as e:
                print(f"Error cleaning up old spectrum tab: {e}")

        # Create new spectrum tab based on mode
        print(f"Creating new {self.current_mode} spectrum tab...")
        if self.current_mode == "mca_mode":
            from pixie16.ui.mca_spectrum_plotter import MCASpectrumPlotter

            self.spectrum_tab = MCASpectrumPlotter(
                channels=self.channel_numbers, title="PIXIE-16 MCA Spectra"
            )
        elif self.current_mode == "list_mode":
            self.spectrum_tab = ContinuousSpectrumPlotter(
                app=None,
                instrument_name="pixie16",
                display_name="PIXIE-16 List Mode Spectra",
                channels=self.channel_numbers,
                energy_range=(0, 4096),
                bins=1000,
            )
        elif self.current_mode == "traces_mode":
            self.spectrum_tab = TracesPlotter(
                channels=self.channel_numbers, title="PIXIE-16 Traces"
            )

            # Pass timing settings to plotter
            if hasattr(self.spectrum_tab, "set_timing_settings"):
                self.spectrum_tab.set_timing_settings(
                    {
                        "trace_delay_ns": self.trace_delay_ns,
                        "sampling_period_ns": self.sampling_period_ns,
                        "alpha_channel": self.alpha_channel,
                    }
                )

        # Add new spectrum tab
        self.left_layout.addWidget(self.spectrum_tab)

        mode_status = "DUMMY MODE - " if self.dummy_mode else ""
        self.info_bar.setText(
            f"{mode_status}Mode changed: {old_mode} -> {self.current_mode}"
        )
        print(f"Mode change complete: {old_mode} -> {self.current_mode}")

    def start_acquisition(self):
        """Start acquisition based on selected mode"""
        try:
            mode_text = self.mode_combo.currentText()
            mode_status = "DUMMY MODE - " if self.dummy_mode else ""
            self.info_bar.setText(f"{mode_status}Starting {mode_text} acquisition...")

            if self.current_mode == "mca_mode":
                self.start_mca_acquisition()
            elif self.current_mode == "list_mode":
                self.start_list_mode_acquisition()
            elif self.current_mode == "traces_mode":
                self.start_traces_acquisition()
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
        """Stop current acquisition with proper cleanup"""
        try:
            print(f"Stopping {self.current_mode} acquisition...")

            if self.acquisition_timer:
                self.acquisition_timer.stop()

            if hasattr(self.spectrum_tab, "stop_live_updates"):
                self.spectrum_tab.stop_live_updates()

            # Clean up live reader and data source
            self.cleanup_live_reader()

            if hasattr(self, "data_timer"):
                self.data_timer.stop()

            # Only call end_run for real hardware in list/traces mode
            if not self.dummy_mode and self.current_mode in [
                "list_mode",
                "traces_mode",
            ]:
                try:
                    px.control.end_run()
                except:
                    pass

            self.is_acquiring = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.status_label.setText("Status: Stopped")

            mode_status = "DUMMY MODE - " if self.dummy_mode else ""
            self.info_bar.setText(f"{mode_status}Acquisition stopped")

            print(f"Successfully stopped {self.current_mode} acquisition")

        except Exception as e:
            print(f"Error stopping acquisition: {e}")

    def start_mca_acquisition(self):
        """Start MCA mode acquisition"""
        try:
            if not self.dummy_mode:
                # Real hardware mode - apply settings and use px.control.take_MCA_spectra
                px.control.change_setting_from_dict(self.settings, call_pixie=True)
                print(
                    f"MCA acquisition starting for real hardware on channels: {self.channel_numbers}"
                )
            else:
                # Dummy mode - use numpy file
                print(
                    f"MCA acquisition starting in DUMMY MODE using: {DUMMY_NUMPY_FILE}"
                )

            # Start the MCA plotter's update timer
            if hasattr(self.spectrum_tab, "start_live_updates"):
                self.spectrum_tab.start_live_updates()

            # Set up timer to read MCA data
            self.acquisition_timer = QTimer()
            self.acquisition_timer.timeout.connect(self.read_mca_data)
            self.acquisition_timer.start(2000)  # Read every 2 seconds

            mode_status = "DUMMY MODE - " if self.dummy_mode else ""
            self.info_bar.setText(
                f"{mode_status}MCA mode: Collecting histogram data..."
            )

        except Exception as e:
            error_msg = f"Error starting MCA: {str(e)}"
            print(error_msg)
            self.info_bar.setText(error_msg)
            raise

    def start_list_mode_acquisition(self):
        """Start list mode acquisition"""
        try:
            if not self.dummy_mode:
                px.control.change_setting_from_dict(self.settings, call_pixie=True)
                px.control.start_list_mode_run()
                print(f"List mode acquisition starting for real hardware")
            else:
                print(
                    f"List mode acquisition starting in DUMMY MODE using: {DUMMY_BINARY_FILE}"
                )

            # create a fresh LiveDataReader for list mode
            self.cleanup_live_reader()  # Clean up old reader first

            self.live_reader = LiveDataReader()
            self.data_source = LiveDataSourceInterface(self.live_reader)
            self.live_reader.add_event_callback(self.process_list_mode_event)
            print("Created fresh LiveDataReader for list mode")

            if self.dummy_mode:
                self.start_dummy_list_mode_data()
            else:
                self.data_timer.start(50)

            self.data_source.start_acquisition()

            if hasattr(self.spectrum_tab, "start_live_updates"):
                self.spectrum_tab.start_live_updates()

            mode_status = "DUMMY MODE - " if self.dummy_mode else ""
            self.info_bar.setText(f"{mode_status}List mode: Real-time event processing")

        except Exception as e:
            error_msg = f"Error starting list mode: {str(e)}"
            print(error_msg)
            self.info_bar.setText(error_msg)
            raise

    def cleanup_live_reader(self):
        """Clean up existing live reader and data source - ENHANCED"""
        try:
            print("Starting cleanup of live reader and data source...")

            # Stop any existing dummy threads first
            if (
                hasattr(self, "dummy_thread")
                and self.dummy_thread
                and self.dummy_thread.is_alive()
            ):
                print("Stopping existing dummy thread...")
                # The thread should stop when data_source.is_active becomes False

            # Stop existing data source
            if hasattr(self, "data_source") and self.data_source:
                try:
                    self.data_source.stop_acquisition()
                    print("Stopped existing data source")
                except Exception as e:
                    print(f"Error stopping data source: {e}")
                finally:
                    self.data_source = None

            # Clean up existing live reader
            if hasattr(self, "live_reader") and self.live_reader:
                try:
                    if hasattr(self.live_reader, "stop_processing"):
                        self.live_reader.stop_processing()
                    print("Cleaned up existing live reader")
                except Exception as e:
                    print(f"Error stopping live reader: {e}")
                finally:
                    self.live_reader = None

            # Give threads time to stop
            time.sleep(0.2)
            print("Live reader cleanup completed")

        except Exception as e:
            print(f"Error during live reader cleanup: {e}")

    def start_traces_acquisition(self):
        """Start traces mode acquisition"""
        try:
            if not self.dummy_mode:
                trace_settings = self.settings.copy()
                trace_settings["CaptureTrace"] = True
                trace_settings["TRACE_LENGTH"] = 1.0
                px.control.change_setting_from_dict(trace_settings, call_pixie=True)
                px.control.start_list_mode_run()
                print(f"Traces acquisition starting for real hardware")
            else:
                print(
                    f"Traces acquisition starting in DUMMY MODE using: {DUMMY_BINARY_FILE}"
                )

            # fresh LiveDataReader for traces mode
            self.cleanup_live_reader()  # Clean up old reader first

            self.live_reader = LiveDataReader()
            self.data_source = LiveDataSourceInterface(self.live_reader)
            self.live_reader.add_event_callback(self.process_traces_event)
            print("Created fresh LiveDataReader for traces mode")

            if self.dummy_mode:
                self.start_dummy_traces_data()
            else:
                self.data_timer.start(100)

            self.data_source.start_acquisition()

            if hasattr(self.spectrum_tab, "start_live_updates"):
                self.spectrum_tab.start_live_updates()

            mode_status = "DUMMY MODE - " if self.dummy_mode else ""
            self.info_bar.setText(f"{mode_status}Traces mode: Real-time trace capture")

        except Exception as e:
            error_msg = f"Error starting traces mode: {str(e)}"
            print(error_msg)
            self.info_bar.setText(error_msg)
            raise

    def read_dummy_mca_data(self):
        if not Path(DUMMY_NUMPY_FILE).exists():
            print(f"Dummy numpy file not found: {DUMMY_NUMPY_FILE}")
            return

        mca_data = np.load(DUMMY_NUMPY_FILE)
        print(f"Loaded MCA data from {DUMMY_NUMPY_FILE}, shape: {mca_data.shape}")

        if len(mca_data.shape) == 2:
            # Multiple channels in file - distribute to available channels
            for i, channel in enumerate(self.channel_numbers):
                if i < mca_data.shape[0]:
                    fresh_data = mca_data[i, :].astype(np.int64)
                    # Add some variation to make it look live
                    noise = np.random.poisson(fresh_data * 0.01 + 1).astype(np.int64)
                    self.accumulate_channel_data(channel, noise)
        else:
            # Single channel - give to first channel with some distribution
            if self.channel_numbers:
                fresh_data = mca_data.astype(np.int64)
                for i, channel in enumerate(self.channel_numbers):
                    # Scale data differently for each channel
                    scale_factor = 0.5 + (i * 0.3)
                    scaled_data = (fresh_data * scale_factor).astype(np.int64)
                    noise = np.random.poisson(scaled_data * 0.01 + 1).astype(np.int64)
                    self.accumulate_channel_data(channel, noise)

    def read_mca_data(self):
        try:
            if self.dummy_mode:
                self.read_dummy_mca_data()
                return

            histogram_result = px.control.take_MCA_spectra(
                channels=self.channels,
                duration=1.0,
                verbose=False,
            )

            if isinstance(histogram_result | (list | np.ndarray)):
                for i, fresh_histogram in enumerate(histogram_result):
                    if i < len(self.channel_numbers):
                        channel = self.channel_numbers[i]
                        fresh_data = np.array(fresh_histogram, dtype=np.int64)
                        self.accumulate_channel_data(channel, fresh_data)

        except Exception as e:
            print(f"Error in read_mca_data: {e}")

    def start_dummy_list_mode_data(self):
        def dummy_list_mode_reader():
            if not Path(DUMMY_BINARY_FILE).exists():
                print(f"Dummy binary file not found: {DUMMY_BINARY_FILE}")
                return

            # ALWAYS start from beginning of file (for testing)
            binary_data = np.fromfile(DUMMY_BINARY_FILE, dtype=np.uint32)
            print(
                f"LIST MODE: Loaded {len(binary_data)} words from binary file (fresh start)"
            )

            chunk_size = 1000
            position = 0  # Always start from 0

            while (
                hasattr(self, "data_source")
                and self.data_source is not None
                and getattr(self.data_source, "is_active", False)
                and position < len(binary_data)
            ):
                end_pos = min(position + chunk_size, len(binary_data))
                chunk = binary_data[position:end_pos]

                if hasattr(self, "live_reader") and self.live_reader is not None:
                    self.live_reader.add_data(chunk)
                else:
                    print("Live reader no longer available, stopping binary reader")
                    break

                position = end_pos

                if position % 10000 == 0:  # Progress every 10k words
                    print(f"LIST MODE: Fed {position}/{len(binary_data)} words")

                time.sleep(0.1)  # 10 Hz chunk feeding

            print("LIST MODE: Binary file simulation completed")

        # Stop any existing thread before starting new one
        if (
            hasattr(self, "dummy_thread")
            and self.dummy_thread
            and self.dummy_thread.is_alive()
        ):
            print("Waiting for existing dummy thread to stop...")
            time.sleep(0.2)

        self.dummy_thread = threading.Thread(target=dummy_list_mode_reader, daemon=True)
        self.dummy_thread.start()
        print("Started fresh dummy list mode thread")

    def start_dummy_traces_data(self):
        def dummy_traces_reader():
            if not Path(DUMMY_BINARY_FILE).exists():
                print(f"Dummy binary file not found: {DUMMY_BINARY_FILE}")
                return

            # ALWAYS start from beginning of file
            binary_data = np.fromfile(DUMMY_BINARY_FILE, dtype=np.uint32)
            print(
                f"TRACES MODE: Loaded {len(binary_data)} words from binary file (fresh start)"
            )

            chunk_size = 500  # Smaller chunks for traces
            position = 0  # Always start from 0

            while (
                hasattr(self, "data_source")
                and self.data_source is not None
                and getattr(self.data_source, "is_active", False)
                and position < len(binary_data)
            ):
                end_pos = min(position + chunk_size, len(binary_data))
                chunk = binary_data[position:end_pos]

                if hasattr(self, "live_reader") and self.live_reader is not None:
                    self.live_reader.add_data(chunk)
                else:
                    print("Live reader no longer available, stopping traces reader")
                    break

                position = end_pos

                if position % 5000 == 0:  # Progress every 5k words
                    print(f"TRACES MODE: Fed {position}/{len(binary_data)} words")

                time.sleep(0.2)  # 5 Hz chunk feeding for traces

            print("TRACES MODE: Binary file traces simulation completed")

        # Stop any existing thread before starting new one
        if (
            hasattr(self, "dummy_thread")
            and self.dummy_thread
            and self.dummy_thread.is_alive()
        ):
            print("Waiting for existing dummy thread to stop...")
            time.sleep(0.2)

        self.dummy_thread = threading.Thread(target=dummy_traces_reader, daemon=True)
        self.dummy_thread.start()
        print("Started fresh dummy traces thread")

    def accumulate_channel_data(self, channel, fresh_data):
        try:
            data_size = len(fresh_data)

            # Initialize arrays based on incoming data size
            if channel not in self.cumulative_mca_data:
                self.cumulative_mca_data[channel] = np.zeros(data_size, dtype=np.int64)
                self.mca_data[channel] = np.zeros(data_size, dtype=np.int32)
                print(f"Initialized channel {channel} with {data_size} bins")
            elif len(self.cumulative_mca_data[channel]) != data_size:
                # Data size changed, reinitialize
                self.cumulative_mca_data[channel] = np.zeros(data_size, dtype=np.int64)
                self.mca_data[channel] = np.zeros(data_size, dtype=np.int32)
                print(f"Resized channel {channel} to {data_size} bins")

            self.cumulative_mca_data[channel] += fresh_data
            self.mca_data[channel] = np.clip(
                self.cumulative_mca_data[channel], 0, np.iinfo(np.int32).max
            ).astype(np.int32)

            if hasattr(self.spectrum_tab, "update_mca_histogram"):
                self.spectrum_tab.update_mca_histogram(channel, self.mca_data[channel])

        except Exception as e:
            print(f"Error accumulating data for channel {channel}: {e}")

    def process_list_mode_event(self, event):
        try:
            channel = getattr(event, "channel", 0)
            energy = getattr(event, "energy", 0)

            if (
                hasattr(self.spectrum_tab, "energy_data")
                and channel in self.channel_numbers
            ):
                self.spectrum_tab.energy_data[channel].append(energy)

                if hasattr(self, "_event_counter"):
                    self._event_counter += 1
                else:
                    self._event_counter = 1

                if self._event_counter % 100 == 0:  # Update every 100 events
                    self.update_list_mode_channel_stats()

        except Exception as e:
            print(f"Error processing list mode event: {e}")

    def process_traces_event(self, event):
        """Enhanced traces event processing with real-time axis"""
        try:
            channel = getattr(event, "channel", 0)
            trace = getattr(event, "trace", None)
            timestamp = getattr(event, "timestamp", 0)

            if (
                hasattr(self, "spectrum_tab")
                and self.spectrum_tab
                and channel in self.channel_numbers
                and trace is not None
                and len(trace) > 0
            ):
                # Just use the standard add_trace - real-time axis calculated in update_plots()
                self.spectrum_tab.add_trace(channel, trace)

                # Update stats periodically
                if hasattr(self, "_trace_counter"):
                    self._trace_counter += 1
                else:
                    self._trace_counter = 1

                if self._trace_counter % 10 == 0:
                    self.update_traces_channel_stats()

        except Exception as e:
            print(f"Error processing traces event: {e}")

    def update_mca_channel_stats(self):
        """Update channel statistics for MCA mode"""
        try:
            channel_stats = {}

            # Get statistics from accumulated MCA data
            for channel in self.channel_numbers:
                if channel in self.mca_data:
                    total_counts = int(np.sum(self.mca_data[channel]))
                    channel_stats[channel] = total_counts
                else:
                    channel_stats[channel] = 0

            # Update the channel controls
            if hasattr(self, "channel_controls"):
                self.channel_controls.update_channel_statistics(channel_stats)

            print(f"MCA Stats updated: {channel_stats}")

        except Exception as e:
            print(f"Error updating MCA channel stats: {e}")

    def update_list_mode_channel_stats(self):
        """Update channel statistics for List Mode"""
        try:
            channel_stats = {}

            # Get statistics from energy data
            if hasattr(self.spectrum_tab, "energy_data"):
                for channel in self.channel_numbers:
                    if channel in self.spectrum_tab.energy_data:
                        event_count = len(self.spectrum_tab.energy_data[channel])
                        channel_stats[channel] = event_count
                    else:
                        channel_stats[channel] = 0
            else:
                # No energy data available
                for channel in self.channel_numbers:
                    channel_stats[channel] = 0

            # Update the channel controls
            if hasattr(self, "channel_controls"):
                self.channel_controls.update_channel_statistics(channel_stats)

            print(f"List Mode Stats updated: {channel_stats}")

        except Exception as e:
            print(f"Error updating List Mode channel stats: {e}")

    def update_traces_channel_stats(self):
        """Update channel statistics for Traces Mode"""
        try:
            channel_stats = {}

            # Get statistics from trace data
            if hasattr(self.spectrum_tab, "trace_data"):
                for channel in self.channel_numbers:
                    if channel in self.spectrum_tab.trace_data:
                        trace_count = len(self.spectrum_tab.trace_data[channel])
                        channel_stats[channel] = trace_count
                    else:
                        channel_stats[channel] = 0
            else:
                # No trace data available
                for channel in self.channel_numbers:
                    channel_stats[channel] = 0

            # Update the channel controls
            if hasattr(self, "channel_controls"):
                self.channel_controls.update_channel_statistics(channel_stats)

            print(f"Traces Stats updated: {channel_stats}")

        except Exception as e:
            print(f"Error updating Traces channel stats: {e}")

    def read_pixie_data(self):
        """Read data from PIXIE FIFO for list mode and traces (real hardware only)"""
        if not self.is_acquiring or not self.live_reader or self.dummy_mode:
            return

        try:
            # Use the actual pixie16 control function like in reference code
            data_list = px.control.read_list_mode_fifo(check=True, threshold=32)

            for data in data_list:
                if len(data) > 0:
                    self.live_reader.add_data(data)

        except Exception as e:
            print(f"Error reading PIXIE data: {e}")

    def clear_data(self):
        """Clear all data"""
        if self.current_mode == "mca_mode":
            # Reset cumulative MCA data
            for channel in self.channel_numbers:
                self.cumulative_mca_data[channel].fill(0)
                self.mca_data[channel].fill(0)

        # Clear plotter data
        if hasattr(self.spectrum_tab, "clear_data"):
            self.spectrum_tab.clear_data()

        mode_status = "DUMMY MODE - " if self.dummy_mode else ""
        self.info_bar.setText(f"{mode_status}All data cleared")

    def update_display_channels(self, selected_channels):
        print(f"Scope: channels changed to {selected_channels}")
        print(f"Scope: current mode is {self.current_mode}")

        try:
            # Update the spectrum plotter's display channels
            if hasattr(self.spectrum_tab, "set_display_channels"):
                print(f"Calling set_display_channels with {selected_channels}")
                self.spectrum_tab.set_display_channels(selected_channels)
            elif hasattr(self.spectrum_tab, "set_channels"):
                print(f"Calling set_channels with {selected_channels}")
                self.spectrum_tab.set_channels(selected_channels)
            else:
                print(f"ERROR: spectrum_tab doesn't have display channel methods")
                print(f"spectrum_tab type: {type(self.spectrum_tab)}")
                print(
                    f"spectrum_tab methods: {[m for m in dir(self.spectrum_tab) if not m.startswith('_')]}"
                )

            # Update status message
            if selected_channels:
                mode_status = "DUMMY MODE - " if self.dummy_mode else ""
                self.info_bar.setText(
                    f"{mode_status}Displaying {len(selected_channels)} channels: {selected_channels}"
                )
            else:
                self.info_bar.setText("No channels selected for display")

        except Exception as e:
            print(f"ERROR in update_display_channels: {e}")
            import traceback

            traceback.print_exc()

    def handle_parameter_change(self, param_name, value, module, channel):
        """Handle parameter changes from the UI"""
        try:
            if not self.dummy_mode:
                # Real hardware - use px.control like in reference code
                px.control.set_channel_parameter(param_name, value, module, channel)
                self.info_bar.setText(
                    f"Set {param_name} = {value} on M{module}:Ch{channel}"
                )
            else:
                self.info_bar.setText(
                    f"DUMMY MODE - {param_name} = {value} on M{module}:Ch{channel}"
                )
        except Exception as e:
            error_msg = f"Error setting {param_name}: {e}"
            self.info_bar.setText(error_msg)

    def handle_apply_all_parameters(self, params_dict, module, channel):
        """Handle applying all parameters"""
        try:
            if not self.dummy_mode:
                # Real hardware - apply each parameter
                for param_name, value in params_dict.items():
                    px.control.set_channel_parameter(param_name, value, module, channel)
                self.info_bar.setText(
                    f"Applied all {len(params_dict)} parameters to M{module}:Ch{channel}"
                )
            else:
                self.info_bar.setText(
                    f"DUMMY MODE - Applied {len(params_dict)} parameters to M{module}:Ch{channel}"
                )
        except Exception as e:
            error_msg = f"Error applying parameters: {e}"
            self.info_bar.setText(error_msg)

    def update_info_bar(self, message):
        """Update the info bar with a message"""
        mode_status = "DUMMY MODE - " if self.dummy_mode else ""
        self.info_bar.setText(f"{mode_status}{message}")

    def init_pixie16(self):
        try:
            if not self.dummy_mode:
                print("Booting PIXIE-16...")
                available_modules = [self.module_number]  # Convert to list
                px.control.init_and_boot(modules=available_modules)
                self.info_bar.setText(
                    f"PIXIE-16 Module {self.module_number} initialized"
                )
            else:
                self.info_bar.setText("DUMMY MODE - No hardware initialization")
        except Exception as e:
            if "invalid module count" in str(e):
                error_msg = f"Module {self.module_number} not available. Check hardware connections."
            else:
                error_msg = f"Failed to initialize PIXIE-16: {str(e)}"

            QMessageBox.critical(self, "PIXIE-16 Initialization Error", error_msg)
            self.info_bar.setText("Initialization failed - check hardware")

    def setup_timers(self):
        """Set up update timers"""
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)  # 1s

        # Only create data timer for real hardware
        if not self.dummy_mode:
            self.data_timer = QTimer()
            self.data_timer.timeout.connect(self.read_pixie_data)

    def update_status(self):
        if self.live_reader:
            try:
                stats = self.live_reader.get_statistics()
                rate = stats.get("processing_rate", 0)
                events = stats.get("events_processed", 0)

                self.rate_label.setText(f"Rate: {rate:.1f} Hz")
                self.events_label.setText(f"Events: {events}")

            except Exception as e:
                print(f"Error updating status: {e}")

        try:
            if self.current_mode == "mca_mode":
                self.update_mca_channel_stats()
            elif self.current_mode == "list_mode":
                self.update_list_mode_channel_stats()
            elif self.current_mode == "traces_mode":
                self.update_traces_channel_stats()
        except Exception as e:
            print(f"Error updating channel statistics: {e}")

    def closeEvent(self, event):
        try:
            print("Shutting down Pixie16 Scope...")

            # Stop acquisition first
            if self.is_acquiring:
                self.stop_acquisition()

            # Stop all timers
            if hasattr(self, "status_timer") and self.status_timer:
                self.status_timer.stop()
                self.status_timer = None

            if hasattr(self, "acquisition_timer") and self.acquisition_timer:
                self.acquisition_timer.stop()
                self.acquisition_timer = None

            if hasattr(self, "data_timer") and self.data_timer:
                self.data_timer.stop()
                self.data_timer = None

            # Clean up data source and threads
            if hasattr(self, "data_source") and self.data_source:
                self.data_source.stop_acquisition()
                self.data_source = None

            if hasattr(self, "live_reader") and self.live_reader:
                self.live_reader = None

            # Stop dummy threads if they exist
            if (
                hasattr(self, "dummy_thread")
                and self.dummy_thread
                and self.dummy_thread.is_alive()
            ):
                # The thread will stop when data_source.is_active becomes False
                pass

            # Clean up spectrum tab BEFORE setting parent to None
            if hasattr(self, "spectrum_tab") and self.spectrum_tab:
                try:
                    if hasattr(self.spectrum_tab, "stop_live_updates"):
                        self.spectrum_tab.stop_live_updates()

                    # Remove from layout first
                    if hasattr(self, "left_layout"):
                        self.left_layout.removeWidget(self.spectrum_tab)

                    # Then delete the widget

                    self.spectrum_tab.deleteLater()
                    self.spectrum_tab = None

                except Exception as e:
                    print(f"Error cleaning up spectrum tab: {e}")

            # Exit PIXIE system for real hardware
            if not self.dummy_mode:
                try:
                    px.control.exit_system()
                    print("PIXIE system shut down")
                except Exception as e:
                    print(f"Error shutting down PIXIE system: {e}")

            # Process any remaining events
            if hasattr(QApplication, "processEvents"):
                QApplication.processEvents()

            print("Shutdown complete")

        except Exception as e:
            print(f"Error during shutdown: {e}")
        finally:
            event.accept()


def main():
    args = docopt(__doc__)

    dummy_mode = args["--dummy"]
    module_number = int(args["--module"]) if args["--module"] else 2

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

    # Print startup info
    if dummy_mode:
        print("Starting Pixie16 Scope in DUMMY MODE")
        print(f"  - MCA data source: {DUMMY_NUMPY_FILE}")
        print(f"  - Binary data source: {DUMMY_BINARY_FILE}")
    else:
        print("Starting Pixie16 Scope with REAL HARDWARE")
        print(f"  - Module: {module_number}")
        print(f"  - Channels: {channels}")

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
