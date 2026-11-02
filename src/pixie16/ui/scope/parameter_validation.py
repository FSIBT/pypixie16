"""
Parameter validation system for PIXIE-16 with range checking.
"""

from dataclasses import dataclass
import logging
import threading

logger = logging.getLogger(__name__)


@dataclass
class ParameterSpec:
    name: str
    data_type: type
    min_value: float
    max_value: float
    unit: str
    description: str
    dsp_variable: str = ""
    requires_restart: bool = False
    module_level: bool = False


class PixieParameterValidator:
    def __init__(self, module_type: str = "100MHz"):
        """
        Initialize validator for specific module type.

        Args:
            module_type: "100MHz", "250MHz", or "500MHz" for timing calculations
        """
        self.module_type = module_type
        self.parameters = self._initialize_parameter_specs()

    def _initialize_parameter_specs(self) -> dict[str, ParameterSpec]:
        # Module type dependent timing constraints
        if self.module_type == "100MHz":
            trigger_rise_max = 127 * 0.01  # 127 * 10ns
            trigger_flat_max = 125 * 0.01  # 125 * 10ns
            energy_rise_min = 2 * 0.01  # 2 * 10ns
            energy_rise_max = 124 * 0.01  # 124 * 10ns
            energy_flat_min = 3 * 0.01  # 3 * 10ns
            energy_flat_max = 125 * 0.01  # 125 * 10ns
        elif self.module_type == "250MHz":
            trigger_rise_max = 127 * 0.008  # 127 * 8ns
            trigger_flat_max = 125 * 0.008  # 125 * 8ns
            energy_rise_min = 2 * 0.008  # 2 * 8ns
            energy_rise_max = 124 * 0.008  # 124 * 8ns
            energy_flat_min = 3 * 0.008  # 3 * 8ns
            energy_flat_max = 125 * 0.008  # 125 * 8ns
        else:  # 500MHz
            trigger_rise_max = 127 * 0.01  # Same as 100MHz for now
            trigger_flat_max = 125 * 0.01
            energy_rise_min = 2 * 0.01
            energy_rise_max = 124 * 0.01
            energy_flat_min = 3 * 0.01
            energy_flat_max = 125 * 0.01

        specs = {
            # Core Trigger Parameters
            "TRIGGER_THRESHOLD": ParameterSpec(
                name="TRIGGER_THRESHOLD",
                data_type=int,
                min_value=1,
                max_value=65535,
                unit="ADC units",
                description="Threshold for event detection",
                dsp_variable="FASTTHRESH",
            ),
            "TRIGGER_RISETIME": ParameterSpec(
                name="TRIGGER_RISETIME",
                data_type=float,
                min_value=0.02,  # 2 * 10ns for 100MHz
                max_value=trigger_rise_max,
                unit="μs",
                description="Fast filter rise time",
                dsp_variable="FASTLENGTH",
            ),
            "TRIGGER_FLATTOP": ParameterSpec(
                name="TRIGGER_FLATTOP",
                data_type=float,
                min_value=0.0,
                max_value=trigger_flat_max,
                unit="μs",
                description="Fast filter flat top time",
                dsp_variable="FASTGAP",
            ),
            # Energy Filter Parameters
            "ENERGY_RISETIME": ParameterSpec(
                name="ENERGY_RISETIME",
                data_type=float,
                min_value=energy_rise_min,
                max_value=energy_rise_max,
                unit="μs",
                description="Energy filter rise time",
                dsp_variable="SLOWLENGTH",
            ),
            "ENERGY_FLATTOP": ParameterSpec(
                name="ENERGY_FLATTOP",
                data_type=float,
                min_value=energy_flat_min,
                max_value=energy_flat_max,
                unit="μs",
                description="Energy filter flat top time",
                dsp_variable="SLOWGAP",
            ),
            # Trace Parameters
            "TRACE_LENGTH": ParameterSpec(
                name="TRACE_LENGTH",
                data_type=float,
                min_value=0.0,
                max_value=163.8,  # μs, depends on module revision
                unit="μs",
                description="Waveform acquisition length",
                dsp_variable="TRACELENGTH",
            ),
            "TRACE_DELAY": ParameterSpec(
                name="TRACE_DELAY",
                data_type=float,
                min_value=0.0,
                max_value=10.24,  # μs, module dependent
                unit="μs",
                description="Pre-trigger waveform length",
                dsp_variable="TRIGGERDELAY",
            ),
            # Baseline and Offset
            "VOFFSET": ParameterSpec(
                name="VOFFSET",
                data_type=float,
                min_value=-1.5,
                max_value=1.5,
                unit="V",
                description="DC offset voltage",
                dsp_variable="OFFSETDAC",
            ),
            "BASELINE_PERCENT": ParameterSpec(
                name="BASELINE_PERCENT",
                data_type=float,
                min_value=0.0,
                max_value=100.0,
                unit="%",
                description="Baseline averaging percentage",
                dsp_variable="BASELINEPERCENT",
            ),
            "BASELINE_AVERAGE": ParameterSpec(
                name="BASELINE_AVERAGE",
                data_type=int,
                min_value=0,
                max_value=16,  # 2^16 samples max
                unit="power of 2",
                description="Baseline averaging length (log2)",
                dsp_variable="LOG2BWEIGHT",
            ),
            "BLCUT": ParameterSpec(
                name="BLCUT",
                data_type=int,
                min_value=0,
                max_value=65535,  # 16-bit max
                unit="ADC units",
                description="Baseline cut threshold for clipping detection",
                dsp_variable="BLCUT",
            ),
            # Digital filter tap values for energy filter debugging
            "ENERGY_L": ParameterSpec(
                name="ENERGY_L",
                data_type=int,
                min_value=2,
                max_value=127,
                unit="taps",
                description="Energy filter rise time in filter taps (L)",
                dsp_variable="SLOWLENGTH",
            ),
            "ENERGY_G": ParameterSpec(
                name="ENERGY_G",
                data_type=int,
                min_value=3,
                max_value=127,
                unit="taps",
                description="Energy filter gap time in filter taps (G)",
                dsp_variable="SLOWGAP",
            ),
            # Energy Discrimination
            "EMIN": ParameterSpec(
                name="EMIN",
                data_type=int,
                min_value=0,
                max_value=65535,
                unit="energy units",
                description="Minimum energy for list mode",
                dsp_variable="ENERGYLOW",
            ),
            # Timing Parameters
            "TAU": ParameterSpec(
                name="TAU",
                data_type=float,
                min_value=0.0,
                max_value=1000.0,  # μs, reasonable range
                unit="μs",
                description="Preamplifier decay time constant",
                dsp_variable="PREAMPTAU",
            ),
            "XDT": ParameterSpec(
                name="XDT",
                data_type=float,
                min_value=0.0,
                max_value=10.0,  # μs
                unit="μs",
                description="External deadtime",
                dsp_variable="XWAIT",
            ),
            # CFD Parameters
            "CFDDelay": ParameterSpec(
                name="CFDDelay",
                data_type=float,
                min_value=0.0,
                max_value=0.63,  # μs (63 FPGA ticks × 10ns)
                unit="μs",
                description="CFD delay time",
                dsp_variable="CFDDELAY",
            ),
            "CFDScale": ParameterSpec(
                name="CFDScale",
                data_type=float,
                min_value=0.0,
                max_value=8.0,
                unit="scale factor",
                description="CFD scale factor",
                dsp_variable="CFDSCALE",
            ),
            "CFDThresh": ParameterSpec(
                name="CFDThresh",
                data_type=int,
                min_value=0,
                max_value=65535,
                unit="ADC units",
                description="CFD threshold",
                dsp_variable="CFDTHRESH",
            ),
            # QDC Parameters
            **{
                f"QDCLen{i}": ParameterSpec(
                    name=f"QDCLen{i}",
                    data_type=float,
                    min_value=0.0,
                    max_value=100.0,
                    unit="μs",
                    description=f"QDC integration length {i}",
                    dsp_variable=f"QDCLEN{i}",
                )
                for i in range(8)
            },
            # Coincidence and Trigger Extensions
            "FASTTRIGBACKLEN": ParameterSpec(
                name="FASTTRIGBACKLEN",
                data_type=float,
                min_value=0.0,
                max_value=10.0,
                unit="μs",
                description="Fast trigger backplane length",
                dsp_variable="FASTTRIGBACKLEN",
            ),
            "ExtTrigStretch": ParameterSpec(
                name="ExtTrigStretch",
                data_type=float,
                min_value=0.0,
                max_value=100.0,
                unit="μs",
                description="External trigger stretch",
                dsp_variable="EXTTRIGSTRETCH",
            ),
            "VetoStretch": ParameterSpec(
                name="VetoStretch",
                data_type=float,
                min_value=0.0,
                max_value=100.0,
                unit="μs",
                description="Veto signal stretch",
                dsp_variable="VETOSTRETCH",
            ),
            "ChanTrigStretch": ParameterSpec(
                name="ChanTrigStretch",
                data_type=float,
                min_value=0.0,
                max_value=100.0,
                unit="μs",
                description="Channel trigger stretch",
                dsp_variable="CHANTRIGSTRETCH",
            ),
            # UI-specific parameters
            "Gain": ParameterSpec(
                name="Gain",
                data_type=float,
                min_value=0.625,
                max_value=2.5,
                unit="V/V",
                description="Analog input gain",
                dsp_variable="CHANNEL_CSRA",
            ),
            "Polarity": ParameterSpec(
                name="Polarity",
                data_type=str,
                min_value=0,  # Not used for strings
                max_value=1,  # Not used for strings
                unit="polarity",
                description="Signal polarity (negative/positive)",
                dsp_variable="CHANNEL_CSRA",
            ),
            "GoodChannel": ParameterSpec(
                name="GoodChannel",
                data_type=bool,
                min_value=0,
                max_value=1,
                unit="boolean",
                description="Enable channel for data collection",
                dsp_variable="CHANNEL_CSRA",
            ),
            "CaptureTrace": ParameterSpec(
                name="CaptureTrace",
                data_type=bool,
                min_value=0,
                max_value=1,
                unit="boolean",
                description="Enable trace capture for this channel",
                dsp_variable="CHANNEL_CSRA",
            ),
            # Module-level Parameters
            "SYNCH_WAIT": ParameterSpec(
                name="SYNCH_WAIT",
                data_type=int,
                min_value=0,
                max_value=1,
                unit="boolean",
                description="Synchronization wait enable",
                module_level=True,
            ),
            "IN_SYNCH": ParameterSpec(
                name="IN_SYNCH",
                data_type=int,
                min_value=0,
                max_value=1,
                unit="boolean",
                description="Module synchronization enable",
                module_level=True,
            ),
        }

        return specs

    def validate_parameter(
        self, name: str, value: any, module: int = 0, channel: int = 0
    ) -> tuple[bool, any, str]:
        """
        Validate a parameter value against specifications.

        Args:
            name: Parameter name
            value: Parameter value to validate
            module: Module number (for error messages)
            channel: Channel number (for error messages)

        Returns:
            Tuple of (is_valid, corrected_value, error_message)
        """
        if name not in self.parameters:
            return False, value, f"Unknown parameter: {name}"

        spec = self.parameters[name]

        # Type conversion
        try:
            if spec.data_type == int:
                corrected_value = int(float(value))  # Handle string numbers
            elif spec.data_type == float:
                corrected_value = float(value)
            else:
                corrected_value = value
        except (ValueError, TypeError):
            return (
                False,
                value,
                f"Invalid type for {name}: expected {spec.data_type.__name__}",
            )

        # Range validation
        if isinstance(corrected_value, int | float):
            if corrected_value < spec.min_value:
                return (
                    False,
                    spec.min_value,
                    f"{name} too low: {corrected_value} < {spec.min_value}",
                )
            if corrected_value > spec.max_value:
                return (
                    False,
                    spec.max_value,
                    f"{name} too high: {corrected_value} > {spec.max_value}",
                )

        # Additional validation rules
        validation_result = self._validate_parameter_constraints(
            name, corrected_value, module, channel
        )
        if not validation_result[0]:
            return validation_result

        return True, corrected_value, ""

    def _validate_parameter_constraints(
        self, name: str, value: any, module: int, channel: int
    ) -> tuple[bool, any, str]:
        # Energy filter constraints: rise time + flat top affects performance
        if name == "ENERGY_RISETIME":
            # Warning for very short rise times (poor resolution)
            if value < 0.5:
                logger.warning(
                    f"M{module}:Ch{channel} - Short energy rise time ({value} μs) may reduce resolution"
                )

        elif name == "ENERGY_FLATTOP":
            # Warning for very short flat tops (poor resolution)
            if value < 0.1:
                logger.warning(
                    f"M{module}:Ch{channel} - Short energy flat top ({value} μs) may reduce resolution"
                )

        # Trigger filter constraints
        elif name == "TRIGGER_THRESHOLD":
            if value < 50:
                logger.warning(
                    f"M{module}:Ch{channel} - Low trigger threshold ({value}) may cause noise triggers"
                )
            elif value > 32000:
                logger.warning(
                    f"M{module}:Ch{channel} - High trigger threshold ({value}) may miss low-energy events"
                )

        # Trace length constraints
        elif name == "TRACE_LENGTH":
            if value > 80.0:
                logger.warning(
                    f"M{module}:Ch{channel} - Long traces ({value} μs) increase data volume significantly"
                )

        # Reject filter times that would exceed half the trace length.
        # The fast filter needs 2*L + G FPGA ticks; FPGA trace is ~trace_μs/0.01/5.
        # As a safe limit, reject rise/flat times > trace_length/2.
        elif name in ("TRIGGER_RISETIME", "TRIGGER_FLATTOP"):
            if value > 0.5:
                logger.warning(
                    f"M{module}:Ch{channel} - Large trigger {name}={value} μs may not fit "
                    f"within short traces. If plotting fails, reduce this value."
                )

        return True, value, ""

    def get_parameter_info(self, name: str) -> ParameterSpec | None:
        return self.parameters.get(name)

    def get_all_parameters(self) -> dict[str, ParameterSpec]:
        return self.parameters.copy()

    def get_channel_parameters(self) -> dict[str, ParameterSpec]:
        return {
            name: spec
            for name, spec in self.parameters.items()
            if not spec.module_level
        }

    def get_module_parameters(self) -> dict[str, ParameterSpec]:
        return {
            name: spec for name, spec in self.parameters.items() if spec.module_level
        }

    def validate_parameter_set(
        self, params: dict[str, any], module: int = 0, channel: int = 0
    ) -> dict[str, any]:
        """
        Validate a complete set of parameters.

        Args:
            params: Dictionary of parameter name -> value
            module: Module number
            channel: Channel number

        Returns:
            Dictionary of validated parameters with corrections applied
        """
        validated = {}
        errors = []

        for name, value in params.items():
            is_valid, corrected_value, error_msg = self.validate_parameter(
                name, value, module, channel
            )

            if is_valid:
                validated[name] = corrected_value
            else:
                errors.append(f"M{module}:Ch{channel} - {error_msg}")
                validated[name] = corrected_value  # Use corrected value even if invalid

        if errors:
            logger.warning("Parameter validation issues:\n" + "\n".join(errors))

        return validated


class ParameterChangeManager:
    def __init__(self, validator: PixieParameterValidator, update_callback=None):
        """
        Initialize parameter change manager.

        Args:
            validator: Parameter validator instance
            update_callback: Function to call for hardware updates
        """
        self.validator = validator
        self.update_callback = update_callback
        self.pending_changes = {}
        self.debounce_timer = None
        self.debounce_delay = 0.5  # seconds
        self.lock = threading.Lock()

    def queue_parameter_change(self, name: str, value: any, module: int, channel: int):
        with self.lock:
            # Validate the parameter
            is_valid, corrected_value, error_msg = self.validator.validate_parameter(
                name, value, module, channel
            )

            if not is_valid:
                logger.error(f"Parameter validation failed: {error_msg}")
                return False

            # Queue the change
            key = (module, channel, name)
            self.pending_changes[key] = corrected_value

            # Reset debounce timer
            if self.debounce_timer:
                self.debounce_timer.cancel()

            self.debounce_timer = threading.Timer(
                self.debounce_delay, self._process_pending_changes
            )
            self.debounce_timer.start()

            return True

    def _process_pending_changes(self):
        with self.lock:
            if not self.pending_changes:
                return

            changes_by_target = {}
            for (module, channel, name), value in self.pending_changes.items():
                target = (module, channel)
                if target not in changes_by_target:
                    changes_by_target[target] = {}
                changes_by_target[target][name] = value

            # Clear pending changes
            self.pending_changes.clear()

        # Apply changes
        if self.update_callback:
            for (module, channel), params in changes_by_target.items():
                try:
                    self.update_callback(params, module, channel)
                except Exception as e:
                    logger.error(
                        f"Failed to apply parameters to M{module}:Ch{channel}: {e}"
                    )

    def immediate_update(self, name: str, value: any, module: int, channel: int):
        is_valid, corrected_value, error_msg = self.validator.validate_parameter(
            name, value, module, channel
        )

        if not is_valid:
            logger.error(f"Parameter validation failed: {error_msg}")
            return False

        if self.update_callback:
            try:
                self.update_callback({name: corrected_value}, module, channel)
                return True
            except Exception as e:
                logger.error(
                    f"Failed to apply parameter {name} to M{module}:Ch{channel}: {e}"
                )
                return False

        return True
