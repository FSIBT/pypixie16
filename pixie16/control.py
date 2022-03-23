"""Python interface to controlling the pixie16.

Based on XIA's C-library from their SDK, we try to provide a more
pythonic interface, make use of a config file to store different
configurations, and supply addtional functionality.

The config file (which is a requirement) stores some of the parameter
for booting the pixie as well as the main output directory. Therefore,
our boot and init commands take less parameters then their SDK version.

Once the `init_system` function was called, we also cache the list of
modules. We then provide functions that don't need the addtional input
of curent modules.

We provide some functions to modify channel and module parameters
directly on the pixie, as well as, setting the run time and sync mode
or enabling taking traces. Furthermore, there we provide function to
start/stop acquisition and get information on all modules and save
this to a json file.

We also provide our own mechanism of changing settings by providing a
dictionary with name of the settings as key in the dictioinary and the
settings value only provided for the channels in use. Since the
pixie16 provides many settings by manipulating bits in a 32bit
integer, we provide functions that help with this and one can access
bits by name (inspired by the names in the manual).  We also provide
the option to overwrite some of the calculated values such as
`PAFlength` or have them calculated automatically.

At the moment pypixie16 only supports Windows, but other platforms
should be easy to add.

"""
from contextlib import contextmanager
from collections import OrderedDict
import datetime
import json
import logging
from pathlib import Path
import sys
import tempfile
import time
from typing import Iterable, List, Tuple, Dict, Union, Optional, ByteString

import numpy as np
from rich.progress import Progress

from . import config
from . import C_library_sdk as SDK
from . import variables
from .read import Settings, Stats

# set up logging
log = logging.getLogger(__name__)

module_list: List[int] = [2]  # default setting, overwritten by init_and_boot

SETTINGS = variables.settings
SETTINGS_NAME_CHANNEL = []
SETTINGS_NAME_MODULE = []
for setting_name, (startpos, length) in SETTINGS.items():
    if length == 16:
        SETTINGS_NAME_CHANNEL.append(setting_name)
    else:
        SETTINGS_NAME_MODULE.append(setting_name)


def init(modules: List[int], offline_mode: bool = False, verbose: bool = False) -> None:
    """Initialize the system.

    Calls init_system in the XIA library and saves the list of modules, so that we can use it as a default in later XIA library calls.

    Parameters
    ----------
    modules
        list of modules (slot numbers, e.g. [2,3])
    offline_mode
        Run with the pixie present or not
    verbose
        print some extra information
    """
    global module_list
    module_list = modules
    SDK.init_system(module_list, offline_mode, verbose)


def boot(
    section_name: Optional[str] = "default",
    modules: Optional[List[int]] = None,
    boot_pattern: int = 0x7F,
    verbose: bool = False,
) -> None:
    """Boot modules with boot_pattern.

    Parameters
    ----------
    section_name
        name for Firmware section in config file that defines the FPGA code, etc that should be used.
    modules
        Boot certain modules (module list given in positions, i.e. not slots), if `None` use modules defined in `init` call.
    boot_pattern
        Bit pattern defining what gets booted.
    verbose
        Print some extra information if True
    """
    FPGAcom, FPGAsp, dsp_code, dsp_var, setting = config.load_config(section_name)

    if modules:
        for m in modules:
            SDK.boot_module(
                setting, FPGAcom, FPGAsp, dsp_code, dsp_var, m, boot_pattern, verbose
            )
    else:
        SDK.boot_module(
            setting,
            FPGAcom,
            FPGAsp,
            dsp_code,
            dsp_var,
            len(module_list),
            boot_pattern,
            verbose,
        )


def init_and_boot(
    offline_mode: bool = False,
    section_name: Optional[str] = "default",
    modules: Optional[List[int]] = None,
    boot_pattern: int = 0x7F,
    verbose: bool = False,
) -> None:
    """Init and boot in one function call.

    Parameters
    ----------
    modules
        list of modules (slot numbers, e.g. [2,3])
    offline_mode
        Run with the pixie present or not
    section_name
        name for Firmware section in config file that defines the FPGA code, etc that should be used.
    boot_pattern
        Bit pattern defining what gets booted.
    verbose
        Print some extra information if True
    """
    init(modules, offline_mode, verbose)
    boot(section_name, boot_pattern=boot_pattern, verbose=verbose)


def adjust_offsets(modules: Optional[Iterable[int]] = None) -> None:
    """Adjust offsets for all channels in the list of module".

    Parameters
    ----------
    modules
        Iterable of slots with modules (e.g. [2, 3]), uses modules defined in init call otherwise
    """
    if modules is None:
        modules = module_list

    for m, _ in enumerate(modules):
        SDK.adjust_offsets(m)


def set_sync_mode(modules: Optional[Iterable[int]] = None) -> None:
    """Turn on sync mode for every module.

    Parameters
    ----------
    modules
        Iterable of slots with modules (e.g. [2, 3]), uses modules defined in init call otherwise
    """
    if modules is None:
        modules = module_list

    for m, _ in enumerate(modules):
        SDK.write_single_module_parameter("SYNCH_WAIT", 1, m)
        SDK.write_single_module_parameter("IN_SYNCH", 0, m)


def set_channel_parameter(name: str, value, module: int, channel: int):
    """Set and read back a parameter for a channel on the pixie16.

    Parameters
    ----------
    name
        The name of the parameter
    value
        The new value
    module
        The module number
    channel
        The channel number

    Returns
    -------
        The new setting
    """
    SDK.write_single_channel_parameter(name, value, module, channel)
    return SDK.read_single_channel_parameter(
        name, module, channel, convert_bit_pattern=False
    )


def set_module_parameter(name: str, value, module: int):
    """Set and read back a parameter for a module on the pixie16.

    Parameters
    ----------
    name
        The setting name
    value
        The new settings value
    module
        The module number (starting with 0)

    Returns
    -------
        The new setting
    """
    SDK.write_single_module_parameter(name, value, module)
    return SDK.read_single_module_parameter(name, module)


def set_run_time(runtime, module):
    """Sets the run time for the next run on the pixie16.

    Parameters
    ----------
    runtime
        time in seconds
    module
        module number starting at 0
    """
    return set_module_parameter("HOST_RT_PRESET", runtime, module)


def set_traces(module: int, channel: int, status: bool) -> None:
    """Turn on/off taking traces for a certain channel in a specific module on the pixie16.

    Parameters
    ----------
    module
        The module number (starting at 0)
    channel
        The channel number (0-15)
    status
        True: record traces, False: do not record traces
    """
    channel_setting = SDK.read_single_channel_parameter(
        "CHANNEL_CSRA", module, channel, convert_bit_pattern=True
    )
    # we need to set bit eight
    # in python we can address the last element as -1, which is bit 0, so bit 8 is -9
    channel_setting[-9] = status
    SDK.write_single_channel_parameter("CHANNEL_CSRA", channel_setting, module, channel)


def empty_fifo(module: int) -> None:
    """Read all data in a fifo of a specific module and discard it.

    Parameters
    ----------
    module
        The module number (starting at 0)
    """
    while number_of_words := SDK.check_external_FIFO_status(module):
        SDK.read_data_from_external_FIFO(module, number_of_words)


def empty_all_fifos() -> None:
    """Read data from all fifos and discard it.

    Uses the module list defined in `init`.
    """
    for m, _ in enumerate(module_list):
        empty_fifo(m)


def start_histogram_run() -> None:
    """Start a histogram run.

    Uses the module list defined during `init`.
    """
    for m, _ in enumerate(module_list):
        SDK.start_histogram_run(m)


def start_list_mode_run() -> None:
    """Start a list mode run.

    Uses the module list defined during `init`.
    """
    for m, _ in enumerate(module_list):
        SDK.start_list_mode_run(m)


def check_run_status() -> bool:
    """Checks the run status of all known modules."""

    status = True
    for m, _ in enumerate(module_list):
        status = status & SDK.check_run_status(m)
    return status


def get_stats() -> List[Stats]:
    """Get statistics for all modules."""
    return [
        Stats.from_dict(SDK.read_statistics_from_module(m))
        for m, _ in enumerate(module_list)
    ]


def save_stats_to_json(filename: Path) -> None:
    """Get statistics for all modules and save as json to file.

    Parameters
    ----------
    filename
        name to save the settings to
    """
    stats = get_stats()
    # convert to something that can be saved as json (our Stats class doesn't work)
    out = [dict(x) for x in stats]
    if filename.is_file():
        log.error(f"Filename {filename} exists. Not overwriting!!")
        return

    with filename.open("w") as f:
        json.dump(out, f)


def end_run() -> None:
    """Calls end_run on all the modules."""
    for m, _ in enumerate(module_list):
        SDK.end_run(m)


def exit_system() -> None:
    """Calls exit_system on all the modules."""
    for m, _ in enumerate(module_list):
        SDK.exit_system(m)


def read_list_mode_fifo(
    check: bool = True, threshold: int = 1024, modules: Optional[Iterable[int]] = None
) -> List[np.ndarray]:
    """Reads data from pixies FIFO across all modules defined in pixie16.control.modules

    Parameters
    ----------
    check
        If True, check first if there is enough data that should be read.
        Otherwise always read all data.
    threshold
        Minimum number of data to read when `check` is active.
    modules
        List of modules (slot numbers, e.g. [2]). Uses modules defined in `init` if None.

    Returns
    -------
    List[np.ndarray]
        List with data as a numpy array of 32 bit unsigned integers for each module.
    """
    if modules is None:
        modules = module_list

    do_read = True
    if check:
        do_read = False
        for i, _ in enumerate(modules):
            number_of_words = SDK.check_external_FIFO_status(i)
            if number_of_words > threshold:
                do_read = True
                break

    output = []
    if do_read:
        for i, _ in enumerate(modules):
            number_of_words = SDK.check_external_FIFO_status(i)
            if number_of_words > 0:
                data = SDK.read_data_from_external_FIFO(i, number_of_words)
            else:
                data = np.array([], dtype=np.uint32)
            output.append(data)

    return output


def run_list_mode(filename: Optional[str] = None, runtime: int = 5) -> None:
    """Run the pixie16 in list mode.

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
    filename
       the filename
    runtime
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
        filename = filename[:-3]
    except ValueError:
        number = 0
    if number > 999:
        print("list-mode-data: filenumber too large. Use a new filename....existing!")
        sys.exit()

    filename = f"{filename}{number:03d}.bin"

    if not filename.startswith(YYYYMMDD):
        filename = f"{YYYYMMDD}-{filename}"
    # add correct directory
    filename = config.data_dir / YYYYMMDD / filename
    # make sure directory exists
    filename.parent.mkdir(parents=True, exist_ok=True)

    if filename.exists():
        print(f"filename {filename} already exists...exiting")
        return

    with filename.open("wb") as outfile:
        start_list_mode_run()
        start = time.time()
        stop = start + runtime

        while time.time() < stop:
            data = read_list_mode_fifo()
            for d in data:
                d.newbyteorder("S").tofile(outfile)

        end_run()
        time.sleep(0.4)

        # read final data
        data = read_list_mode_fifo(check=False)
        for d in data:
            d.newbyteorder("S").tofile(outfile)


def reset_coincidence_setting(channels: Iterable[Tuple[int, int]]) -> None:
    """Reset all setting in regards to coincedence mode.

    Also, unsets capturing traces, etc.

    This is usefule before an MCA run for example to just get raw channel spectra.

    Parameters
    ----------
    channels
        List of (module, channel) tuples
    """
    settings = OrderedDict(
        {
            "channels": channels,
            "MultiplicityMaskL": 0,
            "MultiplicityMaskH": 0,
            "TrigConfig": [[0, 0, 0, 0]],
            "CaptureTrace": False,
            "CaptureHistogram": True,
            "CaptureSums": False,
            "FastTrigSelect": "group",
            "EnableModVal": False,
            "EnableChannelVal": False,
            "GroupTrigSignal": "local",
            "RejectPileup": False,
            "RejectIfFull": False,
        }
    )
    change_setting_from_dict(settings, auto_update=False)


def enable_trace_settings(
    channels: Iterable[Tuple[int, int]], disable_CFD: bool = True
) -> None:
    """Enable traces, histograms, and sums.

    Also turn CFD settings off (or optionally leave unchanged).  These
    data are useful when trying to analyze traces and optimize
    settings offline by trying out different settings values in
    software, for example, using pypixie16's binary-browser.

    Parameters
    ----------
    channels
        List of (modules, channel) tuples
    disable_CFD
        Option to disable CFD for the listed channels

    """
    settings = OrderedDict(
        {
            "channels": channels,
            "CaptureTrace": True,
            "CaptureHistogram": True,
            "CaptureSums": True,
        }
    )
    change_setting_from_dict(settings, auto_update=False)

    if disable_CFD:
        print("[INFO] traces: turned CFD off")
        settings = OrderedDict({"channels": channels, "EnableCFD": False})
        change_setting_from_dict(settings, auto_update=False)


def read_histograms(module_channels: Iterable[Tuple[int, int]]) -> List[np.ndarray]:
    """Read histograms from several channels.

    Uses (module, channel) tuples, e.g. [(0, 8), (0, 3)] to read histograms.

    Parameters
    ----------
    module_channels
        List of tuples of (module, channel) to define which histograms we want to read

    Returns
    -------
    List[np.ndarray]
        List of numpy arrays with the histograms
    """
    return [SDK.read_histogram_from_module(m, c) for m, c in module_channels]


def take_MCA_spectra(
    channels: Iterable[Tuple[int, int]],
    duration: float,
    verbose: bool = True,
    position: int = 0,
) -> List[np.ndarray]:
    """Takes MCA spectra for a certain time on the specified channels.

    This does the data acquisition and returns the data.

    Parameters
    ----------
    channels
         list of (modules, channel number) tuples
    duration
         MCA time in seconds

    Returns
    -------
    list(nd.ndarray)
         List of numpy arrays. One for each channel.
    """
    settings = OrderedDict(
        {
            "channels": channels,
            "HostRunTimePreset": SDK.converter_IEEE754_to_ulong(duration).value,
        }
    )
    change_setting_from_dict(settings, auto_update=False)

    modules = list({x for x, y in channels})  # unique list of modules

    # take MCA spectra
    if verbose:
        print("[INFO] Taking MCA spectrum", end="", flush=True)

    start_histogram_run()
    sys.stdout.flush()
    time.sleep(0.5)

    start = time.time()
    keep_running = True
    with Progress() as progress:
        task = progress.add_task("[red] MCA", total=duration)

        while keep_running and (time.time() - start < duration):
            keep_running = False
            for m, _ in enumerate(modules):
                r = SDK.check_run_status(m)
                sys.stdout.flush()
                if r == 1:
                    keep_running = True
            time.sleep(1)
            dt = time.time() - start
            progress.update(task, advance=dt)
        progress.update(task, completed=duration)
    print()
    end_run()

    return read_histograms(channels)


def take_list_mode_data(
    duration: float,
    modules: Optional[Iterable[int]] = None,
) -> Dict[int, ByteString]:
    """Take list mode data for a certain time.

    It also stops at 1 Gb of raw data to avoid too much memory use.
    If you want to take mor data, you need to use another mechanism
    and write the data to disk more often.

    Parameters
    ----------
    duration
       Length in seconds of how long data is acquired for
    modules
       List of modules, use the ones defined during `init` if None.

    Returns
    -------
    dict[int, ByteString]
       Dictionary with the raw binary data in it. Each module gets is a key
       in the dictionary and the values are the bytestring.
    """
    if modules is None:
        modules = module_list

    start_list_mode_run()

    # initialize output module
    raw_data = {i: b"" for i, _ in enumerate(modules)}

    start = time.time()
    raw_data_length = 0

    with Progress() as progress:
        task = progress.add_task("[red] Traces", total=duration)

        while (time.time() - start < duration) and (raw_data_length < 1e9):
            data = read_list_mode_fifo(threshold=32 * 1024)
            for i, d in enumerate(data):
                if d is not None:
                    raw_data[i] += d.tobytes()
                    raw_data_length += len(d)
            dt = time.time() - start
            progress.update(task, advance=dt)
        progress.update(task, completed=duration)

    end_run()
    time.sleep(0.5)

    # read remainig data in queue
    tmp = read_list_mode_fifo(check=False)
    if not tmp:
        return raw_data

    for i, _ in enumerate(modules):
        if tmp[i] is not None:
            raw_data[i] += tmp[i].tobytes()

    return raw_data


def save_settings_to_json(filename: Path):
    """Save the current settings to a file."""
    SDK.save_dsp_parameters_as_json(filename)


def read_settings_from_json(filename: Path):
    """Reads the settings from a new-style json settings file."""
    with filename.open("r") as f:
        data = json.load(f)
    return data


def read_settings() -> List[Settings]:
    """Read the current setting into memory.

    Reads the setting into a temporary json file using XIA's library and then parse that file.

    Returns
    -------
       A dictonary of setting data
    """
    # note: using tempfile in a context manager has problems on windows when writing and
    # then reading from the same file
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    filename = Path(f.name)
    SDK.save_dsp_parameters_as_json(filename)
    f.seek(0)
    data = json.load(f)
    f.close()
    filename.unlink()
    return [Settings.from_dict(x) for x in data]


def write_settings_from_file(filename: Path) -> None:
    """Loads a setting file into the pixie16.

    Parameters
    ----------
    filename
        settings file to load

    """
    SDK.load_dsp_parameters_from_file(filename)


def write_settings(data: List[Settings]) -> None:
    """Writes a setting object to the pixie16.

    Parameters
    ----------
    data
        Object created by `read_settings`.
    """
    # note: using tempfile in a context manager has problems on windows when writing and
    # then reading from the same file
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    filename = Path(f.name)
    with filename.open("w") as f:
        json.dump([dict(x) for x in data], f)
    SDK.load_dsp_parameters_from_file(filename)
    filename.unlink()


@contextmanager
def temporary_settings() -> None:
    """Making it easy to temporary change settings in the pixie16.

    A context manager that will remember the current setting, execute
    some code that can change those settings, and then reset the
    setting back to the original.

    It saves the settings of all modules defined in the `init` call.
    """
    current_settings = read_settings()

    try:
        yield None  # this is were the code gets executed
    finally:
        write_settings(current_settings)


def _change_setting_locally(
    setting: List[Settings],
    name: str,
    value,
    channel: Optional[int] = None,
    module: int = 0,
) -> List[Settings]:
    """Changes a single setting inside an object returned by read_settings.

    This function does not talk to the pixie16 and only changes the value
    inside a dict that then later can be written to the pixie16. This way
    multiple changes can be made and data only needs to be transfered once
    to the pixie16.

    Users of pypixie16 should use `change_setting_from_dict` to modify settings
    or if they only want to change a single setting we provide `change_setting`.

    Parameters
    ----------
    setting
        Object returned by `read_settings`
    name
        Name of value to change
    value
        New value. This normally needs to match the shape of the existing value.
        For channel values, it is also allowed to provide just a single float or int
        which will then be used for all channels.
    channel
        Optional channel number
    module
        Module number
    """

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

    if channel is None:
        current_value = setting[module]["module"]["input"][name]
        if isinstance(value, (int, float)):
            setting[module]["channel"]["input"][name] = value
        else:
            if len(current_value) != len(value):
                raise ValueError(
                    f"change_setting: wrong number of arguments"
                    f" for setting {name}.",
                    f" Need {len(current_value)}, got {len(value)}",
                )
            setting[module]["module"]["input"][name] = value
    else:
        current_value = setting[module]["channel"]["input"][name]
        if isinstance(value, (int, float)):
            setting[module]["channel"]["input"][name][channel] = value
        else:
            if len(current_value) != len(value):
                raise ValueError(
                    f"change_setting: wrong number of arguments"
                    f" for setting {name}.",
                    f" Need {len(current_value)}, got {len(value)}",
                )
            setting[module]["channel"]["input"][name] = value
    return setting


def change_setting(
    name: str, value, channel: Optional[int] = None, module: int = 0
) -> None:
    """Changes the value of a single setting on the pixie16.

    First reads all values, changes one and then sends the new setting
    back to the pixie.

    Module parameter can be set by setting channel to None.

    Parameters
    ----------
    name
        setting name
    value
        new value
    channel
        channel name (if None, we assume a module paramter)
    module
        the module number (starting at 0)
    """
    setting = read_settings()

    new = _change_setting_locally(setting, name, value, channel, module)

    write_settings(new)


def _change_channel_register_bit_locally(
    setting: List[Settings],
    name: str,
    value: bool,
    bit: int,
    channel: int,
    module: int = 0,
) -> List[Settings]:
    """Update a bit in a channel register.

    Parameters
    ----------
    setting
        from read_setting
    name
        name of the register
    value
        new value: True or False
    bit
        the bit that should be changed
    channel
        the channel number
    module
        the module number (starting at 0)
    """
    current = setting[module]["channel"]["input"][name][channel]
    new = 1 << bit
    if value:
        # set the bit
        new = current | new
    else:
        # unset the bit
        new = current & ~new
    setting[module]["channel"]["input"][name][channel] = new

    return setting


def _change_module_register_bit_locally(
    setting: List[Settings], name: str, value: bool, bit: int, module: int = 0
) -> List[Settings]:
    """Update a bit in module register.

    Parameters
    ----------
    setting
        from read_setting
    name
        name of the register
    value
        new value: True or False
    bit
        the bit that should be changed
    module
        the module number (starting at 0)
    """
    current = setting[module]["module"]["input"][name]
    new = 1 << bit
    if value:
        # set the bit
        new = current | new
    else:
        # unset the bit
        new = current & ~new
    setting[module]["module"]["input"][name] = new

    return setting


def _change_CSRA_bit_locally(
    setting: List[Settings], value: bool, channel: int, module: int, bit: int
) -> List[Settings]:
    return _change_channel_register_bit_locally(
        setting, "ChanCSRa", value, bit, channel, module
    )


def _change_CSRB_bit_locally(
    setting: List[Settings], value: bool, module: int, bit: int
) -> List[Settings]:
    return _change_module_register_bit_locally(setting, "ModCSRB", value, bit, module)


def _change_CSRA_locally(
    setting: List[Settings], name: str, value, channel: int, module: int
) -> List[Settings]:
    """Update bits by name for channel CSRa

    Parameters
    ----------
    setting
        from read_setting
    name
        name of the setting (defined here)
    value
        either True/False or custom strings (see below)
    channel
        channel number to update
    module
        the module number (starting at 0)
    """
    if name == "FastTrigSelect":
        # value: 'external' or 'group'
        return _change_CSRA_bit_locally(
            setting, value == "external", channel, module, 0
        )
    if name == "ModValSignal":
        # value: 'modgate' or 'global'
        return _change_CSRA_bit_locally(setting, value == "modgate", channel, module, 1)
    if name == "GoodChannel":
        # value: True = enable channel
        return _change_CSRA_bit_locally(setting, value, channel, module, 2)
    if name == "ChanValSignal":
        # value: 'channelgate' or 'channelvalidation'
        return _change_CSRA_bit_locally(
            setting, value == "channelgate", channel, module, 3
        )
    if name == "RejectIfFull":
        # value: True = reject data if buffer is full
        return _change_CSRA_bit_locally(setting, value, channel, module, 4)
    if name == "Polarity":
        # value: True=positive slope, False=negative slope
        return _change_CSRA_bit_locally(
            setting, value == "positive", channel, module, 5
        )
    if name == "EnableVeto":
        # value: True = enable veto
        return _change_CSRA_bit_locally(setting, value, channel, module, 6)
    if name == "CaptureHistogram":
        # value: True = enable capture of MCA histograms
        return _change_CSRA_bit_locally(setting, value, channel, module, 7)
    if name == "CaptureTrace":
        # value: True = enable capture trace
        return _change_CSRA_bit_locally(setting, value, channel, module, 8)
    if name == "EnableQDC":
        # value: True = enable capture QDC sums
        return _change_CSRA_bit_locally(setting, value, channel, module, 9)
    if name == "EnableCFD":
        # value: True = enable CFD
        return _change_CSRA_bit_locally(setting, value, channel, module, 10)
    if name == "EnableModVal":
        # value: True = enable module validation
        return _change_CSRA_bit_locally(setting, value, channel, module, 11)
    if name == "CaptureSums":
        # value: True = enable capture raw energy susms
        return _change_CSRA_bit_locally(setting, value, channel, module, 12)
    if name == "EnableChannelVal":
        # value: True = enable channel validation
        return _change_CSRA_bit_locally(setting, value, channel, module, 13)
    if name == "Gain":
        # value: 0.625 or 2.5
        return _change_CSRA_bit_locally(setting, value == 2.5, channel, module, 14)
    if name == "RejectPileup":
        # value: 'all' (no energies for pileup events),
        #        'single' (reject pileup),
        #        'pileup' (trace, timestamp for pileup, no trace for single)
        #        'pileup-only' (only record trace, timestamp, etc for pileup
        #                       events, no single events)
        bit0 = (value == "single") or (value == "pileup-only")
        bit1 = (value == "pileup") or (value == "pileup-only")
        setting = _change_CSRA_bit_locally(setting, bit0, channel, module, 15)
        setting = _change_CSRA_bit_locally(setting, bit1, channel, module, 16)
        return setting
    if name == "SkipLargePulses":
        # value: True = don't record traces for large pulses
        return _change_CSRA_bit_locally(setting, value, channel, module, 17)
    if name == "GroupTrigSignal":
        # value: 'external' or 'local'
        return _change_CSRA_bit_locally(
            setting, value == "external", channel, module, 18
        )
    if name == "ChannelVetoSignal":
        # value: 'channel' or 'front'
        return _change_CSRA_bit_locally(
            setting, value == "channel", channel, module, 19
        )
    if name == "ModVetoSignal":
        # value: 'module' or 'front'
        return _change_CSRA_bit_locally(setting, value == "module", channel, module, 20)
    if name == "ExtTimestamps":
        # value: True = include external timestamps in header
        return _change_CSRA_bit_locally(setting, value, channel, module, 21)

    raise KeyError(f"Error: unknown key for ChannelCSRa {name}")


def _change_CSRB_locally(
    setting: List[Settings], name: str, value: float, module: int
) -> List[Settings]:
    """Update bits by name for the module CSRb.

    Parameters
    ----------
    setting
        from read_setting
    name
        name of the setting (defined here)
    value
        either True/False or custom strings (see below)
    module
        the module number (starting at 0)
    """
    if name == "BackplanePullup":
        # value: True = connect backplane to pullup resistor
        return _change_CSRB_bit_locally(setting, value, module, 0)
    if name == "Director":
        # value: True = set to director
        return _change_CSRB_bit_locally(setting, value, module, 4)
    if name == "ChassisMaster":
        # value: True = set to chassis master
        return _change_CSRB_bit_locally(setting, value, module, 6)
    if name == "GlobalFastTrigger":
        # value: True = select global fast trigger source
        return _change_CSRB_bit_locally(setting, value, module, 7)
    if name == "ExternalTrigger":
        # value: True = select external trigger source
        return _change_CSRB_bit_locally(setting, value, module, 8)
    if name == "ExternalInhibit":
        # value: True = use inhibit
        return _change_CSRB_bit_locally(setting, value, module, 10)
    if name == "DistributeClocks":
        # value: True = multiple crates
        return _change_CSRB_bit_locally(setting, value, module, 11)
    if name == "SortEvents":
        # value: True = sort events based on timestamp
        return _change_CSRB_bit_locally(setting, value, module, 12)
    if name == "ConnectFastTriggerBP":
        # value: True = Connect the fast trigger to the backplane
        return _change_CSRB_bit_locally(setting, value, module, 13)

    raise KeyError(f"Error: unknown key for ModuleCSRb {name}")


def _get_setting_value(
    name: str,
    settings_dict: Dict,
    channels: List[Tuple[int, int]],
    current_settings: List[Settings],
    module: int = 0,
) -> List[Union[int, float]]:
    """Returns name from setting dictionary or from memory.

    This is a helper function for `change_settings_from_dict` that is used
    in `autoupdate` mode for settings that depend on other settings. The functions
    returns values needed to re-calculate autoupdate values.

    Parameters
    ----------
    name
        Setting name
    settings_dict
        dictionary with new values to be set
    channels
        List of (module, channels) pairs
    current_settings
        Object returned by `read_settings`


    Returns
    -------
    List
        A list of the same length as channels with the values for each channel.
        Similar to the values that need to be used in `change_settings_from_dict`.
    """

    if name in settings_dict:
        temp = settings_dict[name]
        if isinstance(temp, (int, float)):
            temp = [temp] * len(channels)
    else:
        if name in current_settings[module]["module"]["input"]:
            temp = []
            for mod, c in channels:
                temp.append(current_settings[module]["module"]["input"][name])
        elif name in current_settings[module]["channel"]["input"]:
            temp = []
            for mod, c in channels:
                temp.append(current_settings[module]["channel"]["input"][name][c])
        else:
            print(f"[ERROR] get_setting_value cannot get value for {name}")

    return temp


def change_setting_from_dict(settings, auto_update=True):
    """Takes a dictionary with setting names as keys and setting values

    The dictionary must also contain an entry called 'channels' that
    list all channels that should be set. Channels should be pairs in
    the form (module, channel).

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

    # get all the settings data from the pixie
    current = read_settings()

    # update depend values
    if "SlowLength" in settings or "SlowGap" in settings:
        SL = _get_setting_value("SlowLength", settings, channels, current)
        SG = _get_setting_value("SlowGap", settings, channels, current)
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
        filter_range = _get_setting_value(
            "SlowFilterRange", settings, channels, current
        )
        SL = _get_setting_value("SlowLength", settings, channels, current)
        SG = _get_setting_value("SlowGap", settings, channels, current)
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
        SL = _get_setting_value("SlowLength", settings, channels, current)
        SG = _get_setting_value("SlowGap", settings, channels, current)
        PeakSep = [sl + sg for sl, sg in zip(SL, SG)]
        settings["PeakSep"] = PeakSep

    if auto_update and ("TriggerDelay" not in settings):
        filter_range = _get_setting_value(
            "SlowFilterRange", settings, channels, current
        )
        PeakSep = _get_setting_value("PeakSep", settings, channels, current)
        settings["TriggerDelay"] = [
            (p - 1) * 2 ** f for f, p in zip(filter_range, PeakSep)
        ]
    if auto_update and ("PAFlength" in settings) and ("TraceDelay" in settings):
        print("Warning: PAFlength and TraceDelay set. TraceDelay will be ignored.")
        settings.pop("TraceDelay")
    if auto_update and ("PAFlength" not in settings) and ("TraceDelay" in settings):
        TriggerDelay = _get_setting_value("TriggerDelay", settings, channels, current)
        FastFilterRange = _get_setting_value(
            "FastFilterRange", settings, channels, current
        )
        TraceDelay = _get_setting_value("TraceDelay", settings, channels, current)
        FIFOLength = _get_setting_value("FIFOLength", settings, channels, current)
        settings.pop("TraceDelay")

        PAFlength = [
            t / (2 ** f) + d / 5
            for t, f, d in zip(TriggerDelay, FastFilterRange, TraceDelay)
        ]

        settings["PAFlength"] = PAFlength
    if auto_update and ("PAFlength" in settings):
        PAFlength = _get_setting_value("PAFlength", settings, channels, current)
        FIFOLength = _get_setting_value("FIFOLength", settings, channels, current)
        FastFilterRange = _get_setting_value(
            "FastFilterRange", settings, channels, current
        )
        if "TraceDelay" in settings:
            TraceDelay = _get_setting_value("TraceDelay", settings, channels, current)
            TraceDelay = [
                x / 5 for x in TraceDelay
            ]  # convert from data points to FPGA cycles
        else:
            TriggerDelay = _get_setting_value(
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
            settings[name] = SDK.converter_IEEE754_to_ulong(settings[name]).value
        else:
            settings[name] = [
                SDK.converter_IEEE754_to_ulong(x).value for x in settings[name]
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
                    current = _change_CSRB_locally(current, name, values, mod)
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
                        current = _change_CSRA_locally(current, name, value, ch, mod)
                else:
                    raise TypeError(
                        f"Wrong type (or length) for channel parameter {name}"
                        f" in change_settings_dict, values: {settings[name]}"
                    )
            else:
                for channel in channels:
                    mod, ch = channel
                    current = _change_CSRA_locally(current, name, values, ch, mod)
        elif name in SETTINGS_NAME_CHANNEL:
            if isinstance(settings[name], (list, tuple)):
                if len(settings[name]) == len(channels):
                    for value, channel in zip(settings[name], channels):
                        mod, ch = channel
                        current = _change_setting_locally(current, name, value, ch, mod)
                elif len(settings[name]) == len(modules):
                    for value, mod in zip(settings[name], modules):
                        for ch in range(16):
                            current = _change_setting_locally(
                                current, name, value, ch, mod
                            )
                else:
                    raise TypeError(
                        f"Wrong type (or length) for channel parameter {name}"
                        f" in change_settings_dict, values: {settings[name]}"
                    )
            elif isinstance(settings[name], int):
                value = settings[name]
                for mod in modules:
                    for ch in range(16):
                        current = _change_setting_locally(current, name, value, ch, mod)
            else:
                raise TypeError(
                    "Wrong type (or length) for channel parameter"
                    " in change_settings_dict"
                )
        elif name in SETTINGS_NAME_MODULE:
            if isinstance(settings[name], int):
                for mod in modules:
                    current = _change_setting_locally(
                        current, name, settings[name], None, mod
                    )
            elif isinstance(settings[name], (list, tuple)):
                for mod, value in zip(modules, settings[name]):
                    current = _change_setting_locally(current, name, value, None, mod)
        else:
            log.error(f"Change settings dict: unkown settings name {name}")

    # always enable all channels, we don't get any data otherwise... bug in pixie16?
    for m in modules:
        for c in range(16):
            current = _change_CSRA_bit_locally(current, True, c, m, 2)

    write_settings(current)
