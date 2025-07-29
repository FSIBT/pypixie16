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
import signal
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

from .binary_loader import BinaryFileLoader

# Import the plotting modules
from pixie16.ui.mca_spectrum_plotter import MCASpectrumPlotter
from pixie16.ui.spectrum_plotter import ContinuousSpectrumPlotter
from pixie16.ui.traces_plotter import TracesPlotter
from pixie16.ui.channel_controls import ChannelDisplayControls
from pixie16.ui.parameter_controls import ParameterControls

import logging

logger = logging.getLogger(__name__)


class PixieHardwareManager:
    def __init__(self, physical_slot: int = 2, dummy_mode: bool = False):
        self.physical_slot = physical_slot
        self.dummy_mode = dummy_mode
        self.is_initialized = False
        self.is_running = False
        self.current_mode = None  # 'histogram', 'list', or None
        self.enabled_channels = list(range(16))  # All 16 channels

    def initialize_system(self) -> bool:
        if self.dummy_mode:
            print("DUMMY MODE: Simulating PIXIE-16 initialization")
            self.is_initialized = True
            return True

        if px is None:
            raise RuntimeError("pypixie16 not available")

        try:
            print(f"Initializing PIXIE-16 system...")
            print(f"Physical slot: {self.physical_slot}")

            # Initialize and boot the system
            px.control.init_and_boot(modules=[self.physical_slot], verbose=True)

            # Verify initialization worked
            try:
                settings = px.control.read_settings()
                if len(settings) > 0:
                    print(f"✓ PIXIE-16 system initialized successfully")
                    print(f"  Logical modules available: {len(settings)}")
                    self.is_initialized = True
                    return True
                else:
                    raise RuntimeError("No modules found after initialization")
            except Exception as e:
                raise RuntimeError(f"Initialization verification failed: {e}")

        except Exception as e:
            print(f"PIXIE-16 initialization failed: {e}")
            return False

    def start_histogram_mode(self) -> bool:
        if self.dummy_mode:
            print("DUMMY MODE: Starting histogram collection")
            self.is_running = True
            self.current_mode = "histogram"
            return True

        try:
            self.stop_current_run()

            print("Starting histogram mode...")

            # Configure for histogram mode
            settings = {
                "channels": [
                    (0, ch) for ch in self.enabled_channels
                ],  # Logical module 0
                "CaptureHistogram": True,
                "CaptureTrace": False,
                "CaptureSums": False,
                "GoodChannel": True,
            }
            px.control.change_setting_from_dict(settings, call_pixie=True)

            px.control.start_histogram_run()

            self.is_running = True
            self.current_mode = "histogram"
            print("✓ Histogram mode started")
            return True

        except Exception as e:
            print(f"Failed to start histogram mode: {e}")
            return False

    def start_list_mode(self) -> bool:
        if self.dummy_mode:
            print("DUMMY MODE: Starting list mode")
            self.is_running = True
            self.current_mode = "list"
            return True

        try:
            self.stop_current_run()

            print("Starting list mode...")

            # Configure for list mode
            settings = {
                "channels": [
                    (0, ch) for ch in self.enabled_channels
                ],  # Logical module 0
                "CaptureHistogram": False,  # Don't capture histograms in list mode
                "CaptureTrace": False,  # Don't capture traces (use traces mode for that)
                "CaptureSums": False,  # Don't capture sums
                "GoodChannel": True,  # Enable channels
                "EnableChannelVal": True,  # Enable channel validation
                # Trigger settings to ensure we get events
                "TRIGGER_THRESHOLD": 50,  # Lower threshold to get more events
                "ENERGY_RISETIME": 0.5,  # Reasonable energy filter
                "ENERGY_FLATTOP": 0.1,
                "TRIGGER_RISETIME": 0.02,  # Fast trigger settings
                "TRIGGER_FLATTOP": 0.02,
            }
            px.control.change_setting_from_dict(settings, call_pixie=True)
            print("✓ List mode settings applied")

            px.control.start_list_mode_run()
            print("List mode run started")

            # Verify the run is active
            time.sleep(0.5)  # Give it time to start
            try:
                run_active = px.control.check_run_status()
                print(f"Run status check: {run_active}")
            except:
                print("Could not check run status")

            self.is_running = True
            self.current_mode = "list"
            print("List mode started successfully")
            return True

        except Exception as e:
            print(f"Failed to start list mode: {e}")
            import traceback

            traceback.print_exc()
            return False

    def start_traces_mode(self) -> bool:
        if self.dummy_mode:
            print("DUMMY MODE: Starting traces mode")
            self.is_running = True
            self.current_mode = "traces"
            return True

        try:
            self.stop_current_run()

            print("Starting traces mode...")

            # Configure for traces mode
            settings = {
                "channels": [
                    (0, ch) for ch in self.enabled_channels
                ],  # Logical module 0
                "CaptureHistogram": False,
                "CaptureTrace": True,
                "CaptureSums": True,
                "GoodChannel": True,
                "EnableChannelVal": True,
                "TRACE_LENGTH": 2.0,  # 2 microseconds
                "TRACE_DELAY": 0.5,  # 0.5 microseconds
            }
            px.control.change_setting_from_dict(settings, call_pixie=True)

            # traces come through list mode
            px.control.start_list_mode_run()

            self.is_running = True
            self.current_mode = "traces"
            print("✓ Traces mode started")
            return True

        except Exception as e:
            print(f"Failed to start traces mode: {e}")
            return False

    def read_histograms(self) -> dict:
        if self.current_mode != "histogram":
            return {}

        histograms = {}
        try:
            # Read histograms using logical module 0
            module_channels = [(0, ch) for ch in self.enabled_channels]
            hist_list = px.control.read_histograms(module_channels)

            # Convert to dict keyed by channel number
            for i, channel in enumerate(self.enabled_channels):
                if i < len(hist_list) and hist_list[i] is not None:
                    histograms[channel] = np.array(hist_list[i], dtype=np.int32)
                else:
                    histograms[channel] = np.zeros(32768, dtype=np.int32)

        except Exception as e:
            print(f"Error reading histograms: {e}")
            # Return empty histograms for all channels
            for channel in self.enabled_channels:
                histograms[channel] = np.zeros(32768, dtype=np.int32)

        return histograms

    def read_list_mode_data(self) -> list:
        if self.dummy_mode or self.current_mode not in ["list", "traces"]:
            return []

        try:
            # Use lower threshold and more aggressive reading
            data_list = px.control.read_list_mode_fifo(check=True, threshold=8)

            if not hasattr(self, "_hw_debug_counter"):
                self._hw_debug_counter = 0
                self._last_hw_debug = time.time()

            total_words = sum(len(data) for data in data_list) if data_list else 0
            self._hw_debug_counter += total_words

            # Debug output every 3 seconds
            current_time = time.time()
            if current_time - self._last_hw_debug > 3.0:
                print(
                    f"Hardware FIFO: Read {total_words} words, {self._hw_debug_counter} total, {len(data_list) if data_list else 0} buffers"
                )
                self._last_hw_debug = current_time

                # Also check FIFO status
                try:
                    # Try to check FIFO status directly if available
                    if hasattr(px.control, "check_external_FIFO_status"):
                        for i in range(len(px.control.module_list)):
                            words = px.control.check_external_FIFO_status(i)
                            print(f"  Module {i} FIFO: {words} words available")
                except:
                    pass

            return data_list if data_list else []

        except Exception as e:
            print(f"Error reading list mode data: {e}")
            return []

    def stop_current_run(self):
        if not self.is_running:
            return

        try:
            if not self.dummy_mode:
                px.control.end_run()
                time.sleep(0.1)  # Give time for cleanup

            self.is_running = False
            self.current_mode = None
            print("✓ Acquisition stopped")

        except Exception as e:
            print(f"Error stopping run: {e}")

    def cleanup(self):
        self.stop_current_run()
        print("✓ Hardware manager cleaned up")


class CompletePixieScopeApp(QMainWindow):
    shutdown_requested = pyqtSignal()

    def __init__(self, dummy_mode=False, physical_slot=2, channels=None):
        super().__init__()

        self.setWindowTitle(f"Complete PIXIE-16 Scope - Slot {physical_slot}")
        self.setGeometry(100, 100, 1600, 1000)

        # Set up signal handlers for graceful shutdown
        self.setup_signal_handlers()

        self.dummy_mode = dummy_mode
        self.physical_slot = physical_slot

        if channels is None:
            channels = list(range(16))
        self.channel_numbers = channels

        self.pixie_hw = PixieHardwareManager(physical_slot, dummy_mode)

        print(f"Initializing PIXIE-16 system for slot {physical_slot}...")
        if not self.pixie_hw.initialize_system():
            if not dummy_mode:
                reply = QMessageBox.question(
                    self,
                    "Hardware Initialization Failed",
                    f"Failed to initialize PIXIE-16 in slot {physical_slot}.\n\n"
                    "Continue in dummy mode?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    print("Switching to dummy mode...")
                    self.dummy_mode = True
                    self.pixie_hw = PixieHardwareManager(physical_slot, dummy_mode=True)
                    self.pixie_hw.initialize_system()
                else:
                    sys.exit(1)

        # Data acquisition components
        self.live_reader = None
        self.data_source = None
        self.is_acquiring = False
        self.current_mode = "mca_mode"

        # Timers
        self.acquisition_timer = None
        self.status_timer = None
        self.data_timer = None

        # Shutdown flag
        self.shutdown_in_progress = False

        # Data storage for MCA mode
        self.mca_data = {}
        self.cumulative_mca_data = {}

        # Initialize data storage for all channels
        for ch in self.channel_numbers:
            self.cumulative_mca_data[ch] = np.zeros(32768, dtype=np.int64)
            self.mca_data[ch] = np.zeros(32768, dtype=np.int32)

        # Connect shutdown signal
        self.shutdown_requested.connect(self.manual_shutdown)

        self.init_ui()
        self.setup_timers()

    def setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown"""

        def signal_handler(signum, frame):
            print(f"\nReceived signal {signum}, initiating graceful shutdown...")
            if hasattr(self, "shutdown_requested"):
                self.shutdown_requested.emit()
            else:
                self.manual_shutdown()

        # Handle common termination signals
        signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # Termination
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, signal_handler)  # Hang up (Unix only)

    def manual_shutdown(self):
        """Perform graceful shutdown when requested"""
        if self.shutdown_in_progress:
            return

        self.shutdown_in_progress = True
        self.close()

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

        self.binary_loader = BinaryFileLoader(parent_scope=self)
        right_layout.addWidget(self.binary_loader)

        # Create channel controls (using logical module 0)
        self.channel_controls = ChannelDisplayControls(
            channels=[(0, ch) for ch in self.channel_numbers], title="Channels"
        )
        self.channel_controls.channels_changed.connect(self.update_display_channels)
        right_layout.addWidget(self.channel_controls)

        self.parameter_controls = ParameterControls(
            initial_module=0,
            title="Parameters",  # Logical module 0
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
        mode_status = "DUMMY MODE - " if self.dummy_mode else ""
        self.info_bar = QLabel(
            f"{mode_status}PIXIE-16 Slot {self.physical_slot} → Logical Module 0 - Ready"
        )
        self.info_bar.setMaximumHeight(25)
        main_layout.addWidget(self.info_bar)

        main_widget.setLayout(main_layout)

    def create_control_panel(self):
        group = QGroupBox("Acquisition Controls")
        group.setMaximumHeight(120)
        layout = QVBoxLayout()

        # Mode and control buttons
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
                channels=self.channel_numbers, title="PIXIE-16 MCA Spectra"
            )
        elif self.current_mode == "list_mode":
            self.spectrum_tab = ContinuousSpectrumPlotter(
                app=None,
                instrument_name="pixie16",
                display_name="PIXIE-16 List Mode Spectra",
                channels=self.channel_numbers,
                energy_range=(0, 8192),
                bins=1000,
            )
        elif self.current_mode == "traces_mode":
            self.spectrum_tab = TracesPlotter(
                channels=self.channel_numbers, title="PIXIE-16 Traces"
            )

        self.left_layout.addWidget(self.spectrum_tab)
        self.info_bar.setText(f"Mode changed: {old_mode} → {self.current_mode}")

    def start_acquisition(self):
        try:
            success = False

            # Check if we should use binary replay instead of live acquisition
            if (
                hasattr(self, "binary_loader")
                and self.binary_loader.is_using_binary_data()
            ):
                print("Using binary file replay instead of live acquisition")

                # Start binary replay
                success = self.binary_loader.start_replay()

                if success:
                    # Start the spectrum plotter updates
                    if hasattr(self.spectrum_tab, "start_live_updates"):
                        self.spectrum_tab.start_live_updates()

                    data_source = self.binary_loader.get_data_source_info()
                    self.info_bar.setText(f"Replaying: {data_source}")
            else:
                # Regular live acquisition
                if self.current_mode == "mca_mode":
                    success = self.start_mca_acquisition()
                elif self.current_mode == "list_mode":
                    success = self.start_list_mode_acquisition()
                elif self.current_mode == "traces_mode":
                    success = self.start_traces_acquisition()

            if success:
                self.is_acquiring = True
                self.start_btn.setEnabled(False)
                self.stop_btn.setEnabled(True)
                self.status_label.setText(f"Status: Acquiring ({self.current_mode})")
            else:
                raise RuntimeError("Failed to start acquisition")

        except Exception as e:
            error_msg = f"Failed to start acquisition: {str(e)}"
            print(error_msg)
            self.info_bar.setText(error_msg)

    def start_mca_acquisition(self) -> bool:
        try:
            # Start hardware histogram collection
            if not self.pixie_hw.start_histogram_mode():
                return False

            # Start the MCA plotter's update timer
            if hasattr(self.spectrum_tab, "start_live_updates"):
                self.spectrum_tab.start_live_updates()

            # Set up timer to read histogram data every 2 seconds
            self.acquisition_timer = QTimer()
            self.acquisition_timer.timeout.connect(self.read_histogram_data)
            self.acquisition_timer.start(2000)

            mode_status = "DUMMY MODE - " if self.dummy_mode else ""
            self.info_bar.setText(f"{mode_status}MCA mode: Collecting histograms...")
            return True

        except Exception as e:
            print(f"Error starting MCA: {str(e)}")
            return False

    def start_list_mode_acquisition(self) -> bool:
        try:
            # Start hardware list mode
            if not self.pixie_hw.start_list_mode():
                return False

            print("Setting up live data processing...")

            # Set up live data reader for event processing
            self.live_reader = LiveDataReader()
            self.data_source = LiveDataSourceInterface(self.live_reader)

            # Add event callback with debugging
            def debug_event_callback(event):
                self.process_list_mode_event(event)

            self.live_reader.add_event_callback(debug_event_callback)
            print("✓ Event callback added")

            if self.dummy_mode:
                print("No binary file loaded")
            else:
                print("Starting FIFO reader for real hardware...")
                # Set up timer to read FIFO data every 50ms
                self.data_timer = QTimer()
                self.data_timer.timeout.connect(self.read_list_mode_fifo)
                self.data_timer.start(50)
                print("✓ FIFO timer started (50ms intervals)")

            # Start the data source
            self.data_source.start_acquisition()
            print("✓ Data source started")

            # Start the spectrum plotter updates
            if hasattr(self.spectrum_tab, "start_live_updates"):
                self.spectrum_tab.start_live_updates()
                print("✓ Spectrum plotter live updates started")

            mode_status = "DUMMY MODE - " if self.dummy_mode else ""
            self.info_bar.setText(f"{mode_status}List mode: Processing events...")

            print("Live data processing started")
            return True

        except Exception as e:
            print(f"Error starting list mode: {str(e)}")
            import traceback

            traceback.print_exc()
            return False

    def start_traces_acquisition(self) -> bool:
        try:
            # Start hardware traces mode
            if not self.pixie_hw.start_traces_mode():
                return False

            # Set up live data reader for trace processing
            self.live_reader = LiveDataReader()
            self.data_source = LiveDataSourceInterface(self.live_reader)
            self.live_reader.add_event_callback(self.process_traces_event)

            # self.binary_loader.set_live_data_source(self.data_source)

            if self.dummy_mode:
                print("No binary file loaded")
            else:
                # Set up timer to read FIFO data every 100ms
                self.data_timer = QTimer()
                self.data_timer.timeout.connect(self.read_list_mode_fifo)
                self.data_timer.start(100)

            self.data_source.start_acquisition()

            if hasattr(self.spectrum_tab, "start_live_updates"):
                self.spectrum_tab.start_live_updates()

            mode_status = "DUMMY MODE - " if self.dummy_mode else ""
            self.info_bar.setText(f"{mode_status}Traces mode: Capturing traces...")
            return True

        except Exception as e:
            print(f"Error starting traces mode: {str(e)}")
            return False

    def read_histogram_data(self):
        try:
            # Read histograms from hardware
            histograms = self.pixie_hw.read_histograms()

            # Track statistics for channel controls
            channel_stats = {}

            for channel, histogram in histograms.items():
                if channel in self.channel_numbers:
                    # Update cumulative data
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

            # Update channel controls
            if channel_stats and hasattr(self, "channel_controls"):
                self.channel_controls.update_channel_statistics(channel_stats)

        except Exception as e:
            print(f"Error reading histogram data: {e}")

    def read_list_mode_fifo(self):
        if not self.is_acquiring or not self.live_reader or self.dummy_mode:
            return

        try:
            # Read data with debugging
            data_list = self.pixie_hw.read_list_mode_data()

            if not hasattr(self, "_fifo_debug_counter"):
                self._fifo_debug_counter = 0
                self._last_fifo_debug = time.time()

            total_words = sum(len(data) for data in data_list)
            self._fifo_debug_counter += total_words

            # Debug output every 5 seconds
            current_time = time.time()
            if current_time - self._last_fifo_debug > 5.0:
                print(
                    f"FIFO Debug: Read {total_words} words this cycle, {self._fifo_debug_counter} total"
                )
                self._last_fifo_debug = current_time

            # Feed data to live reader
            for data in data_list:
                if len(data) > 0:
                    self.live_reader.add_data(data)
                    print(f"List Mode: Fed {len(data)} words to live reader")

        except Exception as e:
            print(f"Error reading PIXIE FIFO: {e}")
            import traceback

            traceback.print_exc()

    def process_list_mode_event(self, event):
        try:
            channel = getattr(event, "channel", 0)
            energy = getattr(event, "energy", 0)

            if not hasattr(self, "_event_debug_counter"):
                self._event_debug_counter = 0

            self._event_debug_counter += 1
            if self._event_debug_counter % 1000 == 0:
                data_source = (
                    "BINARY FILE"
                    if (
                        hasattr(self, "binary_loader")
                        and self.binary_loader.is_using_binary_data()
                    )
                    else "DUMMY DATA"
                )
                print(
                    f"List Mode ({data_source}): Processed {self._event_debug_counter} events, latest: Ch{channel} E={energy}"
                )

            if channel in self.channel_numbers:
                # Feed data to the spectrum plotter
                if hasattr(self.spectrum_tab, "add_energy_event"):
                    self.spectrum_tab.add_energy_event(channel, energy)
                elif hasattr(self.spectrum_tab, "energy_data"):
                    if channel not in self.spectrum_tab.energy_data:
                        from collections import deque

                        self.spectrum_tab.energy_data[channel] = deque(maxlen=50000)
                    self.spectrum_tab.energy_data[channel].append(energy)

        except Exception as e:
            print(f"Error processing list mode event: {e}")

    def process_traces_event(self, event):
        try:
            channel = getattr(event, "channel", 0)
            trace = getattr(event, "trace", None)

            if not hasattr(self, "_trace_debug_counter"):
                self._trace_debug_counter = 0

            self._trace_debug_counter += 1

            if self._trace_debug_counter % 100 == 0:
                data_source = (
                    "BINARY FILE"
                    if (
                        hasattr(self, "binary_loader")
                        and self.binary_loader.is_using_binary_data()
                    )
                    else "DUMMY DATA"
                )
                print(
                    f"Traces Mode ({data_source}): Processed {self._trace_debug_counter} traces, latest: Ch{channel} trace_len={len(trace) if trace else 0}"
                )

            if channel in self.channel_numbers and trace is not None and len(trace) > 0:
                # For coincidence analysis, feed event + trace to enhanced plotter
                if hasattr(self.spectrum_tab, "add_event_with_trace"):
                    self.spectrum_tab.add_event_with_trace(event, trace)
                # Fallback to regular trace processing
                elif hasattr(self.spectrum_tab, "add_trace"):
                    self.spectrum_tab.add_trace(channel, trace)
                elif hasattr(self.spectrum_tab, "trace_data"):
                    if channel not in self.spectrum_tab.trace_data:
                        from collections import deque

                        self.spectrum_tab.trace_data[channel] = deque(maxlen=100)
                    self.spectrum_tab.trace_data[channel].append(trace)

        except Exception as e:
            print(f"Error processing traces event: {e}")

    def stop_acquisition(self):
        if self.shutdown_in_progress:
            return

        try:
            print("Stopping acquisition...")

            # Stop binary replay if running
            if (
                hasattr(self, "binary_loader")
                and self.binary_loader.is_using_binary_data()
            ):
                self.binary_loader.stop_replay()

            # Stop timers first
            if hasattr(self, "acquisition_timer") and self.acquisition_timer:
                self.acquisition_timer.stop()
                self.acquisition_timer = None

            if hasattr(self, "data_timer") and self.data_timer:
                self.data_timer.stop()
                self.data_timer = None

            # Stop spectrum tab updates
            if (
                hasattr(self, "spectrum_tab")
                and self.spectrum_tab
                and hasattr(self.spectrum_tab, "stop_live_updates")
            ):
                try:
                    self.spectrum_tab.stop_live_updates()
                except RuntimeError:
                    pass  # Widget already deleted

            # Stop data source
            if hasattr(self, "data_source") and self.data_source:
                try:
                    self.data_source.stop_acquisition()
                except:
                    pass
                self.data_source = None

            # Stop hardware
            self.pixie_hw.stop_current_run()

            # Clean up live reader
            if hasattr(self, "live_reader"):
                self.live_reader = None

            self.is_acquiring = False

            # Update UI
            if not self.shutdown_in_progress:
                try:
                    self.start_btn.setEnabled(True)
                    self.stop_btn.setEnabled(False)
                    self.status_label.setText("Status: Stopped")

                    mode_status = "DUMMY MODE - " if self.dummy_mode else ""
                    self.info_bar.setText(f"{mode_status}Acquisition stopped")
                except RuntimeError:
                    pass  # UI elements already deleted

            print("✓ Acquisition stopped successfully")

        except Exception as e:
            print(f"Error stopping acquisition: {e}")

    def clear_data(self):
        try:
            # Clear MCA data
            for channel in self.channel_numbers:
                if channel in self.cumulative_mca_data:
                    self.cumulative_mca_data[channel].fill(0)
                if channel in self.mca_data:
                    self.mca_data[channel].fill(0)

            # Clear spectrum tab data
            if hasattr(self.spectrum_tab, "clear_data"):
                self.spectrum_tab.clear_data()

            mode_status = "DUMMY MODE - " if self.dummy_mode else ""
            self.info_bar.setText(f"{mode_status}All data cleared")

        except Exception as e:
            print(f"Error clearing data: {e}")

    def update_display_channels(self, selected_channels):
        try:
            # Filter to only enabled channels
            valid_channels = [
                ch for ch in selected_channels if ch in self.channel_numbers
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
        mode_status = "DUMMY MODE - " if self.dummy_mode else ""
        self.info_bar.setText(f"{mode_status}{message}")

    def setup_timers(self):
        """Set up status update timers"""
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)  # 1 second updates

    def update_status(self):
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
        try:
            if not hasattr(self, "mca_data") or not self.mca_data:
                return

            channel_stats = {}
            for channel in self.channel_numbers:
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
        try:
            channel_stats = {}

            # Get statistics from energy data in spectrum tab
            if hasattr(self.spectrum_tab, "energy_data") and hasattr(
                self.spectrum_tab.energy_data, "keys"
            ):
                for channel in self.channel_numbers:
                    if channel in self.spectrum_tab.energy_data:
                        event_count = len(self.spectrum_tab.energy_data[channel])
                        channel_stats[channel] = event_count
                    else:
                        channel_stats[channel] = 0
            else:
                # Fallback
                for channel in self.channel_numbers:
                    channel_stats[channel] = 0

            # Update channel controls
            if channel_stats and hasattr(self, "channel_controls"):
                self.channel_controls.update_channel_statistics(channel_stats)

        except Exception as e:
            print(f"Error updating List Mode channel stats: {e}")

    def update_traces_channel_stats(self):
        try:
            channel_stats = {}

            # Get statistics from trace data in spectrum tab
            if hasattr(self.spectrum_tab, "trace_data") and hasattr(
                self.spectrum_tab.trace_data, "keys"
            ):
                for channel in self.channel_numbers:
                    if channel in self.spectrum_tab.trace_data:
                        trace_count = len(self.spectrum_tab.trace_data[channel])
                        channel_stats[channel] = trace_count
                    else:
                        channel_stats[channel] = 0
            else:
                # Fallback
                for channel in self.channel_numbers:
                    channel_stats[channel] = 0

            # Update channel controls
            if channel_stats and hasattr(self, "channel_controls"):
                self.channel_controls.update_channel_statistics(channel_stats)

        except Exception as e:
            print(f"Error updating Traces channel stats: {e}")

    def closeEvent(self, event):
        try:
            print("Shutting down Complete PIXIE-16 Scope...")

            # Stop acquisition first
            if self.is_acquiring:
                print("  Stopping acquisition...")
                self.stop_acquisition()
                time.sleep(0.5)

            # Stop all timers
            print("  Stopping timers...")
            if hasattr(self, "status_timer") and self.status_timer:
                self.status_timer.stop()
                self.status_timer.deleteLater()
                self.status_timer = None

            # Clean up spectrum tab
            print("  Cleaning up spectrum tab...")
            if hasattr(self, "spectrum_tab") and self.spectrum_tab:
                try:
                    if hasattr(self.spectrum_tab, "stop_live_updates"):
                        self.spectrum_tab.stop_live_updates()

                    if (
                        hasattr(self.spectrum_tab, "update_timer")
                        and self.spectrum_tab.update_timer
                    ):
                        self.spectrum_tab.update_timer.stop()
                        self.spectrum_tab.update_timer.deleteLater()

                    if hasattr(self, "left_layout"):
                        self.left_layout.removeWidget(self.spectrum_tab)

                    self.spectrum_tab.setParent(None)
                    self.spectrum_tab.deleteLater()
                    self.spectrum_tab = None

                except Exception as e:
                    print(f"    Error cleaning up spectrum tab: {e}")

            # Hardware cleanup (gentle, doesn't kill system for others)
            print("  Cleaning up hardware...")
            if hasattr(self, "pixie_hw") and self.pixie_hw:
                try:
                    self.pixie_hw.cleanup()
                except Exception as e:
                    print(f"    Error during hardware cleanup: {e}")

            # Process remaining Qt events
            print("  Processing remaining events...")
            if hasattr(QApplication, "processEvents"):
                QApplication.processEvents()
                time.sleep(0.1)
                QApplication.processEvents()

            print("  Shutdown complete")

        except Exception as e:
            print(f"Error during shutdown: {e}")

        finally:
            # Always accept the close event
            event.accept()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="PixieScope")
    parser.add_argument("--dummy", action="store_true", help="Run in dummy mode")
    parser.add_argument(
        "--slot", type=int, default=2, help="Physical slot number in PXI crate"
    )
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

    # Create QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("PIXIE-16 Scope")

    def exception_hook(exctype, value, traceback_obj):
        print(f"Unhandled exception: {exctype.__name__}: {value}")
        import traceback

        traceback.print_exception(exctype, value, traceback_obj)

    sys.excepthook = exception_hook

    # Print startup info
    if args.dummy:
        print("Starting PIXIE-16 Scope in DUMMY MODE")
        print(f"  - Will simulate PIXIE-16 in slot {args.slot}")
    else:
        print("Starting PIXIE-16 Scope with REAL HARDWARE")
        print(f"  - Physical slot: {args.slot}")
        print(f"  - Channels: {channels}")

    window = None
    try:
        window = CompletePixieScopeApp(
            dummy_mode=args.dummy, physical_slot=args.slot, channels=channels
        )
        window.show()

        print("\n" + "=" * 60)
        print("PIXIE-16 Scope is ready!")
        print("Usage:")
        print("  - Select mode: MCA, List, or Traces")
        print("  - Click Start to begin acquisition")
        print("  - Use parameter controls to adjust settings")
        print("  - Click Stop to end acquisition")
        print("=" * 60 + "\n")

        # Run the application
        exit_code = app.exec()

        print("Application exited cleanly")
        sys.exit(exit_code)

    except KeyboardInterrupt:
        print("\nKeyboard interrupt received...")
        if window:
            window.manual_shutdown()
        sys.exit(0)

    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback

        traceback.print_exc()

        if window:
            try:
                window.manual_shutdown()
            except:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
