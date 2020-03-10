"""Make library functions available in python

At the moment, many items are still a mix between raw C-library calls
and a more pythonic interface. The goal is to slowly make this more pythonic.

Currently also some path are hardcoded, better would be to read from a setting file.

At the moment this also only supports Windows and needs python32 to run.

Currently only support Rev-B-D

"""

import appdirs
import configparser
from collections import namedtuple
import datetime
import ctypes
import logging
import numpy as np
from pathlib import Path
import os
import sys
import time

# load information about where in the memory block for settings certain
# variables are located
from . import variables

SETTINGS = variables.settings
SETTINGS_NAME_CHANNEL = []
SETTINGS_NAME_MODULE = []
for name, (startpos, length) in SETTINGS.items():
    if length == 16:
        SETTINGS_NAME_CHANNEL.append(name)
    else:
        SETTINGS_NAME_MODULE.append(name)

if sys.maxsize > 2 ** 32:
    print("WARNING: need to run 32bit python to use this library")
#    sys.exit()

dirs = appdirs.AppDirs("PIXIE16")
inifile = Path(dirs.user_config_dir) / "config.ini"

config = configparser.ConfigParser()
config.read(inifile)


def config_get_parameters(section, name):
    try:
        path = config.get(section, name).replace('"', "")
        path = path.replace("'", "")
        path = Path(path)
    except (configparser.NoOptionError, configparser.NoSectionError):
        path = None
        print()
        print(f"No {name} found in {section}, please add it to {inifile}")
        print(f"   The file should contain something like:")
        print(f"       [{section}]")
        print(f"       {name} = <setting for  {name}>")
        print()
        print("The file should contain the following sections and keys:")
        print("   [Libraries]")
        print("   app = '<path do PixieAppDll.dll>")
        print("   sys = '<path do Pixie16SysDll.dll>")
        print("   [Data]")
        print("   datair = '<path where the data files should live")
        print("   [Firmware.default]")
        print("   ComFPGAConfigFile = '<path do syspixie16 firmware>")
        print("   SPFPGAConfigFile = '<path do fippixie16 firmware>")
        print("   DSPCodeFile = '<path do Pixie16DSP*.ldr>")
        print("   DSPVarFile = '<path do Pixie16DSP*.var>")
        print()
        # sys.exit()
    return path


lib_app = config_get_parameters("Libraries", "app")
lib_sys = config_get_parameters("Libraries", "sys")

data_dir = config_get_parameters("Data", "datadir")

firmware_com = config_get_parameters("Firmware.default", "ComFPGAConfigFile")
firmware_sp = config_get_parameters("Firmware.default", "SPFPGAConfigFile")
firmware_dsp_code = config_get_parameters("Firmware.default", "DSPCodeFile")
firmware_dsp_var = config_get_parameters("Firmware.default", "DSPVarFile")


# make sure the library directory in the path, so that we can find
# dependencies, otherwise we get a "[WinError 126] The specified
# module could not be found" error
if lib_app:
    os.environ["PATH"] = str(lib_app.parent) + ";" + os.environ["PATH"]
PixieAppDLL = None
PixieSysDLL = None
if lib_app:
    PixieAppDLL = ctypes.cdll.LoadLibrary(str(lib_app))
    PixieSysDLL = ctypes.cdll.LoadLibrary(str(lib_sys))

# set up logging
log = logging.getLogger(__name__)


current_dir = Path(".")
# make sure pxisys.ini is available
initfile = current_dir / "pxisys.ini"
if not initfile.exists():
    log.error(
        f"Error: please copy the pxisys.ini file into the directory: {current_dir}"
    )

# module global that keeps track of some information for us, so that we don't have to pass it to every function
modules = []  # list of PCI slot numbers, should start with 2, e.g. [2, 3]
init_done = False
boot_done = False

# end globals

valid_module_parameter_names = [
    "MODULE_NUMBER",
    "MODULE_CSRA",
    "MODULE_CSRB",
    "MODULE_FORMAT",
    "MAX_EVENTS",
    "SYNCH_WAIT",
    "IN_SYNCH",
    "SLOW_FILTER_RANGE",
    "FAST_FILTER_RANGE",
    "FastTrigBackplaneEna",
    "CrateID",
    "SlotID",
    "ModID",
    "TrigConfig",
    "HOST_RT_PRESET",
]

valid_channel_parameter_names = [
    "TRIGGER_RISETIME",
    "TRIGGER_FLATTOP",
    "TRIGGER_THRESHOLD",
    "ENERGY_RISETIME",
    "ENERGY_FLATTOP",
    "TAU",
    "TRACE_LENGTH",
    "TRACE_DELAY",
    "VOFFSET",
    "XDT",
    "BASELINE_PERCENT",
    "EMIN",
    "BINFACTOR",
    "CHANNEL_CSRA",
    "CHANNEL_CSRB",
    "BLCUT",
    "FASTTRIGBACKLEN",
    "CFDDelay",
    "CFDScale",
    "QDCLen0",
    "QDCLen1",
    "QDCLen2",
    "QDCLen3",
    "QDCLen4",
    "QDCLen5",
    "QDCLen6",
    "QDCLen7",
    "ExtTrigStretch",
    "ChanTrigStretch",
    "MultiplicityMaskL",
    "MultiplicityMaskH",
    "ExternDelayLen",
    "FtrigoutDelay",
    "VetoStretch",
]

# in the following we supply python functions for some of the library
# functions in the PixieAppDLL

# Pixie16ReadHistogramFromFile
read_histogram_prototype = ctypes.WINFUNCTYPE(
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.c_ulong,
    ctypes.c_ushort,
    ctypes.c_ushort,
)

CReadHistogram = read_histogram_prototype(("Pixie16ReadHistogramFromFile", PixieAppDLL))


def ReadHistogramFromFile(filename, module, channel, N=32768):
    """Uses the XIA library to read a single channel histogram from a file.

    filename: mca data file saved from XIA pixie16 module
    module:   module number
    channel:  channel in module
    N:        number of bins in the histogram, by default 32768

    return a 1D-numpy array with the histogram data
    """

    filename = Path(filename)
    if not filename.exists():
        raise FileNotFoundError

    # convert to ctypes for library call
    Cfilename = ctypes.c_char_p(bytes(filename))
    Cmodule = ctypes.c_ushort(module)
    Cchannel = ctypes.c_ushort(channel)
    result = (ctypes.c_ulong * N)()

    ret = CReadHistogram(Cfilename, result, ctypes.c_ulong(N), Cmodule, Cchannel)
    if ret != 0:
        log.error("got an error in ReadHistogram")

    return np.ctypeslib.as_array(result)


def ReadHistogramFromFileAll(filename, module, N=32768):
    """Read out all channels of a module

    filename: mca data file saved from XIA pixie16 module
    module:   module number
    N:        number of bins in the histogram, by defaul 32768

    return a 2D-numpy array with the histogram data
    """

    all = []
    for i in range(16):
        all.append(ReadHistogramFromFile(filename, module, i, N))
    return np.array(all)


# Pixie16GetModuleEvents
GetModuleEvents_prototype = ctypes.WINFUNCTYPE(
    ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_ulong)
)

CGetModuleEvents = GetModuleEvents_prototype(("Pixie16GetModuleEvents", PixieAppDLL))


def GetModuleEvents(filename, max_number_of_modules=14):
    """Uses the XIA library to read the number of events in a list mode data file.

    filename: list mode data file

    return the number of events in the file as numpy array
    """

    filename = Path(filename)
    if not filename.exists():
        raise FileNotFoundError

    # convert to ctypes for library call
    Cfilename = ctypes.c_char_p(bytes(filename))
    result = (ctypes.c_ulong * max_number_of_modules)()

    ret = CGetModuleEvents(Cfilename, result)

    if ret == -1:
        log.error("Error: GetModuleEvents: Null pointer *ModuleEvents")
    elif ret == -2:
        log.error("Error: GetModuleEvents: Failed to open list mode data file")
    elif ret == -3:
        log.error("Error: GetModuleEvents: Module number read out is invalid")

    return np.ctypeslib.as_array(result)


# Pixie16GetEventsInfo

GetEventsInfo_prototype = ctypes.WINFUNCTYPE(
    ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_ulong), ctypes.c_ushort
)

CGetEventsInfo = GetEventsInfo_prototype(("Pixie16GetEventsInfo", PixieAppDLL))

# see page 32 of Programmer Manual
EventsInfo = namedtuple(
    "EventsInfo",
    [
        "EventNumber",
        "ChannelNumber",
        "SlotNumber",
        "CrateNumber",
        "HeaderLength",
        "EventLength",
        "FinishCode",
        "EventTimestamp_lower_32_bit",
        "EventTimestamp_upper_16_bit",
        "EventEnergy",
        "TraceLength",
        "TraceLocation",
        "EventTimestamp",
    ],
)


def GetEventsInfo(filename, module):
    """Uses the XIA library to read detailed information about events in a list mode data file.

    filename: list mode data file
    module:   module number

    return dictionary with information about events
    """

    filename = Path(filename)
    if not filename.exists():
        raise FileNotFoundError

    # convert to ctypes for library call
    Cfilename = ctypes.c_char_p(bytes(filename))
    nr_of_events = GetModuleEvents(filename, max_number_of_modules=module + 1)[module]
    result = (ctypes.c_ulong * (68 * nr_of_events))()
    Cmodule = ctypes.c_ushort(module)

    ret = CGetEventsInfo(Cfilename, result, Cmodule)

    if ret == -1:
        log.error("Error: GetEventsInfo: Null pointer *EventInformation")
    elif ret == -2:
        log.error("Error: GetEventsInfo: Invalid Pixie-16 module number")
    elif ret == -3:
        log.error("Error: GetEventsInfo: Failed to open list mode data file")
    elif ret == -4:
        log.error("Error: GetEventsInfo: Module number read out is invalid")

    result = np.ctypeslib.as_array(result)
    result = result.reshape(nr_of_events, 68)

    events = []
    for r in result:
        timestamp = 2 ** 32 * r[8] + r[7]
        r = list(r[:12])
        r.append(timestamp)
        events.append(EventsInfo._make(r))
    return events


# Pixie16ReadListModeTrace

ReadListModeTrace_prototype = ctypes.WINFUNCTYPE(
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.POINTER(ctypes.c_ushort),
    ctypes.c_ushort,
    ctypes.c_ulong,
)

CReadListModeTrace = ReadListModeTrace_prototype(
    ("Pixie16ReadListModeTrace", PixieAppDLL)
)


def ReadListModeTrace(filename, Event):
    """Uses the XIA library to read a list mode trace from a data file.

    filename: list mode data file
    Event:    EventsInfo namedtuple (from GetEventsInfo)

    return numpy array
    """

    filename = Path(filename)
    if not filename.exists():
        raise FileNotFoundError

    # convert to ctypes for library call
    Cfilename = ctypes.c_char_p(bytes(filename))
    result = (ctypes.c_ushort * (Event.TraceLength))()
    CNumWords = ctypes.c_ushort(Event.TraceLength)
    CFileLocation = ctypes.c_ulong(Event.TraceLocation)

    ret = CReadListModeTrace(Cfilename, result, CNumWords, CFileLocation)

    if ret == -1:
        log.error("Error: GetEventsInfo: Failed to open list mode data file")

    result = np.ctypeslib.as_array(result)
    return result


# Pixie16InitSystem
init_sys_prototype = ctypes.WINFUNCTYPE(
    ctypes.c_int, ctypes.c_ushort, ctypes.POINTER(ctypes.c_ushort), ctypes.c_ushort
)

Cinit_sys = init_sys_prototype(("Pixie16InitSystem", PixieAppDLL))


def InitSys(PXISlotMap=None, OfflineMode=False):
    """Uses the XIA library to initialize the system.

    PXISlotMap:   array containing the slot numbers of each module
    OfflineMode:  specify to use online or offline mode

    """
    # convert to ctypes for library call
    global modules
    global init_done

    if init_done:
        log.warning("Init already done")
        return 0

    # set this module wide
    if PXISlotMap is not None:
        modules = PXISlotMap

    print(f"[INFO] Using modules in slot(s) {' '.join([str(x) for x in modules])}.")

    NumModules = len(modules)
    CNumModules = ctypes.c_ushort(NumModules)

    CPXISlotMap = (ctypes.c_ushort * (NumModules))()
    if OfflineMode:
        COfflineMode = ctypes.c_ushort(1)
    else:
        COfflineMode = ctypes.c_ushort(0)

    for i, slot in enumerate(modules):
        CPXISlotMap[i] = slot

    ret = Cinit_sys(CNumModules, CPXISlotMap, COfflineMode)
    if ret == 0:
        log.debug("Initialize Success!")
        init_done = True
    else:
        errors = {
            -1: [
                "Invalid total number of Pixie-16 modules",
                "Check if NumModules <= PRESET_MAX_MODULES",
            ],
            -2: ["Null pointer *PXISlotMap", "Correct PXISlotMap"],
            -3: [
                "Failed to initialize system",
                "Check error message log file Pixie16msg.txt",
            ],
        }
        message, solution = errors[ret]
        log.error("Error in InitSys")
        log.error(message, "Try:", solution)

    return ret


# Pixie16BootModule
boot_module_prototype = ctypes.WINFUNCTYPE(
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_ushort,
    ctypes.c_ushort,
)

Cboot_module = boot_module_prototype(("Pixie16BootModule", PixieAppDLL))


def BootModule(
    DSPParFile,
    ComFPGAConfigFile=firmware_com,
    SPFPGAConfigFile=firmware_sp,
    TrigFPGAConfigFile=" ",
    DSPCodeFile=firmware_dsp_code,
    DSPVarFile=firmware_dsp_var,
    ModNum=None,
    BootPattern=0x7F,
    section=None,
    verbose=False,
):
    """Uses the XIA library to boot the module.

    See page 13 of the programming manual.


    Parameters
    ----------

    ComFPGAConfigFile :
         config file found under Firmware
    SPFPGAConfigFile :
         config file found under Firmware
    TrigFPGAConfigFile :
         No longer in use. Kept for legacy reasons. Enter " " here
    DSPCodeFile :
         config file found under DSP
    DSPParFile :
         config file found under Configuration
    DSPVarFile :
         config file found under DSP
    ModNum : int
         location of module you want to boot
         (either 0,...,k-1 for individual modules or k for all modules)
         if None, check global modules variable to boot all modules
    BootPattern : int
        boot pattern mask. 0x7F to boot all on-board chips.
    section :
        use a different section from the config file to boot the firmware
    verbose : bool
        print out what firmware we are using

    Returns
    -------

    Returns 0 on success, otherwise it returns the error message from the library call.

    """

    global boot_done

    if boot_done:
        log.warning("boot already done")
        return 0

    # allow pathlib.Path objects
    if not isinstance(DSPParFile, Path):
        DSPParFile = Path(DSPParFile)

    for f in [ComFPGAConfigFile, SPFPGAConfigFile, DSPCodeFile, DSPVarFile]:
        if (not f.exists()) and (not f.is_file()):
            print(f"Error: cannot open firmware file {f}")
            sys.exit(1)

    if section is not None:
        section = f"Firmware.{section}"
        if section not in config.sections():
            print("Error: cannot find section {section} in the config file {inifile}")
            sys.exit(1)
        # load new path to firmware
        firmware_com = config_get_parameters(section, "ComFPGAConfigFile")
        firmware_sp = config_get_parameters(section, "SPFPGAConfigFile")
        firmware_dsp_code = config_get_parameters(section, "DSPCodeFile")
        firmware_dsp_var = config_get_parameters(section, "DSPVarFile")
        ComFPGAConfigFile = firmware_com
        SPFPGAConfigFile = firmware_sp
        DSPCodeFile = firmware_dsp_code
        DSPVarFile = firmware_dsp_var

    if verbose:
        print("Booting Pixie using the following firmware:")
        print(f"  Com      = {ComFPGAConfigFile}")
        print(f"  SP       = {SPFPGAConfigFile}")
        print(f"  DSP Code = {DSPCodeFile}")
        print(f"  DSP Var  = {DSPVarFile}")

    # convert to ctypes for library call
    CComFPGAConfigFile = ctypes.c_char_p(bytes(ComFPGAConfigFile))
    CSPFPGAConfigFile = ctypes.c_char_p(bytes(SPFPGAConfigFile))
    # converting a string next, so we need to specify utf8
    CTrigFPGAConfigFile = ctypes.c_char_p(bytes(TrigFPGAConfigFile, "utf8"))
    CDSPCodeFile = ctypes.c_char_p(bytes(DSPCodeFile))
    CDSPParFile = ctypes.c_char_p(bytes(DSPParFile))
    CDSPVarFile = ctypes.c_char_p(bytes(DSPVarFile))
    if ModNum is None:
        if modules is None:
            log.error(
                "You need to set ModNum or the global variable modules need to be set!"
            )
            return -1
        else:
            CModNum = ctypes.c_ushort(len(modules))
    else:
        CModNum = ctypes.c_ushort(ModNum)
    CBootPattern = ctypes.c_ushort(BootPattern)

    ret = Cboot_module(
        CComFPGAConfigFile,
        CSPFPGAConfigFile,
        CTrigFPGAConfigFile,
        CDSPCodeFile,
        CDSPParFile,
        CDSPVarFile,
        CModNum,
        CBootPattern,
    )
    if ret == 0:
        log.debug("Boot Success!")
        boot_done = True
    else:
        errors = {
            -1: ["Invalid Pixie-16 module number", "Correct ModNum"],
            -2: ["Size of ComFPGAConfigFile is invalid", "Correct ComFPGAConfigFile"],
            -3: [
                "Failed to boot Communication FPGA",
                "Check log file (Pixie16msg.txt)",
            ],
            -4: [
                "Failed to allocate memory to store data in ComFPGAConfigFile",
                "Close other programs or reboot the computer",
            ],
            -5: ["Failed to open ComFPGAConfigFile", "Correct ComFPGAConfigFile"],
            -6: ["Size of TrigFPGAConfigFile is invalid", "Correct TrigFPGAConfigFile"],
            -7: ["Failed to boot trigger FPGA", " Check log file (Pixie16msg.txt)"],
            -8: [
                "Failed to allocate memory to store data in TrigFPGAConfigFile",
                "Close other programs or reboot the computer",
            ],
            -9: ["Failed to open TrigFPGAConfigFile", "Correct TrigFPGAConfigFile"],
            -10: ["Size of SPFPGAConfigFile is invalid", "Correct SPFPGAConfigFile"],
            -11: [
                "Failed to boot signal processing FPGA",
                "Check log file (Pixie16msg.txt)",
            ],
            -12: [
                "Failed to allocate memory to store data in SPFPGAConfigFile",
                "Close other programs or reboot the computer",
            ],
            -13: ["Failed to open SPFPGAConfigFile", "Correct SPFPGAConfigFile"],
            -14: ["Failed to boot DSP", "Check log file (Pixie16msg.txt)"],
            -15: [
                "Failed to allocate memory to store DSP executable code",
                "Close other programs or reboot the computer",
            ],
            -16: ["Failed to open DSPCodeFile", "Correct DSPCodeFile"],
            -17: ["Size of DSPParFile is invalid", "Correct DSPParFile"],
            -18: ["Failed to open DSPParFile", "Correct DSPParFile"],
            -19: ["Cannot initialize DSP variable indices", "Correct DSPVarFile"],
            -20: [
                "Cannot copy DSP variable indices",
                "Check log file (Pixie16msg.txt)",
            ],
            -21: [
                "Failed to program Fippi in a module",
                "Check log file (Pixie16msg.txt)",
            ],
            -22: ["Failed to set DACs in a module", "Check log file (Pixie16msg.txt)"],
        }
        message, solution = errors[ret]
        log.error(message, "Try:", solution)
    return ret


# Pixie16ExitSystem
exit_sys_prototype = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_ushort)

Cexit_sys = exit_sys_prototype(("Pixie16ExitSystem", PixieAppDLL))


def ExitSys(ModNum):
    """Uses the XIA library to exit the system.

    ModNum:     set to module you want to exit.
                set to total number of modules initialized to exit all modules

    For k modules, the number is either 0,...,k-1 for individual modules or k for all modules.
    """
    global init_done
    global boot_done

    # convert to ctypes for library call
    CModNum = ctypes.c_ushort(ModNum)

    ret = Cexit_sys(CModNum)

    if ret == 0:
        log.debug("Exit system Success!")
        boot_done = False
        init_done = False
    else:
        errors = {
            -1: [
                "Invalid Pixie-16 module number",
                "Correct ModNum (it should not be greater than the total number of modules in the system)",
            ],
            -2: [
                "Failed to close Pixie-16 modules",
                "Check error message log file Pixie16msg.txt",
            ],
        }
        message, solution = errors[ret]
        log.error(message, "Try:", solution)

    return ret


# Pixie16WriteSglChanPar
write_chan_param_prototype = ctypes.WINFUNCTYPE(
    ctypes.c_int, ctypes.c_char_p, ctypes.c_double, ctypes.c_ushort, ctypes.c_ushort
)

CChanParam = write_chan_param_prototype(("Pixie16WriteSglChanPar", PixieAppDLL))


def WriteChanParam(ChanParName, ChanParData, module, channel):
    """Uses the XIA library to change a parameter in one channel in a module.
 see pg. 67 of the programmers manual for a list of parameters available.

    ChanParName:    parameter name
    ChanParData:    value of the parameter you wish to set
    module:         module number
    channel:        channel number
    """

    assert (
        ChanParName in valid_channel_parameter_names
    ), "Not a valid channel parameter name"

    if ChanParName in [
        "CHANNEL_CSRA",
        "CHANNEL_CSRB",
        "MultiplicityMaskL",
        "MultiplicityMaskH",
    ]:
        data = [str(int(x)) for x in ChanParData]
        ChanParData = int("".join(data), 2)

    # convert to ctypes for library call
    CChanParName = ctypes.c_char_p(bytes(ChanParName, "utf8"))
    CChanParData = ctypes.c_double(ChanParData)
    Cmodule = ctypes.c_ushort(module)
    Cchannel = ctypes.c_ushort(channel)

    ret = CChanParam(CChanParName, CChanParData, Cmodule, Cchannel)
    if ret == 0:
        log.debug("Change Chan Param Success!")
    else:
        log.error("got an error in WriteChanParam")

    return ret


# Pixie16ReadSglChanPar
read_chan_param_prototype = ctypes.WINFUNCTYPE(
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.POINTER(ctypes.c_double),
    ctypes.c_ushort,
    ctypes.c_ushort,
)

CReadChanParam = read_chan_param_prototype(("Pixie16ReadSglChanPar", PixieAppDLL))


def ReadChanParam(ChanParName, module, channel):
    """Uses the XIA library to read a parameter in one channel in a module.
 see pg. 51 of the programmers manual for a list of parameters available.

    ChanParName:    parameter name
    module:         module number
    channel:        channel number
    """

    assert (
        ChanParName in valid_channel_parameter_names
    ), "Not a valid channel parameter name"

    bit_pattern = False
    if ChanParName in [
        "CHANNEL_CSRA",
        "CHANNEL_CSRB",
        "MultiplicityMaskL",
        "MultiplicityMaskH",
    ]:
        bit_pattern = True

    # convert to ctypes for library call
    CChanParName = ctypes.c_char_p(bytes(ChanParName, "utf8"))
    Cmodule = ctypes.c_ushort(module)
    Cchannel = ctypes.c_ushort(channel)
    CChanParData = (ctypes.c_double)()

    ret = CReadChanParam(CChanParName, CChanParData, Cmodule, Cchannel)
    if ret == 0:
        log.debug("Read Chan Param Success!")
    elif ret == -1:
        log.error("got an error in ReadChanParam, Correct module")
    elif ret == -2:
        log.error("got an error in ReadChanParam, Correct channel")
    elif ret == -3:
        log.error("got an error in ReadChanParam, Correct ChanParName")

    if bit_pattern:
        value = np.ctypeslib.as_array(CChanParData)
        value = bin(int(value))[2:]
        value = [bool(int(x)) for x in value]
        return value

    return np.ctypeslib.as_array(CChanParData)


def set_channel_parameter(name, value, module, channel):
    """Set and read back a parameter in a channel"""

    out = WriteChanParam(name, value, module, channel)
    if out != 0:
        log.error(
            f"Error setting {name} in module {module} at channel {channel} to {value}"
        )

    return ReadChanParam(name, module, channel)


def converter_IEEE754_to_ulong(x):
    a = (ctypes.c_float * 1)(x)
    b = ctypes.cast(a, ctypes.POINTER(ctypes.c_ulong))
    return b.contents


def converter_ulong_to_IEEE754(x):
    a = (ctypes.c_ulong * 1)(x)
    b = ctypes.cast(a, ctypes.POINTER(ctypes.c_float))
    return b.contents


# Pixie16WriteSglModPar
write_mod_param_prototype = ctypes.WINFUNCTYPE(
    ctypes.c_int, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_ushort
)

CModParam = write_mod_param_prototype(("Pixie16WriteSglModPar", PixieAppDLL))


def WriteModParam(ModParName, ModParData, module):
    """Uses the XIA library to change a parameter in one module.
 see pg. 69 of the programmers manual for a list of parameters available.

    ModParName:    parameter name
    ModParData:    value of the parameter you wish to set
    module:        module number
    """

    assert ModParName in valid_module_parameter_names, "Wrong module parameter name"

    # which parameters do we need to convert from float?
    parameter_list_convert_from_IEEE = ["HOST_RT_PRESET"]

    # convert to ctypes for library call
    CModParName = ctypes.c_char_p(bytes(ModParName, "utf8"))
    if ModParName in parameter_list_convert_from_IEEE:
        CModParData = converter_IEEE754_to_ulong(ModParData)
    else:
        CModParData = ctypes.c_ulong(ModParData)
    Cmodule = ctypes.c_ushort(module)

    ret = CModParam(CModParName, CModParData, Cmodule)
    if ret == 0:
        log.debug("Change Mod Param Success!")
    else:
        log.error("got an error in WriteModParam")
        log.error("ret=", ret)

    return ret


# Pixie16ReadSglModPar
read_mod_param_prototype = ctypes.WINFUNCTYPE(
    ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_ulong), ctypes.c_ushort
)

CReadModParam = read_mod_param_prototype(("Pixie16ReadSglModPar", PixieAppDLL))


def ReadModParam(ModParName, module):
    """Uses the XIA library to read a parameter in one module.
 see pg. 53 of the programmers manual for a list of parameters available.

    ModParName:    parameter name
    module:         module number
    """

    assert ModParName in valid_module_parameter_names, "Wrong  parameter name"

    # which parameters do we need to convert to float?
    parameter_list_convert_to_IEEE = ["HOST_RT_PRESET"]

    # convert to ctypes for library call
    CModParName = ctypes.c_char_p(bytes(ModParName, "utf8"))
    Cmodule = ctypes.c_ushort(module)
    CModParData = (ctypes.c_ulong)()

    ret = CReadModParam(CModParName, CModParData, Cmodule)
    if ret == 0:
        log.debug("Read Chan Param Success!")
    else:
        errors = {
            -1: ["Invalid total number of Pixie-16 modules", "Correct module"],
            -2: ["Invalid module parameter name", "Correct ModParName"],
        }
        message, solution = errors[ret]
        log.error("Error in ReadModParam")
        log.error(message, "Try:", solution)

    if ModParName in parameter_list_convert_to_IEEE:
        return np.ctypeslib.as_array(converter_ulong_to_IEEE754(CModParData))
    else:
        return np.ctypeslib.as_array(CModParData)


def set_module_parameter(name, value, module):
    """Set and read back a parameter in a module"""

    out = WriteModParam(name, value, module)
    if out != 0:
        log.error(f"Error setting {name} in module {module} to {value}")

    return ReadModParam(name, module)


def set_run_time(runtime, module):
    return set_module_parameter("HOST_RT_PRESET", runtime, module)


# Pixie16StartHistogramRun
start_hist_run_prototype = ctypes.WINFUNCTYPE(
    ctypes.c_int, ctypes.c_ushort, ctypes.c_ushort
)

CStartHistRun = start_hist_run_prototype(("Pixie16StartHistogramRun", PixieAppDLL))


def start_histogram_run(module=None, resume=False):
    """Uses the XIA library to start an MCA run in one channel in a module.

    Parameters
    ----------

    module :
         module number
         0,..., k-1 to start individual modules, k to start all modules
         None to use module wide definition of modules

    resume : bool
         Resume the run?

    """

    if module is None:
        module = len(modules)
    if module is None:
        log.error("need to set number of modules")

    # convert to ctypes for library call
    Cmodule = ctypes.c_ushort(module)
    if resume:
        Cmode = ctypes.c_ushort(0)
    else:
        Cmode = ctypes.c_ushort(1)

    ret = CStartHistRun(Cmodule, Cmode)
    if ret == 0:
        log.debug("Start Hist Run Success!")
    else:
        log.error("got an error in StartHistRun")

    return ret


# Pixie16StartListModeRun
start_listmode_run_prototype = ctypes.WINFUNCTYPE(
    ctypes.c_int, ctypes.c_ushort, ctypes.c_ushort, ctypes.c_ushort
)

CStartListModeRun = start_listmode_run_prototype(
    ("Pixie16StartListModeRun", PixieAppDLL)
)


def start_listmode_run(module=None, runtype=0x100, resume=False):
    """Uses the XIA library to start a list mode run in one channel in a module.

    Parameters
    ----------

    module :
         module number
         0,..., k-1 to start individual modules, k to start all modules
         None to use module wide definition of modules
    runtype :
         taks number
    resume :
         resume run?
    """

    if module is None:
        module = len(modules)
    if module is None:
        log.error("need to set number of modules")

    # convert to ctypes for library call
    Cmodule = ctypes.c_ushort(module)
    CrunType = ctypes.c_ushort(0x100)
    if resume:
        Cmode = ctypes.c_ushort(0)
    else:
        Cmode = ctypes.c_ushort(1)

    ret = CStartListModeRun(Cmodule, CrunType, Cmode)
    if ret == 0:
        log.debug("Start List Mode Run Success!")
    else:
        log.error("got an error in StartListModeRun")

    return ret


# Pixie16CheckRunStatus
check_run_status_prototype = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_ushort)

CCheckRunStatus = check_run_status_prototype(("Pixie16CheckRunStatus", PixieAppDLL))


def CheckRunStatus(module):
    """Uses the XIA library to check the run status of a module.

    module:         module number

    See page 17 in the manual.
    """

    # convert to ctypes for library call
    Cmodule = ctypes.c_ushort(module)

    ret = CCheckRunStatus(Cmodule)

    if ret == 0:
        log.debug("No run is in progress")
    elif ret == 1:
        log.debug("Run is still in progress")
    else:
        log.error("Got return value -1")
        log.error("Invalid Pixie-16 module number. Try:  Correct ModNum")

    return ret


# Pixie16ReadHistogramFromModule
read_hist_mod_prototype = ctypes.WINFUNCTYPE(
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_uint),
    ctypes.c_uint,
    ctypes.c_ushort,
    ctypes.c_ushort,
)

CReadHistogramMod = read_hist_mod_prototype(
    ("Pixie16ReadHistogramFromModule", PixieAppDLL)
)


def ReadHistogramFromModule(module, channel, N=32768):
    """Uses the XIA library to read a single channel histogram from the module.

    Parameters
    ----------
    module : int
        module number
    channel : int
        channel in module
    N : int
        number of bins in the histogram, by default 32768

    Returns:
    --------

    result : np.array
         1D-numpy array with the histogram data
    """

    # convert to ctypes for library call
    Cmodule = ctypes.c_ushort(module)
    Cchannel = ctypes.c_ushort(channel)
    result = (ctypes.c_uint * N)()

    ret = CReadHistogramMod(result, ctypes.c_uint(N), Cmodule, Cchannel)
    if ret == 0:
        log.debug("Read Hist from Mod Success!")

    else:
        log.error("got an error in ReadHistogramFromModule")

    return np.ctypeslib.as_array(result)


# Pixie16EndRun
end_run_prototype = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_ushort)

Cend_run = end_run_prototype(("Pixie16EndRun", PixieAppDLL))


def EndRun(ModNum):
    """Uses the XIA library to end the current measurement run.

    ModNum:     set to module you want to end.
    """
    # convert to ctypes for library call
    CModNum = ctypes.c_ushort(ModNum)

    ret = Cend_run(CModNum)

    if ret == 0:
        log.debug("End run Success!")
    else:
        log.error("got an error in EndRun")
        log.error("ret=", ret)

    return ret


# ProgramFippi
program_fippi_prototype = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

Cprogram_fippi = program_fippi_prototype(("Pixie16ProgramFippi", PixieAppDLL))


def ProgramFippi(modnum):
    """Uses the XIA library to update settings

    modnum    the module that will be updated. The new setting already
              needs to be set. This just activates it.

    """
    Cmod = ctypes.c_uint(modnum)

    ret = Cprogram_fippi(Cmod)

    if ret == 0:
        log.debug(f"Programmed Fippi for module {modnum}!")
    else:
        log.error(f"Could not program Fippi for module {modnum}")
        errors = {
            -1: ["Could not program the fippi", "?"],
            -2: ["Programming fippi timed out", "?"],
        }
        message, solution = errors[ret]
        log.error(message, "Try:", solution)

    return ret


# SetDACS (voltage offsets)
program_SetDACs_prototype = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

Cprogram_SetDACs = program_SetDACs_prototype(("Pixie16SetDACs", PixieAppDLL))


def ProgramSetDACs(modnum):
    """Uses the XIA library to update voltage offsets from the current setting

    modnum    the module that will be updated. The new setting already
              needs to be set. This just activates it.

    """
    Cmod = ctypes.c_uint(modnum)

    ret = Cprogram_SetDACs(Cmod)

    if ret == 0:
        log.debug(f"Programmed DACs for module {modnum}!")
    else:
        log.error(f"Could not program DACs for module {modnum}")
        errors = {
            -1: ["Failed to start SET_DACs run", "?"],
            -2: ["SET_DACs run timed out", "?"],
        }
        message, solution = errors[ret]
        log.error(message, "Try:", solution)

    return ret


# Pixie16SaveDSPParametersToFile
save_dsp_param_prototype = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_char_p)

Csave_dsp_param = save_dsp_param_prototype(
    ("Pixie16SaveDSPParametersToFile", PixieAppDLL)
)


def SaveParam(newfilename):
    """Uses the XIA library to save the current DSP parameters to a file.

    Filename:     DSP parameter file name (with complete path)
    """
    Cfilename = ctypes.c_char_p(bytes(newfilename, "utf8"))

    ret = Csave_dsp_param(Cfilename)

    if ret == 0:
        log.debug("Save Parameters Success!")
    else:
        log.error("Error in Saveparam")
        errors = {
            -1: [
                "Failed to read DSP parameter values from the Pixie-16 modules",
                "Reboot the modules",
            ],
            -2: [
                "Failed to open the DSP parameters file",
                "Correct the DSP parameters file name",
            ],
        }
        message, solution = errors[ret]
        log.error(message, "Try:", solution)

    return ret


################################
# pixie sys functions          #
################################

# read/write setting in pixie directly
pixie_DSP_memory_io_prototype = ctypes.CFUNCTYPE(
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

    if not type(setting) == np.ndarray:
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
                f"Error: {name} cannot be larger than 16! value {value} channel {channel} module {module}"
            )
        if value == 0 and name == "Log2Ebin":
            raise ValueError(
                f"Error: {name} cannot be 0! value {value} channel {channel} module {module}"
            )
    elif name == "FastThresh":
        if value > 65534:
            raise ValueError(
                f"Error: {name} must be smaller than 65535! value {value} channel {channel} module {module}"
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
                        f"change_setting: wrong number of arguments for setting {name}.",
                        f" Need {length}, got {len(value)}",
                    )
                    return
            except TypeError:
                log.error(
                    f"change_setting: wrong type of argument. Need a list of values for {name}, got {value}."
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

    start, length = variables.settings[name]
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
        #        'pileup-only' (only record trace, timestamp, etc for pileup events, no single events)
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

    The dictionary must also contain an entry called 'channels' that list all
    channels that should be set. Channels should be pairs in the form [module, channel].

    This function will also set variabels that depend on other variables (e.g. PeakSample depends on SlowLength).
    However, if PeakSample is given, those values will be used.

    The values in the dictonary depends on the type of variable:
        a) Channel parameter
           The value needs to be either a list of the same name as the number of channels
           or smaller lists are checked to see if they match the list of modules, in
           which case each number will be used to set all channels in the module, or
           a single number in which case this number will be used for all channels in
           all modules
        b) module parameter
           The value needs to be either a single number in case a single module is used
           or a list of numbers that has the same length as the number of modules used.
           For some parameters, e.g. TrigConfig the value needs to be a list (number of
           modules) of lists (4 entries for TrigConfig)

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
                        f"Wrong type (or length) for channel parameter {name} in change_settings_dict, values: {settings[name]}"
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
                        f"Wrong type (or length) for channel parameter {name} in change_settings_dict, values: {settings[name]}"
                    )
            elif isinstance(settings[name], int):
                value = settings[name]
                for mod in modules:
                    for ch in range(16):
                        change_setting_in_memory(current[mod], name, value, ch, mod)
            else:
                raise TypeError(
                    "Wrong type (or length) for channel parameter in change_settings_dict"
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
Pixie_Read_ExtFIFOStatus_prototype = ctypes.CFUNCTYPE(
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


Pixie_ExtFIFO_Read_prototype = ctypes.CFUNCTYPE(
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
    else:
        log.error("got an error in ReadFIFO")

    return np.ctypeslib.as_array(Cdata)


##############################################
# create an interface that feels pythonic    #
##############################################


def list_firmware():
    print(f"The config file used is: {inifile}")
    print("The following firmware definitions exists")
    names = []
    for section in config.sections():
        if not section.startswith("Firmware."):
            continue
        print(f"{section}")
        names.append(section[9:])
        for key in config[section].keys():
            print(f"   {key} = {config[section][key]}")
    print(
        f'Use only the name after the "." for the name of the firmware: {", ".join(names)}'
    )


def set_traces(module, channel, status):
    """Turn on/off taking traces for a certain channel in a specific module"""

    channel_setting = ReadChanParam("CHANNEL_CSRA", module, channel)
    # we need to set bit eight
    # in python we can address the last element as -1, which is bit 0, so bit 8 is -9
    channel_setting[-9] = status
    WriteChanParam("CHANNEL_CSRA", channel_setting, module, channel)


def read_list_mode_fifo(check=True, threshold=1024):
    """Reads data from pixies FIFO across all modules defined in pixie16.control.modules

    Parameters
    ----------

    check : bool
        If True, check first if there is enough data (<1kb) that should be read.
        Otherwise always read all data.

    Returns
    -------

    output : list
        List with data as a numpy array of 32 bit unsigned integers for each module.
    """

    if check:
        do_read = False
        for i, slot in enumerate(modules):
            number_of_words = ReadFIFOStatus(i)
            if number_of_words > threshold:
                do_read = True
                break
    else:
        do_read = True

    output = []
    if do_read:
        for i, slot in enumerate(modules):
            number_of_words = ReadFIFOStatus(i)
            if number_of_words > 0:
                data = ReadFIFO(i, number_of_words)
            else:
                data = None
            output.append(data)

    return output


def run_list_mode(filename=None, runtime=5):
    """Run the pixie16 in list mode

    Start and stop a list mode run. The module needs to be
    initialized.  Data will be written to a file. If the filename
    doesn't end with '.bin' the ending will be added. We use the same
    dataformat as the pixie uses internally.  We also add a '000' or
    higher number before the '.bin' file ending automatically to avoid
    overiding an existing file.  The file gets placed in a the
    directory specified in the config file and within that directory
    in a subdirectory of the form YYYY-MM-DD, which gets created if it
    doesn't exist.


    Parameters
    ----------

    filename :
       the filename
    runtime :
       The time to take data for in seconds

    """

    YYYYMMDD = datetime.datetime.today().strftime("%Y-%m-%d")
    if filename is None:
        filename = "pixie16-data"

    # remove .bin, will add it back in a bit
    if filename.endswith(".bin"):
        filename = filename[:-4]
    # check if filename has 3 digits at the end
    number = filename[-3:]
    try:
        number = int(number) + 1
    except ValueError:
        number = 0
    if number > 999:
        print("list-mode-data: filenumber too large. Use a new filename....existing!")
        sys.exit()

    filename = f"{filename[-3:]}{number:03d}.bin"

    if not filename.startswith(YYYYMMDD):
        filename = f"{YYYYMMDD}-{filename}"
    # add correct directory
    filename = data_dir / YYYYMMDD / filename
    # make sure directory exists
    filename.parent.mkdir(parents=True, exist_ok=True)

    if filename.exists():
        print(f"filename {filename} already exists...exiting")
        return

    with filename.open("wb") as outfile:
        start_listmode_run()
        start = time.time()
        stop = start + runtime

        while time.time() < stop:
            tic = time.time()
            data = read_list_mode_fifo()
            for d in data:
                d.newbyteorder("S").tofile(outfile)
            toc = time.time()
            print(f" elapsed time  {toc-tic:.6f}")

        for i, slot in enumerate(modules):
            EndRun(i)
        time.sleep(0.4)

        # read final data
        data = read_list_mode_fifo(check=False)
        for d in data:
            d.newbyteorder("S").tofile(outfile)
