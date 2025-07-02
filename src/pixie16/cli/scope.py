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
    px = None

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


class PixieHardwareInterface:
    """Handles PIXIE-16 hardware interaction with proper error handling"""

    def __init__(self, module_number: int, dummy_mode: bool = False):
        self.module_number = module_number
        self.dummy_mode = dummy_mode
        self.is_initialized = False
        self.is_histogram_running = False
        self.enabled_channels = []

    def initialize(self) -> bool:
        """Initialize PIXIE-16 hardware with proper error checking"""
        if self.dummy_mode:
            print("Dummy mode: Simulating PIXIE-16 initialization")
            self.is_initialized = True
            self.enabled_channels = list(range(16))  # All channels available in dummy
            return True

        if px is None:
            raise RuntimeError("pypixie16 not available")

        try:
            # Use the actual pypixie16 API - init_and_boot function
            print(f"Testing PIXIE-16 module {self.module_number}...")

            # Try to initialize this module using actual pypixie16 function
            px.control.init_and_boot(modules=[self.module_number])

            # If we get here without exception, module was found
            print(f"Module {self.module_number} initialization successful")

            # For now, assume all 16 channels are enabled (can't easily check without hardware)
            # In real usage, user would specify which channels are actually connected
            self.enabled_channels = list(range(16))
            print(f"Assuming all 16 channels are available")

            self.is_initialized = True
            return True

        except Exception as e:
            error_msg = str(e).lower()
            if (
                "invalid module" in error_msg
                or "module count" in error_msg
                or "not found" in error_msg
            ):
                print(
                    f"Module {self.module_number} not available - check hardware connections"
                )
            else:
                print(f"PIXIE-16 initialization error: {e}")
            return False

    def start_histogram_mode(self) -> bool:
        """Start continuous histogram collection using actual pypixie16 API"""
        if self.dummy_mode:
            print("Dummy mode: Starting histogram simulation")
            self.is_histogram_running = True
            return True

        try:
            # Apply basic settings for histogram mode
            settings = {
                "channels": [(self.module_number, ch) for ch in self.enabled_channels],
                "CaptureHistogram": True,
                "CaptureTrace": False,
            }
            px.control.change_setting_from_dict(settings, call_pixie=True)

            # Use the actual pypixie16 function
            px.control.start_histogram_run()
            self.is_histogram_running = True
            print(f"Started histogram collection on module {self.module_number}")
            return True

        except Exception as e:
            print(f"Failed to start histogram mode: {e}")
            return False

    def read_histograms(self) -> dict:
        """Read current histogram data from all enabled channels"""
        if self.dummy_mode:
            return self._generate_dummy_histograms()

        histograms = {}
        try:
            # Use the actual pypixie16 API function
            module_channels = [(self.module_number, ch) for ch in self.enabled_channels]
            hist_list = px.control.read_histograms(module_channels)

            # Convert list to dict keyed by channel number
            for i, channel in enumerate(self.enabled_channels):
                if i < len(hist_list):
                    histograms[channel] = np.array(hist_list[i], dtype=np.int32)

        except Exception as e:
            print(f"Error reading histograms: {e}")

        return histograms

    def _generate_dummy_histograms(self) -> dict:
        """Generate realistic dummy histogram data"""
        histograms = {}

        for channel in self.enabled_channels[:4]:  # Limit to first 4 channels for demo
            # Create realistic spectrum with peaks
            spectrum = np.zeros(32768, dtype=np.int32)

            # Add some peaks at different energies
            peaks = [500 + channel * 100, 1200 + channel * 50, 2400, 4000, 6000]
            for peak in peaks:
                if peak < 32768:
                    # Gaussian peak with some width
                    sigma = 20 + channel * 2
                    counts = int(1000 * (1 + np.random.random()))
                    for i in range(max(0, peak - 100), min(32768, peak + 100)):
                        spectrum[i] += int(
                            counts * np.exp(-0.5 * ((i - peak) / sigma) ** 2)
                        )

            # Add background
            background = np.random.poisson(5, 32768)
            spectrum += background

            # Accumulate over time
            spectrum = spectrum * int(time.time() % 60 + 1)  # Slow accumulation

            histograms[channel] = spectrum

        return histograms

    def stop_histogram_mode(self):
        """Stop histogram collection"""
        if self.dummy_mode:
            self.is_histogram_running = False
            return

        try:
            if self.is_histogram_running:
                px.control.end_run()
                self.is_histogram_running = False
                print("Stopped histogram collection")
        except Exception as e:
            print(f"Error stopping histogram mode: {e}")

    def cleanup(self):
        """Clean shutdown"""
        if self.is_histogram_running:
            self.stop_histogram_mode()
        if self.is_initialized and not self.dummy_mode and px:
            try:
                px.control.exit_system()
                print("PIXIE system shutdown complete")
            except Exception as e:
                print(f"Error during shutdown: {e}")


class FixedPixieScopeApp(QMainWindow):
    """Fixed PIXIE-16 Scope with proper data handling"""

    def __init__(self, dummy_mode=False, module_number=2, channels=None):
        super().__init__()

        self.setWindowTitle("Fixed Pixie16 Scope")
        self.setGeometry(100, 100, 1600, 1000)

        self.dummy_mode = dummy_mode
        self.module_number = module_number

        if channels is None:
            channels = list(range(16))
        self.channel_numbers = channels

        # Initialize hardware interface
        self.pixie_hw = PixieHardwareInterface(module_number, dummy_mode)

        # Initialize hardware
        if not self.pixie_hw.initialize():
            QMessageBox.critical(
                self,
                "Hardware Error",
                f"Failed to initialize PIXIE-16 module {module_number}",
            )
            if not dummy_mode:
                sys.exit(1)

        self.enabled_channels = self.pixie_hw.enabled_channels
        self.live_reader = None
        self.data_source = None
        self.is_acquiring = False
        self.current_mode = "mca_mode"
        self.acquisition_timer = None

        # Data storage
        self.mca_data = {}
        self.cumulative_mca_data = {}

        # Initialize data storage for enabled channels
        for ch in self.enabled_channels:
            self.cumulative_mca_data[ch] = np.zeros(32768, dtype=np.int64)
            self.mca_data[ch] = np.zeros(32768, dtype=np.int32)

        # PIXIE-16 settings
        self.settings = {
            "channels": [(self.module_number, ch) for ch in self.enabled_channels],
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

        self.init_ui()
        self.setup_timers()

    def init_ui(self):
        """Initialize the user interface"""
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
            channels=self.enabled_channels, title="PIXIE-16 MCA Spectra"
        )
        self.left_layout.addWidget(self.spectrum_tab)

        # Right side - controls
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5, 5, 5, 5)

        # Create channel controls with correct mapping
        self.channel_controls = ChannelDisplayControls(
            channels=[(self.module_number, ch) for ch in self.enabled_channels],
            title="Channels",
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

        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.addWidget(main_splitter)

        # Info bar
        self.info_bar = QLabel(
            f"Ready - Module {self.module_number} with {len(self.enabled_channels)} enabled channels"
        )
        self.info_bar.setMaximumHeight(25)
        main_layout.addWidget(self.info_bar)

        main_widget.setLayout(main_layout)

        if self.dummy_mode:
            self.info_bar.setText(
                f"DUMMY MODE - Module {self.module_number} simulation"
            )

        # Debug: Print initial state
        print(f"UI initialized:")
        print(f"  - Module: {self.module_number}")
        print(f"  - Enabled channels: {self.enabled_channels}")
        print(
            f"  - Channel controls created for: {[(self.module_number, ch) for ch in self.enabled_channels]}"
        )

    def create_control_panel(self):
        """Create the control panel"""
        group = QGroupBox("Controls")
        group.setMaximumHeight(100)
        layout = QVBoxLayout()

        top_layout = QHBoxLayout()

        # Mode selection
        top_layout.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["MCA Mode", "List Mode", "Traces Mode"])
        self.mode_combo.currentTextChanged.connect(self.on_mode_changed)
        top_layout.addWidget(self.mode_combo)

        # Acquisition control buttons
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.start_acquisition)
        top_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_acquisition)
        self.stop_btn.setEnabled(False)
        top_layout.addWidget(self.stop_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_data)
        top_layout.addWidget(self.clear_btn)

        top_layout.addStretch()

        # Status display
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Status: Ready")
        self.rate_label = QLabel("Rate: 0 Hz")
        self.events_label = QLabel("Events: 0")

        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.rate_label)
        status_layout.addWidget(self.events_label)
        status_layout.addStretch()

        layout.addLayout(top_layout)
        layout.addLayout(status_layout)
        group.setLayout(layout)
        return group

    def on_mode_changed(self, mode_text):
        """Handle mode changes"""
        if self.is_acquiring:
            self.stop_acquisition()

        old_mode = self.current_mode
        self.current_mode = mode_text.lower().replace(" ", "_")

        # Clean up old spectrum tab
        if hasattr(self, "spectrum_tab") and self.spectrum_tab:
            if hasattr(self.spectrum_tab, "stop_live_updates"):
                self.spectrum_tab.stop_live_updates()
            self.left_layout.removeWidget(self.spectrum_tab)
            self.spectrum_tab.setParent(None)

        # Create new spectrum tab
        if self.current_mode == "mca_mode":
            self.spectrum_tab = MCASpectrumPlotter(
                channels=self.enabled_channels, title="PIXIE-16 MCA Spectra"
            )
        elif self.current_mode == "list_mode":
            self.spectrum_tab = ContinuousSpectrumPlotter(
                app=None,
                instrument_name="pixie16",
                display_name="PIXIE-16 List Mode Spectra",
                channels=self.enabled_channels,
                energy_range=(0, 4096),
                bins=1000,
            )
        elif self.current_mode == "traces_mode":
            self.spectrum_tab = TracesPlotter(
                channels=self.enabled_channels, title="PIXIE-16 Traces"
            )

        self.left_layout.addWidget(self.spectrum_tab)
        self.info_bar.setText(f"Mode changed: {old_mode} -> {self.current_mode}")

    def start_acquisition(self):
        """Start acquisition based on current mode"""
        try:
            if self.current_mode == "mca_mode":
                self.start_mca_acquisition()
            elif self.current_mode == "list_mode":
                self.start_list_mode_acquisition()
            elif self.current_mode == "traces_mode":
                self.start_traces_acquisition()

            self.is_acquiring = True
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.status_label.setText(f"Status: Acquiring ({self.current_mode})")

        except Exception as e:
            error_msg = f"Failed to start acquisition: {str(e)}"
            print(error_msg)
            self.info_bar.setText(error_msg)

    def start_mca_acquisition(self):
        """Start MCA mode - uses histogram collection"""
        try:
            # Start hardware histogram collection
            if not self.pixie_hw.start_histogram_mode():
                raise RuntimeError("Failed to start histogram mode")

            # Start the MCA plotter's update timer
            if hasattr(self.spectrum_tab, "start_live_updates"):
                self.spectrum_tab.start_live_updates()

            # Set up timer to read histogram data
            self.acquisition_timer = QTimer()
            self.acquisition_timer.timeout.connect(self.read_histogram_data)
            self.acquisition_timer.start(2000)  # Read every 2 seconds

            mode_status = "DUMMY MODE - " if self.dummy_mode else ""
            self.info_bar.setText(f"{mode_status}MCA mode: Collecting histograms...")

        except Exception as e:
            error_msg = f"Error starting MCA: {str(e)}"
            print(error_msg)
            self.info_bar.setText(error_msg)
            raise

    def start_list_mode_acquisition(self):
        """Start list mode - uses binary data processing"""
        try:
            if not self.dummy_mode:
                # Real hardware list mode
                px.control.change_setting_from_dict(self.settings, call_pixie=True)
                px.control.start_list_mode_run()

            # Set up live data reader for binary processing
            self.live_reader = LiveDataReader()
            self.data_source = LiveDataSourceInterface(self.live_reader)
            self.live_reader.add_event_callback(self.process_list_mode_event)

            if self.dummy_mode:
                self.start_binary_file_reader()
            else:
                # For real hardware, start FIFO reading timer
                self.data_timer = QTimer()
                self.data_timer.timeout.connect(self.read_pixie_fifo)
                self.data_timer.start(50)

            self.data_source.start_acquisition()

            if hasattr(self.spectrum_tab, "start_live_updates"):
                self.spectrum_tab.start_live_updates()

            mode_status = "DUMMY MODE - " if self.dummy_mode else ""
            self.info_bar.setText(f"{mode_status}List mode: Processing events...")

        except Exception as e:
            error_msg = f"Error starting list mode: {str(e)}"
            print(error_msg)
            self.info_bar.setText(error_msg)
            raise

    def start_traces_acquisition(self):
        """Start traces mode - similar to list mode but with trace capture"""
        try:
            if not self.dummy_mode:
                trace_settings = self.settings.copy()
                trace_settings["CaptureTrace"] = True
                px.control.change_setting_from_dict(trace_settings, call_pixie=True)
                px.control.start_list_mode_run()

            # Set up live data reader
            self.live_reader = LiveDataReader()
            self.data_source = LiveDataSourceInterface(self.live_reader)
            self.live_reader.add_event_callback(self.process_traces_event)

            if self.dummy_mode:
                self.start_binary_file_reader()
            else:
                self.data_timer = QTimer()
                self.data_timer.timeout.connect(self.read_pixie_fifo)
                self.data_timer.start(100)

            self.data_source.start_acquisition()

            if hasattr(self.spectrum_tab, "start_live_updates"):
                self.spectrum_tab.start_live_updates()

            mode_status = "DUMMY MODE - " if self.dummy_mode else ""
            self.info_bar.setText(f"{mode_status}Traces mode: Capturing traces...")

        except Exception as e:
            error_msg = f"Error starting traces mode: {str(e)}"
            print(error_msg)
            self.info_bar.setText(error_msg)
            raise

    def read_histogram_data(self):
        """Read histogram data from hardware (MCA mode only)"""
        try:
            # Read histograms from hardware interface
            histograms = self.pixie_hw.read_histograms()

            # Track statistics for channel controls
            channel_stats = {}

            for channel, histogram in histograms.items():
                if channel in self.enabled_channels:
                    # Update data
                    if len(histogram) != len(self.cumulative_mca_data[channel]):
                        # Resize if needed
                        self.cumulative_mca_data[channel] = np.zeros_like(
                            histogram, dtype=np.int64
                        )
                        self.mca_data[channel] = np.zeros_like(
                            histogram, dtype=np.int32
                        )

                    self.cumulative_mca_data[channel] = histogram.astype(np.int64)
                    self.mca_data[channel] = np.clip(
                        self.cumulative_mca_data[channel], 0, np.iinfo(np.int32).max
                    ).astype(np.int32)

                    # Update display
                    if hasattr(self.spectrum_tab, "update_mca_histogram"):
                        self.spectrum_tab.update_mca_histogram(
                            channel, self.mca_data[channel]
                        )

                    # Calculate statistics
                    total_counts = int(np.sum(self.mca_data[channel]))
                    channel_stats[channel] = total_counts

                    if total_counts > 0:
                        print(f"Channel {channel}: {total_counts:,} total counts")

            # Update channel controls with all statistics at once
            if channel_stats and hasattr(self, "channel_controls"):
                self.channel_controls.update_channel_statistics(channel_stats)
                print(f"Updated channel statistics: {channel_stats}")

        except Exception as e:
            print(f"Error reading histogram data: {e}")

    def start_binary_file_reader(self):
        """Start binary file reader for dummy mode"""

        def binary_reader():
            if not Path(DUMMY_BINARY_FILE).exists():
                print(f"Dummy binary file not found: {DUMMY_BINARY_FILE}")
                return

            binary_data = np.fromfile(DUMMY_BINARY_FILE, dtype=np.uint32)
            print(f"Loaded {len(binary_data)} words from binary file")

            chunk_size = 1000
            position = 0

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
                    break

                position = end_pos
                time.sleep(0.1)  # 10 Hz feeding rate

            print("Binary file processing completed")

        self.binary_thread = threading.Thread(target=binary_reader, daemon=True)
        self.binary_thread.start()

    def read_pixie_fifo(self):
        """Read data from PIXIE FIFO for real hardware"""
        if not self.is_acquiring or not self.live_reader or self.dummy_mode:
            return

        try:
            data_list = px.control.read_list_mode_fifo(check=True, threshold=32)
            for data in data_list:
                if len(data) > 0:
                    self.live_reader.add_data(data)
        except Exception as e:
            print(f"Error reading PIXIE FIFO: {e}")

    def process_list_mode_event(self, event):
        """Process list mode events"""
        try:
            channel = getattr(event, "channel", 0)
            energy = getattr(event, "energy", 0)

            if channel in self.enabled_channels:
                # Pass event to spectrum tab for processing
                if hasattr(self.spectrum_tab, "energy_data"):
                    if channel not in self.spectrum_tab.energy_data:
                        self.spectrum_tab.energy_data[channel] = []
                    self.spectrum_tab.energy_data[channel].append(energy)

                # Update statistics periodically to avoid UI slowdown
                if not hasattr(self, "_list_mode_event_counter"):
                    self._list_mode_event_counter = 0

                self._list_mode_event_counter += 1

                # Update stats every 100 events
                if self._list_mode_event_counter % 100 == 0:
                    self.update_list_mode_channel_stats()

        except Exception as e:
            print(f"Error processing list mode event: {e}")

    def process_traces_event(self, event):
        """Process traces events"""
        try:
            channel = getattr(event, "channel", 0)
            trace = getattr(event, "trace", None)

            if (
                channel in self.enabled_channels
                and trace is not None
                and len(trace) > 0
            ):
                # Pass trace to spectrum tab for processing
                if hasattr(self.spectrum_tab, "add_trace"):
                    self.spectrum_tab.add_trace(channel, trace)
                elif hasattr(self.spectrum_tab, "trace_data"):
                    if channel not in self.spectrum_tab.trace_data:
                        from collections import deque

                        self.spectrum_tab.trace_data[channel] = deque(maxlen=100)
                    self.spectrum_tab.trace_data[channel].append(trace)

                # Update statistics periodically
                if not hasattr(self, "_traces_event_counter"):
                    self._traces_event_counter = 0

                self._traces_event_counter += 1

                # Update stats every 10 traces to avoid UI slowdown
                if self._traces_event_counter % 10 == 0:
                    self.update_traces_channel_stats()

        except Exception as e:
            print(f"Error processing traces event: {e}")

    def stop_acquisition(self):
        """Stop current acquisition"""
        try:
            if self.acquisition_timer:
                self.acquisition_timer.stop()

            if hasattr(self.spectrum_tab, "stop_live_updates"):
                self.spectrum_tab.stop_live_updates()

            if hasattr(self, "data_timer") and hasattr(self.data_timer, "stop"):
                self.data_timer.stop()

            if hasattr(self, "data_source") and self.data_source:
                self.data_source.stop_acquisition()

            # Stop hardware
            if self.current_mode == "mca_mode":
                self.pixie_hw.stop_histogram_mode()
            else:
                # For list mode and traces mode
                if not self.dummy_mode and px:
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

        except Exception as e:
            print(f"Error stopping acquisition: {e}")

    def clear_data(self):
        """Clear all accumulated data"""
        if self.current_mode == "mca_mode":
            for channel in self.enabled_channels:
                if channel in self.cumulative_mca_data:
                    self.cumulative_mca_data[channel].fill(0)
                if channel in self.mca_data:
                    self.mca_data[channel].fill(0)

        if hasattr(self.spectrum_tab, "clear_data"):
            self.spectrum_tab.clear_data()

        mode_status = "DUMMY MODE - " if self.dummy_mode else ""
        self.info_bar.setText(f"{mode_status}All data cleared")

    def update_display_channels(self, selected_channels):
        """Update which channels are displayed"""
        try:
            # Filter to only enabled channels
            valid_channels = [
                ch for ch in selected_channels if ch in self.enabled_channels
            ]

            if hasattr(self.spectrum_tab, "set_display_channels"):
                self.spectrum_tab.set_display_channels(valid_channels)
            elif hasattr(self.spectrum_tab, "set_channels"):
                self.spectrum_tab.set_channels(valid_channels)

            self.info_bar.setText(
                f"Displaying {len(valid_channels)} channels: {valid_channels}"
            )

        except Exception as e:
            print(f"Error updating display channels: {e}")

    def handle_parameter_change(self, param_name, value, module, channel):
        """Handle parameter changes"""
        try:
            if not self.dummy_mode and px:
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
            if not self.dummy_mode and px:
                for param_name, value in params_dict.items():
                    px.control.set_channel_parameter(param_name, value, module, channel)
                self.info_bar.setText(
                    f"Applied {len(params_dict)} parameters to M{module}:Ch{channel}"
                )
            else:
                self.info_bar.setText(
                    f"DUMMY MODE - Applied {len(params_dict)} parameters"
                )
        except Exception as e:
            error_msg = f"Error applying parameters: {e}"
            self.info_bar.setText(error_msg)

    def update_info_bar(self, message):
        """Update info bar with message"""
        mode_status = "DUMMY MODE - " if self.dummy_mode else ""
        self.info_bar.setText(f"{mode_status}{message}")

    def setup_timers(self):
        """Set up status update timers"""
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)  # 1 second updates

    def update_status(self):
        """Update status display"""
        try:
            # Update live reader statistics
            if self.live_reader:
                try:
                    stats = self.live_reader.get_statistics()
                    rate = stats.get("processing_rate", 0)
                    events = stats.get("events_processed", 0)
                    self.rate_label.setText(f"Rate: {rate:.1f} Hz")
                    self.events_label.setText(f"Events: {events}")
                except Exception as e:
                    print(f"Error updating live reader stats: {e}")

            # Update mode-specific channel statistics
            if self.current_mode == "mca_mode":
                self.update_mca_channel_stats()
            elif self.current_mode == "list_mode":
                self.update_list_mode_channel_stats()
            elif self.current_mode == "traces_mode":
                self.update_traces_channel_stats()

        except Exception as e:
            print(f"Error in update_status: {e}")

    def update_mca_channel_stats(self):
        """Update channel statistics for MCA mode"""
        try:
            if not hasattr(self, "mca_data") or not self.mca_data:
                return

            channel_stats = {}
            for channel in self.enabled_channels:
                if channel in self.mca_data and len(self.mca_data[channel]) > 0:
                    total_counts = int(np.sum(self.mca_data[channel]))
                    channel_stats[channel] = total_counts
                else:
                    channel_stats[channel] = 0

            # Update channel controls
            if channel_stats and hasattr(self, "channel_controls"):
                self.channel_controls.update_channel_statistics(channel_stats)

        except Exception as e:
            print(f"Error updating MCA channel stats: {e}")

    def update_list_mode_channel_stats(self):
        """Update channel statistics for List Mode"""
        try:
            channel_stats = {}

            # Get statistics from energy data in spectrum tab
            if hasattr(self.spectrum_tab, "energy_data") and hasattr(
                self.spectrum_tab.energy_data, "keys"
            ):
                for channel in self.enabled_channels:
                    if channel in self.spectrum_tab.energy_data:
                        event_count = len(self.spectrum_tab.energy_data[channel])
                        channel_stats[channel] = event_count
                    else:
                        channel_stats[channel] = 0
            else:
                # Fallback - check if spectrum tab has other data structures
                for channel in self.enabled_channels:
                    channel_stats[channel] = 0

            # Update channel controls
            if channel_stats and hasattr(self, "channel_controls"):
                self.channel_controls.update_channel_statistics(channel_stats)

        except Exception as e:
            print(f"Error updating List Mode channel stats: {e}")

    def update_traces_channel_stats(self):
        """Update channel statistics for Traces Mode"""
        try:
            channel_stats = {}

            # Get statistics from trace data in spectrum tab
            if hasattr(self.spectrum_tab, "trace_data") and hasattr(
                self.spectrum_tab.trace_data, "keys"
            ):
                for channel in self.enabled_channels:
                    if channel in self.spectrum_tab.trace_data:
                        trace_count = len(self.spectrum_tab.trace_data[channel])
                        channel_stats[channel] = trace_count
                    else:
                        channel_stats[channel] = 0
            else:
                # Fallback
                for channel in self.enabled_channels:
                    channel_stats[channel] = 0

            # Update channel controls
            if channel_stats and hasattr(self, "channel_controls"):
                self.channel_controls.update_channel_statistics(channel_stats)

        except Exception as e:
            print(f"Error updating Traces channel stats: {e}")

    def closeEvent(self, event):
        try:
            print("Shutting down PIXIE-16 Scope...")

            # Stop acquisition
            if self.is_acquiring:
                self.stop_acquisition()
                time.sleep(0.5)
            # Stop all timers
            if hasattr(self, "status_timer") and self.status_timer:
                self.status_timer.stop()
                self.status_timer.deleteLater()
                self.status_timer = None
            if hasattr(self, "acquisition_timer") and self.acquisition_timer:
                self.acquisition_timer.stop()
                self.acquisition_timer.deleteLater()
                self.acquisition_timer = None
            # Stop binary file threads (for dummy mode)
            if (
                hasattr(self, "binary_thread")
                and self.binary_thread
                and self.binary_thread.is_alive()
            ):
                print("  Stopping binary thread...")
                # thread should stop when data_source.is_active becomes False
                time.sleep(0.2)

            # Clean up data source and live reader
            print("  Cleaning up data interfaces...")
            if hasattr(self, "data_source") and self.data_source:
                try:
                    self.data_source.stop_acquisition()
                except:
                    pass
                self.data_source = None

            if hasattr(self, "live_reader") and self.live_reader:
                try:
                    if hasattr(self.live_reader, "stop_processing"):
                        self.live_reader.stop_processing()
                except:
                    pass
                self.live_reader = None
            if hasattr(self, "spectrum_tab") and self.spectrum_tab:
                try:
                    # Stop any live updates
                    if hasattr(self.spectrum_tab, "stop_live_updates"):
                        self.spectrum_tab.stop_live_updates()

                    # Stop any timers in the spectrum tab
                    if (
                        hasattr(self.spectrum_tab, "update_timer")
                        and self.spectrum_tab.update_timer
                    ):
                        self.spectrum_tab.update_timer.stop()
                        self.spectrum_tab.update_timer.deleteLater()

                    # Remove from layout BEFORE deleting
                    if hasattr(self, "left_layout"):
                        self.left_layout.removeWidget(self.spectrum_tab)

                    # Set parent to None to prevent Qt from trying to delete it twice
                    self.spectrum_tab.setParent(None)

                    # Delete the widget
                    self.spectrum_tab.deleteLater()
                    self.spectrum_tab = None

                except Exception as e:
                    print(f"    Error cleaning up spectrum tab: {e}")

            # Clean up other UI components
            if hasattr(self, "channel_controls") and self.channel_controls:
                try:
                    self.channel_controls.setParent(None)
                    self.channel_controls.deleteLater()
                    self.channel_controls = None
                except:
                    pass

            if hasattr(self, "parameter_controls") and self.parameter_controls:
                try:
                    self.parameter_controls.setParent(None)
                    self.parameter_controls.deleteLater()
                    self.parameter_controls = None
                except:
                    pass

            if hasattr(self, "pixie_hw") and self.pixie_hw:  # cleanup hardware
                try:
                    self.pixie_hw.cleanup()
                except Exception as e:
                    print(f"    Error during hardware cleanup: {e}")
            if hasattr(QApplication, "processEvents"):
                QApplication.processEvents()
                time.sleep(0.1)  # Give Qt time to clean up
                QApplication.processEvents()

            print("  Shutdown complete")
        except Exception as e:
            print(f"Error during shutdown: {e}")
            # Even if there's an error, accept the close event
        finally:
            event.accept()  # Always accept the close event to prevent hanging


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="PIXIE-16 Scope")
    parser.add_argument("--dummy", action="store_true", help="Run in dummy mode")
    parser.add_argument("--module", type=int, default=2, help="Module number")
    parser.add_argument(
        "--channels",
        type=str,
        default="0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15",
        help="Comma-separated channel list",
    )

    args = parser.parse_args()

    # Parse channels
    try:
        channels = [int(ch.strip()) for ch in args.channels.split(",")]
    except ValueError:
        print("Error: Invalid channel list format")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("Fixed Pixie16 Scope")

    # Print startup info
    if args.dummy:
        print("Starting PIXIE-16 Scope in DUMMY MODE")
        print(f"  - Binary data source: {DUMMY_BINARY_FILE}")
    else:
        print("Starting PIXIE-16 Scope with REAL HARDWARE")
        print(f"  - Module: {args.module}")
        print(f"  - Channels: {channels}")

    try:
        window = FixedPixieScopeApp(
            dummy_mode=args.dummy, module_number=args.module, channels=channels
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
