"""Interface to C-libary function provided by XIA in app DLL.

Currently calling the XIA C-library functions is only supported on Windows.

This file provides python function that directly call functions in the
app.dll libarary using ctypes.

List of C-functions and their python equivalent:

* Pixie16ReadHistogramFromFile   -> ReadHistogramFromFile
* Pixie16GetModuleEvents         -> GetModuleEvents
* Pixie16GetEventsInfo           -> GetEventsInfo
* Pixie16ReadListModeTrace       -> ReadListModeTrace
* Pixie16InitSystem              -> InitSys
* Pixie16BootModule              -> BootModule
* Pixie16ExitSystem              -> ExitSys
* Pixie16WriteSglChanPar         -> WriteChanParam
* Pixie16ReadSglChanPar          -> ReadChanParam
* Pixie16WriteSglModPar          -> WriteModParam
* Pixie16ReadSglModPar           -> ReadModParam
* Pixie16StartHistogramRun       -> start_histogram_run
* Pixie16StartListModeRun        -> start_listmode_run
* Pixie16CheckRunStatus          -> CheckRunStatus
* Pixie16ReadHistogramFromModule -> ReadHistogramFromModule
* Pixie16EndRun                  -> EndRun
* Pixie16ProgramFippi            -> ProgramFippi
* Pixie16SetDACs                 -> ProgramSetDACs
* Pixie16SaveDSPParametersToFile -> SaveParam

List of helper functions:

* ReadHistogramFromFileAll
* set_channel_parameter
* converter_IEEE754_to_ulong
* converter_ulong_to_IEEE754
* set_module_parameter
* set_run_time

"""

__all__ = [
    "ReadHistogramFromFile",
    "GetModuleEvents",
    "GetEventsInfo",
    "ReadListModeTrace",
    "InitSys",
    "BootModule",
    "ExitSys",
    "WriteChanParam",
    "ReadChanParam",
    "WriteModParam",
    "ReadModParam",
    "start_histogram_run",
    "start_listmode_run",
    "CheckRunStatus",
    "ReadHistogramFromModule",
    "EndRun",
    "ProgramFippi",
    "ProgramSetDACs",
    "SaveParam",
    "ReadHistogramFromFileAll",
    "set_channel_parameter",
    "converter_IEEE754_to_ulong",
    "converter_ulong_to_IEEE754",
    "set_module_parameter",
    "set_run_time",
]

from collections import namedtuple
import ctypes
import logging
from pathlib import Path
import sys
from unittest.mock import MagicMock

import numpy as np

from .config import (
    lib_app,
    config,
    config_get_parameters,
    firmware_com,
    firmware_sp,
    firmware_dsp_code,
    firmware_dsp_var,
)

# set up logging
log = logging.getLogger(__name__)

if sys.platform == "win32" and sys.maxsize < 2 ** 32:
    if not lib_app:
        print("[ERROR] no path for lib_app set.")
        sys.exit()
    current_dir = Path(".")

    # make sure pxisys.ini is available
    initfile = current_dir / "pxisys.ini"
    if not initfile.exists():
        log.error(
            f"Error: please copy the pxisys.ini file into the directory: {current_dir}"
        )
    PixieAppDLL = ctypes.cdll.LoadLibrary(str(lib_app))
    PROTO = ctypes.WINFUNCTYPE
else:
    # on all other platforms we mock the DLL calls
    # mostly so that readthedocs can still build the documentation
    PixieAppDLL = MagicMock(
        name="Need to run in 32 bit mode on Windows to use the control module"
    )
    PROTO = MagicMock(
        name="Need to run in 32 bit mode on Windows to use the control module"
    )

# some globals
init_done = False
boot_done = False

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
read_histogram_prototype = PROTO(
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
GetModuleEvents_prototype = PROTO(
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

GetEventsInfo_prototype = PROTO(
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
    """Read detailed information about events in a list mode data file.

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

ReadListModeTrace_prototype = PROTO(
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
init_sys_prototype = PROTO(
    ctypes.c_int, ctypes.c_ushort, ctypes.POINTER(ctypes.c_ushort), ctypes.c_ushort
)

Cinit_sys = init_sys_prototype(("Pixie16InitSystem", PixieAppDLL))


def InitSys(PXISlotMap=None, OfflineMode=False, modules=None, verbose=True):
    """Uses the XIA library to initialize the system.

    PXISlotMap:   array containing the slot numbers of each module
    OfflineMode:  specify to use online or offline mode

    """
    # convert to ctypes for library call
    global init_done

    if modules is None:
        modules = [2]

    if init_done:
        log.warning("Init already done")
        return 0

    # set this module wide
    if PXISlotMap is not None:
        modules = PXISlotMap

    if verbose:
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
boot_module_prototype = PROTO(
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
    modules=None,
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
    modules : list
        list of modules used (list of slot numbers)

    Returns
    -------

    Returns 0 on success, otherwise it returns the error message from the library call.

    """

    global boot_done

    if boot_done:
        log.warning("boot already done")
        return 0

    if modules is None:
        modules = [2]

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
exit_sys_prototype = PROTO(ctypes.c_int, ctypes.c_ushort)

Cexit_sys = exit_sys_prototype(("Pixie16ExitSystem", PixieAppDLL))


def ExitSys(ModNum):
    """Uses the XIA library to exit the system.

    ModNum:     set to module you want to exit.
                set to total number of modules initialized to exit all modules

    For k modules, the number is either 0,...,k-1 for individual
    modules or k for all modules.

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
                "Correct ModNum (it should not be greater than the"
                " total number of modules in the system)",
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
write_chan_param_prototype = PROTO(
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
        if isinstance(ChanParData, (list, tuple)):
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
read_chan_param_prototype = PROTO(
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
write_mod_param_prototype = PROTO(
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
read_mod_param_prototype = PROTO(
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
start_hist_run_prototype = PROTO(ctypes.c_int, ctypes.c_ushort, ctypes.c_ushort)

CStartHistRun = start_hist_run_prototype(("Pixie16StartHistogramRun", PixieAppDLL))


def start_histogram_run(module=None, resume=False, modules=None):
    """Uses the XIA library to start an MCA run in one channel in a module.

    Parameters
    ----------

    module :
         module number
         0,..., k-1 to start individual modules, k to start all modules
         None to use module wide definition of modules

    resume : bool
         Resume the run?

    modules :  list[int]
         List of slots that have modules installed, defaults to a single one in slot2

    """

    if modules is None:
        modules = [2]
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
start_listmode_run_prototype = PROTO(
    ctypes.c_int, ctypes.c_ushort, ctypes.c_ushort, ctypes.c_ushort
)

CStartListModeRun = start_listmode_run_prototype(
    ("Pixie16StartListModeRun", PixieAppDLL)
)


def start_listmode_run(module=None, resume=False, modules=None):
    """Uses the XIA library to start a list mode run in one channel in a module.

    Parameters
    ----------

    module :
         module number
         0,..., k-1 to start individual modules, k to start all modules
         None to use module wide definition of modules
    resume :
         If `False` erase histogram and statistics information
    modules : list[int]
         list of slots that have modules installed, defaults to one module in slot 2
    """

    if modules is None:
        modules = [2]
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
    elif ret == -1:
        log.error("Invalid Pixie16 module number")
    elif ret == -2:
        log.error("Invalid run mode")
    elif ret == -3:
        log.error("Failed to start list mode run! ... need to reboot")
    elif ret == -4:
        log.error("Invalid run type")
    else:
        log.error("got an unkown error in StartListModeRun")

    return ret


# Pixie16CheckRunStatus
check_run_status_prototype = PROTO(ctypes.c_int, ctypes.c_ushort)

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
read_hist_mod_prototype = PROTO(
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
end_run_prototype = PROTO(ctypes.c_int, ctypes.c_ushort)

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
program_fippi_prototype = PROTO(ctypes.c_int, ctypes.c_uint)

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
program_SetDACs_prototype = PROTO(ctypes.c_int, ctypes.c_uint)

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
save_dsp_param_prototype = PROTO(ctypes.c_int, ctypes.c_char_p)

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
