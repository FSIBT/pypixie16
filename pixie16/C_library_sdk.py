"""Interface to C-library function provided by XIA.

The interface to python is provided by the ctypes library.

Currently calling the XIA C-library functions is only supported on
Windows. Adding Linux support should be relatively straight forward
though (just changing the ctype loading of the library).

We provide access to all XIA functions and try to provide a
more pythonic interface. This include providing our own names for the
functions (mostly just removing the Pixie16 in front and converting
from CamelCase to lower case seperated by underscores).

This file only includes the functions that are in XIA's library and a
very few helper functions. We see these as more low level functions
and build our own set of python function on top of these in
`control.py` that automate several aspects, e.g. providing information
from a config file, etc. See config.py for more details. There should
be no need for the user to call any of the functions in here directly.

XIA's code can be found here:
  https://github.com/xiallc/pixie_sdk
Their document can be accessed here:
  https://docs.pixie16.xia.com/

This is based on version 3.3a2 of XIA's SDK.

Here is the list of supported functions and their names in our package:

.. list-table:: Functions
   :widths: 25 25
   :header-rows: 1

   * - SDK name
     - python name
   * - Pixie16AcquireADCTrace, Pixie16ReadSglChanADCTrace
     - acquire_adc_trace
   * - Pixie16AdjustOffsets
     - adjust_offsets
   * - Pixie16BLcutFinder
     - baseline_cut_finder
   * - Pixie16BootModule
     - boot_module
   * - Pixie16CheckExternalFIFOStatus
     - check_external_FIFO_status
   * - Pixie16CheckRunStatus
     - check_run_status
   * - Pixi16CopyDSPParameters
     - copy_DSP_parameters
   * - Pixie16EndRun
     - end_run
   * - Pixie16ExitSystem
     - exit_system
   * - Pixie16InitSystem
     - init_system
   * - Pixie16LoadDSPParametersFromFile
     - load_dsp_parameters_from_file
   * - Pixie16ReadDataFromExternalFIFO
     - read_data_from_external_FIFO
   * - Pixie16ReadHistogramFromModule
     - read_histogram_from_module
   * - Pixie16ReadModuleInfo
     - read_module_info
   * - Pixie16ReadSglChanBaselines, Pixie16AcquireBaselines
     - read_baselines
   * - Pixie16ReadSglChanPar
     - read_single_channel_parameter
   * - Pixie16ReadSglModPar
     - read_single_module_parameter
   * - Pixie16ReadStatisticsFromModule,
       Pixie16GetStatisticsSize,
       Pixie16ComputeRealTime,
       Pixie16ComputeLiveTime,
       Pixie16ComputeRawInputCount,
       Pixie16ComputeInputCountRate,
       Pixie16ComputeRawOutputCount,
       Pixie16ComputeOutputCountRate
     - read_statistics_from_module
   * - Pixie16SaveDSPParametersToFile
     - save_dsp_parameters_as_json
   * - Pixie16SetDACs
     - set_DACs
   * - Pixie16StartHistogramRun
     - start_histogram_run
   * - Pixie16StartListModeRun
     - start_list_mode_run
   * - Pixie16TauFinder
     - tau_finder
   * - Pixie16WriteSglChanPar
     - write_single_channel_parameter
   * - Pixie16WriteSglModPar
     - write_single_module_parameter

XIA's library provides several other functions that we do not expose
direclty, but use in some of our calls. For example,
`acquire_adc_trace` include the XIA call to set up the measurement.

"""

__all__ = [
    "acquire_adc_trace",
    "adjust_offsets",
    "baseline_cut_finder",
    "boot_module",
    "check_external_FIFO_status",
    "check_run_status",
    "end_run",
    "exit_system",
    "init_system",
    "load_dsp_parameters_from_file",
    "read_data_from_external_FIFO",
    "read_histogram_from_module",
    "read_module_info",
    "read_baselines",
    "read_single_channel_parameter",
    "read_single_module_parameter",
    "read_statistics_from_module",
    "save_dsp_parameters_as_json",
    "set_DACs",
    "start_histogram_run",
    "start_list_mode_run",
    "tau_finder",
    "write_single_channel_parameter",
    "write_single_module_parameter",
    "converter_IEEE754_to_ulong",
    "converter_ulong_to_IEEE754",
]

from collections.abc import Iterable
import ctypes
import logging
from pathlib import Path
import sys
from typing import Dict, List, Union, Optional
from typing import Iterable as Iterable_type
from unittest.mock import MagicMock

import numpy as np

from . import config

# set up logging
log = logging.getLogger(__name__)

SDK = None


def load_library() -> bool:
    """Loads the C-library or a MagidMock in case the library is not available.

    Returns True on success, else False.
    """
    global SDK
    try:
        SDK = ctypes.cdll.LoadLibrary(config.get_sdk())

        for func in [
            SDK.Pixie16ComputeRealTime,
            SDK.Pixie16ComputeInputCountRate,
            SDK.Pixie16ComputeLiveTime,
            SDK.Pixie16ComputeOutputCountRate,
            SDK.Pixie16ComputeProcessedEvents,
            SDK.Pixie16ComputeRawInputCount,
            SDK.Pixie16ComputeRawOutputCount,
        ]:
            func.restype = ctypes.c_double
        return True

    except:
        SDK = MagicMock(name="Mock of XIA's C-library")
        return False


valid_module_parameter_names = [
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
    "TrigConfig0",
    "TrigConfig1",
    "TrigConfig2",
    "TrigConfig3",
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
    "BASELINE_AVERAGE",
    "CHANNEL_CSRA",
    "CHANNEL_CSRB",
    "BLCUT",
    "INTEGRATOR",
    "FASTTRIGBACKLEN",
    "CFDDelay",
    "CFDScale",
    "CFDThresh",
    "QDCLen0",
    "QDCLen1",
    "QDCLen2",
    "QDCLen3",
    "QDCLen4",
    "QDCLen5",
    "QDCLen6",
    "QDCLen7",
    "ExtTrigStretch",
    "VetoStretch",
    "MultiplicityMaskL",
    "MultiplicityMaskH",
    "ExternDelayLen",
    "FtrigoutDelay",
    "ChanTrigStretch",
]


def converter_IEEE754_to_ulong(x: float) -> ctypes.c_ulong:
    """Converts a floating point number to a 32 bit integers representation."""
    a = (ctypes.c_float * 1)(x)
    b = ctypes.cast(a, ctypes.POINTER(ctypes.c_ulong))
    return b.contents


def converter_ulong_to_IEEE754(x: ctypes.c_ulong) -> float:
    """Converts a 32bit integer into a float."""
    a = (ctypes.c_ulong * 1)(x)
    b = ctypes.cast(a, ctypes.POINTER(ctypes.c_float))
    return b.contents


def check_return_code(return_code: int, function: str) -> None:
    """Checks that the API call's return code didn't return an error.

    Note
    ----
    Copied from XIA's python example.

    Parameters
    ----------
    return_code
        Value returned by XIA SDK library
    function
        Name of the function that produced the error code
    """

    if isinstance(return_code, MagicMock):
        return
    if return_code < 0:
        msg = ctypes.create_string_buffer(1024, 1024)
        SDK.PixieGetReturnCodeText(return_code, msg, 1024)

        msg = "".join(x.decode() for x in msg if x).strip()
        log.error(f"{function} failed with Error Code {return_code} : {msg}.")


def acquire_adc_trace(module: int) -> List[np.ndarray]:
    """Collects ADC traces for all 16 channels in a specific module.

    Parameters
    ----------
    module
       Module number to collect traces from

    Returns
    -------
    List[np.ndarray]
       list containing 16 traces as numpy arrays
    """
    Cmodule = ctypes.c_ushort(module)

    ret = SDK.Pixie16AcquireADCTrace(Cmodule)
    check_return_code(ret, "Pixie16AcquireADCTrace")

    traces = []
    for ch in range(16):
        Cch = ctypes.c_ushort(ch)
        trc_length = ctypes.c_uint(0)
        ret = SDK.PixieGetTraceLength(Cmodule, Cch, ctypes.byref(trc_length))
        check_return_code(ret, "PixieGetTraceLength")

        trace = (ctypes.c_ushort * trc_length.value)()
        ret = SDK.Pixie16ReadSglChanADCTrace(
            ctypes.cast(trace, ctypes.POINTER(ctypes.c_ushort * 1)),
            trc_length,
            Cmodule,
            Cch,
        )
        check_return_code(ret, "Pixie16ReadSglChanADCTrace")

        trace = np.ctypeslib.as_array(trace)

        traces.append(trace)

    return traces


def adjust_offsets(module: int) -> None:
    """Executes the adjust_offsets control task for a module.

    Parameters
    ----------
    module
       Module number to collect traces from
    """
    Cmodule = ctypes.c_ushort(module)

    ret = SDK.Pixie16AdjustOffsets(Cmodule)
    check_return_code(ret, "Pixie16AdjustOffsets")


def baseline_cut_finder(module: int, channel: int) -> None:
    """Find an appropriate baseline cuts for a channel in a module.

    Parameters
    ----------
    module
       Module number
    channel
       Channel number
    """
    Cmodule = ctypes.c_ushort(module)

    Cch = ctypes.c_ushort(channel)
    val = ctypes.c_uint32(0)
    ret = SDK.Pixie16BLcutFinder(Cmodule, Cch, ctypes.byref(val))
    check_return_code(ret, "Pixie16BLcutFinder")
    return ret


def boot_module(
    DSPParFile: Path,
    ComFPGAConfigFile: Path,
    SPFPGAConfigFile: Path,
    DSPCodeFile: Path,
    DSPVarFile: Path,
    ModNum: int,
    BootPattern: int = 0x7F,
    verbose: bool = False,
) -> None:
    """Boot the module(s).

    See page 13 of the programming manual.


    Parameters
    ----------
    ComFPGAConfigFile
         config file found under Firmware
    SPFPGAConfigFile
         config file found under Firmware
    DSPCodeFile
         config file found under DSP
    DSPParFile
         config file found under Configuration
    DSPVarFile
         config file found under DSP
    ModNum
         location of module you want to boot
         (either 0,...,k-1 for individual modules or k for all modules)
         if None, check global modules variable to boot all modules
    BootPattern
        boot pattern mask. 0x7F to boot all on-board chips.
    verbose
        print out what firmware we are using

    Returns
    -------
    bool
       return True on success and False on error
    """
    for f in [ComFPGAConfigFile, SPFPGAConfigFile, DSPCodeFile, DSPVarFile]:
        if not f.is_file():
            print(f"[Error] cannot open firmware file {f}")
            sys.exit(1)

    # config option is not used anymore, just pass an empty string
    TrigFPGAConfigFile = " "

    if verbose:
        print("Booting Pixie using the following firmware:")
        print(f"  Com      = {ComFPGAConfigFile}")
        print(f"  SP       = {SPFPGAConfigFile}")
        print(f"  DSP Code = {DSPCodeFile}")
        print(f"  DSP Var  = {DSPVarFile}")
        print(f"  Setting  = {DSPParFile}")

    # convert to ctypes for library call
    CComFPGAConfigFile = ctypes.c_char_p(bytes(ComFPGAConfigFile))
    CSPFPGAConfigFile = ctypes.c_char_p(bytes(SPFPGAConfigFile))
    # converting a string next, so we need to specify utf8
    CTrigFPGAConfigFile = ctypes.c_char_p(bytes(TrigFPGAConfigFile, "utf8"))
    CDSPCodeFile = ctypes.c_char_p(bytes(DSPCodeFile))
    CDSPParFile = ctypes.c_char_p(bytes(DSPParFile))
    CDSPVarFile = ctypes.c_char_p(bytes(DSPVarFile))
    CModNum = ctypes.c_ushort(ModNum)
    CBootPattern = ctypes.c_ushort(BootPattern)

    ret = SDK.Pixie16BootModule(
        CComFPGAConfigFile,
        CSPFPGAConfigFile,
        CTrigFPGAConfigFile,
        CDSPCodeFile,
        CDSPParFile,
        CDSPVarFile,
        CModNum,
        CBootPattern,
    )
    check_return_code(ret, "boot_module")
    if ret == 0:
        log.debug("Boot Success!")

    return


def check_external_FIFO_status(module: int) -> int:
    """Read how many 32bit words are available in the FIFO of a specific module.

    Parameters
    ----------
    module
       module number

    Returns
    -------
    int
       number of 32 bit words available
    """
    Cmodule = ctypes.c_ushort(module)
    Cwords = (ctypes.c_uint)()

    ret = SDK.Pixie16CheckExternalFIFOStatus(ctypes.byref(Cwords), Cmodule)
    check_return_code(ret, "check_external_FIFO_status")

    return Cwords.value


def check_run_status(module: int) -> bool:

    """Check the run status of a module.

    See page 17 in the manual.

    Parameters
    ----------
    module
       module number

    Returns
    -------
    bool or None
       True if run is still ongoing, False if not and None on error.
    """
    Cmodule = ctypes.c_ushort(module)

    ret = SDK.Pixie16CheckRunStatus(Cmodule)
    check_return_code(ret, "check_run_status")

    if ret == 1:
        return True
    if ret == 0:
        return False
    # ret < 0 indicates an error
    return False


def copy_DSP_parameters(
    bitmask: int,
    source_module: int,
    source_channel: int,
    destination_mask: List[List[bool]],
) -> None:
    """Copy DSP parameters from one module to other modules.

    The bit mask allows to select 13 different parameter groups that will be copied or not:

    .. list-table:: Functions
       :widths: 25 25
       :header-rows: 1

       * - Bit
         - Item
       * - 0
         - Filter (energy and trigger)
       * - 1
         - Analog signal conditioning (polarity, dc-offset, gain/attenuation)
       * - 2
         - Histogram control (minimum energy, binning factor)
       * - 3
         - Decay time
       * - 4
         - Pulse shape analysis (trace length and trace delay)
       * - 5
         - Baseline control (baseline cut, baseline percentage)
       * - 7
         - Channel CSRA register (good channel, trigger enabled, etc.)
       * - 8
         - CFD trigger (CFD delay, scaling factor)
       * - 9
         - Trigger stretch lengths (veto, external trigger, etc.)
       * - 10
         - FIFO delays (analog input delay, fast trigger output delay, etc.)
       * - 11
         - Multiplicity (bit masks, thresholds, etc.)
       * - 12
         - QDC (QDC sum lengths)

    Paramters
    ---------
    bitmask
        Bit pattern of what to copy, see above
    source_module
        The module number to copy from
    source_channel
        The source channel
    destination_mask
        List of List. For each module in the system a List of 16 True/False
        values that indicate if the settings should be copied to this module
        and this channel.
    """
    # flatten the list
    destination_mask = [ch_bit for module in destination_mask for ch_bit in module]

    CModNum = ctypes.c_ushort(source_module)
    CChannel = ctypes.c_ushort(source_channel)
    Cbitmask = ctypes.c_ushort(bitmask)
    CDestinationMask = (ctypes.c_ushort * len(destination_mask))()
    for i, value in enumerate(destination_mask):
        CDestinationMask[i] = value

    ret = SDK.Pixie16CopyDSPParameters(Cbitmask, CModNum, CChannel, CDestinationMask)
    check_return_code(ret, "copy_DSP_parameters")


def end_run(module: int) -> None:
    """End the current measurement run in a specific module.

    Parameters
    ----------
    module
       module number
    """
    CModNum = ctypes.c_ushort(module)

    ret = SDK.Pixie16EndRun(CModNum)
    check_return_code(ret, "end_run")


def exit_system(module: int) -> None:
    """Release resources used by the modules before exiting the application.

    For k modules, the number is either 0,...,k-1 for individual
    modules or k for all modules.

    Parameters
    ----------
    module
       module number
    """
    CModNum = ctypes.c_ushort(module)

    ret = SDK.Pixie16ExitSystem(CModNum)
    check_return_code(ret, "exit_system")

    if ret == 0:
        log.debug("Exit system Success!")


def init_system(
    modules: Optional[List[int]] = None,
    offline_mode: bool = False,
    verbose: bool = True,
) -> None:
    """Initialize the system.

    Parameters
    ----------
    modules
       array containing the slot numbers of each module
    offline_mode
       specify to use online or offline mode
    verbose
       if True, print more output

    Returns
    -------
    bool
       returns True if system initialized or False otherwise
    """
    if modules is None:
        modules = [2]

    if verbose:
        print(f"[INFO] Using modules in slot(s) {' '.join([str(x) for x in modules])}.")

    NumModules = len(modules)
    CNumModules = ctypes.c_ushort(NumModules)
    CPXISlotMap = (ctypes.c_ushort * (NumModules))()
    for i, slot in enumerate(modules):
        CPXISlotMap[i] = ctypes.c_ushort(slot)
    COfflineMode = ctypes.c_ushort(offline_mode)
    ret = SDK.Pixie16InitSystem(CNumModules, CPXISlotMap, COfflineMode)
    check_return_code(ret, "init_system")

    if ret == 0:
        log.debug("Initialize Success!")

    return


def load_dsp_parameters_from_file(filename: Path) -> None:
    """Read the DSP parameter from either an old .set file or a json file.

    Parameters
    ----------
    filename
       DSP parameter file (either old .set or new .json)
    """
    if not filename.exists():
        log.error(f"Setting file {filename} does not exist.")
        return
    if filename.suffix not in [".set", ".json"]:
        log.error(f"Setting file {filename} needs to be either .set or .json.")
        return

    Cfilename = ctypes.c_char_p(bytes(str(filename.absolute()), "utf8"))

    ret = SDK.Pixie16LoadDSPParametersFromFile(Cfilename)
    check_return_code(ret, "load_dsp_parameters_from_file")


def read_data_from_external_FIFO(module: int, words: int) -> np.ndarray:
    """Read data in 32bit words from module N.

    Parameters
    ----------
    module
        module number
    words
        number of words to read

    Returns
    -------
    np.ndarray
         numpy array of 32 bit words (unsigned integers 32bit)
    """
    Cmodule = ctypes.c_ushort(module)
    Cwords = ctypes.c_uint(words)
    Cdata = (ctypes.c_uint * words)()

    ret = SDK.Pixie16ReadDataFromExternalFIFO(Cdata, Cwords, Cmodule)
    check_return_code(ret, "read_data_from_external_FIFO")

    return np.ctypeslib.as_array(Cdata)


def read_histogram_from_module(module: int, channel: int, N: int = 32768) -> np.ndarray:
    """Read a single channel histogram from the module.

    Parameters
    ----------
    module
       module number
    channel
       channel in module
    N
       number of bins in the histogram, by default 32768

    Returns
    -------
    np.ndarray
       1D-numpy array with the histogram data
    """
    Cmodule = ctypes.c_ushort(module)
    Cchannel = ctypes.c_ushort(channel)
    result = (ctypes.c_uint * N)()
    N = ctypes.c_uint(N)

    ret = SDK.Pixie16ReadHistogramFromModule(result, N, Cmodule, Cchannel)
    check_return_code(ret, "read_histogram_from_module")

    return np.ctypeslib.as_array(result)


def read_module_info(module: int) -> Dict:
    """Read the module information.

    Parameters
    ----------
    module
       The module number

    Results
    -------
    dict
       dictionary with serial number, revision and other information
    """
    Cmodule = ctypes.c_ushort(module)

    rev = ctypes.c_ushort()
    sn = ctypes.c_uint()
    adc_bits = ctypes.c_ushort()
    adc_msps = ctypes.c_ushort()
    num_channels = ctypes.c_ushort()

    ret = SDK.Pixie16ReadModuleInfo(
        Cmodule,
        ctypes.byref(rev),
        ctypes.byref(sn),
        ctypes.byref(adc_bits),
        ctypes.byref(adc_msps),
        ctypes.byref(num_channels),
    )
    check_return_code(ret, "read_module_info")

    return {
        "module": module,
        "serial number": sn.value,
        "rev": rev.value,
        "adc_bits": adc_bits.value,
        "adc_msps": adc_msps.value,
        "num_channels": num_channels.value,
    }


def read_baselines(module: int) -> List[List[np.ndarray]]:
    """Acquire and read back baselines for all channels in a module.

    Parameters
    ----------
    module
       The module number

    Returns
    -------
    List[np.ndarray]
       Baselines for each channels in the module
    """
    Cmodule = ctypes.c_ushort(module)

    ret = SDK.Pixie16AcquireBaselines(Cmodule)
    check_return_code(ret, "Pixie16AcquireBaselines")

    baselines = []
    timestamps = []
    max_num_baselines = 3640

    Cmax_num_baselines = ctypes.c_ushort(max_num_baselines)

    for ch in range(16):
        Cch = ctypes.c_ushort(ch)
        bl = (ctypes.c_double * max_num_baselines)()
        ts = (ctypes.c_double * max_num_baselines)()

        ret = SDK.Pixie16ReadSglChanBaselines(
            ctypes.cast(bl, ctypes.POINTER(ctypes.c_double * 1)),
            ctypes.cast(ts, ctypes.POINTER(ctypes.c_double * 1)),
            Cmax_num_baselines,
            Cmodule,
            Cch,
        )
        check_return_code(ret, "Pixie16ReadSglChanBaselines")

        bl = np.ctypeslib.as_array(bl)
        ts = np.ctypeslib.as_array(ts)

        baselines.append(bl)
        timestamps.append(ts)
    return [baselines, timestamps]


def read_single_channel_parameter(
    channel_parameter_name: str,
    module: int,
    channel: int,
    convert_bit_pattern: bool = True,
) -> Union[List[bool], float]:
    """Read a parameter in one channel in a module.

    See pg. 51 of the programmers manual for a list of parameters available.

    Parameters
    ----------
    channel_parameter_name
        parameter name
    module
        module number
    channel
        channel number

    Returns
    -------
    float or List[bools]
        Returns the value as floating number or for bitmasks as list of bools
    """

    assert (
        channel_parameter_name in valid_channel_parameter_names
    ), "Not a valid channel parameter name"

    # only convert certain settings to an array of bits (if requested)
    if convert_bit_pattern and channel_parameter_name not in [
        "CHANNEL_CSRA",
        "CHANNEL_CSRB",
        "MultiplicityMaskL",
        "MultiplicityMaskH",
    ]:
        convert_bit_pattern = False

    # convert to ctypes for library call
    CChanParName = ctypes.c_char_p(bytes(channel_parameter_name, "utf8"))
    Cmodule = ctypes.c_ushort(module)
    Cchannel = ctypes.c_ushort(channel)
    CChanParData = (ctypes.c_double)()

    ret = SDK.Pixie16ReadSglChanPar(
        CChanParName, ctypes.byref(CChanParData), Cmodule, Cchannel
    )
    check_return_code(ret, "read_single_channel_parameter")

    if convert_bit_pattern:
        value = np.ctypeslib.as_array(CChanParData)
        value = f"{int(value):032b}"
        value = [bool(int(x)) for x in value]
        return value

    return np.ctypeslib.as_array(CChanParData)


def read_single_module_parameter(
    module_parameter_name: str, module: int, convert_bit_pattern: Optional[bool] = False
) -> Union[int, float, List[bool]]:
    """Read a parameter in one module.

    See pg. 53 of the programmers manual for a list of parameters available.

    Parameters
    ----------
    module_parameter_name
        parameter name
    module
        module number

    Returns
    -------
    int or float
        The value of the parameter
    """
    assert (
        module_parameter_name in valid_module_parameter_names
    ), "Wrong  parameter name"

    # only convert certain settings to an array of bits (if requested)
    if convert_bit_pattern and module_parameter_name not in [
        "MODULE_CSRA",
        "MODULE_CSRB",
        "FastTrigBackplaneEna",
        "TrigConfig0",
        "TrigConfig1",
        "TrigConfig2",
        "TrigConfig3",
    ]:
        convert_bit_pattern = False

    # which parameters do we need to convert to float?
    parameter_list_convert_to_IEEE = ["HOST_RT_PRESET"]

    # convert to ctypes for library call
    CModParName = ctypes.c_char_p(bytes(module_parameter_name, "utf8"))
    Cmodule = ctypes.c_ushort(module)
    CModParData = (ctypes.c_uint)()

    ret = SDK.Pixie16ReadSglModPar(CModParName, ctypes.byref(CModParData), Cmodule)
    check_return_code(ret, "read_single_module_parameter")

    if convert_bit_pattern:
        value = np.ctypeslib.as_array(CModParData)
        value = f"{int(value):032b}"
        value = [bool(int(x)) for x in value]
        return value

    if module_parameter_name in parameter_list_convert_to_IEEE:
        return np.ctypeslib.as_array(converter_ulong_to_IEEE754(CModParData))

    return np.ctypeslib.as_array(CModParData)


def read_statistics_from_module(module: int) -> Dict:
    """Read statistics from a module.

    Parameters
    ----------
    module
       module number

    Returns
    -------
    dict
       Return stats for one module
    """
    Cmodule = ctypes.c_ushort(module)

    bin_stats = (ctypes.c_uint * SDK.Pixie16GetStatisticsSize())()
    ret = SDK.Pixie16ReadStatisticsFromModule(
        ctypes.cast(bin_stats, ctypes.POINTER(ctypes.c_uint * 1)), Cmodule
    )
    check_return_code(ret, "read_statistics_from_module")

    stats_labels = (
        "real_time",
        "live_time",
        "input_counts",
        "input_count_rate",
        "output_counts",
        "output_count_rate",
    )

    stats = [[0] * 16 for x in range(len(stats_labels))]

    for ch in range(16):
        stats[0][ch] = SDK.Pixie16ComputeRealTime(bin_stats, Cmodule)
        stats[1][ch] = SDK.Pixie16ComputeLiveTime(bin_stats, Cmodule, ch)
        stats[2][ch] = SDK.Pixie16ComputeRawInputCount(bin_stats, Cmodule, ch)
        stats[3][ch] = SDK.Pixie16ComputeInputCountRate(bin_stats, Cmodule, ch)
        stats[4][ch] = SDK.Pixie16ComputeRawOutputCount(bin_stats, Cmodule, ch)
        stats[5][ch] = SDK.Pixie16ComputeOutputCountRate(bin_stats, Cmodule, ch)
        logging.info(
            {
                "module": module,
                "channel": ch,
                "real_time": stats[0][ch],
                "live_time": stats[1][ch],
                "input_counts": stats[2][ch],
                "input_count_rate": stats[3][ch],
                "output_counts": stats[4][ch],
                "output_count_rate": stats[5][ch],
            }
        )
    out = {
        "module": module,
        "real_time": stats[0],
        "live_time": stats[1],
        "input_counts": stats[2],
        "input_count_rate": stats[3],
        "output_counts": stats[4],
        "output_count_rate": stats[5],
    }

    return out


def save_dsp_parameters_as_json(filename: Path) -> None:
    """Save the current DSP parameters to a file.

    Uses the new json style.

    Parameters
    ----------
    Filename
        DSP parameter file name (with complete path)
    """
    if not filename.suffix == ".json":
        log.error("Filename does not end in .json for saving settings")
        return
    Cfilename = ctypes.c_char_p(bytes(str(filename.absolute()), "utf8"))

    ret = SDK.Pixie16SaveDSPParametersToFile(Cfilename)
    check_return_code(ret, "save_dsp_parameters_as_json")


def set_DACs(module: int) -> None:
    """Update voltage offsets from the current setting

    The new setting already needs to be set. This just activates it.

    Parameters
    ----------
    module
        the module that will be updated
    """
    Cmod = ctypes.c_ushort(module)

    ret = SDK.Pixie16SetDACs(Cmod)
    check_return_code(ret, "set_DACs")


def start_histogram_run(module: int, resume: bool = False) -> None:
    """Start an MCA run in a module.

    Parameters
    ----------
    module
         module number
         0,..., k-1 to start individual modules, k to start all modules
    resume
         Resume the run or clear old histograms
    """
    Cmodule = ctypes.c_ushort(module)
    Cmode = ctypes.c_ushort(not resume)  # 1 = start new run, 0 = resume old

    ret = SDK.Pixie16StartHistogramRun(Cmodule, Cmode)
    check_return_code(ret, "start_histogram_run")


def start_list_mode_run(module: int, resume: bool = False) -> None:
    """Start a list mode run in one channel in a module.

    Parameters
    ----------
    module
         module number
         0,..., k-1 to start individual modules, k to start all modules
    resume
         If `False` erase histogram and statistics information
    """
    Cmodule = ctypes.c_ushort(module)
    CrunType = ctypes.c_ushort(0x100)
    Cmode = ctypes.c_ushort(not resume)  # 1 = start new run, 0 = resume old

    ret = SDK.Pixie16StartListModeRun(Cmodule, CrunType, Cmode)
    check_return_code(ret, "start_list_mode_run")


def tau_finder(module: int) -> np.ndarray:
    """Find the decay constants.

    Parameters
    ----------
    module
       module number

    Returns
    -------
    np.ndarray
       The values of the decay constant for each channel, -1 if no tau has been found
    """
    Cmodule = ctypes.c_ushort(module)
    Ctaus = (ctypes.c_double * 16)()

    ret = SDK.Pixie16TauFinder(
        Cmodule,
        ctypes.cast(Ctaus, ctypes.POINTER(ctypes.c_double * 1)),
    )
    check_return_code(ret, "tau_finder")

    return np.ctypeslib.as_array(Ctaus)


def write_single_channel_parameter(
    channel_parameter_name: str,
    channel_parameter_data: Union[int, float, Iterable_type[bool]],
    module: int,
    channel: int,
) -> None:
    """Change a parameter in one channel in a module.

    See pg. 67 of the programmers manual for a list of parameters available.

    Parameters
    ----------
    channel_parameter_name
        parameter name
    channel_parameter_data
        value of the parameter you wish to set
    module
        module number
    channel
        channel number
    """
    assert (
        channel_parameter_name in valid_channel_parameter_names
    ), f"Not a valid channel parameter name. Given value {channel_parameter_name}"

    if channel_parameter_name in [
        "CHANNEL_CSRA",
        "CHANNEL_CSRB",
        "MultiplicityMaskL",
        "MultiplicityMaskH",
    ]:
        if isinstance(channel_parameter_data, (list, tuple)):
            data = [str(int(x)) for x in channel_parameter_data]
            channel_parameter_data = int("".join(data), 2)

    # We encountered a bug when setting coincidence windows to 10ns, so we check here and print a warning
    if channel_parameter_name == "FASTTRIGBACKLEN":
        if channel_parameter_data == 0.01:
            print(
                f"[red]CRITICAL[/] :boom: :boom: :boom:The coincidence window for mod={module}:ch={channel} was set to 10 ns. "
                f"This could lead to data loss. :boom: :boom: :boom:"
            )

    # convert to ctypes for library call
    CChanParName = ctypes.c_char_p(bytes(channel_parameter_name, "utf8"))
    CChanParData = ctypes.c_double(channel_parameter_data)
    Cmodule = ctypes.c_ushort(module)
    Cchannel = ctypes.c_ushort(channel)

    ret = SDK.Pixie16WriteSglChanPar(CChanParName, CChanParData, Cmodule, Cchannel)
    check_return_code(ret, "write_single_channel_parameter")
    if ret < 0:
        print(
            f"   Problem in mod={module} ch={channel} name={channel_parameter_name} value={channel_parameter_data}"
        )


def write_single_module_parameter(
    module_parameter_name: str,
    module_parameter_data: Union[int, float, List[bool]],
    module: int,
) -> None:
    """Change a parameter in one module.

    See pg. 69 of the programmers manual for a list of parameters available.

    Parameters
    ----------
    module_parameter_name
        parameter name
    module_parameter_data
        value of the parameter you wish to set
    module
        module number
    """

    assert (
        module_parameter_name in valid_module_parameter_names
    ), f"Module parameter name is invalid. Given module parameter name: {module_parameter_name}"
    assert isinstance(module_parameter_data, (int, float)) or all(
        isinstance(x, bool) for x in module_parameter_data
    ), f"Module parameter '{module_parameter_name}' not an integer or float. Given value is {module_parameter_data}"
    # which parameters do we need to convert from float?
    parameter_list_convert_from_IEEE = ["HOST_RT_PRESET"]

    if module_parameter_name in [
        "MODULE_CSRA",
        "MODULE_CSRB",
    ]:
        if isinstance(module_parameter_data, Iterable):
            data = [str(int(x)) for x in module_parameter_data]
            module_parameter_data = int("".join(data), 2)

    # convert to ctypes for library call
    CModParName = ctypes.c_char_p(bytes(module_parameter_name, "utf8"))
    if module_parameter_name in parameter_list_convert_from_IEEE:
        CModParData = converter_IEEE754_to_ulong(module_parameter_data)
    else:
        CModParData = ctypes.c_uint(module_parameter_data)
    Cmodule = ctypes.c_ushort(module)

    ret = SDK.Pixie16WriteSglModPar(CModParName, CModParData, Cmodule)
    check_return_code(ret, "write_single_module_parameter")
    if ret != 0:
        print(
            f" write_single_module_parameter error for {module_parameter_name=} {module_parameter_data=} {module=}"
        )
