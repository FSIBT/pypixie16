"""Python interface to controlling the pixie16.

Consists of python calls directly to two C-libraries provided by XIA and
some high level functions to make running the pixie16 easier in python.

At the moment this also only supports Windows and needs python32 to run.

"""

from contextlib import contextmanager
from collections import OrderedDict
import datetime
import logging
from pathlib import Path
import sys
import time
from typing import Iterable, List, Tuple, Dict, Union, Optional, ByteString

import numpy as np
import tqdm

from .config import config, inifile, data_dir
from .C_library_app import *
from .C_library_sys import *

# set up logging
log = logging.getLogger(__name__)


def set_sync_mode(modules: Iterable[int]) -> None:
    """Turn on sync mode for every module."""
    for m, _ in enumerate(modules):
        WriteModParam("SYNCH_WAIT", 1, m)
        WriteModParam("IN_SYNCH", 0, m)


def list_firmware() -> None:
    """List all firmwars defined in the config files"""
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
        f'Use only the name after the "." for the name of'
        f' the firmware: {", ".join(names)}'
    )


def set_traces(module: int, channel: int, status: bool) -> None:
    """Turn on/off taking traces for a certain channel in a specific module"""

    channel_setting = ReadChanParam("CHANNEL_CSRA", module, channel)
    # we need to set bit eight
    # in python we can address the last element as -1, which is bit 0, so bit 8 is -9
    channel_setting[-9] = status
    WriteChanParam("CHANNEL_CSRA", channel_setting, module, channel)


def empty_fifo(module: int) -> None:
    """Read all data in a fifo of a specific module and discard it."""

    while ReadFIFOStatus(module):
        number_of_words = ReadFIFOStatus(module)
        ReadFIFO(i, number_of_words)


def empty_all_fifos(modules: Iterable[int]) -> None:
    """Read data from all fifos and discard it."""

    for m in modules:
        empty_fifo(m)


def read_list_mode_fifo(
    check: bool = True, threshold: int = 1024, modules: Optional[Iterable[int]] = None
) -> List[np.ndarray]:
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

    if modules is None:
        modules = [2]

    if check:
        do_read = False
        for i in range(len(modules)):
            number_of_words = ReadFIFOStatus(i)
            if number_of_words > threshold:
                do_read = True
                break
    else:
        do_read = True

    output = []
    if do_read:
        for i in range(len(modules)):
            number_of_words = ReadFIFOStatus(i)
            if number_of_words > 0:
                data = ReadFIFO(i, number_of_words)
            else:
                data = np.array([], dtype=np.uint32)
            output.append(data)

    return output


def run_list_mode(filename: Optional[str] = None, runtime: int = 5) -> None:
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

        for i, _ in enumerate(modules):
            EndRun(i)
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
    change_setting_dict(settings, auto_update=False)


def enable_trace_settings(
    channels: Iterable[List[int]], disable_CFD: bool = True
) -> None:
    """Enable traces, historgrams, and sums.

    Also turn CFD settings off (or optionally leave unchanged).

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
    change_setting_dict(settings, auto_update=False)

    if disable_CFD:
        print("[INFO] traces: turned CFD off")
        settings = OrderedDict({"channels": channels, "EnableCFD": False})
        change_setting_dict(settings, auto_update=False)


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
            "HostRunTimePreset": converter_IEEE754_to_ulong(duration).value,
        }
    )
    change_setting_dict(settings, auto_update=False)

    modules = list({x for x, y in channels})

    # take MCA spectra
    if verbose:
        print("[INFO] Taking MCA spectrum", end="", flush=True)

    start_histogram_run()
    sys.stdout.flush()
    time.sleep(0.5)

    start = time.time()
    keep_running = True
    with tqdm.tqdm(
        total=duration, desc="MCA", unit="s", unit_scale=True, position=position
    ) as pbar_mca:
        while keep_running and (time.time() - start < duration):
            keep_running = False
            for m, _ in enumerate(modules):
                r = CheckRunStatus(m)
                sys.stdout.flush()
                if r == 1:
                    keep_running = True
            time.sleep(1)
            dt = round(time.time() - start, 2)
            pbar_mca.update(dt - pbar_mca.n)
        pbar_mca.update(duration - pbar_mca.n)
    print()
    for m, _ in enumerate(modules):
        EndRun(m)

    data = [ReadHistogramFromModule(m, c) for m, c in channels]
    return data


def take_list_mode_data(
    modules: Iterable[int], duration: float
) -> Dict[int, ByteString]:
    """Take list mode data for a certain time.

    It also stops at 1 Gb of raw data to avoid too much memory use.
    If you want to take mor data, you need to use another mechanism
    and write the data to disk more often.

    Parameters
    ----------
    modules
       List of modules
    duration
       Length in seconds of how long data is acquired for

    Returns
    -------
    dict[int, ByteString]
       Dictionary with the raw binary data in it. Each module gets is a key
       in the dictionary and the values are the bytestring.

    """

    start_listmode_run()

    # initialize output module
    raw_data = {i: b"" for i, _ in enumerate(modules)}

    start = time.time()
    raw_data_length = 0

    with tqdm.tqdm(
        total=duration, desc="Traces", unit="s", unit_scale=True
    ) as pbar_traces:
        while (time.time() - start < duration) and (raw_data_length < 1e9):
            data = read_list_mode_fifo(threshold=32 * 1024)
            for i, d in enumerate(data):
                if d is not None:
                    raw_data[i] += d.tobytes()
                    raw_data_length += len(d)
            dt = round(time.time() - start, 2)
            pbar_traces.update(dt - pbar_traces.n)
        pbar_traces.update(duration - pbar_traces.n)
    print()

    # stop run
    for i, _ in enumerate(modules):
        EndRun(i)

    time.sleep(0.5)

    # read remainig data in queue
    tmp = read_list_mode_fifo(check=False)
    if tmp:
        for i, _ in enumerate(modules):
            if tmp[i] is not None:
                raw_data[i] += tmp[i].tobytes()

    return raw_data


@contextmanager
def temporary_settings(modules: Iterable[int]) -> None:
    """Making it easy to temporary change settings in the pixie16.

    A context manager that will remember the current setting, execute
    some code that can change those settings, and then reset the
    setting back to the original.

    """

    # get the current settings
    current_settings = [read_raw_settings(m, N=1280) for m, _ in enumerate(modules)]

    try:
        yield None  # this is were the code gets executed
    finally:
        # write the old settings back
        for m, _ in enumerate(modules):
            write_raw_settings(m, current_settings[m])
