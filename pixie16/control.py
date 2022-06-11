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

from importlib.resources import files
import numpy as np
from rich.progress import Progress
from rich import print

from . import config
from . import C_library_sdk as SDK
from . import variables
from .read import Settings, Stats, CrateSettings

# set up logging
log = logging.getLogger(__name__)

module_list: List[int] = [2]  # default setting, overwritten by init_and_boot

SETTINGS = variables.settings
SETTINGS_NAME_CHANNEL = []
SETTINGS_NAME_MODULE = []

BIT_PARAMETERS = {
    "FastTrigSelect": "CHANNEL_CSRA",
    "ModValSignal": "CHANNEL_CSRA",
    "GoodChannel": "CHANNEL_CSRA",
    "ChanValSignal": "CHANNEL_CSRA",
    "RejectIfFull": "CHANNEL_CSRA",
    "Polarity": "CHANNEL_CSRA",
    "EnableVeto": "CHANNEL_CSRA",
    "CaptureHistogram": "CHANNEL_CSRA",
    "CaptureTrace": "CHANNEL_CSRA",
    "EnableQDC": "CHANNEL_CSRA",
    "EnableCFD": "CHANNEL_CSRA",
    "EnableModVal": "CHANNEL_CSRA",
    "CaptureSums": "CHANNEL_CSRA",
    "EnableChannelVal": "CHANNEL_CSRA",
    "Gain": "CHANNEL_CSRA",
    "RejectPileup": "CHANNEL_CSRA",
    "SkipLargePulses": "CHANNEL_CSRA",
    "GroupTrigSignal": "CHANNEL_CSRA",
    "ChannelVetoSignal": "CHANNEL_CSRA",
    "ModVetoSignal": "CHANNEL_CSRA",
    "ExtTimestamps": "CHANNEL_CSRA",
    "BackplanePullup": "MODULE_CSRB",
    "Director": "MODULE_CSRB",
    "ChassisMaster": "MODULE_CSRB",
    "GlobalFastTrigger": "MODULE_CSRB",
    "ExternalTrigger": "MODULE_CSRB",
    "ExternalInhibit": "MODULE_CSRB",
    "DistributeClocks": "MODULE_CSRB",
    "SortEvents": "MODULE_CSRB",
    "ConnectFastTriggerBP": "MODULE_CSRB",
}
CHANNEL_PARAMETERS = SDK.valid_channel_parameter_names + [
    x for x in BIT_PARAMETERS if BIT_PARAMETERS[x] == "CHANNEL_CSRA"
]
MODULE_PARAMETERS = SDK.valid_module_parameter_names + [
    x for x in BIT_PARAMETERS if BIT_PARAMETERS[x] == "MODULE_CSRB"
]


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
    if not SDK.load_library():
        print(
            "[orange3]WARNING[/] Mocking the pixie library (useful for testing when the library is not installed)"
        )

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
    if modules is None:
        modules = [2]
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
        json.dump(out, f, indent=2)


def end_run() -> None:
    """Calls end_run on all the modules."""
    for m, _ in enumerate(module_list):
        SDK.end_run(m)


def exit_system() -> None:
    """Calls exit_system on all the modules."""
    for m, _ in enumerate(module_list):
        SDK.exit_system(m)


def read_list_mode_fifo(
    check: bool = True, threshold: int = 64, modules: Optional[Iterable[int]] = None
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
    datadir = config.config_get_parameters("Data", "datadir", verbose=False)
    if datadir is None:
        datadir = Path(".")
        print(
            f"[orange3]WARNING[/] Could not find datadir in Data section in ini-file {config.inifile}."
        )
        print(f"[orange3]WARNING[/] Using {datadir.absolute()} to save data.")
    filename = datadir / YYYYMMDD / filename
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
            "TrigConfig0": 0,
            "TrigConfig1": 0,
            "TrigConfig2": 0,
            "TrigConfig3": 0,
            "CaptureTrace": False,
            "CaptureHistogram": True,
            "CaptureSums": False,
            "FastTrigSelect": "group",
            "EnableModVal": False,
            "EnableChannelVal": False,
            "GroupTrigSignal": "local",
            "RejectPileup": "pileup",
            "RejectIfFull": False,
        }
    )
    change_setting_from_dict(settings)


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
    change_setting_from_dict(settings)

    if disable_CFD:
        print("[yellow]INFO[/] traces: turned CFD off")
        settings = OrderedDict({"channels": channels, "EnableCFD": False})
        change_setting_from_dict(settings)


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
            "HOST_RT_PRESET": duration,
        }
    )
    change_setting_from_dict(settings)

    modules = list({x for x, y in channels})  # unique list of modules

    # take MCA spectra
    if verbose:
        print("[yellow]INFO[/] Taking MCA spectrum", end="", flush=True)

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

    # read remainig data from pixie
    tmp = read_list_mode_fifo(check=False)
    if not tmp:
        return raw_data

    for i, d in enumerate(tmp):
        if d is not None:
            raw_data[i] += d.tobytes()

    return raw_data


def save_settings_to_json(filename: Path):
    """Save the current settings to a file."""
    SDK.save_dsp_parameters_as_json(filename)


def read_settings_from_json(filename: Path):
    """Reads the settings from a new-style json settings file."""
    with filename.open("r") as f:
        data = json.load(f)
    return data


def read_settings() -> CrateSettings:
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
    if data is None:
        print("[red]Error[/] Cannot read settings from pixie")
        return CrateSettings([])
    return CrateSettings([Settings.from_dict(x) for x in data])


def read_dummy_settings(modules) -> CrateSettings:
    """Read the current setting into memory.

    Reads settings from a given file to be used as dummy data.
    Needed, for example, for tests.

    Returns
    -------
       A dictonary of setting data
    """
    with files("pixie16.data").joinpath("default.json").open("r") as f:
        data = json.load(f)
    return CrateSettings([Settings.from_dict(x) for x in data])


def write_settings_from_file(filename: Path) -> None:
    """Loads a setting file into the pixie16.

    Parameters
    ----------
    filename
        settings file to load

    """
    SDK.load_dsp_parameters_from_file(filename)


def write_settings(data: CrateSettings) -> None:
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
        json.dump([dict(x) for x in data], f, indent=2)
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


def change_setting_from_dict(settings: dict, call_pixie: Optional[bool] = True):
    """Update settings in the pixie16.

    Takes a dictionary with setting names as keys and setting values

    The dictionary must also contain an entry called 'channels' that
    list all channels that should be set. Channels should be pairs in
    the form (module, channel).

    The values in the dictionary can either be a single value, in which case the value
    will be used for all channels or a list of the same length as `channels` in which case
    each (module, channel) combination will get its own value.
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

    out = []  # this list is mainly for testing
    for name, value in settings.items():
        if name in CHANNEL_PARAMETERS:
            # convert single values to lists that matches the number of channels
            if isinstance(value, (int, float, str)):
                value_lst = [value] * len(channels)
            else:
                value_lst = value
            # set each value in the list
            for (module, channel), ch_value in zip(channels, value_lst):
                # if the parameter is one that we defined for a bit value, we need to
                # read the current value, change the single bit before we write it
                if name in BIT_PARAMETERS:
                    pixie_param_name = BIT_PARAMETERS[name]
                    if call_pixie:
                        bit_param_val = SDK.read_single_channel_parameter(
                            pixie_param_name, module, channel, convert_bit_pattern=True
                        )
                    else:
                        bit_param_val = [False] * 32
                    ch_value_out = _change_bit_parameter(name, ch_value, bit_param_val)
                    name_out = pixie_param_name
                else:
                    ch_value_out = ch_value
                    name_out = name
                if call_pixie:
                    SDK.write_single_channel_parameter(
                        name_out, ch_value_out, module, channel
                    )
                out.append(["channel", name_out, ch_value, module, channel])
        elif name in MODULE_PARAMETERS:
            # for a module parameter things are a bit simpler, since we don't
            # have to scale things from a single value
            for module in modules:
                # we still need to handle some parameters that have bit values
                # for which we defined our own names
                if name in BIT_PARAMETERS:
                    pixie_param_name = BIT_PARAMETERS[name]
                    if call_pixie:
                        bit_param_val = SDK.read_single_module_parameter(
                            pixie_param_name, module, convert_bit_pattern=True
                        )
                    else:
                        bit_param_val = [False] * 32
                    value = _change_bit_parameter(name, value, bit_param_val)
                    name = pixie_param_name
                if call_pixie:
                    SDK.write_single_module_parameter(name, value, module)
                out.append(["module", name, value, module])

        else:
            print(f"[red]Error[/] {name} not a valid Pixie16 parameter name.")
    return out


def _change_bit_parameter(
    name: str, value: Union[bool, int, str], bit_list: List[bool]
) -> List[bool]:
    """Internal function to adjust single bits in MODULE_CSRB and CHANNEL_CSRA.

    This sets the correct bits for certain settings, so that the user doesn't have to
    figure out which bits to set in an integer. To make this easier, we invented new
    settings names listed below that correspond to certain bits. The table below will
    list the valid parameters.

    .. list-table:: Functions
       :widths: 25 25
       :header-rows: 1

       * - Setting Name
         - Parameter
         - bit
         - possible values
       * - BackplanePullup
         - MODULE_CSRB
         - 0
         - True/False
       * - Director
         - MODULE_CSRB
         - 4
         - True/False
       * - ChassisMaster
         - MODULE_CSRB
         - 6
         - True/False
       * - GlobalFastTrigger
         - MODULE_CSRB
         - 7
         - True/False
       * - ExternalTrigger
         - MODULE_CSRB
         - 8
         - True/False
       * - ExternalInhibit
         - MODULE_CSRB
         - 10
         - True/False
       * - DistributeClocks
         - MODULE_CSRB
         - 11
         - True/False
       * - SortEvents
         - MODULE_CSRB
         - 12
         - True/False
       * - ConnectFastTriggerBP
         - MODULE_CSRB
         - 13
         - True/False
       * - FastTrigSelect
         - CHANNEL_CSRA
         - 0
         - external(=True)/group(=False)
       * - ModValSignal
         - CHANNEL_CSRA
         - 1
         - modgate(=True)/global(=False)
       * - GoodChannel
         - CHANNEL_CSRA
         - 2
         - True/False
       * - ChanValSignal
         - CHANNEL_CSRA
         - 3
         - channelgate(=True)/channelvalidation(=False)
       * - RejectIfFull
         - CHANNEL_CSRA
         - 4
         - True/False
       * - Polarity
         - CHANNEL_CSRA
         - 5
         - positive(=True)/negative(=False)
       * - EnableVeto
         - CHANNEL_CSRA
         - 6
         - True/False
       * - CaptureHistogram
         - CHANNEL_CSRA
         - 7
         - True/False
       * - CaptureTrace
         - CHANNEL_CSRA
         - 8
         - True/False
       * - EnableQDC
         - CHANNEL_CSRA
         - 9
         - True/False
       * - EnableCFD
         - CHANNEL_CSRA
         - 10
         - True/False
       * - EnableModVal
         - CHANNEL_CSRA
         - 11
         - True/False
       * - CaptureSums
         - CHANNEL_CSRA
         - 12
         - True/False
       * - EnableChannelVal
         - CHANNEL_CSRA
         - 13
         - True/False
       * - Gain
         - CHANNEL_CSRA
         - 14
         - 2.5(=True)/0.625(=False)
       * - RejectPileup
         - CHANNEL_CSRA
         - 15, 16
         - single(b15=1, b16=0)/pileup-only(b15=1, b16=1)/pileup(b15=0, b16=1)/all(b15=0, b16=0)
       * - SkipLargePulses
         - CHANNEL_CSRA
         - 17
         - True/False
       * - GroupTrigSignal
         - CHANNEL_CSRA
         - 18
         - external(=True)/local(=False)
       * - ChannelVetoSignal
         - CHANNEL_CSRA
         - 19
         - channel(=True)/front(=False)
       * - ModVetoSignal
         - CHANNEL_CSRA
         - 20
         - channel(=True)/front(=False)
       * - ExtTimestamps
         - CHANNEL_CSRA
         - 21
         - True/False
    """
    # Module parameters (currently onlChanValSignaly MODULE_CSRB)
    if name == "BackplanePullup":
        # value: True = connect backplane to pullup resistor
        assert isinstance(
            value, bool
        ), "BackplanePullup needs to be either True or False"
        bit_list[31 - 0] = value
    elif name == "Director":
        # value: True = set to director
        assert isinstance(value, bool), "Director needs to be either True or False"
        bit_list[31 - 4] = value
    elif name == "ChassisMaster":
        # value: True = set to chassis master
        assert isinstance(value, bool), "ChassisMaster needs to be either True or False"
        bit_list[31 - 6] = value
    elif name == "GlobalFastTrigger":
        # value: True = select global fast trigger source
        assert isinstance(
            value, bool
        ), "GlobalFastTrigger needs to be either True or False"
        bit_list[31 - 7] = value
    elif name == "ExternalTrigger":
        # value: True = select external trigger source
        assert isinstance(
            value, bool
        ), "ExternalTrigger needs to be either True or False"
        bit_list[31 - 8] = value
    elif name == "ExternalInhibit":
        # value: True = use inhibit
        assert isinstance(
            value, bool
        ), "ExternalInhibit needs to be either True or False"
        bit_list[31 - 10] = value
    elif name == "DistributeClocks":
        # value: True = multiple crates
        assert isinstance(
            value, bool
        ), "DistributeClocks needs to be either True or False"
        bit_list[31 - 11] = value
    elif name == "SortEvents":
        # value: True = sort events based on timestamp
        assert isinstance(value, bool), "SortEvents needs to be either True or False"
        bit_list[31 - 12] = value
    elif name == "ConnectFastTriggerBP":
        # value: True = Connect the fast trigger to the backplane
        assert isinstance(
            value, bool
        ), "ConnectFastTriggerBP needs to be either True or False"
        bit_list[31 - 13] = value

    # Channel parameters  (currently CHAN_CSRA)
    elif name == "FastTrigSelect":
        # value: 'external' or 'group'
        assert value in [
            "external",
            "group",
        ], "FastTrigSelect needs to be either 'external' or 'group'"
        bit = value == "external"
        bit_list[31 - 0] = bit
    elif name == "ModValSignal":
        # value: 'modgate' or 'global'
        assert value in [
            "modgate",
            "global",
        ], "ModValSignal needs to be either 'modgate' or 'global'"
        bit = value == "modgate"
        bit_list[31 - 1] = bit
    elif name == "GoodChannel":
        # value: True = enable channel
        assert isinstance(value, bool), "GoodChannel needs to be either True or False"
        bit_list[31 - 2] = value
    elif name == "ChanValSignal":
        # value: 'channelgate' or 'channelvalidation'
        assert value in [
            "channelgate",
            "channelvalidation",
        ], "ChanValSignal needs to be either 'channelgate' or 'channelvalidation'"
        bit = value == "channelgate"
        bit_list[31 - 3] = bit
    elif name == "RejectIfFull":
        # value: True = reject data if buffer is full
        assert isinstance(value, bool), "RejectIfFull needs to be either True or False"
        bit_list[31 - 4] = value
    elif name == "Polarity":
        # value: True=positive slope, False=negative slope
        assert value in [
            "positive",
            "negative",
        ], "Polarity needs to be either 'positive' or 'negative'"
        bit = value == "positive"
        bit_list[31 - 5] = bit
    elif name == "EnableVeto":
        # value: True = enable veto
        assert isinstance(value, bool), "EnableVeto needs to be either True or False"
        bit_list[31 - 6] = value
    elif name == "CaptureHistogram":
        # value: True = enable capture of MCA histograms
        assert isinstance(
            value, bool
        ), "CaptureHistogram needs to be either True or False"
        bit_list[31 - 7] = value
    elif name == "CaptureTrace":
        # value: True = enable capture trace
        assert isinstance(value, bool), "CaptureTrace needs to be either True or False"
        bit_list[31 - 8] = value
    elif name == "EnableQDC":
        # value: True = enable capture QDC sums
        assert isinstance(value, bool), "EnableQDC needs to be either True or False"
        bit_list[31 - 9] = value
    elif name == "EnableCFD":
        # value: True = enable CFD
        assert isinstance(value, bool), "EnableCFD needs to be either True or False"
        bit_list[31 - 10] = value
    elif name == "EnableModVal":
        # value: True = enable module validation
        assert isinstance(value, bool), "EnableModVal needs to be either True or False"
        bit_list[31 - 11] = value
    elif name == "CaptureSums":
        # value: True = enable capture raw energy susms
        assert isinstance(value, bool), "CaptureSums needs to be either True or False"
        bit_list[31 - 12] = value
    elif name == "EnableChannelVal":
        # value: True = enable channel validation
        assert isinstance(
            value, bool
        ), "EnableChannelVal needs to be either True or False"
        bit_list[31 - 13] = value
    elif name == "Gain":
        # value: 2.5 (True) or 0.625 (False)
        assert value in [2.5, 0.625], "Gain needs to be either 0.625 or 2.5"
        bit = value == 2.5
        bit_list[31 - 14] = bit
    elif name == "RejectPileup":
        # value: 'all' (no energies for pileup events),
        #        'single' (reject pileup),
        #        'pileup' (trace, timestamp for pileup, no trace for single)
        #        'pileup-only' (only record trace, timestamp, etc for pileup
        #                       events, no single events)
        assert value in [
            "single",
            "pileup-only",
            "pileup",
            "all",
        ], "RejectPileup needs to be either 'all', 'single', 'pileup', 'pileup-only'"
        bit0 = (value == "single") or (value == "pileup-only")
        bit1 = (value == "pileup") or (value == "pileup-only")
        bit_list[31 - 15] = bit0
        bit_list[31 - 16] = bit1
    elif name == "SkipLargePulses":
        # value: True = don't record traces for large pulses
        assert isinstance(
            value, bool
        ), "SkipLargePulses needs to be either True or False"
        bit_list[31 - 17] = value
    elif name == "GroupTrigSignal":
        # value: 'external' or 'local'
        assert value in [
            "external",
            "local",
        ], "GroupTrigSignal needs to be either 'external' or 'local'"
        bit = value == "external"
        bit_list[31 - 18] = bit
    elif name == "ChannelVetoSignal":
        # value: 'channel' or 'front'
        assert value in [
            "channel",
            "front",
        ], "ChannelVetoSignal needs to be either 'channel' or 'front'"
        bit = value == "channel"
        bit_list[31 - 19] = bit
    elif name == "ModVetoSignal":
        # value: 'module' or 'front'
        assert value in [
            "module",
            "front",
        ], "ModVetoSignal needs to be either 'module' or 'front'"
        bit = value == "module"
        bit_list[31 - 20] = bit
    elif name == "ExtTimestamps":
        # value: True = include external timestamps in header
        assert isinstance(value, bool), "ExtTimestamps needs to be either True or False"
        bit_list[31 - 21] = value
    return bit_list


def change_raw_setting_from_dict(settings: Dict, call_pixie: Optional[bool] = True):
    """Modify the raw settings on the pixie.

    Note: this bypasses any checks that are normally done in XIA's C-libary. This can be
    used to, for example, modify `Peaksample` if needed. However, if you set parameters
    to invalid numbers, there will be no error and the binary stream can be invalid.

    Parameters
    ----------
    settings
        A dictionary with the settings names as key and the values for each channel
        (or a single value that will be applied to all channels). One key must be called
        `channels` and must be a list of (module, channel) tuples.
    call_pixie
        Can be set to False, in which case the pixie16 is not actually called (used for tests)
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

    # get all the settings data from the pixie
    if call_pixie:
        current = read_settings()
    else:
        current = read_dummy_settings(
            list({mod for (mod, ch) in channels})
        )  # mostly used for testing

    # update all settings
    for name, value in settings.items():
        for i, (module, channel) in enumerate(channels):
            current_value = current[module].get_by_name(name)

            if isinstance(current_value, (bool, int, float)):
                assert isinstance(value, (bool, int, float))
                current[module].set_by_name(name, value)
            if isinstance(current_value, (list, tuple)):
                if isinstance(value, (bool, int, float)):
                    value_list = [value] * len(channels)
                else:
                    value_list = list(value)
                current_value[channel] = value_list[i]
                current[module].set_by_name(name, current_value)

    if call_pixie:
        write_settings(current)
    return current


def set_defaults_for_module(module: int, call_pixie: Optional[bool] = True):
    """Sets defaults for all used module and channel parameters in a module.

    Parameters
    ----------
    module
        The module number (0, 1, ...)
    call_pixie
        Can be set to False, in which case the pixie16 is not actually called (used for tests)

    """
    channels = [(module, x) for x in range(16)]
    settings = {
        "channels": channels,
        "BASELINE_AVERAGE": 3,
        "BASELINE_PERCENT": 10,
        "BINFACTOR": 1,
        "BLCUT": 200,
        "CaptureHistogram": False,
        "CaptureSums": False,
        "CaptureTrace": False,
        "CFDDelay": 8,
        "CFDScale": 1,
        "CFDThresh": 100,
        "CHANNEL_CSRA": 0,
        "ChanTrigStretch": 0.01,
        "ChanValSignal": "channelvalidation",
        "ChannelVetoSignal": "front",
        "ModVetoSignal": "front",
        "ExtTimestamps": False,
        "EMIN": 100,
        "EnableCFD": False,
        "EnableChannelVal": False,
        "ENERGY_FLATTOP": 0.04,  # as above
        "ENERGY_RISETIME": 0.020,  # times 2**SLOW_FILTER_RANGE
        "ExternDelayLen": 0.01,
        "ExtTrigStretch": 0.01,
        "FAST_FILTER_RANGE": 0,
        "FASTTRIGBACKLEN": 0.01,
        "FastTrigBackplaneEna": 0,
        "FastTrigSelect": "group",
        "FtrigoutDelay": 0.01,
        "Gain": 0.625,
        "GoodChannel": True,
        "GroupTrigSignal": "local",
        "IN_SYNCH": 0,
        "MODULE_CSRB": 0,
        "MultiplicityMaskH": 0,
        "MultiplicityMaskL": 0,
        "Polarity": "negative",
        "QDCLen0": 0.06,
        "QDCLen1": 0.06,
        "QDCLen2": 0.06,
        "QDCLen3": 0.06,
        "QDCLen4": 0.06,
        "QDCLen5": 0.06,
        "QDCLen6": 0.06,
        "QDCLen7": 0.06,
        "RejectIfFull": True,
        "RejectPileup": "all",
        "SkipLargePulses": False,
        "SLOW_FILTER_RANGE": 1,
        "SYNCH_WAIT": 0,
        "TAU": 0.03,
        "TRACE_DELAY": 0.4,
        "TRACE_LENGTH": 1.0,
        "TrigConfig0": 0,
        "TrigConfig1": 0,
        "TrigConfig2": 0,
        "TrigConfig3": 0,
        "TRIGGER_FLATTOP": 0.02,
        "TRIGGER_RISETIME": 0.02,
        "TRIGGER_THRESHOLD": 1_000,
        "VetoStretch": 0.30,
        "VOFFSET": 0.0,
        "XDT": 0.1,
    }
    return change_setting_from_dict(settings, call_pixie=call_pixie)
