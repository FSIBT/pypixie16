"""The main implementation of the Settings class."""

import struct

from .units import SETTINGS_UNITS_TBL
from .file_format import SETTINGS_FILE_FORMAT
from .field_classes import (
    Entity,
    ABField,
    BinaryField,
    OffsetVoltageField,
    TraceDelayField,
)

MODULE_SIZE = 4 * 1280


def create_settings_ureg(fast_filter_range, slow_filter_range):
    """Creates a pint unit registry with pixie units specific to the settings of this run"""
    import pint

    ureg = pint.UnitRegistry()
    ureg.define("ADC_cycles = 2*ns")
    ureg.define("FPGA_cycles = 5*ADC_cycles")
    ureg.define(f"fast_filter_cycles = FPGA_cycles*2**{fast_filter_range}")
    ureg.define(f"slow_filter_cycles = FPGA_cycles*2**{slow_filter_range}")
    return ureg


class Settings(Entity):
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
        self.ureg = create_settings_ureg(self.FastFilterRange, self.SlowFilterRange)

    def __getitem__(self, item):
        return self.get(item)

    def get(self, key, channel=None, as_pint=False):
        """A utility function to get a channel's settings value or get a settings value with units"""
        value = getattr(self, key)
        if channel is not None:
            value = value[channel]
        if as_pint:
            units = getattr(self.ureg, SETTINGS_UNITS_TBL[key])
            value = value * units
        return value

    @classmethod
    def from_file(cls, file, module=0):
        """An alternate initializer. Takes the name as a settings file and returns a Settings object."""
        # get bytes from file
        with open(file, "rb") as fp:
            binary_data = fp.read()
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

        return cls(**settings_dict)


def load_settings(file, module=0):
    """Takes the name of a settings file and the index of the module of interest. Returns a Settings object."""
    return Settings.from_file(file, module)
