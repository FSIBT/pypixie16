"""The main implementation of the Settings class."""

from collections import UserDict, UserList
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
                print("[INFO]: Converting settings file from .set to .json")
                file = convert_old_settings(file, [0])
            else:
                print("[ERROR]: Unkonwn file type for setting file (shoudl be .json)")
            return

        with file.open("r") as fp:
            data = json.load(fp)
        setting = cls()
        setting.data = data[module]
        setting.create_index()
        return setting

    @classmethod
    def from_dict(cls, data: Dict):
        """Creates a Settings object from a file."""
        setting = cls()
        setting.data = data
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


class CrateSettings(UserList):
    def __init__(self, input=None):
        if input is None:
            self.data = []
        else:
            self.data = list(input)
            for x in self.data:
                assert isinstance(
                    x, Settings
                ), "Can only put Seetings in CrateSettings."
