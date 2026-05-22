import sys
import time
import signal
import traceback
import gc
import os
import psutil

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
    QSizePolicy,
    QDialog,
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
from pixie16.ui.scope.mca_spectrum_plotter import MCASpectrumPlotter
from pixie16.ui.scope.traces_plotter import TracesPlotter
from pixie16.ui.scope.channel_controls import ChannelDisplayControls
from pixie16.ui.scope.parameter_controls import ParameterControls
from pixie16.ui.scope.data_manager import DataStoragePanel, DataSaver, DataSettingsManager
from pixie16.ui.scope.auto_save_buffer import AutoSaveBufferService
from pixie16.ui.scope.hardware_manager import DynamicPixieHardwareManager
from pixie16.ui.scope.parameter_validation import PixieParameterValidator

from collections import deque

import logging

logger = logging.getLogger(__name__)


class PixieHardwareManager:
    """Wrapper for DynamicPixieHardwareManager."""

    def __init__(self, physical_slot: int = 2, dummy_mode: bool = False):
        self.hw_manager = DynamicPixieHardwareManager(physical_slot, dummy_mode)

        # Maintain compatibility properties
        self.physical_slot = physical_slot
        self.dummy_mode = dummy_mode

    @property
    def is_initialized(self):
        return self.hw_manager.state.is_initialized

    @property
    def is_running(self):
        return self.hw_manager.state.is_running

    @property
    def current_mode(self):
        return self.hw_manager.state.current_mode

    @property
    def enabled_channels(self):
        return self.hw_manager.state.enabled_channels

    def initialize_system(self) -> bool:
        return self.hw_manager.initialize_system()

    def start_histogram_mode(self) -> bool:
        return self.hw_manager.start_mode("histogram")

    def start_list_mode(self) -> bool:
        return self.hw_manager.start_mode("list")

    def start_traces_mode(self) -> bool:
        return self.hw_manager.start_mode("traces")

    def read_histograms(self) -> dict:
        return self.hw_manager.read_histograms()

    def read_list_mode_data(self) -> list:
        return self.hw_manager.read_list_mode_data()

    def stop_current_run(self):
        self.hw_manager.stop_acquisition()

    def cleanup(self):
        self.hw_manager.cleanup()

    # New methods for dynamic parameter management
    def update_parameter(
        self, param_name: str, value, module: int = 0, channel: int = 0
    ) -> bool:
        return self.hw_manager.update_parameter(param_name, value, module, channel)

    def update_parameters(
        self, params: dict, module: int = 0, channel: int = 0
    ) -> bool:
        return self.hw_manager.update_parameters(params, module, channel)

    def get_parameter(self, param_name: str, module: int = 0, channel: int = 0):
        return self.hw_manager.get_parameter(param_name, module, channel)

    def refresh_parameters(self, module: int = 0, channel: int = 0):
        self.hw_manager.refresh_parameter_cache(module, channel)

    def get_hardware_timing_parameters(self, channel: int = 0) -> dict:
        return self.hw_manager.get_hardware_timing_parameters(channel)

    def get_all_parameters(self, module: int = 0, channel: int = 0) -> dict:
        return self.hw_manager.get_all_parameters(module, channel)

    def read_parameter_from_hardware(self, param_name: str, module: int = 0, channel: int = 0):
        return self.hw_manager.read_parameter_from_hardware(param_name, module, channel)

    def refresh_parameter_cache(self, module: int = 0, channel: int = 0):
        return self.hw_manager.refresh_parameter_cache(module, channel)

    def is_parameter_cached(self, param_name: str, module: int = 0, channel: int = 0) -> bool:
        return self.hw_manager.is_parameter_cached(param_name, module, channel)

    def read_from_dictionary(self, settings_dict: dict) -> bool:
        return self.hw_manager.read_from_dictionary(settings_dict)

    def load_default_settings(self) -> bool:
        return self.hw_manager.load_default_settings()

    def get_state(self):
        return self.hw_manager.get_state()


class PixieScopeApp(QMainWindow):
    shutdown_requested = pyqtSignal()

    def __init__(self, dummy_mode=False, physical_slot=2, channels=None):
        super().__init__()

        self.setWindowTitle(f"Complete PIXIE-16 Scope - Slot {physical_slot}")

        self.setup_signal_handlers()

        self.is_remote_desktop = (
            os.environ.get('NXSESSIONID') is not None or
            'nomachine' in os.environ.get('NX_CLIENT', '').lower()
        )
        
        if self.is_remote_desktop:
            print("Remote desktop detected - using performance optimized timers")
        
        self.dummy_mode = dummy_mode
        self.physical_slot = physical_slot

        if channels is None:
            channels = list(range(16))
        self.channel_numbers = channels

        # Initialize hardware manager with dynamic capabilities
        self.pixie_hw = PixieHardwareManager(physical_slot, dummy_mode)

        # Initialize parameter validation system
        self.parameter_validator = PixieParameterValidator("500MHz")

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
        self.current_mode = "list_mode"

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
        if self.shutdown_in_progress:
            return

        self.shutdown_in_progress = True
        self.close()

    def init_ui(self):
        # Set responsive window size
        screen = QApplication.primaryScreen().geometry()
        window_width = min(1200, int(screen.width() * 0.85))
        window_height = min(800, int(screen.height() * 0.8))
        self.resize(window_width, window_height)
        self.setMinimumSize(1000, 500)

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

        # Initialize with List Mode (TracesPlotter) by default
        if 6 not in self.channel_numbers:
            print(f"WARNING: Channel 6 not in enabled channels {self.channel_numbers}, adding it...")
            self.channel_numbers = list(self.channel_numbers) + [6]

        self.spectrum_tab = TracesPlotter(
            channels=self.channel_numbers,
            title="PIXIE-16 List Mode",
            hardware_manager=self.pixie_hw,
        )
        self.spectrum_tab.parameter_changed.connect(self.handle_traces_parameter_change)
        if hasattr(self.spectrum_tab, "request_right_panel_swap"):
            self.spectrum_tab.request_right_panel_swap.connect(self.swap_right_panel_controls)
        self.left_layout.addWidget(self.spectrum_tab)

        # Right side - controls
        right_widget = QWidget()
        self.right_layout = QVBoxLayout(right_widget)  # *** Store as self.right_layout ***
        self.right_layout.setContentsMargins(5, 5, 5, 5)
        self.right_layout.setSpacing(5)
        
        # Binary loader
        self.binary_loader = BinaryFileLoader(parent_scope=self)
        self.binary_loader.replay_stopped.connect(self._on_replay_stopped)
        self.binary_loader.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        self.right_layout.addWidget(self.binary_loader)
        
        # default controls (channel + parameter controls)
        self.default_controls_widget = QWidget()
        default_controls_layout = QVBoxLayout()
        default_controls_layout.setContentsMargins(0, 0, 0, 0)
        default_controls_layout.setSpacing(5)
        
        # Channel controls
        self.channel_controls = ChannelDisplayControls(
            channels=[(0, ch) for ch in self.channel_numbers], title="Channels"
        )
        self.channel_controls.channels_changed.connect(self.update_display_channels)
        default_controls_layout.addWidget(self.channel_controls)
        
        # Parameter controls
        self.parameter_controls = ParameterControls(
            initial_module=0,
            title="Parameters",
            module_type="500MHz",
        )
        self.parameter_controls.parameter_changed.connect(self.apply_all_parameters)
        self.parameter_controls.status_message.connect(self.update_info_bar)
        self.parameter_controls.request_read_hardware.connect(self.read_parameters_from_hardware)
        self.parameter_controls.load_default_btn.clicked.connect(self.load_default_settings)
        self.parameter_controls.load_dict_btn.clicked.connect(self.load_settings_from_file)
        default_controls_layout.addWidget(self.parameter_controls)
        
        # Data storage manager (not in UI panel)
        self.data_storage_manager = DataSettingsManager()
        
        # Initialize data saver
        self.data_saver = DataSaver(self.data_storage_manager)
        
        # Initialize auto-save buffer service
        self.auto_save_service = AutoSaveBufferService(self.data_storage_manager, self)
        self.auto_save_service.cache_status_changed.connect(self.on_cache_status_changed)
        self.auto_save_service.data_auto_saved.connect(self.on_data_auto_saved)
        
        # Register initial data sources and start auto-save
        self.register_data_sources()
        self.auto_save_service.start_service()
        
        default_controls_layout.addStretch()
        self.default_controls_widget.setLayout(default_controls_layout)
        
        self.right_layout.addWidget(self.default_controls_widget)
        
        self.custom_controls_widget = None
        
        # Set sizes
        left_widget.setMinimumWidth(400)
        right_widget.setMinimumWidth(320)

        # Add to splitter
        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(right_widget)
        main_splitter.setStretchFactor(0, 1)  # left (plots) gets all extra space
        main_splitter.setStretchFactor(1, 0)  # right (controls) stays compact
        main_splitter.setSizes([int(window_width * 0.72), int(window_width * 0.28)])
        
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
        self.mode_combo.addItems(["List Mode", "MCA Mode"])
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
        
        # Clear cache button
        self.clear_cache_btn = QPushButton("Clear Cache")
        self.clear_cache_btn.clicked.connect(self.clear_cache_data)
        self.clear_cache_btn.setToolTip("Clear auto-save cache (500MB buffer)")
        top_layout.addWidget(self.clear_cache_btn)

        # Save data button
        self.save_data_btn = QPushButton("Save Data")
        self.save_data_btn.clicked.connect(self.save_current_data)
        top_layout.addWidget(self.save_data_btn)
        
        # Save settings button  
        self.save_settings_btn = QPushButton("Save Settings")
        self.save_settings_btn.clicked.connect(self.open_save_settings_dialog)
        top_layout.addWidget(self.save_settings_btn)

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
    
    def swap_right_panel_controls(self, custom_widget):
        try:
            # Remove current custom widget if exists
            if self.custom_controls_widget is not None:
                self.right_layout.removeWidget(self.custom_controls_widget)
                self.custom_controls_widget.setParent(None)
                self.custom_controls_widget = None
            
            if custom_widget is None:
                # Restore default controls
                if not self.default_controls_widget.parent():
                    self.right_layout.addWidget(self.default_controls_widget)
                self.default_controls_widget.setVisible(True)
            else:
                # Hide default controls and show custom widget
                self.default_controls_widget.setVisible(False)
                self.right_layout.addWidget(custom_widget)
                custom_widget.setVisible(True)
                self.custom_controls_widget = custom_widget
                print(f"swap_right_panel_controls: Added custom widget, visible={custom_widget.isVisible()}, parent={custom_widget.parent()}")
            
        except Exception as e:
            print(f"Error swapping right panel controls: {e}")
            import traceback
            traceback.print_exc()

    def on_mode_changed(self, mode_text):
        if self.is_acquiring:
            self.stop_acquisition()
        
        old_mode = self.current_mode
        self.current_mode = mode_text.lower().replace(" ", "_")
        
        # Clean up old spectrum tab
        if hasattr(self, "spectrum_tab") and self.spectrum_tab:
            # Stop all timers before removing widget
            if hasattr(self.spectrum_tab, "stop_live_updates"):
                self.spectrum_tab.stop_live_updates()
            if hasattr(self.spectrum_tab, "update_timer") and self.spectrum_tab.update_timer:
                self.spectrum_tab.update_timer.stop()

            if hasattr(self.spectrum_tab, "request_right_panel_swap"):
                try:
                    self.spectrum_tab.request_right_panel_swap.disconnect()
                except RuntimeError:
                    pass
            if hasattr(self.spectrum_tab, "parameter_changed"):
                try:
                    self.spectrum_tab.parameter_changed.disconnect()
                except RuntimeError:
                    pass

            # Restore default controls when leaving any mode that had custom panels
            if old_mode in ["listmode_traces", "list_mode"]:
                self.swap_right_panel_controls(None)

            self.left_layout.removeWidget(self.spectrum_tab)
            self.spectrum_tab.setParent(None)
            self.spectrum_tab.deleteLater()
            self.spectrum_tab = None
        
        # Create new spectrum tab
        if self.current_mode == "mca_mode":
            self.spectrum_tab = MCASpectrumPlotter(
                channels=self.channel_numbers, title="PIXIE-16 MCA Spectra"
            )
        elif self.current_mode == "list_mode":
            # Ensure channel 6 is included for debugging
            if 6 not in self.channel_numbers:
                print(f"WARNING: Channel 6 not in enabled channels {self.channel_numbers}, adding it...")
                self.channel_numbers = list(self.channel_numbers) + [6]
                
            self.spectrum_tab = TracesPlotter(
                channels=self.channel_numbers,
                title="PIXIE-16 List Mode",
                hardware_manager=self.pixie_hw,
            )
            
            # Connect parameter changes from traces plotter
            self.spectrum_tab.parameter_changed.connect(self.handle_traces_parameter_change)
            
            # Connect right-panel swap signal
            if hasattr(self.spectrum_tab, "request_right_panel_swap"):
                self.spectrum_tab.request_right_panel_swap.connect(self.swap_right_panel_controls)
                print("PixieScopeApp: Connected right-panel swap signal from TracesPlotter")
        
        self.left_layout.addWidget(self.spectrum_tab)
        self.info_bar.setText(f"Mode changed: {old_mode} → {self.current_mode}")

    def handle_traces_parameter_change(self, param_name, value, module, channel):
        """Handle parameter changes from the traces plotter's own controls."""
        try:
            if not self.dummy_mode and self.pixie_hw:
                # Use the same batch mechanism
                self.apply_all_parameters(param_name, value, module, channel)
            else:
                self.update_info_bar(
                    f"DUMMY MODE - Hardware Validation: {param_name} = {value}"
                )

        except Exception as e:
            error_msg = f"Hardware Validation Error: {e}"
            self.update_info_bar(error_msg)
            print(error_msg)

    def start_acquisition(self):
        # Prevent race conditions from rapid button clicking
        if self.is_acquiring:
            print("Start acquisition called but already acquiring - ignoring")
            return
        
        # Disable both buttons immediately to prevent race conditions
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        
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

            if success:
                self.is_acquiring = True
                self.start_btn.setEnabled(False)
                self.stop_btn.setEnabled(True)
                self.status_label.setText(f"Status: Acquiring ({self.current_mode})")
            else:
                # Failed to start - reset buttons to start state
                self.is_acquiring = False
                self.start_btn.setEnabled(True)
                self.stop_btn.setEnabled(False)
                raise RuntimeError("Failed to start acquisition")

        except Exception as e:
            # Always reset button states on error
            self.is_acquiring = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
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

            # Set up timer to read histogram data
            self.acquisition_timer = QTimer()
            self.acquisition_timer.timeout.connect(self.read_histogram_data)
            interval = 5000 if self.is_remote_desktop else 2000
            self.acquisition_timer.start(interval)

            mode_status = "DUMMY MODE - " if self.dummy_mode else ""
            self.info_bar.setText(f"{mode_status}MCA mode: Collecting histograms...")
            return True

        except Exception as e:
            print(f"Error starting MCA: {str(e)}")
            return False

    def start_list_mode_acquisition(self) -> bool:
        try:
            # Start hardware traces mode
            if not self.pixie_hw.start_traces_mode():
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
                # Set up timer to read FIFO data
                self.data_timer = QTimer()
                self.data_timer.timeout.connect(self.read_list_mode_fifo)
                # Use longer interval for remote desktop to reduce network load
                interval = 200 if self.is_remote_desktop else 50
                self.data_timer.start(interval)
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
            traceback.print_exc()
            return False


    def read_histogram_data(self):
        try:
            # Periodic garbage collection for memory management
            if not hasattr(self, '_histogram_gc_counter'):
                self._histogram_gc_counter = 0
            self._histogram_gc_counter += 1
            
            if self._histogram_gc_counter % 10 == 0:  # Every 10 calls (~20-50 seconds)
                gc.collect()
                
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
            # Periodic garbage collection for memory management (more frequent in list mode)
            if not hasattr(self, '_fifo_gc_counter'):
                self._fifo_gc_counter = 0
            self._fifo_gc_counter += 1
            
            if self._fifo_gc_counter % 20 == 0:  # Every 20 calls (~1-4 seconds)
                gc.collect()
                
            # Read data with debugging
            data_list = self.pixie_hw.read_list_mode_data()

            if not hasattr(self, "_fifo_debug_counter"):
                self._fifo_debug_counter = 0
                self._last_fifo_debug = time.time()

            total_words = sum(len(data) for data in data_list)
            self._fifo_debug_counter += total_words

            # # Debug output every 5 seconds
            # current_time = time.time()
            # if current_time - self._last_fifo_debug > 5.0:
            #     for i, data in enumerate(data_list):
            #         print(f"FIFO Debug: Module {i}: {len(data)} words")
            #     self._last_fifo_debug = current_time

            # Feed data to live reader
            for data in data_list:
                if len(data) > 0:
                    self.live_reader.add_data(data)
                    #print(f"List Mode: Fed {len(data)} words to live reader")

        except Exception as e:
            print(f"Error reading PIXIE FIFO: {e}")
            traceback.print_exc()

    def process_list_mode_event(self, event):
        try:
            channel = getattr(event, "channel", 0)
            energy = getattr(event, "energy", 0)

            if channel in self.channel_numbers:
                # For unified plotter, feed data to both histogram and traces
                if hasattr(self.spectrum_tab, "add_event"):
                    # Feed to histogram tab
                    self.spectrum_tab.add_event(event)
                    
                # If trace data is available, also feed to traces tab
                trace = getattr(event, "trace", None)
                if trace is not None and hasattr(self.spectrum_tab, "add_event_with_trace"):
                    self.spectrum_tab.add_event_with_trace(event, trace)
                
                # Fallback for older spectrum plotters
                elif hasattr(self.spectrum_tab, "add_energy_event"):
                    self.spectrum_tab.add_energy_event(channel, energy)
                elif hasattr(self.spectrum_tab, "energy_data"):
                    if channel not in self.spectrum_tab.energy_data:
                        self.spectrum_tab.energy_data[channel] = deque(maxlen=50000)
                    self.spectrum_tab.energy_data[channel].append(energy)

        except Exception as e:
            print(f"Error processing list mode event: {e}")


    def stop_acquisition(self):
        if self.shutdown_in_progress:
            return
            
        # Prevent race conditions from rapid button clicking
        if not self.is_acquiring:
            print("Stop acquisition called but not acquiring - ignoring")
            return

        # Disable both buttons immediately to prevent race conditions
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)

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

            if self.current_mode == "list_mode":
                if hasattr(self.spectrum_tab, 'restore_current_sidebar'):
                    self.spectrum_tab.restore_current_sidebar()
                else:
                    self.swap_right_panel_controls(None)
            
            self.is_acquiring = False

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

            # Update UI - Always set correct final state
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
            # Always reset button states on error
            if not self.shutdown_in_progress:
                try:
                    self.start_btn.setEnabled(True)
                    self.stop_btn.setEnabled(False)
                except RuntimeError:
                    pass
            print(f"Error stopping acquisition: {e}")

    def _on_replay_stopped(self):
        """Handle binary replay completion or stop — reset UI and timers."""
        if not self.is_acquiring:
            return
        # Stop live update timers
        if (
            hasattr(self, "spectrum_tab")
            and self.spectrum_tab
            and hasattr(self.spectrum_tab, "stop_live_updates")
        ):
            try:
                self.spectrum_tab.stop_live_updates()
            except RuntimeError:
                pass
        self.is_acquiring = False
        if not self.shutdown_in_progress:
            try:
                self.start_btn.setEnabled(True)
                self.stop_btn.setEnabled(False)
                self.status_label.setText("Status: Replay finished")
                self.info_bar.setText("Binary replay completed")
            except RuntimeError:
                pass

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
            
    def clear_cache_data(self):
        try:
            # Get cache info first
            if hasattr(self, 'auto_save_service'):
                cache_info = self.auto_save_service.get_cache_info()
                cache_size_mb = cache_info.get('cache_size_mb', 0)
                cached_files = cache_info.get('cached_files', 0)
                
                # Show confirmation dialog
                reply = QMessageBox.question(
                    self, 
                    "Clear Cache?", 
                    f"This will permanently delete:\n\n"
                    f"• {cached_files} cached files\n"
                    f"• {cache_size_mb:.1f} MB of auto-saved data\n"
                    f"• All buffer overflow statistics\n\n"
                    f"This cannot be undone. Continue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    # Clear the cache
                    cache_dir = self.auto_save_service.cache_manager.cache_dir
                    import shutil
                    if cache_dir.exists():
                        shutil.rmtree(cache_dir)
                        cache_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Reset cache manager state
                    self.auto_save_service.cache_manager.access_times.clear()
                    
                    # Update info bar
                    mode_status = "DUMMY MODE - " if self.dummy_mode else ""
                    self.info_bar.setText(f"{mode_status}Auto-save cache cleared ({cache_size_mb:.1f}MB freed)")
                    
                    print(f"Cache cleared: {cached_files} files, {cache_size_mb:.1f}MB freed")
                else:
                    self.info_bar.setText("Cache clear cancelled")
            else:
                QMessageBox.warning(self, "Cache Not Available", "Auto-save service not running")
                
        except Exception as e:
            error_msg = f"Error clearing cache: {str(e)}"
            print(error_msg)
            QMessageBox.critical(self, "Cache Clear Failed", error_msg)

    def update_display_channels(self, selected_channels):
        try:
            # Filter to only enabled channels
            valid_channels = [
                ch for ch in selected_channels if ch in self.channel_numbers
            ]

            # Update the main spectrum tab
            if hasattr(self.spectrum_tab, "set_display_channels"):
                self.spectrum_tab.set_display_channels(valid_channels)
            elif hasattr(self.spectrum_tab, "set_channels"):
                self.spectrum_tab.set_channels(valid_channels)

            # Store selected channels for performance-sensitive operations
            self.active_channels = valid_channels

            self.info_bar.setText(
                f"Displaying {len(valid_channels)} channels: {valid_channels}"
            )

        except Exception as e:
            print(f"Error updating display channels: {e}")

    # Mapping from SDK parameter names to traces_plotter hardware_params keys.
    # Conversion: None = direct copy, otherwise a callable (value) -> plotter value.
    _PARAM_TO_PLOTTER = {
        "TRIGGER_THRESHOLD": ("fast_threshold", None),
        "TRIGGER_RISETIME": ("fast_L", lambda v: int(round(v / 0.01))),  # μs → FPGA ticks
        "TRIGGER_FLATTOP": ("fast_G", lambda v: int(round(v / 0.01))),   # μs → FPGA ticks
        "ENERGY_RISETIME": ("energy_L", lambda v: int(round(v / 0.01))), # μs → steps
        "ENERGY_FLATTOP": ("energy_G", lambda v: int(round(v / 0.01))),  # μs → steps
        "TAU": ("decay_ns", lambda v: v * 1000),                         # μs → ns
        "EMIN": ("energy_P", None),                                      # peak sample
        "CFDDelay": ("CFD_delay", None),                                 # FPGA ticks
        "CFDThresh": ("CFD_threshold", None),                            # ADC units
        "ENERGY_L": ("energy_L", None),                                  # UI-only, direct FPGA steps
        "ENERGY_G": ("energy_G", None),                                  # UI-only, direct FPGA steps
    }

    def apply_all_parameters(self, param_name, value, module, channel):
        """Called for each parameter from Apply to Channel. Batches via a timer."""
        # Accumulate parameters to apply
        if not hasattr(self, '_pending_params'):
            self._pending_params = []

        self._pending_params.append((param_name, value, module, channel))

        # Debounce: schedule the actual apply after all signals have been emitted
        if not hasattr(self, '_apply_timer') or self._apply_timer is None:
            self._apply_timer = QTimer(self)
            self._apply_timer.setSingleShot(True)
            self._apply_timer.timeout.connect(self._execute_apply_batch)

        self._apply_timer.start(50)  # 50ms debounce

    def _execute_apply_batch(self):
        """Stop acquisition, apply params, read back, restart. All synchronous."""
        params = self._pending_params
        self._pending_params = []

        if not params:
            return

        was_acquiring = self.is_acquiring
        module = params[0][2]
        channel = params[0][3]

        print(f"APPLY: was_acquiring={was_acquiring}, params={[(p[0],p[1]) for p in params]}")

        # Fully stop everything before touching the SDK
        if was_acquiring:
            self.stop_acquisition()

        # Kill any lingering FIFO timer to prevent concurrent SDK access
        if hasattr(self, "data_timer") and self.data_timer:
            self.data_timer.stop()
            self.data_timer = None

        # Process pending events so any in-flight timer callbacks complete
        QApplication.processEvents()

        # Ensure hardware run is fully ended before writing params
        if not self.dummy_mode:
            try:
                import pixie16 as px
                time.sleep(0.3)  # Let any in-flight SDK calls finish
                px.control.end_run()
                time.sleep(0.3)  # Let DSP fully stop
                run_active = px.control.check_run_status()
                print(f"  Run status after end_run: {'ACTIVE' if run_active else 'STOPPED'}")
            except Exception as e:
                print(f"  end_run check failed: {e}")

        self.update_info_bar("Applying parameters to hardware...")
        QApplication.processEvents()

        # Apply all parameters to hardware
        success_count = 0
        for param_name, value, mod, ch in params:
            is_valid, corrected_value, error_msg = (
                self.parameter_validator.validate_parameter(param_name, value, mod, ch)
            )
            if not is_valid:
                print(f"  SKIP {param_name}={value} - validation failed: {error_msg}")
                continue
            if not self.dummy_mode:
                result = self.pixie_hw.update_parameter(param_name, corrected_value, mod, ch)
                print(f"  {'OK' if result else 'FAIL'} {param_name}={corrected_value} → M{mod}:Ch{ch}")
                if result:
                    success_count += 1
            else:
                success_count += 1

        written_names = {p[0] for p in params}
        print(f"  Applied {success_count}/{len(params)} params. Reading back from M{module}:Ch{channel}...")
        if not self.dummy_mode and self.pixie_hw.is_initialized:
            try:
                self.pixie_hw.refresh_parameters(module, channel)
                readback_params = self.pixie_hw.get_all_parameters(module, channel)
                if readback_params:
                    # Only update spinboxes + plotter for params we actually wrote
                    applied_readback = {
                        name: readback_params[name]
                        for name in written_names
                        if name in readback_params
                    }
                    for name, val in applied_readback.items():
                        print(f"  READ-BACK {name} = {val}")
                    self.parameter_controls.set_all_parameters(applied_readback)
                    for p_name, p_value in applied_readback.items():
                        self._sync_parameter_to_plotter(p_name, p_value, channel)
            except Exception as e:
                print(f"  Read-back failed: {e}")

        # Clear trace buffers if trace params changed (old data is stale/wrong size)
        written_names = {p[0] for p in params}
        if written_names & {"TRACE_LENGTH", "TRACE_DELAY"}:
            plotter = getattr(self, "spectrum_tab", None)
            if plotter and hasattr(plotter, "clear_data"):
                plotter.clear_data()
                print(f"  Cleared trace buffers ({written_names & {'TRACE_LENGTH', 'TRACE_DELAY'}} changed)")

        self.update_info_bar(
            f"Applied {success_count}/{len(params)} parameters to M{module}:Ch{channel}"
        )

        # Always restart
        print("APPLY DONE: restarting acquisition...")
        self.start_acquisition()

    def _sync_parameter_to_plotter(self, param_name, value, channel):
        """Push a parameter change into the traces plotter's internal state."""
        plotter = getattr(self, "spectrum_tab", None)
        if plotter is None or not hasattr(plotter, "hardware_params"):
            return

        # Handle TRACE_DELAY separately (per-channel dict, different storage)
        if param_name == "TRACE_DELAY":
            plotter.trace_delay_ns[channel] = value * 1000  # μs → ns
            return

        # Handle Polarity (per-channel, stored in channel_polarity dict)
        if param_name == "Polarity":
            is_normal = (value == "positive") if isinstance(value, str) else bool(value)
            plotter.channel_polarity[channel] = is_normal
            return

        mapping = self._PARAM_TO_PLOTTER.get(param_name)
        if mapping is None:
            return

        plotter_key, converter = mapping
        plotter_value = converter(value) if converter else value
        plotter.hardware_params[plotter_key] = plotter_value

    def read_parameters_from_hardware(self):
        """Read parameters synchronously. The PIXIE SDK is not thread-safe."""
        module = self.parameter_controls.module_spin.value()
        channel = self.parameter_controls.channel_spin.value()

        if not self.dummy_mode and self.pixie_hw.is_initialized:
            self.update_info_bar(f"Reading parameters from M{module}:Ch{channel}...")
            QApplication.processEvents()
            try:
                self.pixie_hw.refresh_parameters(module, channel)
                current_params = self.pixie_hw.get_all_parameters(module, channel)
                self._finish_read_parameters(current_params, module, channel)
            except Exception as e:
                self.update_info_bar(f"Error reading parameters: {e}")
                logger.error(f"Error reading parameters from hardware: {e}")
        else:
            self.update_info_bar("Hardware not available for parameter reading")

    def _finish_read_parameters(self, params, module, channel):
        """Update UI with parameters read from hardware (runs on GUI thread)."""
        if params:
            self.parameter_controls.set_all_parameters(params)
            # Sync to plotter so plots use the correct values for this channel
            for p_name, p_value in params.items():
                self._sync_parameter_to_plotter(p_name, p_value, channel)
            self.update_info_bar(
                f"Read {len(params)} parameters from M{module}:Ch{channel}"
            )
        else:
            self.update_info_bar(f"No parameters found for M{module}:Ch{channel}")

    def load_default_settings(self):
        try:
            success = self.pixie_hw.load_default_settings()
            if success:
                # Refresh UI with loaded params
                module = self.parameter_controls.module_spin.value()
                channel = self.parameter_controls.channel_spin.value()
                current_params = self.pixie_hw.get_all_parameters(module, channel)
                if current_params:
                    self.parameter_controls.set_all_parameters(current_params)
                    for p_name, p_value in current_params.items():
                        self._sync_parameter_to_plotter(p_name, p_value, channel)
                self.update_info_bar("Loaded default settings successfully")
            else:
                self.update_info_bar("Failed to load default settings")
        except Exception as e:
            self.update_info_bar(f"Error loading defaults: {e}")
            logger.error(f"Error loading default settings: {e}")

    def load_settings_from_file(self):
        try:
            from PyQt6.QtWidgets import QFileDialog
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Load Settings File", "", "JSON Files (*.json);;All Files (*)"
            )
            if not file_path:
                return

            import json
            with open(file_path, "r") as f:
                settings_dict = json.load(f)

            success = self.pixie_hw.read_from_dictionary(settings_dict)
            if success:
                module = self.parameter_controls.module_spin.value()
                channel = self.parameter_controls.channel_spin.value()
                current_params = self.pixie_hw.get_all_parameters(module, channel)
                if current_params:
                    self.parameter_controls.set_all_parameters(current_params)
                    for p_name, p_value in current_params.items():
                        self._sync_parameter_to_plotter(p_name, p_value, channel)
                self.update_info_bar(f"Loaded settings from {file_path}")
            else:
                self.update_info_bar("Failed to load settings from file")
        except Exception as e:
            self.update_info_bar(f"Error loading settings: {e}")
            logger.error(f"Error loading settings from file: {e}")

    def update_info_bar(self, message):
        mode_status = "DUMMY MODE - " if self.dummy_mode else ""
        self.info_bar.setText(f"{mode_status}{message}")
    
    def on_cache_status_changed(self, message):
        # Update status bar with cache info
        if hasattr(self, 'info_bar'):
            self.update_info_bar(f"Cache: {message}")
    
    def on_data_auto_saved(self, data_type, count):
        logger.info(f"Auto-saved {count} {data_type} items to cache")
        if hasattr(self, 'info_bar'):
            self.update_info_bar(f"Auto-saved {count} {data_type} items")
    
    def register_data_sources(self):
        try:
            # Register the currently active spectrum tab
            if hasattr(self, 'spectrum_tab') and self.spectrum_tab:
                if hasattr(self.spectrum_tab, 'mca_data'):
                    # MCA mode
                    self.auto_save_service.register_data_source('mca_spectrum', self.spectrum_tab)
                elif hasattr(self.spectrum_tab, 'trace_data'):
                    # List mode with traces
                    self.auto_save_service.register_data_source('traces', self.spectrum_tab)
                    
                    # If it has a histogram tab, register that too
                    if hasattr(self.spectrum_tab, 'histogram_tab'):
                        self.auto_save_service.register_data_source('histogram', self.spectrum_tab.histogram_tab)
            
            # Register any other data sources that exist
            # This will be expanded as more tabs/modes are implemented
            logger.info("Data sources registered with auto-save service")
            
        except Exception as e:
            logger.warning(f"Error registering data sources: {e}")
    
    def clear_all_buffers(self):
        """Clear all data buffers in the application"""
        import gc
        try:
            if hasattr(self, 'spectrum_tab') and self.spectrum_tab:
                # Clear TracesPlotter buffers
                if hasattr(self.spectrum_tab, 'trace_data'):
                    for ch in self.spectrum_tab.trace_data:
                        self.spectrum_tab.trace_data[ch].clear()
                    logger.info("Cleared trace data buffers")
                
                if hasattr(self.spectrum_tab, 'trace_timestamps'):
                    for ch in self.spectrum_tab.trace_timestamps:
                        self.spectrum_tab.trace_timestamps[ch].clear()
                    logger.info("Cleared timestamp buffers")
                
                if hasattr(self.spectrum_tab, 'single_persistence_data'):
                    for ch in self.spectrum_tab.single_persistence_data:
                        self.spectrum_tab.single_persistence_data[ch].clear()
                    logger.info("Cleared persistence buffers")
                
                # Clear persistence histograms (critical for memory)
                if hasattr(self.spectrum_tab, 'persistence_histogram'):
                    for ch in self.spectrum_tab.persistence_histogram:
                        if hasattr(self.spectrum_tab.persistence_histogram[ch], 'reset'):
                            self.spectrum_tab.persistence_histogram[ch].reset()
                    logger.info("Cleared persistence histograms")
                
                # Clear MCA buffers
                if hasattr(self.spectrum_tab, 'mca_data'):
                    for ch in self.spectrum_tab.mca_data:
                        self.spectrum_tab.mca_data[ch] = np.array([])
                    logger.info("Cleared MCA data buffers")
                
                # Clear histogram tab buffers
                if hasattr(self.spectrum_tab, 'histogram_tab') and hasattr(self.spectrum_tab.histogram_tab, 'energy_data'):
                    self.spectrum_tab.histogram_tab.energy_data.clear()
                    logger.info("Cleared histogram energy buffers")
                
                # Clear coincidence tab data
                if hasattr(self.spectrum_tab, 'coincidence_tab'):
                    if hasattr(self.spectrum_tab.coincidence_tab, 'event_buffer'):
                        self.spectrum_tab.coincidence_tab.event_buffer.clear()
                    if hasattr(self.spectrum_tab.coincidence_tab, 'binary_data'):
                        self.spectrum_tab.coincidence_tab.binary_data.clear()
                    logger.info("Cleared coincidence data")
                
                # Reset overflow counters
                if hasattr(self.spectrum_tab, 'trace_overflow_count'):
                    self.spectrum_tab.trace_overflow_count = {ch: 0 for ch in self.spectrum_tab.channels}
                if hasattr(self.spectrum_tab, 'timestamp_overflow_count'):
                    self.spectrum_tab.timestamp_overflow_count = {ch: 0 for ch in self.spectrum_tab.channels}
                if hasattr(self.spectrum_tab, 'single_persistence_overflow_count'):
                    self.spectrum_tab.single_persistence_overflow_count = {ch: 0 for ch in self.spectrum_tab.channels}
                    
                logger.info("Reset overflow counters")
            
            # Clear main app MCA data
            if hasattr(self, 'mca_data'):
                for ch in self.mca_data:
                    self.mca_data[ch].fill(0)
            if hasattr(self, 'cumulative_mca_data'):
                for ch in self.cumulative_mca_data:
                    self.cumulative_mca_data[ch].fill(0)
            
            # Force garbage collection after clearing buffers
            gc.collect()
            logger.info("All buffers cleared and garbage collected successfully")
            
        except Exception as e:
            logger.warning(f"Error clearing buffers: {e}")

    def open_save_settings_dialog(self):        
        dialog = QDialog(self)
        dialog.setWindowTitle("Save Settings")
        dialog.setModal(True)
        dialog.resize(500, 300)
        
        layout = QVBoxLayout()
        
        # Create data storage panel for the dialog
        storage_panel = DataStoragePanel()
        storage_panel.get_settings_manager().data_directory = self.data_storage_manager.data_directory
        storage_panel.get_settings_manager().auto_create_subdirs = self.data_storage_manager.auto_create_subdirs
        storage_panel.get_settings_manager().use_timestamps = self.data_storage_manager.use_timestamps
        storage_panel.update_directory_display()
        storage_panel.auto_subdirs_cb.setChecked(self.data_storage_manager.auto_create_subdirs)
        storage_panel.timestamps_cb.setChecked(self.data_storage_manager.use_timestamps)
        
        def on_settings_changed():
            # Update main data storage manager
            self.data_storage_manager = storage_panel.get_settings_manager()
            self.data_saver = DataSaver(self.data_storage_manager)
            
        storage_panel.settings_changed.connect(on_settings_changed)
        layout.addWidget(storage_panel)
        
        # Add cache status info
        from PyQt6.QtWidgets import QGroupBox, QVBoxLayout as QVBox
        cache_group = QGroupBox("Auto-Save Cache Status")
        cache_layout = QVBox()
        
        if hasattr(self, 'auto_save_service'):
            cache_info = self.auto_save_service.get_cache_info()
            cache_size = cache_info.get('cache_size_mb', 0)
            max_size = cache_info.get('max_size_mb', 500)
            usage_percent = cache_info.get('usage_percent', 0)
            cached_files = cache_info.get('cached_files', 0)
            
            cache_info_label = QLabel(
                f"Cache Usage: {cache_size:.1f}MB / {max_size}MB ({usage_percent:.1f}%)\n"
                f"Cached Files: {cached_files}\n"
                f"Auto-save Interval: {cache_info.get('auto_save_interval_sec', 30)}s"
            )
        else:
            cache_info_label = QLabel("Auto-save service not available")
            
        cache_layout.addWidget(cache_info_label)
        cache_group.setLayout(cache_layout)
        layout.addWidget(cache_group)
        
        dialog.setLayout(layout)
        dialog.exec()

    def save_current_data(self):
        try:
            if self.current_mode == "mca_mode":
                self.save_mca_data()
            elif self.current_mode == "list_mode":
                self.save_list_mode_data()
            else:
                QMessageBox.warning(self, "Save Warning", "No data mode selected")
                
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Error saving data: {str(e)}")

    def save_mca_data(self):
        if not hasattr(self, 'spectrum_tab') or not self.spectrum_tab:
            QMessageBox.warning(self, "No Data", "No MCA data to save")
            return
            
        # Get MCA data from the spectrum tab
        if hasattr(self.spectrum_tab, 'get_spectrum_data'):
            mca_data = self.spectrum_tab.get_spectrum_data()
        elif hasattr(self.spectrum_tab, 'mca_data'):
            mca_data = self.spectrum_tab.mca_data
        else:
            QMessageBox.warning(self, "No Data", "Cannot access MCA data")
            return
            
        # Check if there's actually data
        if not mca_data or all(len(data) == 0 for data in mca_data.values()):
            QMessageBox.warning(self, "No Data", "No MCA data collected yet")
            return
            
        # Prepare metadata
        metadata = {
            'channels': self.channel_numbers,
            'hardware_slot': self.physical_slot,
            'dummy_mode': self.dummy_mode,
            'acquisition_time': getattr(self, 'acquisition_start_time', 'unknown')
        }
        
        # Save the data
        success = self.data_saver.save_mca_data(mca_data, metadata, self)
        if success:
            print(f"MCA data saved successfully")

    def save_list_mode_data(self):
        if not hasattr(self, 'spectrum_tab') or not self.spectrum_tab:
            QMessageBox.warning(self, "No Data", "No List Mode data to save")
            return
            
        # Get current tab in list mode
        if hasattr(self.spectrum_tab, 'tab_widget'):
            current_index = self.spectrum_tab.tab_widget.currentIndex()
            tab_name = self.spectrum_tab.tab_widget.tabText(current_index)
            
            if tab_name == "Histogram":
                self.save_histogram_data()
            elif tab_name == "Raw Traces":
                self.save_traces_data()
            elif tab_name == "Single Channel Analysis":
                self.save_analysis_data()
            elif tab_name == "Coincidence Logic":
                self.save_coincidence_data()
        else:
            QMessageBox.warning(self, "Save Error", "Cannot determine List Mode tab")

    def save_histogram_data(self):
        histogram_tab = getattr(self.spectrum_tab, 'histogram_tab', None)
        if not histogram_tab:
            QMessageBox.warning(self, "No Data", "No histogram data available")
            return
            
        if hasattr(histogram_tab, 'energy_data'):
            energy_data = histogram_tab.energy_data
            
            if not energy_data or all(len(data) == 0 for data in energy_data.values()):
                QMessageBox.warning(self, "No Data", "No histogram data collected yet")
                return
                
            metadata = {
                'data_type': 'list_mode_histogram',
                'channels': list(energy_data.keys()),
                'energy_range': getattr(histogram_tab, 'energy_range', (0, 80000)),
                'bins': getattr(histogram_tab, 'bins', 2000)
            }
            
            # Convert energy data to histogram format for saving
            histogram_data = {}
            for channel, energies in energy_data.items():
                if energies:
                    counts, _ = np.histogram(list(energies), 
                                           bins=metadata['bins'], 
                                           range=metadata['energy_range'])
                    histogram_data[channel] = counts
                    
            success = self.data_saver.save_mca_data(histogram_data, metadata, self)
            if success:
                print("List Mode histogram data saved successfully")

    def save_traces_data(self):
        if hasattr(self.spectrum_tab, 'trace_data'):
            trace_data = self.spectrum_tab.trace_data
            
            if not trace_data or all(len(traces) == 0 for traces in trace_data.values()):
                QMessageBox.warning(self, "No Data", "No trace data collected yet")
                return
                
            metadata = {
                'data_type': 'raw_traces',
                'channels': list(trace_data.keys()),
                'sampling_period_ns': getattr(self.spectrum_tab, 'sampling_period_ns', 2.0),
                'hardware_params': getattr(self.spectrum_tab, 'hardware_params', {})
            }
            
            success = self.data_saver.save_traces_data(trace_data, metadata, self)
            if success:
                print("Traces data saved successfully")
        else:
            QMessageBox.warning(self, "No Data", "No trace data available")

    def save_analysis_data(self):
        # Check if we're in list mode with TracesPlotter
        if hasattr(self.spectrum_tab, 'tab_widget'):
            # Get current tab info
            current_index = self.spectrum_tab.tab_widget.currentIndex()
            tab_name = self.spectrum_tab.tab_widget.tabText(current_index)
            
            if tab_name == "Single Channel Analysis":              
                # get data from histogram tab (energy spectrum)
                if hasattr(self.spectrum_tab, 'histogram_tab') and hasattr(self.spectrum_tab.histogram_tab, 'energy_data'):
                    energy_data = self.spectrum_tab.histogram_tab.get_spectrum_data()
                    
                    if energy_data:
                        # Get metadata from histogram tab
                        histogram_tab = self.spectrum_tab.histogram_tab
                        metadata = {
                            'instrument': getattr(histogram_tab, 'instrument', 'pixie16'),
                            'channels_analyzed': list(energy_data.keys()),
                            'energy_range': getattr(histogram_tab, 'energy_range', (0, 80000)),
                            'bins': getattr(histogram_tab, 'bins', 2000),
                            'display_channels': getattr(histogram_tab, 'display_channels', []),
                            'data_source': 'histogram_tab_energy_spectrum'
                        }
                        
                        # Save using the energy spectrum save method
                        success = self.data_saver.save_energy_spectrum_data(energy_data, metadata, self)
                        if success:
                            print(f"Single channel analysis (energy spectrum) data saved successfully")
                        return
                        
                # get persistence data from single channel analysis
                if hasattr(self.spectrum_tab, 'single_persistence_data'):
                    persistence_data = {}
                    for channel, traces in self.spectrum_tab.single_persistence_data.items():
                        if len(traces) > 0:
                            # Convert trace data to energy-like data for saving
                            # This is trace amplitude data, not true energy data
                            persistence_data[channel] = list(traces)
                    
                    if persistence_data:
                        metadata = {
                            'instrument': 'pixie16',
                            'channels_analyzed': list(persistence_data.keys()),
                            'data_type': 'single_channel_persistence_traces',
                            'sampling_period_ns': getattr(self.spectrum_tab, 'sampling_period_ns', 2.0),
                            'persistence_enabled': getattr(self.spectrum_tab, 'single_channel_persistence', False),
                            'data_source': 'single_channel_persistence'
                        }
                        
                        # Save persistence data as traces data (different from energy spectrum)
                        success = self.data_saver.save_traces_data(persistence_data, metadata, self)
                        if success:
                            print(f"Single channel analysis (persistence traces) data saved successfully")
                        return
                
                # No data found
                QMessageBox.warning(self, "No Data", 
                    "No single channel analysis data available to save.\n\n"
                    "Make sure you have:\n"
                    "• Energy events in the Histogram tab, OR\n"  
                    "• Persistence traces enabled with collected data")
            else:
                QMessageBox.warning(self, "Wrong Tab", 
                    f"Please switch to the 'Single Channel Analysis' tab to save analysis data.\n"
                    f"Currently on: {tab_name}")
        else:
            QMessageBox.warning(self, "No Data", "Cannot access List Mode tabs. Make sure you're in List Mode.")

    def save_coincidence_data(self):
        if hasattr(self.spectrum_tab, 'tab_widget'):
            current_index = self.spectrum_tab.tab_widget.currentIndex()
            tab_name = self.spectrum_tab.tab_widget.tabText(current_index)
            
            if tab_name == "Coincidence Logic":
                # Get the coincidence tab
                coincidence_tab = getattr(self.spectrum_tab, 'coincidence_tab', None)
                
                if coincidence_tab and hasattr(coincidence_tab, 'binary_data'):
                    # Collect all coincidence data
                    coincidence_data = {}
                    
                    # Get latest binary data
                    latest_data = coincidence_tab.binary_data.get_latest_data()
                    coincidence_data['latest_binary_data'] = latest_data
                    
                    # Get histogram data for both channels
                    hist_a, total_a = coincidence_tab.binary_data.get_histogram_data('A', coincidence_tab.histogram_normalize)
                    hist_b, total_b = coincidence_tab.binary_data.get_histogram_data('B', coincidence_tab.histogram_normalize)
                    
                    coincidence_data['histograms_a'] = hist_a
                    coincidence_data['histograms_b'] = hist_b
                    coincidence_data['total_events_a'] = total_a
                    coincidence_data['total_events_b'] = total_b
                    
                    # Get event buffers if available
                    if hasattr(coincidence_tab, 'event_buffer'):
                        coincidence_data['event_buffer'] = coincidence_tab.event_buffer
                    if hasattr(coincidence_tab, 'coincidence_events'):
                        coincidence_data['coincidence_events'] = coincidence_tab.coincidence_events
                        coincidence_data['total_coincidences'] = len(coincidence_tab.coincidence_events)
                    else:
                        coincidence_data['total_coincidences'] = 0
                    
                    # Get settings and parameters
                    coincidence_data['channel_a'] = getattr(coincidence_tab, 'channel_a', 0)
                    coincidence_data['channel_b'] = getattr(coincidence_tab, 'channel_b', 1)
                    coincidence_data['hardware_params'] = getattr(coincidence_tab, 'hardware_params', {})
                    coincidence_data['sampling_period_ns'] = getattr(coincidence_tab, 'sampling_period_ns', 2.0)
                    coincidence_data['fpga_period_ns'] = getattr(coincidence_tab, 'fpga_period_ns', 10.0)
                    coincidence_data['logic_steps'] = getattr(coincidence_tab.binary_data, 'logic_steps', [])
                    
                    # Get histogram settings
                    if hasattr(coincidence_tab.binary_data, 'ch_a_histogram'):
                        hist_settings = coincidence_tab.binary_data.ch_a_histogram
                        coincidence_data['time_bins'] = hist_settings.time_bins
                        coincidence_data['time_range_ns'] = hist_settings.time_range_ns
                    coincidence_data['normalize_histograms'] = getattr(coincidence_tab, 'histogram_normalize', False)
                    
                    # Check if there's any data to save
                    has_data = (total_a > 0 or total_b > 0 or 
                               (hasattr(coincidence_tab, 'event_buffer') and len(coincidence_tab.event_buffer) > 0))
                    
                    if not has_data:
                        QMessageBox.warning(self, "No Data", 
                            "No coincidence data available to save.\n\n"
                            "Make sure you have:\n"
                            "• Events processed in channels A and B\n"
                            "• Binary logic analysis enabled\n"
                            "• Some histogram or event data collected")
                        return
                    
                    # Prepare metadata
                    metadata = {
                        'acquisition_mode': 'coincidence_analysis',
                        'channels_analyzed': [coincidence_data['channel_a'], coincidence_data['channel_b']],
                        'binary_logic_enabled': getattr(coincidence_tab, 'binary_logic_enabled', True),
                        'coincidence_mode': getattr(coincidence_tab, 'coincidence_mode', False),
                        'data_source': 'coincidence_logic_tab'
                    }
                    
                    # Save the data
                    success = self.data_saver.save_coincidence_data(coincidence_data, metadata, self)
                    if success:
                        print(f"Coincidence data saved successfully")
                        print(f"  Channel A events: {total_a}")
                        print(f"  Channel B events: {total_b}")
                        print(f"  Coincidences: {coincidence_data.get('total_coincidences', 0)}")
                else:
                    QMessageBox.warning(self, "No Data", "Cannot access coincidence tab data")
            else:
                QMessageBox.warning(self, "Wrong Tab", 
                    f"Please switch to the 'Coincidence Logic' tab to save coincidence data.\n"
                    f"Currently on: {tab_name}")
        else:
            QMessageBox.warning(self, "No Data", "Cannot access List Mode tabs. Make sure you're in List Mode.")

    def setup_timers(self):
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)  # 1 second updates

    def update_status(self):
        try:
            # Get current memory usage using psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / (1024 * 1024)  # Convert to MB
            
            memory_threshold = 800 if self.is_remote_desktop else 1500
            warning_threshold = 600 if self.is_remote_desktop else 1200
            
            # Only warn occasionally to avoid spam
            if memory_mb > warning_threshold and int(memory_mb) % 50 == 0:  # Every 50MB increment
                print(f"NOTICE: Memory usage {memory_mb:.1f}MB (warning: {warning_threshold}MB, cleanup: {memory_threshold}MB)")
                
            if memory_mb > memory_threshold:
                self.clear_all_buffers()
                gc.collect()
                
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

            if hasattr(self, '_memory_counter'):
                self._memory_counter += 1
            else:
                self._memory_counter = 0
                
            if self._memory_counter % 10 == 0:  # Every 10 seconds
                mode_status = "DUMMY MODE - " if self.dummy_mode else ""
                self.info_bar.setText(f"{mode_status}Memory: {memory_mb:.0f}MB - {self.status_label.text()}")

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


    def closeEvent(self, event):
        try:
            print("Shutting down Complete PIXIE-16 Scope...")

            # Close any secondary/child windows (detached plots, dialogs, etc.)
            for child in self.findChildren(QWidget):
                if child.isWindow() and child is not self:
                    child.close()

            # Stop acquisition first
            if self.is_acquiring:
                print("  Stopping acquisition...")
                self.stop_acquisition()
                time.sleep(0.5)

            # Stop auto-save service
            print("  Stopping auto-save service...")
            if hasattr(self, "auto_save_service") and self.auto_save_service:
                self.auto_save_service.stop_service()
            
            # Stop all timers
            print("  Stopping timers...")
            if hasattr(self, '_apply_timer') and self._apply_timer:
                self._apply_timer.stop()
                self._apply_timer.deleteLater()
                self._apply_timer = None
                self._pending_params = []

            if hasattr(self, "status_timer") and self.status_timer:
                self.status_timer.stop()
                self.status_timer.deleteLater()
                self.status_timer = None

            # Clear all buffers before cleanup
            print("  Clearing data buffers...")
            self.clear_all_buffers()
            
            # Clean up spectrum tab
            print("  Cleaning up spectrum tab...")
            if hasattr(self, "spectrum_tab") and self.spectrum_tab:
                if hasattr(self.spectrum_tab, "stop_live_updates"):
                    self.spectrum_tab.stop_live_updates()

                if (
                    hasattr(self.spectrum_tab, "update_timer")
                    and self.spectrum_tab.update_timer
                ):
                    self.spectrum_tab.update_timer.stop()
                    self.spectrum_tab.update_timer.deleteLater()

                # Clear plot widgets explicitly to prevent memory leaks
                if hasattr(self.spectrum_tab, "plot_widget"):
                    self.spectrum_tab.plot_widget.clear()
                    self.spectrum_tab.plot_widget.getPlotItem().clear()
                    if hasattr(self.spectrum_tab, "curves"):
                        for curve in self.spectrum_tab.curves.values():
                            if curve is not None:
                                curve.setData([], [])
                        self.spectrum_tab.curves.clear()
                
                # Clear MCA data to free memory
                if hasattr(self.spectrum_tab, "mca_data"):
                    self.spectrum_tab.mca_data.clear()

                # Clear TracesPlotter widgets if it's a TracesPlotter
                if hasattr(self.spectrum_tab, "raw_plot_widget"):
                    self.spectrum_tab.raw_plot_widget.clear()
                    self.spectrum_tab.raw_plot_widget.getPlotItem().clear()
                    if hasattr(self.spectrum_tab, "raw_curves"):
                        for curve in self.spectrum_tab.raw_curves.values():
                            if curve is not None:
                                curve.setData([], [])
                        self.spectrum_tab.raw_curves.clear()

                # Clear histogram tab if it exists
                if hasattr(self.spectrum_tab, "histogram_tab") and self.spectrum_tab.histogram_tab:
                    if hasattr(self.spectrum_tab.histogram_tab, "plot_widget"):
                        self.spectrum_tab.histogram_tab.plot_widget.clear()
                        self.spectrum_tab.histogram_tab.plot_widget.getPlotItem().clear()
                    if hasattr(self.spectrum_tab.histogram_tab, "energy_data"):
                        self.spectrum_tab.histogram_tab.energy_data.clear()

                if hasattr(self, "left_layout"):
                    self.left_layout.removeWidget(self.spectrum_tab)

                self.spectrum_tab.setParent(None)
                self.spectrum_tab.deleteLater()
                self.spectrum_tab = None
            if hasattr(self, "traces_plotter") and self.traces_plotter:
                # Stop live updates first
                self.traces_plotter.stop_live_updates()

                # Clear all plot data BEFORE deleting widgets
                self.traces_plotter.clear_data()

                # Clear specific plot widgets to avoid painter crashes
                if hasattr(self.traces_plotter, "raw_plot_widget"):
                    self.traces_plotter.raw_plot_widget.clear()
                if hasattr(self.traces_plotter, "channel_a_plot"):
                    self.traces_plotter.channel_a_plot.clear()
                if hasattr(self.traces_plotter, "channel_b_plot"):
                    self.traces_plotter.channel_b_plot.clear()

                # Remove from layout BEFORE deleting
                if hasattr(self, "main_layout"):
                    self.main_layout.removeWidget(self.traces_plotter)

                # Finally delete
                self.traces_plotter.setParent(None)
                self.traces_plotter.deleteLater()
                self.traces_plotter = None

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
