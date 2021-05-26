"""Interface to C-libary function provided by XIA in sys DLL.

Currently calling the XIA C-library functions is only supported on Windows.

This file provides python function that directly call functions in the
sys.dll libarary using ctypes.

List of C-functions and their python equivalent:

* Pixie_DSP_Memory_IO       -> read_raw_settings
                            -> write_raw_settings
* Pixie_Read_ExtFIFIOStatus -> ReadFIFOStatus
* Pixie_ExtFIFO_Read        -> ReadFIFO

List of helper functions:

* change_setting_in_memory
* change_setting
* change_register_bit
* change_CSRA_bit
* change_CSRB_bit
* change_CSRA
* change_CSRB
* get_setting_value
* change_setting_dict

"""

__all__ = [
    "read_raw_settings",
    "write_raw_settings",
    "ReadFIFOStatus",
    "ReadFIFO",
    "change_setting_in_memory",
    "change_setting",
    "change_register_bit",
    "change_CSRA_bit",
    "change_CSRB_bit",
    "change_CSRA",
    "change_CSRB",
    "get_setting_value",
    "change_setting_dict",
]

import ctypes
import logging
from pathlib import Path
import sys
from unittest.mock import MagicMock

import numpy as np

from .config import lib_sys
from .C_library_app import ProgramFippi, ProgramSetDACs, converter_IEEE754_to_ulong
from . import variables

# set up logging
log = logging.getLogger(__name__)

if sys.platform == "win32" and sys.maxsize < 2 ** 32:
    if not lib_sys:
        print("[ERROR] no path for lib_app set.")
        sys.exit()

    # make sure pxisys.ini is available
    current_dir = Path(".")
    initfile = current_dir / "pxisys.ini"
    if not initfile.exists():
        log.error(
            f"Error: please copy the pxisys.ini file into the directory: {current_dir}"
        )

    PixieSysDLL = ctypes.cdll.LoadLibrary(str(lib_sys))
    PROTO = ctypes.CFUNCTYPE
else:
    PixieSysDLL = MagicMock(
        name="Need to run in 32 bit mode on Windows to use the control module"
    )
    PROTO = MagicMock(
        name="Need to run in 32 bit mode on Windows to use the control module"
    )

SETTINGS = variables.settings
SETTINGS_NAME_CHANNEL = []
SETTINGS_NAME_MODULE = []
for name, (startpos, length) in SETTINGS.items():
    if length == 16:
        SETTINGS_NAME_CHANNEL.append(name)
    else:
        SETTINGS_NAME_MODULE.append(name)


# read/write setting in pixie directly
pixie_DSP_memory_io_prototype = PROTO(
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_uint),
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.c_ushort,
    ctypes.c_ushort,
)

Cpixie_DSP_memory_io = pixie_DSP_memory_io_prototype(
    ("Pixie_DSP_Memory_IO", PixieSysDLL)
)


def read_raw_settings(module, N=832, start=0x4A000):
    """Read the raw data from the pixie for the settings

    These are blocks of uint values that depending on the setting need
    to be converted to float or bit values

    The functions reads out N uint (4 bytes) starting at memory
    locations 0x4a000.

    By default we read out all settings for a module that can be
    changed, e.g. the first 832 settings, but by changing the start
    and length, one can read out single settings too.

    """

    Cmodule = ctypes.c_ushort(module)
    Cdirection = ctypes.c_ushort(1)  # SYS_MOD_READ = 1 for read operations

    Cwords = ctypes.c_uint(N)
    Caddress = ctypes.c_uint(start)
    Cdata = (ctypes.c_uint * N)()

    ret = Cpixie_DSP_memory_io(Cdata, Caddress, Cwords, Cdirection, Cmodule)

    if ret == 0:
        log.debug("Read mod settings success!")
        return np.ctypeslib.as_array(Cdata)
    elif ret == -1:
        log.error(f"Reading DSP memory blocks failed. mod={module}")
    elif ret == -2:
        log.error(f"Reading DSP memory remaining words failed. mod={module}")
    else:
        log.error(f"pixie_DSP_memory_io error {ret} -- should not happen")

    return None


def write_raw_settings(module, setting, start=0x4A000):
    Cmodule = ctypes.c_ushort(module)
    Cdirection = ctypes.c_ushort(0)  # SYS_MOD_WRITE = 0

    if not isinstance(setting, np.ndarray):
        print("Error: setting needs to be a uint32 numpy array")
        return

    if not setting.dtype == "<u4":
        print("Error: setting needs to be a uint32 numpy array in little endian (<u4)")
        return

    N = len(setting)
    if N > 832:
        setting = setting[:832]
        N = 832
    Cwords = ctypes.c_uint(N)
    Caddress = ctypes.c_uint(start)
    Cdata = setting.ctypes.data_as(ctypes.POINTER(ctypes.c_uint))

    ret = Cpixie_DSP_memory_io(Cdata, Caddress, Cwords, Cdirection, Cmodule)

    if ret == 0:
        log.debug("Read mod settings success!")
        fip_ret = ProgramFippi(module)
        if fip_ret != 0:
            log.debug("Could not program fippi")
            return False
        dac_ret = ProgramSetDACs(module)
        if dac_ret != 0:
            log.debug("Could not set DACs")
            return False
        return True
    elif ret == -1:
        log.error(f"Reading DSP memory blocks failed. mod={module}")
    elif ret == -2:
        log.error(f"Reading DSP memory remaining words failed. mod={module}")
    else:
        log.error(f"pixie_DSP_memory_io error {ret} -- should not happen")

    return False


def change_setting_in_memory(setting, name, value, channel=None, module=0):
    """Changes a single setting inside a block of memory read by read_raw_settings"""

    # ensure correct sign for
    if name in ["Log2Ebin", "Log2Bweight"]:
        value = -abs(value)

    # error checking
    if name in ["Log2Bweight", "Log2Ebin"]:
        if abs(value) > 16:
            raise ValueError(
                f"Error: {name} cannot be larger than 16! "
                f"value {value} channel {channel} module {module}"
            )
        if value == 0 and name == "Log2Ebin":
            raise ValueError(
                f"Error: {name} cannot be 0! "
                f"value {value} channel {channel} module {module}"
            )
    elif name == "FastThresh":
        if value > 65534:
            raise ValueError(
                f"Error: {name} must be smaller than 65535!"
                f" value {value} channel {channel} module {module}"
            )

    if name in variables.settings:
        start, length = variables.settings[name]
        if channel is None:
            if length == 1 and isinstance(value, int):
                setting[start] = value
                return setting
            try:
                if len(value) != length:
                    log.error(
                        f"change_setting: wrong number of arguments"
                        f" for setting {name}.",
                        f" Need {length}, got {len(value)}",
                    )
                    return
            except TypeError:
                log.error(
                    f"change_setting: wrong type of argument. "
                    f"Need a list of values for {name}, got {value}."
                )
                return
            for k, v in zip(range(length), value):
                idx = start + k
                setting[idx] = v
        else:
            idx = start + channel
            setting[idx] = value
        return setting
    else:
        log.error(f"change_setting: wrong channel name {name}")
        return None


def change_setting(name, value, channel=None, module=0):
    """Changes the value of a single setting

    First reads all values, changes one and then sends the new setting
    back to the pixie.

    Module parameter can be set by setting channel to None.

    """
    setting = read_raw_settings(0, N=832)

    new = change_setting_in_memory(setting, name, value, channel, module)

    if new is not None:
        write_raw_settings(module, setting)
    else:
        log.error(f"change_setting: Could not change settings")


def change_register_bit(setting, name, value: bool, bit: int, channel: int = 0):
    """Update a bit in register

    setting: from read_raw_setting (a block of memory)
    name:    name of the register
    value:   True or False
    """

    start, _ = variables.settings[name]
    current = setting[start + channel]
    new = 1 << bit
    if value:
        # set the bit
        new = current | new
    else:
        # unset the bit
        new = current & ~new
    setting[start + channel] = new

    return setting


def change_CSRA_bit(setting, value: bool, channel: int, bit: int):
    return change_register_bit(setting, "ChanCSRa", value, bit, channel)


def change_CSRB_bit(setting, value: bool, bit: int):
    return change_register_bit(setting, "ModCSRB", value, bit)


def change_CSRA(setting, name, value, channel: int):
    """Update bits by name for CSRa

    setting: from read_raw_setting (a block of memory)
    name:    name of the setting (defined here)
    value:   either True/False or custom strings (see below)
    channel: channel number to update
    """
    if name == "FastTrigSelect":
        # value: 'external' or 'group'
        return change_CSRA_bit(setting, value == "external", channel, 0)
    elif name == "ModValSignal":
        # value: 'modgate' or 'global'
        return change_CSRA_bit(setting, value == "modgate", channel, 1)
    elif name == "GoodChannel":
        # value: True = enable channel
        return change_CSRA_bit(setting, value, channel, 2)
    elif name == "ChanValSignal":
        # value: 'channelgate' or 'channelvalidation'
        return change_CSRA_bit(setting, value == "channelgate", channel, 3)
    elif name == "RejectIfFull":
        # value: True = reject data if buffer is full
        return change_CSRA_bit(setting, value, channel, 4)
    elif name == "Polarity":
        # value: True=positive slope, False=negative slope
        return change_CSRA_bit(setting, value == "positive", channel, 5)
    elif name == "EnableVeto":
        # value: True = enable veto
        return change_CSRA_bit(setting, value, channel, 6)
    elif name == "CaptureHistogram":
        # value: True = enable capture of MCA histograms
        return change_CSRA_bit(setting, value, channel, 7)
    elif name == "CaptureTrace":
        # value: True = enable capture trace
        return change_CSRA_bit(setting, value, channel, 8)
    elif name == "EnableQDC":
        # value: True = enable capture QDC sums
        return change_CSRA_bit(setting, value, channel, 9)
    elif name == "EnableCFD":
        # value: True = enable CFD
        return change_CSRA_bit(setting, value, channel, 10)
    elif name == "EnableModVal":
        # value: True = enable module validation
        return change_CSRA_bit(setting, value, channel, 11)
    elif name == "CaptureSums":
        # value: True = enable capture raw energy susms
        return change_CSRA_bit(setting, value, channel, 12)
    elif name == "EnableChannelVal":
        # value: True = enable channel validation
        return change_CSRA_bit(setting, value, channel, 13)
    elif name == "Gain":
        # value: 0.625 or 2.5
        return change_CSRA_bit(setting, value == 2.5, channel, 14)
    elif name == "RejectPileup":
        # value: 'all' (no energies for pileup events),
        #        'single' (reject pileup),
        #        'pileup' (trace, timestamp for pileup, no trace for single)
        #        'pileup-only' (only record trace, timestamp, etc for pileup
        #                       events, no single events)
        bit0 = (value == "single") or (value == "pileup-only")
        bit1 = (value == "pileup") or (value == "pileup-only")
        setting = change_CSRA_bit(setting, bit0, channel, 15)
        setting = change_CSRA_bit(setting, bit1, channel, 16)
        return setting
    elif name == "SkipLargePulses":
        # value: True = don't record traces for large pulses
        return change_CSRA_bit(setting, value, channel, 17)
    elif name == "GroupTrigSignal":
        # value: 'external' or 'local'
        return change_CSRA_bit(setting, value == "external", channel, 18)
    elif name == "ChannelVetoSignal":
        # value: 'channel' or 'front'
        return change_CSRA_bit(setting, value == "channel", channel, 19)
    elif name == "ModVetoSignal":
        # value: 'module' or 'front'
        return change_CSRA_bit(setting, value == "module", channel, 20)
    elif name == "ExtTimestamps":
        # value: True = include external timestamps in header
        return change_CSRA_bit(setting, value, channel, 21)
    else:
        raise KeyError(f"Error: unknown key for ChannelCSRa {name}")


def change_CSRB(setting, name, value: float):
    """Update bits by name for CSRb

    setting: from read_raw_setting (a block of memory)
    name:    name of the setting (defined here)
    value:   either True/False or custom strings (see below)
    """
    if name == "BackplanePullup":
        # value: True = connect backplane to pullup resistor
        return change_CSRB_bit(setting, value, 0)
    elif name == "Director":
        # value: True = set to director
        return change_CSRB_bit(setting, value, 4)
    elif name == "ChassisMaster":
        # value: True = set to chassis master
        return change_CSRB_bit(setting, value, 6)
    elif name == "GlobalFastTrigger":
        # value: True = select global fast trigger source
        return change_CSRB_bit(setting, value, 7)
    elif name == "ExternalTrigger":
        # value: True = select external trigger source
        return change_CSRB_bit(setting, value, 8)
    elif name == "ExternalInhibit":
        # value: True = use inhibit
        return change_CSRB_bit(setting, value, 10)
    elif name == "DistributeClocks":
        # value: True = multiple crates
        return change_CSRB_bit(setting, value, 11)
    elif name == "SortEvents":
        # value: True = sort events based on timestamp
        return change_CSRB_bit(setting, value, 12)
    elif name == "ConnectFastTriggerBP":
        # value: True = Connect the fast trigger to the backplane
        return change_CSRB_bit(setting, value, 13)
    else:
        raise KeyError(f"Error: unknown key for ModuleCSRb {name}")


def get_setting_value(name, settings, channels, current_settings):
    """Returns name from setting dictionary or from memory"""
    if name in settings:
        temp = settings[name]
        if isinstance(temp, int):
            temp = [temp] * len(channels)
    else:
        if SETTINGS[name][1] == 16:
            temp = [current_settings[mod][SETTINGS[name][0] + c] for mod, c in channels]
        elif SETTINGS[name][1] == 1:
            temp = [current_settings[mod][SETTINGS[name][0]] for mod, c in channels]
        else:
            print(f"[ERROR] get_setting_value cannot get value for {name}")

    return temp


def change_setting_dict(settings, auto_update=True):
    """Takes a dictionary with setting names as keys and setting values

    The dictionary must also contain an entry called 'channels' that
    list all channels that should be set. Channels should be pairs in
    the form [module, channel].

    This function will also set variabels that depend on other
    variables (e.g. PeakSample depends on SlowLength).  However, if
    PeakSample is given, those values will be used.

    The values in the dictonary depends on the type of variable:
        a) Channel parameter
           The value needs to be either a list of the same name as the
           number of channels or smaller lists are checked to see if
           they match the list of modules, in which case each number
           will be used to set all channels in the module, or a single
           number in which case this number will be used for all
           channels in all modules
        b) module parameter
           The value needs to be either a single number in case a
           single module is used or a list of numbers that has the
           same length as the number of modules used.  For some
           parameters, e.g. TrigConfig the value needs to be a list
           (number of modules) of lists (4 entries for TrigConfig)

    """
    assert (
        "channels" in settings
    ), "The settings dictionary needs an entry listing called 'channels' the channels"
    channels = settings.pop("channels")

    for c in channels:
        assert isinstance(
            c, (list, tuple)
        ), "Setting dictionary: each channel must be a list or tuple"
        assert (
            len(c) == 2
        ), "Setting dictionary: each channel must have two entries (modules, channel)"

    modules = {x[0] for x in channels}

    # get all the raw settings data from the pixie
    current = {}
    for mod in modules:
        current[mod] = read_raw_settings(mod, N=1280)

    # update depend values
    if "SlowLength" in settings or "SlowGap" in settings:
        SL = get_setting_value("SlowLength", settings, channels, current)
        SG = get_setting_value("SlowGap", settings, channels, current)
        for i, (sl, sg) in enumerate(zip(SL, SG)):
            if sl + sg > 127:
                print(f"Warning: SlowLength + SlowGap > 127. SL {SL} SG {SG}")
                sl = 127 - sg
            if sl < 2:
                print(f"Warning: SlowLength < 2. SL {SL}.")
                sl = 2
                if sl + sg > 127:
                    sg = 127 - sl
            if sg < 3:
                print(f"Warning: SlowGap < 3. SG {SG}.")
                sg = 3
                if sl + sg > 127:
                    sl = 127 - sg
            SL[i] = sl
            SG[i] = sg
        settings["SlowLength"] = SL
        settings["SlowGap"] = SG

    if auto_update and ("PeakSample" not in settings):
        filter_range = get_setting_value("SlowFilterRange", settings, channels, current)
        SL = get_setting_value("SlowLength", settings, channels, current)
        SG = get_setting_value("SlowGap", settings, channels, current)
        PeakSample = []
        for sl, sg, f in zip(SL, SG, filter_range):
            if f > 6:
                PeakSample.append(sl + sg - 2)
            elif f > 2:
                PeakSample.append(sl + sg - 5 + f)
            else:
                PeakSample.append(sl + sg - 4 + f)
        settings["PeakSample"] = PeakSample

    if auto_update and ("PeakSep" not in settings):
        SL = get_setting_value("SlowLength", settings, channels, current)
        SG = get_setting_value("SlowGap", settings, channels, current)
        PeakSep = [sl + sg for sl, sg in zip(SL, SG)]
        settings["PeakSep"] = PeakSep

    if auto_update and ("TriggerDelay" not in settings):
        filter_range = get_setting_value("SlowFilterRange", settings, channels, current)
        PeakSep = get_setting_value("PeakSep", settings, channels, current)
        settings["TriggerDelay"] = [
            (p - 1) * 2 ** f for f, p in zip(filter_range, PeakSep)
        ]
    if auto_update and ("PAFlength" in settings) and ("TraceDelay" in settings):
        print("Warning: PAFlength and TraceDelay set. TraceDelay will be ignored.")
        settings.pop("TraceDelay")
    if auto_update and ("PAFlength" not in settings) and ("TraceDelay" in settings):
        TriggerDelay = get_setting_value("TriggerDelay", settings, channels, current)
        FastFilterRange = get_setting_value(
            "FastFilterRange", settings, channels, current
        )
        TraceDelay = get_setting_value("TraceDelay", settings, channels, current)
        FIFOLength = get_setting_value("FIFOLength", settings, channels, current)
        settings.pop("TraceDelay")

        PAFlength = [
            t / (2 ** f) + d / 5
            for t, f, d in zip(TriggerDelay, FastFilterRange, TraceDelay)
        ]

        settings["PAFlength"] = PAFlength
    if auto_update and ("PAFlength" in settings):
        PAFlength = get_setting_value("PAFlength", settings, channels, current)
        FIFOLength = get_setting_value("FIFOLength", settings, channels, current)
        FastFilterRange = get_setting_value(
            "FastFilterRange", settings, channels, current
        )
        if "TraceDelay" in settings:
            TraceDelay = get_setting_value("TraceDelay", settings, channels, current)
            TraceDelay = [
                x / 5 for x in TraceDelay
            ]  # convert from data points to FPGA cycles
        else:
            TriggerDelay = get_setting_value(
                "TriggerDelay", settings, channels, current
            )
            TraceDelay = [
                pl - td / (2 ** f)
                for pl, td, f in zip(PAFlength, TriggerDelay, FastFilterRange)
            ]
        PAFlength = [min(pl, fl - 1) for pl, fl in zip(PAFlength, FIFOLength)]
        TriggerDelay = [
            (pf - td) * 2 ** f
            for pf, td, f in zip(PAFlength, TraceDelay, FastFilterRange)
        ]

        settings["PAFlength"] = PAFlength
        settings["TriggerDelay"] = TriggerDelay
    if "PreampTau" in settings:
        name = "PreampTau"
        if isinstance(settings[name], int):
            settings[name] = converter_IEEE754_to_ulong(settings[name]).value
        else:
            settings[name] = [
                converter_IEEE754_to_ulong(x).value for x in settings[name]
            ]

    # update all settings
    for name, values in settings.items():
        # single bit settings CSRB
        if name in [
            "BackplanePullup",
            "Director",
            "ChassisMaster",
            "GlobalFastTrigger",
            "ExternalTrigger",
            "ExternalInhibit",
            "DistributeClocks",
            "SortEvents",
            "ConnectFastTriggerBP",
        ]:
            if isinstance(values, int):
                for mod in modules:
                    current[mod] = change_CSRB(current[mod], name, values)
            else:
                raise NotImplementedError("Need to add CSRB for non-int values")
        # single bit settings CSRA
        elif name in [
            "FastTrigSelect",
            "ModValSignal",
            "GoodChannel",
            "ChanValSignal",
            "RejectIfFull",
            "Polarity",
            "EnableVeto",
            "CaptureHistogram",
            "CaptureTrace",
            "EnableQDC",
            "EnableCFD",
            "EnableModVal",
            "CaptureSums",
            "EnableChannelVal",
            "Gain",
            "RejectPileup",
            "SkipLargePulses",
            "GroupTrigSignal",
            "ChannelVetoSignal",
            "ModVetoSignal",
            "ExtTimestamps",
        ]:
            if isinstance(values, (list, tuple)):
                if len(values) == len(channels):
                    for value, channel in zip(values, channels):
                        mod, ch = channel
                        current[mod] = change_CSRA(current[mod], name, value, ch)
                else:
                    raise TypeError(
                        f"Wrong type (or length) for channel parameter {name}"
                        f" in change_settings_dict, values: {settings[name]}"
                    )
            else:
                for channel in channels:
                    mod, ch = channel
                    current[mod] = change_CSRA(current[mod], name, values, ch)
        elif name in SETTINGS_NAME_CHANNEL:
            if isinstance(settings[name], (list, tuple)):
                if len(settings[name]) == len(channels):
                    for value, channel in zip(settings[name], channels):
                        mod, ch = channel
                        change_setting_in_memory(current[mod], name, value, ch, mod)
                elif len(settings[name]) == len(modules):
                    for value, mod in zip(settings[name], modules):
                        for ch in range(16):
                            change_setting_in_memory(current[mod], name, value, ch, mod)
                else:
                    raise TypeError(
                        f"Wrong type (or length) for channel parameter {name}"
                        f" in change_settings_dict, values: {settings[name]}"
                    )
            elif isinstance(settings[name], int):
                value = settings[name]
                for mod in modules:
                    for ch in range(16):
                        change_setting_in_memory(current[mod], name, value, ch, mod)
            else:
                raise TypeError(
                    "Wrong type (or length) for channel parameter"
                    " in change_settings_dict"
                )
        elif name in SETTINGS_NAME_MODULE:
            if isinstance(settings[name], int):
                for mod in modules:
                    change_setting_in_memory(
                        current[mod], name, settings[name], None, mod
                    )
            elif isinstance(settings[name], (list, tuple)):
                for mod, value in zip(modules, settings[name]):
                    change_setting_in_memory(current[mod], name, value, None, mod)
        else:
            log.error(f"Change settings dict: unkown settings name {name}")

    # always enable all channels, we don't get any data otherwise... bug in pixie16?
    for m in modules:
        for c in range(16):
            current[m] = change_CSRA_bit(current[m], True, c, 2)

    for mod in modules:
        write_raw_settings(mod, current[mod])


# read data directly for list mode
Pixie_Read_ExtFIFOStatus_prototype = PROTO(
    ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.c_ushort
)

CReadFIFOStatus = Pixie_Read_ExtFIFOStatus_prototype(
    ("Pixie_Read_ExtFIFOStatus", PixieSysDLL)
)


def ReadFIFOStatus(module):
    """Uses the XIA library to read how many 32bit words are available on module N

    module:   module number

    return number of 32 bit words available
    """

    # convert to ctypes for library call
    Cmodule = ctypes.c_ushort(module)
    Cwords = (ctypes.c_uint)()

    ret = CReadFIFOStatus(Cwords, Cmodule)
    if ret >= 0:
        log.debug("Read FIFO status from Mod Success!")
    else:
        log.error(f"got an error in ReadFIFOStatus {ret}")

    return Cwords.value


Pixie_ExtFIFO_Read_prototype = PROTO(
    ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.c_uint, ctypes.c_ushort
)

CReadFIFO = Pixie_ExtFIFO_Read_prototype(("Pixie_ExtFIFO_Read", PixieSysDLL))


def ReadFIFO(module, words):
    """Uses the XIA library to read data in 32bit words from module N

    Parameters
    ----------

    module : int
        module number
    words : int
        number of words to read (from ReadFIFOStats)

    Returns
    -------

    data : np.array
         numpy array of 32 bit words (unsigned integers)
    """

    # convert to ctypes for library call
    Cmodule = ctypes.c_ushort(module)
    Cwords = ctypes.c_uint(words)
    Cdata = (ctypes.c_uint * words)()

    ret = CReadFIFO(Cdata, Cwords, Cmodule)
    if ret >= 0:
        log.debug("Read FIFO from Mod Success!")
    elif ret == -1:
        log.error(f"Invalid Pixie16 module number {module}")
    else:
        log.error("got an error in ReadFIFO")

    return np.ctypeslib.as_array(Cdata)
