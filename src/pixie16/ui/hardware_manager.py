"""
Dynamic hardware manager for PIXIE-16 with real-time parameter updates
and improved mode switching.
"""

import time
import threading
import logging
from typing import Any
from dataclasses import dataclass
import numpy as np

try:
    import pixie16 as px
except ImportError:
    px = None

logger = logging.getLogger(__name__)


@dataclass
class HardwareState:
    is_initialized: bool = False
    is_running: bool = False
    current_mode: str | None = None  # 'histogram', 'list', 'traces'
    enabled_channels: list[int] = None
    current_parameters: dict[str, dict[str, Any]] = None  # module -> channel -> params

    def __post_init__(self):
        if self.enabled_channels is None:
            self.enabled_channels = list(range(16))
        if self.current_parameters is None:
            self.current_parameters = {}


class DynamicPixieHardwareManager:
    def __init__(self, physical_slot: int = 2, dummy_mode: bool = False):
        self.physical_slot = physical_slot
        self.dummy_mode = dummy_mode
        self.state = HardwareState()
        self.parameter_lock = threading.Lock()
        self.mode_transition_lock = threading.Lock()

        # Default parameter sets for different modes
        self.mode_parameter_templates = {
            "histogram": {
                "CaptureHistogram": True,
                "CaptureTrace": False,
                "CaptureSums": False,
                "GoodChannel": True,
            },
            "list": {
                "CaptureHistogram": False,
                "CaptureTrace": False,
                "CaptureSums": False,
                "GoodChannel": True,
                "EnableChannelVal": False,
            },
            "traces": {
                "CaptureHistogram": False,
                "CaptureTrace": True,
                "CaptureSums": True,
                "GoodChannel": True,
                "EnableChannelVal": False,
            },
        }

        # Parameter cache for restoration
        self.parameter_cache = {}

    def initialize_system(self) -> bool:
        if self.dummy_mode:
            logger.info("DUMMY MODE: Simulating PIXIE-16 initialization")
            self.state.is_initialized = True
            self._initialize_dummy_parameters()
            return True

        if px is None:
            raise RuntimeError("pypixie16 not available")

        try:
            logger.info(f"Initializing PIXIE-16 system in slot {self.physical_slot}")

            # Clean initialization
            try:
                px.control.exit_system()
                time.sleep(0.5)
            except:
                pass  # Ignore if system wasn't initialized

            # Initialize and boot
            px.control.init_and_boot(modules=[self.physical_slot], verbose=True)

            # Verify and read initial state
            settings = px.control.read_settings()
            if len(settings) > 0:
                logger.info(
                    f"PIXIE-16 system initialized successfully with {len(settings)} modules"
                )
                self.state.is_initialized = True
                self._read_initial_parameters()
                return True
            else:
                raise RuntimeError("No modules found after initialization")

        except Exception as e:
            logger.error(f"PIXIE-16 initialization failed: {e}")
            return False

    def _initialize_dummy_parameters(self):
        default_params = {
            "TRIGGER_THRESHOLD": 1000,
            "TRIGGER_RISETIME": 0.1,
            "TRIGGER_FLATTOP": 0.1,
            "ENERGY_RISETIME": 2.0,
            "ENERGY_FLATTOP": 0.5,
            "TAU": 50.0,
            "TRACE_LENGTH": 2.0,
            "TRACE_DELAY": 0.5,
            "GoodChannel": True,
            "CaptureTrace": False,
        }

        for module in range(1):  # Logical module 0
            self.state.current_parameters[module] = {}
            for channel in range(16):
                self.state.current_parameters[module][channel] = default_params.copy()

    def _read_initial_parameters(self):
        if self.dummy_mode:
            return

        try:
            # Read settings for logical module 0
            settings = px.control.read_settings()
            if not settings:
                return

            module_settings = settings[0]  # Logical module 0
            self.state.current_parameters[0] = {}

            for channel in range(16):
                channel_params = {}

                # Read key parameters
                param_names = [
                    "TRIGGER_THRESHOLD",
                    "TRIGGER_RISETIME",
                    "TRIGGER_FLATTOP",
                    "ENERGY_RISETIME",
                    "ENERGY_FLATTOP",
                    "TAU",
                    "TRACE_LENGTH",
                    "TRACE_DELAY",
                    "VOFFSET",
                    "BASELINE_PERCENT",
                ]

                for param in param_names:
                    try:
                        value = px.control.get_channel_parameter(param, 0, channel)
                        channel_params[param] = value
                    except Exception as e:
                        logger.warning(f"Could not read {param} for Ch{channel}: {e}")

                self.state.current_parameters[0][channel] = channel_params

            logger.info("Initial parameters read from hardware")

        except Exception as e:
            logger.error(f"Failed to read initial parameters: {e}")

    def update_parameter(
        self, param_name: str, value: Any, module: int = 0, channel: int = 0
    ) -> bool:
        with self.parameter_lock:
            try:
                # Update cache first
                if module not in self.state.current_parameters:
                    self.state.current_parameters[module] = {}
                if channel not in self.state.current_parameters[module]:
                    self.state.current_parameters[module][channel] = {}

                old_value = self.state.current_parameters[module][channel].get(
                    param_name
                )
                self.state.current_parameters[module][channel][param_name] = value

                # Apply to hardware
                if not self.dummy_mode and self.state.is_initialized:
                    success = self._apply_parameter_to_hardware(
                        param_name, value, module, channel
                    )
                    if not success:
                        # Rollback cache on failure
                        if old_value is not None:
                            self.state.current_parameters[module][channel][
                                param_name
                            ] = old_value
                        return False

                logger.debug(f"Updated {param_name}={value} on M{module}:Ch{channel}")
                return True

            except Exception as e:
                logger.error(f"Failed to update parameter {param_name}: {e}")
                return False

    def update_parameters(
        self, params: dict[str, Any], module: int = 0, channel: int = 0
    ) -> bool:
        with self.parameter_lock:
            # Validate all parameters first
            validated_params = {}
            for name, value in params.items():
                if self._is_valid_parameter(name, value):
                    validated_params[name] = value
                else:
                    logger.warning(f"Invalid parameter {name}={value}, skipping")

            if not validated_params:
                return False

            # Store old values for rollback
            old_values = {}
            if (
                module in self.state.current_parameters
                and channel in self.state.current_parameters[module]
            ):
                old_values = {
                    name: self.state.current_parameters[module][channel].get(name)
                    for name in validated_params.keys()
                }

            # Update cache
            if module not in self.state.current_parameters:
                self.state.current_parameters[module] = {}
            if channel not in self.state.current_parameters[module]:
                self.state.current_parameters[module][channel] = {}

            for name, value in validated_params.items():
                self.state.current_parameters[module][channel][name] = value

            # Apply to hardware
            if not self.dummy_mode and self.state.is_initialized:
                success = self._apply_parameters_to_hardware(
                    validated_params, module, channel
                )
                if not success:
                    # Rollback cache
                    for name, old_value in old_values.items():
                        if old_value is not None:
                            self.state.current_parameters[module][channel][name] = (
                                old_value
                            )
                    return False

            logger.info(
                f"Updated {len(validated_params)} parameters on M{module}:Ch{channel}"
            )
            return True

    def _apply_parameter_to_hardware(
        self, param_name: str, value: Any, module: int, channel: int
    ) -> bool:
        try:
            if param_name in ["GoodChannel", "CaptureTrace", "Gain", "Polarity"]:
                # These require special handling via settings dictionary
                settings = {"channels": [(module, channel)], param_name: value}
                px.control.change_setting_from_dict(settings, call_pixie=True)
            else:
                # Standard parameter update
                px.control.set_channel_parameter(param_name, value, module, channel)

            return True

        except Exception as e:
            logger.error(f"Hardware update failed for {param_name}: {e}")
            return False

    def _apply_parameters_to_hardware(
        self, params: dict[str, Any], module: int, channel: int
    ) -> bool:
        try:
            # Separate standard parameters from special ones
            standard_params = {}
            special_params = {}

            for name, value in params.items():
                if name in ["GoodChannel", "CaptureTrace", "Gain", "Polarity"]:
                    special_params[name] = value
                else:
                    standard_params[name] = value

            # Apply standard parameters
            for name, value in standard_params.items():
                px.control.set_channel_parameter(name, value, module, channel)

            # Apply special parameters via settings dictionary
            if special_params:
                settings = {"channels": [(module, channel)], **special_params}
                px.control.change_setting_from_dict(settings, call_pixie=True)

            return True

        except Exception as e:
            logger.error(f"Batch hardware update failed: {e}")
            return False

    def _is_valid_parameter(
        self, name: str, value: Any
    ) -> bool:  # simple check before using ParameterValidator
        if name == "TRIGGER_THRESHOLD":
            return isinstance(value | (int, float)) and 1 <= value <= 65535
        elif name in [
            "TRIGGER_RISETIME",
            "TRIGGER_FLATTOP",
            "ENERGY_RISETIME",
            "ENERGY_FLATTOP",
        ]:
            return isinstance(value | (int, float)) and value >= 0
        elif name in ["GoodChannel", "CaptureTrace"]:
            return isinstance(value, bool)
        return True

    def start_mode(self, mode: str) -> bool:
        with self.mode_transition_lock:
            try:
                # Stop current mode cleanly
                if self.state.is_running:
                    logger.info(f"Stopping current mode: {self.state.current_mode}")
                    self._stop_current_mode()
                    time.sleep(0.2)  # Allow hardware to settle

                # Apply mode-specific settings
                mode_settings = self._get_mode_settings(mode)
                if not self._apply_mode_settings(mode_settings):
                    logger.error(f"Failed to apply settings for {mode} mode")
                    return False

                # Start the specific mode
                if mode == "histogram":
                    success = self._start_histogram_mode()
                elif mode == "list":
                    success = self._start_list_mode()
                elif mode == "traces":
                    success = self._start_traces_mode()
                else:
                    logger.error(f"Unknown mode: {mode}")
                    return False

                if success:
                    self.state.is_running = True
                    self.state.current_mode = mode
                    logger.info(f"Successfully started {mode} mode")
                    return True
                else:
                    logger.error(f"Failed to start {mode} mode")
                    return False

            except Exception as e:
                logger.error(f"Mode transition to {mode} failed: {e}")
                return False

    def _get_mode_settings(self, mode: str) -> dict[str, Any]:
        base_settings = {
            "channels": [(0, ch) for ch in self.state.enabled_channels],
        }

        # Add mode-specific template
        if mode in self.mode_parameter_templates:
            base_settings.update(self.mode_parameter_templates[mode])

        # Apply current user parameters
        current_params = self._get_current_channel_parameters()
        base_settings.update(current_params)

        return base_settings

    def _get_current_channel_parameters(self) -> dict[str, Any]:
        params = {}

        if 0 in self.state.current_parameters:
            # Use parameters from channel 0 as default (could be enhanced per-channel)
            channel_0_params = self.state.current_parameters[0].get(0, {})

            # Map to settings format
            for param_name, value in channel_0_params.items():
                if param_name in [
                    "TRIGGER_THRESHOLD",
                    "TRIGGER_RISETIME",
                    "TRIGGER_FLATTOP",
                    "ENERGY_RISETIME",
                    "ENERGY_FLATTOP",
                    "TRACE_LENGTH",
                    "TRACE_DELAY",
                ]:
                    params[param_name] = value

        return params

    def _apply_mode_settings(self, settings: dict[str, Any]) -> bool:
        if self.dummy_mode:
            logger.info(f"DUMMY MODE: Applying settings: {settings}")
            return True

        try:
            px.control.change_setting_from_dict(settings, call_pixie=True)
            logger.debug("Mode settings applied successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to apply mode settings: {e}")
            return False

    def _start_histogram_mode(self) -> bool:
        if self.dummy_mode:
            logger.info("DUMMY MODE: Starting histogram collection")
            return True

        try:
            px.control.start_histogram_run()
            logger.info("Histogram mode started")
            return True
        except Exception as e:
            logger.error(f"Failed to start histogram mode: {e}")
            return False

    def _start_list_mode(self) -> bool:
        if self.dummy_mode:
            logger.info("DUMMY MODE: Starting list mode")
            return True

        try:
            px.control.start_list_mode_run()

            # Verify the run is active
            time.sleep(0.3)
            try:
                run_active = px.control.check_run_status()
                logger.debug(f"List mode run status: {run_active}")
            except:
                logger.warning("Could not verify list mode run status")

            logger.info("List mode started")
            return True
        except Exception as e:
            logger.error(f"Failed to start list mode: {e}")
            return False

    def _start_traces_mode(self) -> bool:
        if self.dummy_mode:
            logger.info("DUMMY MODE: Starting traces mode")
            return True

        try:
            # Traces come through list mode with trace capture enabled
            px.control.start_list_mode_run()
            logger.info("Traces mode started")
            return True
        except Exception as e:
            logger.error(f"Failed to start traces mode: {e}")
            return False

    def _stop_current_mode(self):
        if not self.state.is_running:
            return

        try:
            if not self.dummy_mode:
                px.control.end_run()
                time.sleep(0.1)

            self.state.is_running = False
            previous_mode = self.state.current_mode
            self.state.current_mode = None
            logger.info(f"Stopped {previous_mode} mode")

        except Exception as e:
            logger.error(f"Error stopping current mode: {e}")

    def read_histograms(self) -> dict[int, np.ndarray]:
        if self.state.current_mode != "histogram":
            return {}

        histograms = {}
        try:
            if self.dummy_mode:
                # Generate dummy histogram data
                for channel in self.state.enabled_channels:
                    # Create realistic-looking dummy data
                    hist = np.zeros(32768, dtype=np.int32)
                    if np.random.random() > 0.7:  # 30% chance of having data
                        # Add some peaks
                        peak_pos = np.random.randint(1000, 20000)
                        peak_width = np.random.randint(50, 200)
                        counts = np.random.randint(10, 1000)

                        x = np.arange(
                            max(0, peak_pos - peak_width),
                            min(32768, peak_pos + peak_width),
                        )
                        gaussian = counts * np.exp(
                            -0.5 * ((x - peak_pos) / (peak_width / 4)) ** 2
                        )
                        hist[x] = gaussian.astype(np.int32)

                    histograms[channel] = hist
            else:
                # Read from hardware
                module_channels = [(0, ch) for ch in self.state.enabled_channels]
                hist_list = px.control.read_histograms(module_channels)

                for i, channel in enumerate(self.state.enabled_channels):
                    if i < len(hist_list) and hist_list[i] is not None:
                        histograms[channel] = np.array(hist_list[i], dtype=np.int32)
                    else:
                        histograms[channel] = np.zeros(32768, dtype=np.int32)

        except Exception as e:
            logger.error(f"Error reading histograms: {e}")
            for channel in self.state.enabled_channels:
                histograms[channel] = np.zeros(32768, dtype=np.int32)

        return histograms

    def read_list_mode_data(self) -> list[Any]:
        if self.dummy_mode or self.state.current_mode not in ["list", "traces"]:
            return []

        try:
            data_list = px.control.read_list_mode_fifo(check=True, threshold=8)
            return data_list if data_list else []

        except Exception as e:
            logger.error(f"Error reading list mode data: {e}")
            return []

    def get_parameter(self, param_name: str, module: int = 0, channel: int = 0) -> Any:
        try:
            if module in self.state.current_parameters:
                if channel in self.state.current_parameters[module]:
                    return self.state.current_parameters[module][channel].get(
                        param_name
                    )
        except Exception as e:
            logger.error(f"Error getting parameter {param_name}: {e}")
        return None

    def get_all_parameters(self, module: int = 0, channel: int = 0) -> dict[str, Any]:
        try:
            if module in self.state.current_parameters:
                if channel in self.state.current_parameters[module]:
                    return self.state.current_parameters[module][channel].copy()
        except Exception as e:
            logger.error(f"Error getting parameters for M{module}:Ch{channel}: {e}")
        return {}

    def read_parameter_from_hardware(
        self, param_name: str, module: int = 0, channel: int = 0
    ) -> Any:
        if self.dummy_mode or not self.state.is_initialized:
            return self.get_parameter(param_name, module, channel)

        try:
            if param_name in ["GoodChannel", "CaptureTrace"]:
                # These require reading from settings
                settings = px.control.read_settings()
                if settings and len(settings) > module:
                    # Extract from channel settings
                    return settings[module].get(param_name, {}).get(channel, False)
            else:
                # Standard parameter read
                return px.control.get_channel_parameter(param_name, module, channel)

        except Exception as e:
            logger.error(f"Failed to read {param_name} from hardware: {e}")
            return None

    def refresh_parameter_cache(self, module: int = 0, channel: int = 0):
        if self.dummy_mode or not self.state.is_initialized:
            return

        param_names = [
            "TRIGGER_THRESHOLD",
            "TRIGGER_RISETIME",
            "TRIGGER_FLATTOP",
            "ENERGY_RISETIME",
            "ENERGY_FLATTOP",
            "TAU",
            "TRACE_LENGTH",
            "TRACE_DELAY",
            "VOFFSET",
            "BASELINE_PERCENT",
        ]

        updated_params = {}
        for param in param_names:
            try:
                value = self.read_parameter_from_hardware(param, module, channel)
                if value is not None:
                    updated_params[param] = value
            except Exception as e:
                logger.warning(f"Could not refresh {param}: {e}")

        if updated_params:
            with self.parameter_lock:
                if module not in self.state.current_parameters:
                    self.state.current_parameters[module] = {}
                if channel not in self.state.current_parameters[module]:
                    self.state.current_parameters[module][channel] = {}

                self.state.current_parameters[module][channel].update(updated_params)
                logger.debug(
                    f"Refreshed {len(updated_params)} parameters from hardware"
                )

    def stop_acquisition(self):
        with self.mode_transition_lock:
            self._stop_current_mode()

    def cleanup(self):
        try:
            self.stop_acquisition()

            if not self.dummy_mode and self.state.is_initialized:
                # Don't call exit_system here as it might affect other applications
                pass

            logger.info("Hardware manager cleaned up")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def get_state(self) -> HardwareState:
        return self.state

    def is_parameter_cached(
        self, param_name: str, module: int = 0, channel: int = 0
    ) -> bool:
        try:
            return (
                module in self.state.current_parameters
                and channel in self.state.current_parameters[module]
                and param_name in self.state.current_parameters[module][channel]
            )
        except:
            return False
