from collections import UserDict
from functools import singledispatchmethod
from inspect import signature
from itertools import starmap
from more_itertools import pairwise
import numpy as np
import struct

from .settings_format import settings_fmt
from .decode_settings import decode
from .conversions import conversions
from .units import SETTINGS_UNITS_TBL

from ..constants import *
from ..utilities import find_path


class SettingsConverter:

    def __init__(self, settings):
        self._settings = settings

    def convert(self, value, units_from, units_to):
        try:
            value = np.array(list(value))
        except TypeError:
            value = np.array([value])
        units_path = find_path(conversions, units_from, units_to)
        if units_path is None:
            raise ValueError('no conversion path from {} to {}'.format(units_from, units_to))
        conversion_path = (conversions[u_from][u_to] for u_from, u_to in pairwise(units_path))
        for conversion in conversion_path:
            _, *parameters = signature(conversion).parameters
            value = conversion(value, *(self._settings[item] for item in parameters))
        return value if len(value) > 1 else value[0]

    def __call__(self, *args, **kwargs):
        return self.convert(*args)


class Settings(UserDict):

    def __init__(self, raw_settings):
        super().__init__(decode(raw_settings))
        self.settings_converter = SettingsConverter(self)

    @classmethod
    def from_bytes(cls, octets):
        raw_settings = {key: np.array(struct.unpack_from(fmt, octets, index))
                        for key, (index, fmt), in settings_fmt.items()}
        return cls(raw_settings)

    @classmethod
    def from_file(cls, file, module=0):
        with open(file, 'rb') as fp:
            octets = memoryview(fp.read())
        assert len(octets) == SETTINGS_FILE_LENGTH, 'got unexpected settings file size'
        octets = octets[module * MODULE_LENGTH: module * MODULE_LENGTH + MODULE_LENGTH]
        return cls.from_bytes(octets)

    # handle request with units
    @singledispatchmethod
    def __getitem__(self, item):
        item, units_to = item
        if not units_to:
            return self[item]
        units_from = SETTINGS_UNITS_TBL[item]
        raw_setting = self.data[item]
        return self.settings_converter(raw_setting, units_from, units_to)

    # handle request without units
    @__getitem__.register(str)
    def _(self, item):
        setting = self.data[item]
        return setting if len(setting) > 1 else setting[0]

    def __setitem__(self, key, value):
        try:
            value = list(value)
        except TypeError:
            value = [value]
        return super().__setitem__(key, value)


class ChannelSettings:

    def __init__(self, channel, settings):
        self._channel = channel
        self._settings = settings

    def __getitem__(self, item):
        setting = self._settings[item]
        try:
            if len(setting) == CHANNELS_PER_MODULE:
                return setting[self._channel]
        except TypeError:
            pass
        return setting

    def __setitem__(self, key, value):
        setting = self._settings[key]
        try:
            if len(setting) == CHANNELS_PER_MODULE:
                setting[self._channel] = value
        except TypeError:
            self._settings[key] = np.array([value])

    def __contains__(self, item):
        return item in self._settings
