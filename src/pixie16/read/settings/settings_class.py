"""The main implementation of the Settings class."""

from collections import UserDict, UserList
import copy
import json
from pathlib import Path
import struct
from typing import Union

import pandas as pd

from .units import SETTINGS_UNITS_TBL
from .file_format import SETTINGS_FILE_FORMAT
from .field_classes import (
    Entity,
    ABField,
    BinaryField,
    OffsetVoltageField,
    TraceDelayField,
)
from .old_settings_class import convert_old_settings


def load_settings(file, module=0):
    """Takes the name of a settings file and the index of the module of interest. Returns a Settings object."""
    return Settings.from_file(file, module)


def load_stats(file, module=0):
    """Takes the name of a settings file and the index of the module of interest. Returns a Settings object."""
    return Stats.from_file(file, module)


class SettingsBase(UserDict):
    """A 1:1 mapping of the settings file to a dictionary.

    We also provide some helper methods to more easily access the values.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.data_raw = {}
        self.index = {}
        self.index_raw = {}
        self.duplicate_keys = []

    def create_index(self, d: dict = None, level: list = None):
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

    def transform(self, data):
        """Function that can be used to transform data.

        Used for Settings where the data stores is not in the same
        format as the data in the settings files, e.g. settings names
        are different and values are different.  For examples, we have
        names and values for certain bits.
        """
        return data

    @classmethod
    def from_file(cls, file: Path | str, module: int = 0):
        """Creates a Settings object from a file."""

        if isinstance(file, str):
            file = Path(file)

        if file.suffix != ".json":
            if file.suffix == ".set":
                print("[INFO]: Converting settings file from .set to .json")
                file = convert_old_settings(file, [0])
            else:
                print("[ERROR]: Unkonwn file type for setting file (should be .json)")
            return

        with file.open("r") as fp:
            data = json.load(fp)
        setting = cls()
        setting.data_raw = copy.deepcopy(data[module])
        setting.data = setting.transform(data[module])
        setting.create_index()
        setting.filename = file
        return setting

    @classmethod
    def from_dict(cls, data: dict):
        """Creates a Settings object from a file."""
        setting = cls()
        setting.data_raw = copy.deepcopy(data)
        setting.data = setting.transform(data)
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
    """Data from a settings json file.

    We also convert certain values from u32 into readable values, e.g.
    OffsetDAC into Volts.

    """

    def apply_func(self, data, name, func):
        """Apply a function to a certain value. Leaves the name untouched."""
        keys = name.split("/")
        name = keys[-1]
        keys = keys[:-1]
        tmp = data
        for k in keys:
            tmp = tmp[k]

        if isinstance(tmp[name], list):
            tmp[name] = [func(x) for x in tmp[name]]
        else:
            tmp[name] = func(tmp[name])
        return data

    def transform_offset(self, value):
        """See Prog Manual Version 3.07, page 97."""
        return 1.5 * ((int(value) - 32768) / 32768)

    def transform(self, data):
        data = self.apply_func(data, "channel/input/OffsetDAC", self.transform_offset)
        return data


class Stats(SettingsBase):
    def to_pandas(self):
        df = pd.DataFrame(self.data)
        df["channel"] = list(range(16))
        return df


class CrateSettings(UserList):
    def __init__(self, input=None):
        if input is None:
            self.data = []
        else:
            self.data = list(input)
            for x in self.data:
                assert isinstance(x, Settings), (
                    "Can only put Seetings in CrateSettings."
                )
