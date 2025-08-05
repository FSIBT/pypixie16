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
import signal
import argparse
import numpy as np

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QSplitter,
    QPushButton,
    QLabel,
    QComboBox,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon

try:
    import pixie16 as px
    from pixie16.live.live_data_reader import LiveDataReader, LiveDataSourceInterface
    from pixie16.ui.mca_spectrum_plotter import MCASpectrumPlotter
    from pixie16.ui.spectrum_plotter import ContinuousSpectrumPlotter
    from pixie16.ui.traces_plotter import TracesPlotter
    from pixie16.ui.channel_controls import ChannelDisplayControls
    from pixie16.ui.parameter_controls import ParameterControls
    from pixie16.ui.widgets import BaseApp
except ImportError as e:
    print(f"Error importing pixie16 modules: {e}")
    px = None

from .binary_loader import BinaryFileLoader


class PixieScopeApp(BaseApp):
    shutdown_requested = pyqtSignal()

    def __init__(self, dummy_mode=False, physical_slot=2, channels=None):
        super().__init__("PIXIE-16 Scope")

        self.dummy_mode = dummy_mode
        self.physical_slot = physical_slot
        self.channels = channels or list(range(16))
        self.channel_numbers = channels or list(range(16))

        self.dynamic_settings = {
            "TRIGGER_THRESHOLD": 100,
            "TRIGGER_RISETIME": 0.02,
            "TRIGGER_FLATTOP": 0.02,
            "ENERGY_RISETIME": 2.0,
            "ENERGY_FLATTOP": 0.5,
            "TRACE_LENGTH": 2.0,
            "TRACE_DELAY": 0.5,
            "SLOW_FILTER_RANGE": 1,
            "FAST_FILTER_RANGE": 1,
            "GoodChannel": True,
            "CaptureHistogram": False,
            "CaptureTrace": False,
            "CaptureSums": False,
        }

        # Per-channel settings
        self.channel_settings = {}
        for ch in self.channels:
            self.channel_settings[ch] = self.dynamic_settings.copy()

        # Acquisition state
        self.is_acquiring = False
        self.current_mode = "mca_mode"
        self.is_initialized = False

        # Data components
        self.live_reader = None
        self.data_source = None
        self.mca_data = {}
        self.cumulative_mca_data = {}

        # Initialize data storage
        for ch in self.channels:
            self.mca_data[ch] = np.zeros(32768, dtype=np.int32)
            self.cumulative_mca_data[ch] = np.zeros(32768, dtype=np.int64)

        self.setup_signal_handlers()
        self.init_pixie16()
        self.init_ui()
        self.setup_timers()

    def setup_signal_handlers(self):
        def signal_handler(signum, frame):
            print(f"\nReceived signal {signum}, shutting down...")
            self.shutdown_requested.emit()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        self.shutdown_requested.connect(self.close)

    def init_pixie16(self):
        if self.dummy_mode:
            self.info_bar.setText("DUMMY MODE - No hardware initialization")
            self.is_initialized = True
            return

        if px is None:
            QMessageBox.critical(self, "Error", "pypixie16 not available")
            sys.exit(1)

        try:
            print(f"Initializing PIXIE-16 in slot {self.physical_slot}...")
            px.control.init_and_boot(modules=[self.physical_slot], verbose=True)

            # Verify initialization
            settings = px.control.read_settings()
            if settings:
                self.is_initialized = True
                self.info_bar.setText(f"PIXIE-16 Slot {self.physical_slot} initialized")
            else:
                raise RuntimeError("No modules found after initialization")

        except Exception as e:
            reply = QMessageBox.question(
                self,
                "Hardware Failed",
                f"PIXIE-16 initialization failed: {e}\n\nContinue in dummy mode?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.dummy_mode = True
                self.info_bar.setText("DUMMY MODE - Hardware initialization failed")
                self.is_initialized = True
            else:
                sys.exit(1)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        # Main splitter layout
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left side - plotting area
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # Control panel
        control_panel = self.create_control_panel()
        left_layout.addWidget(control_panel)

        # Initialize spectrum plotter
        self.spectrum_tab = MCASpectrumPlotter(
            channels=self.channels, title="PIXIE-16 MCA Spectra"
        )
        left_layout.addWidget(self.spectrum_tab)

        # Right side - controls
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # Binary file loader
        self.binary_loader = BinaryFileLoader(parent_scope=self)
        right_layout.addWidget(self.binary_loader)

        # Channel controls
        self.channel_controls = ChannelDisplayControls(
            channels=[(0, ch) for ch in self.channels], title="Channels"
        )
        self.channel_controls.channels_changed.connect(self.update_display_channels)
        right_layout.addWidget(self.channel_controls)

        # Parameter controls
        self.parameter_controls = ParameterControls(
            initial_module=0, title="Parameters"
        )
        self.parameter_controls.parameter_changed.connect(self.handle_parameter_change)
        self.parameter_controls.apply_all_requested.connect(
            self.handle_apply_all_parameters
        )
        self.parameter_controls.status_message.connect(self.update_info_bar)

        # Sync parameter controls with current settings
        self.parameter_controls.set_all_parameters(self.dynamic_settings)
        right_layout.addWidget(self.parameter_controls)

        # Set splitter sizes
        left_widget.setMinimumWidth(400)
        right_widget.setMinimumWidth(200)
        right_widget.setMaximumWidth(350)

        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(right_widget)
        main_splitter.setSizes([900, 300])

        # Main layout with info bar
        main_layout = QVBoxLayout()
        main_layout.addWidget(main_splitter)
        main_layout.addWidget(self.info_bar)

        main_widget.setLayout(main_layout)
        self.setGeometry(100, 100, 1200, 800)

    def create_control_panel(self):
        group = QGroupBox("Acquisition Controls")
        group.setMaximumHeight(120)
        layout = QVBoxLayout()

        # Mode and control buttons
        top_layout = QHBoxLayout()

        top_layout.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["MCA Mode", "List Mode", "Traces Mode"])
        self.mode_combo.currentTextChanged.connect(self.on_mode_changed)
        top_layout.addWidget(self.mode_combo)

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
        # Store pipeline state before switching
        pipeline_state = self.preserve_pipeline_during_mode_switch()

        old_mode = self.current_mode
        self.current_mode = mode_text.lower().replace(" ", "_")

        print(f"DEBUG: Mode change: {old_mode} → {self.current_mode}")
        print(f"DEBUG: Pipeline state: {pipeline_state}")

        # Stop spectrum updates but keep acquisition running if possible
        if hasattr(self.spectrum_tab, "stop_live_updates"):
            self.spectrum_tab.stop_live_updates()

        # Switch spectrum plotter
        old_tab = self.spectrum_tab

        if self.current_mode == "mca_mode":
            self.spectrum_tab = MCASpectrumPlotter(
                channels=self.channels, title="PIXIE-16 MCA Spectra"
            )
            # For MCA mode, we need to stop list/traces and start histogram mode
            if pipeline_state["is_acquiring"] and old_mode in [
                "list_mode",
                "traces_mode",
            ]:
                self.stop_acquisition()
                # Will restart with MCA when user clicks start
        elif self.current_mode == "list_mode":
            self.spectrum_tab = ContinuousSpectrumPlotter(
                app=None,
                instrument_name="pixie16",
                display_name="PIXIE-16 List Mode Spectra",
                channels=self.channels,
                energy_range=(0, 8192),
                bins=1000,
            )
        elif self.current_mode == "traces_mode":
            self.spectrum_tab = TracesPlotter(
                channels=self.channels, title="PIXIE-16 Traces"
            )

        # Replace in layout
        layout = old_tab.parent().layout()
        layout.replaceWidget(old_tab, self.spectrum_tab)
        old_tab.setParent(None)

        # Restore pipeline for list/traces modes
        if self.current_mode in ["list_mode", "traces_mode"]:
            self.restore_pipeline(pipeline_state, self.current_mode)

            # Restart spectrum updates
            if hasattr(self.spectrum_tab, "start_live_updates"):
                self.spectrum_tab.start_live_updates()

        self.info_bar.setText(f"Mode changed: {old_mode} → {self.current_mode}")

    def handle_parameter_change(self, param_name, value, module, channel):
        try:
            print(
                f"DEBUG: Handling parameter change: {param_name} = {value} for M{module}:Ch{channel}"
            )

            # Store whether we were acquiring before parameter change
            was_acquiring = self.is_acquiring
            current_mode = self.current_mode

            # Update our dynamic settings
            if channel is not None and channel in self.channel_settings:
                self.channel_settings[channel][param_name] = value
            self.dynamic_settings[param_name] = value
            print(f"DEBUG: Updated global setting: {param_name} = {value}")

            # Apply to hardware if not in dummy mode
            if not self.dummy_mode and px:
                # CRITICAL: Don't stop acquisition for parameter changes
                # Just update the hardware directly
                if self._is_channel_parameter(param_name):
                    px.control.set_channel_parameter(param_name, value, module, channel)
                else:
                    px.control.set_module_parameter(param_name, value, module)

                # If we're currently acquiring, update the running settings
                if was_acquiring and self.current_mode in ["list_mode", "traces_mode"]:
                    # Apply updated settings to running acquisition
                    settings = self.get_settings_for_mode(current_mode)
                    px.control.change_setting_from_dict(settings, call_pixie=True)

                self.info_bar.setText(
                    f"Set {param_name} = {value} on M{module}:Ch{channel}"
                )
                print(f"DEBUG: Applied to hardware without stopping acquisition")
            else:
                self.info_bar.setText(f"DUMMY MODE - stored {param_name} = {value}")
                print(f"DEBUG: DUMMY MODE - stored {param_name} = {value}")

        except Exception as e:
            error_msg = f"Error setting {param_name}: {e}"
            print(f"DEBUG ERROR: {error_msg}")
            self.info_bar.setText(error_msg)

    def preserve_pipeline_during_mode_switch(self):
        # Store current pipeline state
        had_live_reader = hasattr(self, "live_reader") and self.live_reader is not None
        had_data_source = hasattr(self, "data_source") and self.data_source is not None
        was_fifo_active = (
            hasattr(self, "data_timer")
            and self.data_timer
            and self.data_timer.isActive()
        )

        return {
            "had_live_reader": had_live_reader,
            "had_data_source": had_data_source,
            "was_fifo_active": was_fifo_active,
            "is_acquiring": self.is_acquiring,
        }

    def restore_pipeline(self, pipeline_state, new_mode):
        if not pipeline_state["is_acquiring"]:
            return

        # If we had a working pipeline, recreate it for the new mode
        if pipeline_state["had_live_reader"] and pipeline_state["had_data_source"]:
            if new_mode in ["list_mode", "traces_mode"]:
                print(f"DEBUG: Restoring pipeline for {new_mode}")

                # Recreate live reader if needed
                if not hasattr(self, "live_reader") or self.live_reader is None:
                    self.live_reader = LiveDataReader()

                    if new_mode == "list_mode":
                        self.live_reader.add_event_callback(
                            self.process_list_mode_event
                        )
                    else:
                        self.live_reader.add_event_callback(self.process_traces_event)

                # Recreate data source if needed
                if not hasattr(self, "data_source") or self.data_source is None:
                    self.data_source = LiveDataSourceInterface(self.live_reader)
                    self.data_source.start_acquisition()

                # Restart FIFO timer if needed and not in dummy mode
                if pipeline_state["was_fifo_active"] and not self.dummy_mode:
                    if (
                        not hasattr(self, "data_timer")
                        or not self.data_timer.isActive()
                    ):
                        self.data_timer = QTimer()
                        self.data_timer.timeout.connect(self.read_list_mode_fifo)
                        interval = 50 if new_mode == "list_mode" else 100
                        self.data_timer.start(interval)
                        print(f"DEBUG: Restarted FIFO timer for {new_mode}")

    def handle_apply_all_parameters(self, params_dict, module, channel):
        try:
            print(f"DEBUG: Applying all parameters to M{module}:Ch{channel}")
            print(f"DEBUG: Parameters: {params_dict}")

            # Update our settings
            for param_name, value in params_dict.items():
                if channel is not None and channel in self.channel_settings:
                    self.channel_settings[channel][param_name] = value
                self.dynamic_settings[param_name] = value

            # Apply to hardware if not in dummy mode
            if not self.dummy_mode and px:
                # Use change_setting_from_dict for bulk update
                settings_dict = {"channels": [(module, channel)], **params_dict}
                px.control.change_setting_from_dict(settings_dict, call_pixie=True)
                self.info_bar.setText(
                    f"Applied {len(params_dict)} parameters to M{module}:Ch{channel}"
                )
                print(f"DEBUG: Applied all parameters to hardware")
            else:
                self.info_bar.setText(
                    f"DUMMY MODE - Applied {len(params_dict)} parameters"
                )
                print(f"DEBUG: DUMMY MODE - stored all parameters")

        except Exception as e:
            error_msg = f"Error applying parameters: {e}"
            print(f"DEBUG ERROR: {error_msg}")
            self.info_bar.setText(error_msg)

    def _is_channel_parameter(self, param_name):
        channel_params = {
            "TRIGGER_THRESHOLD",
            "TRIGGER_RISETIME",
            "TRIGGER_FLATTOP",
            "ENERGY_RISETIME",
            "ENERGY_FLATTOP",
            "TRACE_LENGTH",
            "TRACE_DELAY",
            "VOFFSET",
            "TAU",
            "BASELINE_PERCENT",
            "BASELINE_AVERAGE",
            "EMIN",
            "BINFACTOR",
            "CFDDelay",
            "CFDScale",
            "CFDThresh",
            "QDCLen0",
            "QDCLen1",
            "QDCLen2",
            "QDCLen3",
            "QDCLen4",
            "QDCLen5",
            "QDCLen6",
            "QDCLen7",
            "ExtTrigStretch",
            "VetoStretch",
            "ExternDelayLen",
            "FtrigoutDelay",
            "ChanTrigStretch",
            "CHANNEL_CSRA",
            "CHANNEL_CSRB",
            "Gain",
            "Polarity",
            "GoodChannel",
            "CaptureTrace",
        }
        return param_name in channel_params

    def start_acquisition(self):
        try:
            # Check for binary replay mode
            if (
                hasattr(self.binary_loader, "is_using_binary_data")
                and self.binary_loader.is_using_binary_data()
            ):
                success = self.binary_loader.start_replay()
                if success and hasattr(self.spectrum_tab, "start_live_updates"):
                    self.spectrum_tab.start_live_updates()
                    self.is_acquiring = True
                    self.update_acquisition_buttons(True)
                    self.info_bar.setText("Binary file replay started")
                return

            # Get current settings for the mode
            settings = self.get_settings_for_mode(self.current_mode)

            # Start hardware acquisition
            if self.current_mode == "mca_mode":
                success = self.start_mca_mode(settings)
            elif self.current_mode == "list_mode":
                success = self.start_list_mode(settings)
            elif self.current_mode == "traces_mode":
                success = self.start_traces_mode(settings)
            else:
                success = False

            if success:
                self.is_acquiring = True
                self.update_acquisition_buttons(True)
                self.status_label.setText(f"Status: Acquiring ({self.current_mode})")
            else:
                raise RuntimeError("Failed to start acquisition")

        except Exception as e:
            self.info_bar.setText(f"Failed to start acquisition: {e}")

    def get_settings_for_mode(self, mode):
        settings = self.dynamic_settings.copy()
        settings["channels"] = [(0, ch) for ch in self.channels]  # Logical module 0

        if mode == "mca_mode":
            settings.update(
                {
                    "CaptureHistogram": True,
                    "CaptureTrace": False,
                    "CaptureSums": False,
                }
            )
        elif mode == "list_mode":
            settings.update(
                {
                    "CaptureHistogram": False,
                    "CaptureTrace": False,
                    "CaptureSums": False,
                }
            )
        elif mode == "traces_mode":
            settings.update(
                {
                    "CaptureHistogram": False,
                    "CaptureTrace": True,
                    "CaptureSums": True,
                }
            )

        return settings

    def start_mca_mode(self, settings):
        if self.dummy_mode:
            self.setup_dummy_mca_timer()
            return True

        try:
            px.control.change_setting_from_dict(settings, call_pixie=True)
            px.control.start_histogram_run()

            # Start histogram reading timer
            self.acquisition_timer = QTimer()
            self.acquisition_timer.timeout.connect(self.read_histogram_data)
            self.acquisition_timer.start(2000)  # 2 second intervals

            if hasattr(self.spectrum_tab, "start_live_updates"):
                self.spectrum_tab.start_live_updates()

            return True
        except Exception as e:
            print(f"Error starting MCA mode: {e}")
            return False

    def start_list_mode(self, settings):
        if self.dummy_mode:
            return True

        try:
            px.control.change_setting_from_dict(settings, call_pixie=True)
            px.control.start_list_mode_run()

            # Set up live data processing
            self.live_reader = LiveDataReader()
            self.data_source = LiveDataSourceInterface(self.live_reader)
            self.live_reader.add_event_callback(self.process_list_mode_event)

            # Start FIFO reading timer
            self.data_timer = QTimer()
            self.data_timer.timeout.connect(self.read_list_mode_fifo)
            self.data_timer.start(50)  # 50ms intervals

            self.data_source.start_acquisition()

            if hasattr(self.spectrum_tab, "start_live_updates"):
                self.spectrum_tab.start_live_updates()

            return True
        except Exception as e:
            print(f"Error starting list mode: {e}")
            return False

    def start_traces_mode(self, settings):
        if self.dummy_mode:
            return True

        try:
            px.control.change_setting_from_dict(settings, call_pixie=True)
            px.control.start_list_mode_run()  # Traces come through list mode

            # Set up live data processing
            self.live_reader = LiveDataReader()
            self.data_source = LiveDataSourceInterface(self.live_reader)
            self.live_reader.add_event_callback(self.process_traces_event)

            # Start FIFO reading timer
            self.data_timer = QTimer()
            self.data_timer.timeout.connect(self.read_list_mode_fifo)
            self.data_timer.start(100)  # 100ms intervals

            self.data_source.start_acquisition()

            if hasattr(self.spectrum_tab, "start_live_updates"):
                self.spectrum_tab.start_live_updates()

            return True
        except Exception as e:
            print(f"Error starting traces mode: {e}")
            return False

    def setup_dummy_mca_timer(self):
        self.acquisition_timer = QTimer()
        self.acquisition_timer.timeout.connect(self.generate_dummy_mca_data)
        self.acquisition_timer.start(1000)

        if hasattr(self.spectrum_tab, "start_live_updates"):
            self.spectrum_tab.start_live_updates()

    def generate_dummy_mca_data(self):
        for channel in self.channels:
            # Generate synthetic spectrum with peaks
            x = np.arange(32768)
            spectrum = np.zeros(32768)

            # Add some peaks at different energies
            peak_positions = [1000, 2000, 4000, 8000, 16000]
            for pos in peak_positions:
                if pos < 32768:
                    width = 50
                    height = np.random.poisson(1000)  # Poisson statistics
                    spectrum += height * np.exp(-0.5 * ((x - pos) / width) ** 2)

            # Add noise
            noise = np.random.poisson(10, 32768)
            spectrum += noise

            self.mca_data[channel] = spectrum.astype(np.int32)
            self.cumulative_mca_data[channel] += spectrum.astype(np.int64)

            # Update plotter
            if hasattr(self.spectrum_tab, "update_mca_histogram"):
                self.spectrum_tab.update_mca_histogram(channel, self.mca_data[channel])

    def read_histogram_data(self):
        if self.dummy_mode:
            return

        try:
            module_channels = [(0, ch) for ch in self.channels]
            hist_list = px.control.read_histograms(module_channels)

            channel_stats = {}
            for i, channel in enumerate(self.channels):
                if i < len(hist_list) and hist_list[i] is not None:
                    histogram = np.array(hist_list[i], dtype=np.int32)
                    self.mca_data[channel] = histogram
                    self.cumulative_mca_data[channel] = histogram.astype(np.int64)

                    if hasattr(self.spectrum_tab, "update_mca_histogram"):
                        self.spectrum_tab.update_mca_histogram(channel, histogram)

                    channel_stats[channel] = int(np.sum(histogram))

            # Update channel controls
            if hasattr(self.channel_controls, "update_channel_statistics"):
                self.channel_controls.update_channel_statistics(channel_stats)

        except Exception as e:
            print(f"Error reading histograms: {e}")

    def read_list_mode_fifo(self):
        if not self.is_acquiring:
            print("DEBUG: FIFO read called but not acquiring - stopping timer")
            if hasattr(self, "data_timer") and self.data_timer:
                self.data_timer.stop()
            return

        if self.dummy_mode:
            return  # Dummy mode uses binary replay, not FIFO

        if not self.live_reader:
            print("DEBUG: FIFO read called but no live_reader - recreating pipeline")
            # Try to recreate the pipeline
            try:
                self.live_reader = LiveDataReader()
                if self.current_mode == "list_mode":
                    self.live_reader.add_event_callback(self.process_list_mode_event)
                elif self.current_mode == "traces_mode":
                    self.live_reader.add_event_callback(self.process_traces_event)

                if not hasattr(self, "data_source") or not self.data_source:
                    self.data_source = LiveDataSourceInterface(self.live_reader)
                    self.data_source.start_acquisition()

            except Exception as e:
                print(f"DEBUG: Failed to recreate pipeline: {e}")
                return

        try:
            # Read from hardware FIFO
            data_list = px.control.read_list_mode_fifo(check=True, threshold=8)

            # Debug counters
            if not hasattr(self, "_fifo_debug_counter"):
                self._fifo_debug_counter = 0
                self._last_fifo_debug = time.time()

            total_words = sum(len(data) for data in data_list or [])
            self._fifo_debug_counter += total_words

            # Feed data to live reader
            for data in data_list or []:
                if len(data) > 0:
                    self.live_reader.add_data(data)

            # Debug output every 3 seconds
            current_time = time.time()
            if current_time - self._last_fifo_debug > 3.0:
                print(
                    f"FIFO: Read {total_words} words, {self._fifo_debug_counter} total, pipeline OK"
                )
                self._last_fifo_debug = current_time

        except Exception as e:
            print(f"Error reading FIFO: {e}")
            # Don't stop the timer - keep trying

    def process_list_mode_event(self, event):
        try:
            channel = getattr(event, "channel", 0)
            energy = getattr(event, "energy", 0)

            if channel in self.channels:
                if hasattr(self.spectrum_tab, "add_energy_event"):
                    self.spectrum_tab.add_energy_event(channel, energy)

        except Exception as e:
            print(f"Error processing list mode event: {e}")

    def process_traces_event(self, event):
        try:
            channel = getattr(event, "channel", 0)
            trace = getattr(event, "trace", None)

            if channel in self.channels and trace is not None:
                if hasattr(self.spectrum_tab, "add_trace"):
                    self.spectrum_tab.add_trace(channel, trace)

        except Exception as e:
            print(f"Error processing traces event: {e}")

    def stop_acquisition(self):
        try:
            # Stop binary replay
            if hasattr(self.binary_loader, "stop_replay"):
                self.binary_loader.stop_replay()

            # Stop timers
            for timer_name in ["acquisition_timer", "data_timer"]:
                timer = getattr(self, timer_name, None)
                if timer:
                    timer.stop()
                    setattr(self, timer_name, None)

            # Stop spectrum updates
            if hasattr(self.spectrum_tab, "stop_live_updates"):
                self.spectrum_tab.stop_live_updates()

            # Stop hardware acquisition
            if not self.dummy_mode and px:
                px.control.end_run()

            # Clean up data source
            if self.data_source:
                self.data_source.stop_acquisition()
                self.data_source = None

            self.live_reader = None
            self.is_acquiring = False

            self.update_acquisition_buttons(False)
            self.status_label.setText("Status: Stopped")
            self.info_bar.setText("Acquisition stopped")

        except Exception as e:
            print(f"Error stopping acquisition: {e}")

    def clear_data(self):
        try:
            for channel in self.channels:
                self.mca_data[channel].fill(0)
                self.cumulative_mca_data[channel].fill(0)

            if hasattr(self.spectrum_tab, "clear_data"):
                self.spectrum_tab.clear_data()

            self.info_bar.setText("Data cleared")

        except Exception as e:
            print(f"Error clearing data: {e}")

    def update_display_channels(self, selected_channels):
        valid_channels = [ch for ch in selected_channels if ch in self.channels]

        if hasattr(self.spectrum_tab, "set_display_channels"):
            self.spectrum_tab.set_display_channels(valid_channels)

        self.info_bar.setText(f"Displaying {len(valid_channels)} channels")

    def update_acquisition_buttons(self, acquiring):
        self.start_btn.setEnabled(not acquiring)
        self.stop_btn.setEnabled(acquiring)

    def update_info_bar(self, message):
        prefix = "DUMMY MODE - " if self.dummy_mode else ""
        self.info_bar.setText(f"{prefix}{message}")

    def setup_timers(self):
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)

    def update_status(self):
        try:
            if self.live_reader:
                stats = self.live_reader.get_statistics()
                rate = stats.get("processing_rate", 0)
                events = stats.get("events_processed", 0)

                self.rate_label.setText(f"Rate: {rate:.1f} Hz")
                self.events_label.setText(f"Events: {events}")
        except Exception as e:
            print(f"Error updating status: {e}")

    def closeEvent(self, event):
        try:
            if self.is_acquiring:
                self.stop_acquisition()

            if hasattr(self, "status_timer") and self.status_timer:
                self.status_timer.stop()

            print("PIXIE-16 Scope shutdown complete")
            event.accept()
        except Exception as e:
            print(f"Error during shutdown: {e}")
            event.accept()


def main():
    parser = argparse.ArgumentParser(description="PIXIE-16 Scope")
    parser.add_argument("--dummy", action="store_true", help="Run in dummy mode")
    parser.add_argument("--slot", type=int, default=2, help="Physical slot number")
    parser.add_argument(
        "--channels",
        type=str,
        default="0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15",
        help="Comma-separated channel list",
    )

    args = parser.parse_args()

    try:
        channels = [int(ch.strip()) for ch in args.channels.split(",")]
    except ValueError:
        print("Error: Invalid channel list format")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("PIXIE-16 Scope")

    print(f"Starting PIXIE-16 Scope - Slot {args.slot}")
    print(f"Mode: {'DUMMY' if args.dummy else 'HARDWARE'}")
    print(f"Channels: {channels}")

    try:
        window = PixieScopeApp(
            dummy_mode=args.dummy, physical_slot=args.slot, channels=channels
        )
        window.show()

        print("PIXIE-16 Scope ready!")
        sys.exit(app.exec())

    except KeyboardInterrupt:
        print("\nKeyboard interrupt - shutting down...")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
