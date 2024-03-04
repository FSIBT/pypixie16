"""Read list mode data

The file provides a python based list mode data parser.

The input can either come from a data stream or from one or several
binary files (in case a large binary data set is split across multiple
files).

"""


import mmap
from pathlib import Path

import numpy as np

try:
    import cbitstruct as bitstruct
except ModuleNotFoundError:
    import bitstruct

from collections import namedtuple, defaultdict
from collections.abc import Iterable
from itertools import islice
from typing import Union, Optional

import pandas as pd
from rich import print


Event = namedtuple(
    "Event",
    (
        "channel",
        "crate",
        "slot",
        "timestamp",
        "CFD_fraction",
        "energy",
        "trace",
        "CFD_error",
        "pileup",
        "trace_flag",
        "Esum_trailing",
        "Esum_leading",
        "Esum_gap",
        "baseline",
        "QDCSum0",
        "QDCSum1",
        "QDCSum2",
        "QDCSum3",
        "QDCSum4",
        "QDCSum5",
        "QDCSum6",
        "QDCSum7",
        "ext_timestamp",
        "chunk_timestamp",  # not a pixie16 field
    ),
    # note that defaults are aligned to the end and value without defaults are mandatory
    defaults=(-1, -1, -1, -1.0, -1, -1, -1, -1, -1, -1, -1, -1, -1.0, -1.0),
)


WORD_SIZE = 4

EVENTS_PARTS = {
    "header": (
        "b1u14u5u4u4u4u32u3u13u16b1u15u16",
        (
            "pileup",
            "Event Length",
            "Header Length",
            "crate",
            "slot",
            "channel",
            "EVTTIME_LO",
            "CFD trigger source bits",
            "CFD Fractional Time",
            "EVTTIME_HI",
            "trace_flag",
            "Trace Length",
            "energy",
        ),
    ),
    "energy": (
        "u32" * 3 + "f32",
        (
            "Esum_trailing",
            "Esum_leading",
            "Esum_gap",
            "baseline",
        ),
    ),
    "Qsums": (
        "u32" * 8,
        (
            "QDCSum0",
            "QDCSum1",
            "QDCSum2",
            "QDCSum3",
            "QDCSum4",
            "QDCSum5",
            "QDCSum6",
            "QDCSum7",
        ),
    ),
    "Ext Time": (
        "u32p16u16",
        (
            "Ext_TS_Lo",
            "Ext_TS_Hi",
        ),
    ),
}

# We now build all possible combinations out of these parts that can
# show up in list mode data We also add a "0" option to just read the
# first row, since this row contains the header length we need to read
HEADER_FORMATS = bitstruct.CompiledFormatDict(
    EVENTS_PARTS["header"][0], EVENTS_PARTS["header"][1]
)
EXTRA_HEADER_FORMATS = {
    2: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["Ext Time"][0],
        EVENTS_PARTS["Ext Time"][1],
    ),
    4: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["energy"][0],
        EVENTS_PARTS["energy"][1],
    ),
    8: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["Qsums"][0],
        EVENTS_PARTS["Qsums"][1],
    ),
    12: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["energy"][0] + EVENTS_PARTS["Qsums"][0],
        EVENTS_PARTS["energy"][1] + EVENTS_PARTS["Qsums"][1],
    ),
    6: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["energy"][0] + EVENTS_PARTS["Ext Time"][0],
        EVENTS_PARTS["energy"][1] + EVENTS_PARTS["Ext Time"][1],
    ),
    10: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["Qsums"][0] + EVENTS_PARTS["Ext Time"][0],
        EVENTS_PARTS["Qsums"][1] + EVENTS_PARTS["Ext Time"][1],
    ),
    14: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["energy"][0]
        + EVENTS_PARTS["Qsums"][0]
        + EVENTS_PARTS["Ext Time"][0],
        EVENTS_PARTS["energy"][1]
        + EVENTS_PARTS["Qsums"][1]
        + EVENTS_PARTS["Ext Time"][1],
    ),
}


def byteswap_data(bytes_data):
    """returns bytes correctly byteswapped and in word sizes"""
    n_words = len(bytes_data) // WORD_SIZE
    data = bitstruct.byteswap(str(WORD_SIZE) * n_words, bytes_data)
    return data


class EmptyError(Exception):
    """We reached the end of the last file."""


class LeftoverBytesError(Exception):
    """To be raised if a partial event is left in the byte stream/file."""


class FileReader:
    """Read binary data from multiple files.

    Use mmap for fast data access to binary data on disc. The data can
    be distributed across several files.

    This class should  be used as a context manager:
    >>> files = ("file1.bin", "file2.bin")
    >>> with FileReader(files) as r:
    >>>     r.read(100)

    """

    def __init__(self, files: Iterable[Path]):
        self.current_file = 0  # which file do we need to read from
        self.files = files  # list of all files
        self.file_objects = []  # list of opened files
        self.file_size = []
        self.position = 0  # relative to the current file
        self.mmap = []
        self.done = False  # have we reached the end of the last file?

    def open_files(self):
        for f in self.files:
            if not isinstance(f, Path):
                f = Path(f)
            self.file_objects.append(f.open("rb"))
            self.file_size.append(f.stat().st_size)

        for fn in self.file_objects:
            self.mmap.append(mmap.mmap(fn.fileno(), length=0, access=mmap.ACCESS_READ))

    def close_files(self):
        for m in self.mmap:
            m.close()
        for f in self.file_objects:
            f.close()
        self.file_size = []
        self.file_objects = []
        self.mmap = []
        self.current_file = 0

    def __enter__(self):
        """Opens all files, check their sizes and open a mmap read_only connection."""
        self.open_files()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Closes all file descriptors and mmaps at the end of the context manager."""
        self.close_files()

    def read_raw(self, size: int) -> bytes:
        """Retrieve the next `size` bytes from the files and advance the file position.

        Parameters
        ----------
        size
            How many bytes should be returned.

        Raises
        ------
        EmptyError
            When data of the requested size is not available in the data stream.

        """
        if self.done:
            raise EmptyError()

        end = size + self.position
        if end <= self.file_size[self.current_file]:
            out = self.mmap[self.current_file][self.position : end]
            self.position += size
            return out

        tmp = self.mmap[self.current_file][self.position :]
        to_read = size - len(tmp)

        self.current_file += 1
        self.position = 0

        if self.current_file == len(self.files):
            self.done = True
            if len(tmp) == 0:
                raise EmptyError
            raise LeftoverBytesError

        rest = self.read_raw(to_read)
        return tmp + rest

    def read(self, size: int) -> bytes:
        """Retrieve the next `size` bytes from the files in byteswapped order.

        Parameters
        ----------
        size
            How many bytes should be returned.

        """

        out = self.read_raw(size)
        return byteswap_data(out)


class StreamReader:
    """Handle streamed binary data.

    Provides the same interface as FileReader and can be used as a direct replacement.

    New data can be added using the `put` method.

    """

    def __init__(self) -> None:
        self.buffer = bytearray()

    def put(self, input: bytes) -> None:
        self.buffer.extend(input)

    def read_raw(self, size: int) -> bytes:
        if size < len(self.buffer):
            out = self.buffer[:size]
            del self.buffer[:size]
            return out
        raise EmptyError

    def read(self, size: int) -> bytes:
        out = self.read_raw(size)
        return byteswap_data(out)

    def __len__(self):
        return len(self.buffer)


class ListModeDataReader:
    def __init__(self, reader: Union[FileReader, StreamReader]):
        self.reader = reader

    # @profile
    def pop(self) -> Event:
        """Pop the top event from queue"""

        # try to get all the words for the next event
        # if the complete next event isn't in queue an exception is thrown but no data is discarded
        event_header = HEADER_FORMATS.unpack(self.reader.read(4 * WORD_SIZE))
        header_length = event_header["Header Length"]
        extra_header_length = header_length - 4
        event_length = event_header["Event Length"]

        # it's now save to read both header and trace
        if extra_header_length > 0:
            header_words = self.reader.read(extra_header_length * WORD_SIZE)
            # unpack words/trace into their field values
            try:
                event_values = EXTRA_HEADER_FORMATS[extra_header_length].unpack(
                    header_words
                )
                event_header.update(**event_values)
            except KeyError:
                print("Something went wrong with the binary data.")
                raise

        trace_length = event_length - header_length
        if trace_length:
            trace_data = self.reader.read_raw(trace_length * WORD_SIZE)
            trace = np.frombuffer(trace_data, f"({trace_length},2)<u2", count=1)[
                0, :, :
            ]
            trace = trace.flatten()
        else:
            trace_data = None
            trace = ()

        # calculate event values that need to be derived from field values
        CFD_bits = event_header.pop("CFD trigger source bits")
        CFD_error = CFD_bits == 7
        CFD_fractional_time = event_header.pop("CFD Fractional Time")
        if CFD_bits == 7:
            CFD_fraction = 0
        else:
            CFD_fraction = ((CFD_bits - 1) + CFD_fractional_time / 8192) * 2

        timestamp = (
            event_header.pop("EVTTIME_LO") + event_header.pop("EVTTIME_HI") * 2**32
        ) * 10

        if "Ext_TS_Lo" in event_header:
            ext_timestamp = (
                event_header.pop("Ext_TS_Lo") + event_header.pop("Ext_TS_Hi") * 2**32
            )

            event_header.update({"ext_timestamp": ext_timestamp})

        for key in ["Event Length", "Header Length", "Trace Length"]:
            if key in event_header:
                del event_header[key]

        event_header.update(
            {
                "timestamp": timestamp,
                "CFD_fraction": CFD_fraction,
                "trace": trace,
                "CFD_error": CFD_error,
            }
        )

        return Event(**event_header)

    def iterevents(self):
        while True:
            yield self.pop()

    def pop_all(self):
        out = []
        try:
            while True:
                out.append(self.iterevents())
        except (EmptyError, LeftoverBytesError):
            return out


def events_from_files_generator(files):
    """Yields events from a list of binary files"""
    try:
        with FileReader(files) as r:
            reader = ListModeDataReader(r)
            while not reader.reader.done:
                yield from reader.iterevents()
    except (EmptyError, LeftoverBytesError):
        return


def to_tuple(obj):
    if isinstance(obj, (str, Path)):
        obj = [obj]
    else:
        try:
            obj = tuple(obj)
        except TypeError:
            obj = obj
    return obj


def read_list_mode_data(files, buffer_size=int(1e9)):
    """Loads a list of binary files into a pandas DataFrame"""
    files = to_tuple(files)
    events = tuple(events_from_files_generator(files))
    return pd.DataFrame.from_records(events, columns=Event._fields)


def read_list_mode_data_as_events(files, buffer_size=int(1e9), max_size=None):
    """Returns a list of at most max_size events from files"""
    files = to_tuple(files)
    gen = events_from_files_generator(files)
    return list(islice(gen, max_size))


def sort_events_by_channel(events, channel_list=None):
    """Sort events by channel.

    Takes the output of `read_list_mode_data_as_events` and sorts them
    into a dictionary that has the channel number as key and as value
    a list of events (still including the channel number).

    Parameters
    ----------
    events
        List of events as returned by `read_list_mode_data_as_events`
    channel_list
        Optional list of channels to include. This can help to reduce
        the amount of data.

    """

    out = defaultdict(list)

    for e in events:
        ch = e.channel
        if channel_list is not None and ch in channel_list:
            out[ch].append(e)
        else:
            out[ch].append(e)

    return out
