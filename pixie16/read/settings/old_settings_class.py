import numpy as np
import struct
import json
from pathlib import Path
from typing import Union, List, Optional

from .units import SETTINGS_UNITS_TBL
from .file_format import SETTINGS_FILE_FORMAT
from .field_classes import (
    Entity,
    ABField,
    BinaryField,
    OffsetVoltageField,
    TraceDelayField,
)


def combine_hi_lo_registers(hi, lo):
    """Creates a whole parameter that was split into two 32-bit parameters A and B."""
    return (np.array(hi) * 2 ** 32 + np.array(lo)).astype(float)


def _create_settings_ureg(fast_filter_range, slow_filter_range):
    """Creates a pint unit registry with pixie units specific to the settings of this run."""
    import pint

    ureg = pint.UnitRegistry()
    ureg.define("ADC_cycles = 2*ns")
    ureg.define("FPGA_cycles = 5*ADC_cycles")
    ureg.define(f"fast_filter_cycles = FPGA_cycles*2**{fast_filter_range}")
    ureg.define(f"slow_filter_cycles = FPGA_cycles*2**{slow_filter_range}")
    return ureg


class NumpyEncoder(json.JSONEncoder):
    """Special json encoder for numpy types."""

    def default(self, obj):
        if isinstance(
            obj,
            (
                np.int_,
                np.intc,
                np.intp,
                np.int8,
                np.int16,
                np.int32,
                np.int64,
                np.uint8,
                np.uint16,
                np.uint32,
                np.uint64,
            ),
        ):
            return int(obj)
        elif isinstance(obj, (np.float_, np.float16, np.float32, np.float64)):
            return float(obj)
        elif isinstance(obj, (np.ndarray,)):
            return obj.tolist()
        return json.JSONEncoder.default(self, obj)


class OldSettings(Entity):
    """Class that holds settings data from the pixie16. All settings values can be accessed as attributes or through
    the get method."""

    # Derived fields. Look at field_classes.py for implementations/field logic
    LiveTime = ABField()
    FastPeaks = ABField()
    RealTime = ABField()
    RunTime = ABField()
    MultiplicityMaskL = BinaryField()
    MultiplicityMaskH = BinaryField()
    FastTrigBackplaneEna = BinaryField()
    TrigConfig = BinaryField()
    ChanCSRa = BinaryField()
    ChanCSRb = BinaryField()
    ModCSRA = BinaryField()
    ModCSRB = BinaryField()
    OffsetVoltage = OffsetVoltageField()
    TraceDelay = TraceDelayField()

    def __init__(self, **kwargs):
        # set all key value pairs as attributes
        self.__dict__.update(kwargs)
        # create a unit registry with pixie units specific to the settings of this run
        self.ureg = _create_settings_ureg(self.FastFilterRange, self.SlowFilterRange)

    def __getitem__(self, item):
        return self.get(item)

    def get(self, key, channel=None, as_pint=False):
        """A utility function to get a channel's settings value or get a settings value with units."""
        value = getattr(self, key)
        if channel is not None:
            value = value[channel]
        if as_pint:
            units = getattr(self.ureg, SETTINGS_UNITS_TBL[key])
            value = value * units
        return value

    @classmethod
    def _from_file(cls, file: str, module: int = 0):
        """Create a settings dictioanry from .set file for a given module."""
        # get bytes from file
        with open(file, "rb") as fp:
            binary_data = fp.read()
        MODULE_SIZE = 4 * 1280
        binary_data = binary_data[module * MODULE_SIZE : (module + 1) * MODULE_SIZE]

        # unpack field values from bytes
        settings_dict = {}
        for field, (offset, fmt) in SETTINGS_FILE_FORMAT.items():
            settings_dict[field] = struct.unpack_from(fmt, binary_data, offset)

        # unpack singletons
        for key, value in settings_dict.items():
            if len(value) == 1:
                settings_dict[key] = value[0]
            else:
                settings_dict[key] = value

        return settings_dict


def convert_old_settings(
    settings_filename: Union[str, Path],
    modules: List = [0],
    metadata_filename: Optional[Union[str, Path]] = None,
):
    """Convert an old .set file to a .json file.

    .set files do not include the metadata (mostly hardware) information included
    in the .json settings file. If one provides a path (via the optional
    metadata_filename argument) to a new .json settings file that already has
    metadata, the metadata will be added to the .json converted from the .set file."""

    channel_input_params = [
        "BLcut",
        "BaselinePercent",
        "CFDDelay",
        "CFDScale",
        "CFDThresh",
        "ChanCSRa",
        "ChanCSRb",
        "ChanTrigStretch",
        "DigGain",
        "EnergyLow",
        "ExtTrigStretch",
        "ExternDelayLen",
        "FastGap",
        "FastLength",
        "FastThresh",
        "FastTrigBackLen",
        "FtrigoutDelay",
        "GainDAC",
        "Integrator",
        "Log2Bweight",
        "Log2Ebin",
        "MultiplicityMaskH",
        "MultiplicityMaskL",
        "OffsetDAC",
        "PAFlength",
        "PSAlength",
        "PSAoffset",
        "PeakSample",
        "PeakSep",
        "PreampTau",
        "QDCLen0",
        "QDCLen1",
        "QDCLen2",
        "QDCLen3",
        "QDCLen4",
        "QDCLen5",
        "QDCLen6",
        "QDCLen7",
        "ResetDelay",
        "SlowGap",
        "SlowLength",
        "ThreshWidth",
        "TraceLength",
        "TrigOutLen",
        "TriggerDelay",
        "VetoStretch",
        "Xavg",
        "Xwait",
    ]

    module_input_params = [
        "ChanNum",
        "CoincPattern",
        "CoincWait",
        "ControlTask",
        "CrateID",
        "FIFOLength",
        "FastFilterRange",
        "FastTrigBackplaneEna",
        "HostIO",
        "HostRunTimePreset",
        "InSynch",
        "MaxEvents",
        "ModCSRA",
        "ModCSRB",
        "ModFormat",
        "ModID",
        "ModNum",
        "Resume",
        "RunTask",
        "SlotID",
        "SlowFilterRange",
        "SynchWait",
        "TrigConfig",
        "U00",
        "UserIn",
    ]

    stats_params = [
        "RealTimeA",
        "RealTimeB",
        "LiveTimeA",
        "LiveTimeB",
        "FastPeaksA",
        "FastPeaksB",
        "ChanEventsA",
        "ChanEventsB",
    ]

    settings_filename = str(settings_filename)
    # Make sure filename extension is .set
    if not settings_filename.endswith(".set"):
        if settings_filename.endswith(".json"):
            print("[INFO] Settings file is already a json.")
        else:
            print("[ERROR] Settings file is neither a .set nor a .json.")
        print("Not converting settings.")
        return

    new_settings_lst = []
    new_stats_lst = []
    new_settings_filename = settings_filename[:-3] + "json"
    new_stats_filename = new_settings_filename.replace("settings", "stats")

    for module in modules:
        # Load settings and prepare to rewrite settings and stats to dictionaries
        old_settings_dict = OldSettings._from_file(settings_filename, module)
        new_settings_dict = {
            "channel": {"input": {}},
            "metadata": "None",
            "module": {"input": {}},
        }
        new_stats_dict = {"module": module}
        if metadata_filename:
            if not metadata_filename.endswith(".json"):
                print("[ERROR] Settings file with metadata must be a .json file.")
                print("Not writing metadata to settings file.")
            else:
                with open(metadata_filename) as file:
                    metadata = json.load(file)[0]["metadata"]
                new_settings_dict["metadata"] = metadata

        # Organize settings from old file into dictionaries in the new settings/stats format
        for key, value in sorted(old_settings_dict.items()):
            # Channel Parameters
            if key in channel_input_params:
                new_settings_dict["channel"]["input"][key] = value
            # Module Parameters
            elif key in module_input_params:
                new_settings_dict["module"]["input"][key] = value
            # Stats Parameters
            elif key in stats_params:
                # If a parameter has only one value, apply it to all 16 channels
                if isinstance(value, (int, float)):
                    value = [value] * 16
                if key.endswith("A"):
                    A_value = value
                elif key.endswith("B"):
                    combined_key = key[:-1]
                    # Combine A and B 32-bit parameters
                    combined_val = combine_hi_lo_registers(A_value, value)
                    if combined_key in ["RealTime", "LiveTime"]:
                        # Convert from clock cycles to ns (multiply by 10)
                        # Convert from ns to s (divide by 1e9)
                        combined_val = combined_val / 1e8
                        if combined_key == "RealTime":
                            combined_key = "real_time"
                        elif combined_key == "LiveTime":
                            combined_key = "live_time"
                    elif combined_key == "FastPeaks":
                        combined_key = "input_counts"
                    elif combined_key == "ChanEvents":
                        combined_key = "output_counts"
                    new_stats_dict[combined_key] = combined_val
        # Add module settings dictionary to a list of settings dictionaries
        new_settings_lst.append(new_settings_dict)

        # Add input and output count rate to stats dictionary
        new_stats_dict["input_count_rate"] = (
            new_stats_dict["input_counts"] / new_stats_dict["live_time"]
        )
        new_stats_dict["output_count_rate"] = (
            new_stats_dict["output_counts"] / new_stats_dict["real_time"]
        )
        # Assumes dictionaries are ordered, which is only for python >= 3.6
        key_order = [
            "module",
            "real_time",
            "live_time",
            "input_counts",
            "input_count_rate",
            "output_counts",
            "output_count_rate",
        ]
        new_stats_dict_ordered = {}
        # Convert values in stats dictionary from numpy arrays to lists
        for key in key_order:
            if key != "module":
                new_stats_dict[key] = new_stats_dict[key].tolist()
            new_stats_dict_ordered[key] = new_stats_dict[key]
        # Add module stats dictionary to a list of stats dictionaries
        new_stats_lst.append(new_stats_dict_ordered)

    # Write new settings .json file
    new_settings_json = json.dumps(
        new_settings_lst,
        indent=4,
        separators=(",", ": "),
        sort_keys=True,
        cls=NumpyEncoder,
    )
    with open(new_settings_filename, "a") as f:
        f.write(new_settings_json + "\n")

    # Write new stats .json file
    new_stats_json = json.dumps(new_stats_lst)
    with open(new_stats_filename, "a") as f:
        f.write(new_stats_json + "\n")

    return new_settings_filename, new_stats_filename
