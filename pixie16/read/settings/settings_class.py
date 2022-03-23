"""The main implementation of the Settings class."""

from collections import UserDict
import json
from pathlib import Path
import struct
from typing import List, Dict, Union

from .units import SETTINGS_UNITS_TBL
from .file_format import SETTINGS_FILE_FORMAT
from .field_classes import (
    Entity,
    ABField,
    BinaryField,
    OffsetVoltageField,
    TraceDelayField,
)


class SettingsBase(UserDict):
    """A 1:1 mapping of the settings file to a dictionary.

    We also provide some helper methods to more easily access the values.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.index = {}
        self.duplicate_keys = []

    def create_index(self, d: Dict = None, level: List = None):
        """Create an index.

        We use the index later to be able to look up

        self["channel"]["input"]["VetoStretch"]
        by just using
        self.get_by_name("VetoStretch")

        At the same time, we keep track of duplicate keys, so that we
        can raise a KeyError for those.
        """

        if d is None:
            d = self
        if level is None:
            level = []

        keys = {}

        for k, v in d.items():
            if isinstance(v, dict):
                new_level = level.copy()
                new_level.append(k)
                new_keys = self.create_index(v, new_level)
                for nk, nv in new_keys.items():
                    if nk in self:
                        self.duplicate_keys.append(nk)
                    keys[nk] = nv
            else:
                keys[k] = level.copy()

        if d == self:
            self.index = keys

        return keys

    @classmethod
    def from_file(cls, file: Union[Path, str], module: int = 0):
        """Creates a Settings object from a file."""

        if isinstance(file, str):
            file = Path(file)

        if file.suffix != ".json":
            if file.suffix == ".set":
                print(
                    "[Error]: please use pixie16-set2json to convert to the new type settings file"
                )
            else:
                print("[Error]: Unkonwn file type for setting file (shoudl be .json)")
            return

        with file.open("r") as fp:
            data = json.load(fp)
        setting = cls()
        setting.data = data[module]
        setting.create_index()
        return setting

    @classmethod
    def from_dict(cls, data: dict, module: int = 0):
        """Creates a Settings object from a file."""
        setting = cls()
        setting.data = data[module]
        setting.create_index()
        return setting

    def get_by_name(self, name: str):
        """Alternative way to access keys in the dictionary.

        The advantage of using `get` is that it will look at all
        levels inside the setting dict and return the value. This only
        works if the key is unique. Otherwise, we raise an exception.
        """
        if name in self.duplicate_keys:
            raise KeyError

        level = self.index[name]
        d = self
        for l in level:
            d = d[l]
        return d[name]

    def set_by_name(self, name: str, value) -> None:
        """Alternative way to access keys in the dictionary.

        The advantage of using `set` is that it will look at all
        levels inside the setting dict and set the correct value. This only
        works if the key is unique. Otherwise, we raise an exception.
        """
        if name in self.duplicate_keys:
            raise KeyError

        level = self.index[name]
        d = self
        for l in level:
            d = d[l]
        d[name] = value


class Settings(SettingsBase):
    pass


class Stats(SettingsBase):
    pass


# TODO: old setting code: remove for next release and move to convertion tool

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


class SettingsOld(Entity):
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
    def from_file(cls, file: Path, module=0):
        """An alternate initializer. Takes the name as a settings file and returns a Settings object."""
        if file.suffix == ".json":
            with file.open("r") as fp:
                data = json.load(fp)
                data = data[module]
                data = {
                    **data["channel"]["input"],
                    **data["metadata"],
                    **data["module"]["input"],
                }
            return cls(**data)

        # handle old style setting file

        # get bytes from file
        with file.open("rb") as fp:
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


def load_stats(file, module=0):
    """Takes the name of a settings file and the index of the module of interest. Returns a Settings object."""
    return Stats.from_file(file, module)
