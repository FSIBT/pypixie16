"""Read list mode data

The file provides a python based list mode data parser.

The input can either come from a data stream or from one or several
binary files (in case a large binary data set is split across multiple
files).

We keep all the data in numpy arrays, whic are either memmaped or
pre-allocated, to make data access fast.

"""

from collections import defaultdict
from collections.abc import Iterable
from itertools import islice
from pathlib import Path
from typing import Union

import numpy as np
import pandas as pd
import struct

import msgspec
import math


def unpack_header(data):
    """Extract header fields from 16 bytes using bitwise operations.

    Format: b1u14u5u4u4u4u32u3u13u16b1u15u16
    Fields: pileup, Event Length, Header Length, crate, slot, channel,
            EVTTIME_LO, CFD trigger source bits, CFD Fractional Time,
            EVTTIME_HI, trace_flag, Trace Length, energy

    Note: Works on little-endian data bytes directly from mmap.
    """
    # Unpack as 4 little-endian 32-bit words (works with bytes or buffer)
    w0, w1, w2, w3 = struct.unpack_from("<4I", data, 0)

    # Word 0: pileup(1) | Event Length(14) | Header Length(5) | crate(4) | slot(4) | channel(4)
    pileup = bool((w0 >> 31) & 0x1)
    event_length = (w0 >> 17) & 0x3FFF
    header_length = (w0 >> 12) & 0x1F
    crate = (w0 >> 8) & 0xF
    slot = (w0 >> 4) & 0xF
    channel = w0 & 0xF

    # Word 1: EVTTIME_LO (32 bits)
    evttime_lo = w1

    # Word 2: CFD trigger source bits(3) | CFD Fractional Time(13) | EVTTIME_HI(16)
    cfd_trigger = (w2 >> 29) & 0x7
    cfd_frac = (w2 >> 16) & 0x1FFF
    evttime_hi = w2 & 0xFFFF

    # Word 3: trace_flag(1) | Trace Length(15) | energy(16)
    trace_flag = bool((w3 >> 31) & 0x1)
    trace_length = (w3 >> 16) & 0x7FFF
    energy = w3 & 0xFFFF

    return {
        "pileup": pileup,
        "Event Length": event_length,
        "Header Length": header_length,
        "crate": crate,
        "slot": slot,
        "channel": channel,
        "EVTTIME_LO": evttime_lo,
        "CFD trigger source bits": cfd_trigger,
        "CFD Fractional Time": cfd_frac,
        "EVTTIME_HI": evttime_hi,
        "trace_flag": trace_flag,
        "Trace Length": trace_length,
        "energy": energy,
    }


def unpack_energy(data):
    """Extract energy sum fields from 16 bytes (4 32-bit words).

    Format: u32 u32 u32 f32
    Fields: Esum_trailing, Esum_leading, Esum_gap, baseline
    """
    # Unpack as 3 little-endian uint32 and 1 little-endian float32 (works with bytes or buffer)
    esum_trailing, esum_leading, esum_gap, baseline = struct.unpack_from(
        "<3If", data, 0
    )

    return {
        "Esum_trailing": esum_trailing,
        "Esum_leading": esum_leading,
        "Esum_gap": esum_gap,
        "baseline": baseline,
    }


def unpack_qsums(data):
    """Extract QDC sum fields from 32 bytes (8 32-bit words).

    Format: u32 * 8
    Fields: QDCSum0-7
    """
    # Unpack as 8 little-endian uint32 (works with bytes or buffer)
    qsums = struct.unpack_from("<8I", data, 0)

    return {f"QDCSum{i}": qsums[i] for i in range(8)}


def unpack_ext_time(data):
    """Extract extended timestamp from 8 bytes (2 32-bit words).

    Format: u32 p16 u16 (p16 means 16 padding bits)
    Fields: Ext_TS_Lo, Ext_TS_Hi
    """
    # Unpack as 2 little-endian uint32 (works with bytes or buffer)
    ext_ts_lo, ext_ts_hi_word = struct.unpack_from("<2I", data, 0)

    return {
        "Ext_TS_Lo": ext_ts_lo,
        "Ext_TS_Hi": ext_ts_hi_word & 0xFFFF,  # Take lower 16 bits
    }


def unpack_extra_header(data, extra_header_length):
    """Unpack additional header data based on length.

    Args:
        data: Byte data (from byteswapped numpy array)
        extra_header_length: Number of 32-bit words in extra header

    Raises:
        KeyError: If extra_header_length is not a valid value (indicates corrupt data)
    """
    # Valid extra header lengths
    valid_lengths = {2, 4, 6, 8, 10, 12, 14}

    if extra_header_length not in valid_lengths:
        # Raise KeyError to match original behavior (for out-of-order file detection)
        raise KeyError(extra_header_length)

    if hasattr(data, "tobytes"):
        data = data.tobytes()

    result = {}
    byte_offset = 0

    # Determine what fields are present based on length
    # Order: energy (4 words=16 bytes), qsums (8 words=32 bytes), ext_time (2 words=8 bytes)

    if extra_header_length in [4, 6, 12, 14]:
        # Has energy fields (16 bytes)
        result.update(unpack_energy(data[byte_offset : byte_offset + 16]))
        byte_offset += 16

    if extra_header_length in [8, 10, 12, 14]:
        # Has qsum fields (32 bytes)
        result.update(unpack_qsums(data[byte_offset : byte_offset + 32]))
        byte_offset += 32

    if extra_header_length in [2, 6, 10, 14]:
        # Has extended timestamp (8 bytes)
        result.update(unpack_ext_time(data[byte_offset : byte_offset + 8]))
        byte_offset += 8

    return result


class Event(msgspec.Struct):
    """Data storage for a single event that has attribute access.

    This is similar to a namedtuple, but the msgspec implemenation is faster.
    """

    channel: int = -1
    crate: int = -1
    slot: int = -1
    timestamp: float = -1.0
    CFD_fraction: int = -1
    energy: int = -1
    trace: int = -1
    CFD_error: int = -1
    pileup: int = -1
    trace_flag: int = -1
    Esum_trailing: int = -1
    Esum_leading: int = -1
    Esum_gap: int = -1
    baseline: float = -1.0
    QDCSum0: int = -1
    QDCSum1: int = -1
    QDCSum2: int = -1
    QDCSum3: int = -1
    QDCSum4: int = -1
    QDCSum5: int = -1
    QDCSum6: int = -1
    QDCSum7: int = -1
    ext_timestamp: float = -1.0
    chunk_timestamp: float = -1  # not a pixie16 field

    def to_list(self):
        return (getattr(self, f) for f in self.__struct_fields__)


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

    or one needs to call self.open_files() and self.close_files()
    manually.

    """

    def __init__(self, files: Iterable[Path]):
        self.current_file = 0  # which file do we need to read from
        self.files = files  # list of all files
        self.file_size = []
        self.position = 0  # relative to the current file
        self.mmap = []
        self.done = False  # have we reached the end of the last file?

    def open_files(self):
        for f in self.files:
            self.mmap.append(np.memmap(f, dtype=np.uint32, mode="r"))
            self.file_size.append(len(self.mmap[-1]))

    def close_files(self):
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

    def advance(self, size: int):
        """Not needed, since all the data is in the files and we can
        just advance the file position during read()"""
        pass

    def read(self, size: int, offset: int = 0) -> bytes:
        """Retrieve the next `size` bytes from the files and advance the file position.

        Parameters
        ----------
        size
            How many bytes should be returned.
        offset
            ignored here (used in Streamreader)

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

        rest = self.read(to_read)
        if tmp.size > 0:
            return np.concatenate((tmp, rest))
        else:
            return rest


class StreamReader:
    """Handle streamed binary data.

    Provides the same interface as FileReader and can be used as a direct replacement.

    New data can be added using the `put` method.

    Internally we store the data in a np.array of np.uint32.

    We make the array large enough to hold the data and have the
    buffer grow and shrink as needed.

    This is similar to a ring buffer, but we just allocate twice the buffer
    size memory and then keep track of the left and right position in
    the buffer and shift the data to the far left every now and then.

    """

    def __init__(self, initial_buffer_size=25_000_000) -> None:
        self.buffer_size = initial_buffer_size
        self.buffer_size_orig = self.buffer_size
        self.buffer = np.empty(2 * self.buffer_size, dtype=np.uint32)
        self.left = 0
        self.right = 0

    def put(self, input: np.ndarray) -> None:
        """Add data to the buffer.

        Also increase/decrease the buffer size as needed.
        """

        L = input.size
        current = self.right - self.left

        buffer_size_change = False
        # adjust buffer so that it will be large enough for the new data
        while current + L >= self.buffer_size:
            self.buffer_size *= 2
            buffer_size_change = True

        # Can we shrink the buffer?
        while (self.buffer_size > self.buffer_size_orig) and (
            current + L < self.buffer_size // 2
        ):
            self.buffer_size = self.buffer_size // 2
            buffer_size_change = True

        # check if we need to shift the buffer
        if self.left > self.buffer_size or buffer_size_change:
            self.adjust_and_shift_buffer()

        # add input
        self.buffer[self.right : self.right + L] = input
        self.right += L

    def adjust_and_shift_buffer(self) -> None:
        """Create a new buffer and copy the old buffer to beginning.

        This also takes care of changing the size of the buffer
        """
        if (self.left == 0) and (self.buffer.size == self.buffer_size):
            return

        current = self.right - self.left
        tmp = np.empty(2 * self.buffer_size, dtype=np.uint32)
        tmp[:current] = self.buffer[self.left : self.right]
        self.buffer = tmp
        self.left = 0
        self.right = current

    def read(self, size: int, offset: int = 0) -> np.ndarray:
        """Return `size` 32-bit words from the buffer as a numpy array.

        In the streamreader, there might be an incomplete event at the end of the buffer.
        However, we have several read statements to read a single event. We cannot advance
        self.left directly, unless we read a whole event (up to 3 read()). `offset` is used to
        read partial data and advance() is used to move self.left once a full event is read.
        """
        current = self.right - (self.left + offset)
        if size <= current:
            out = self.buffer[self.left + offset : self.left + offset + size]
            return out
        raise EmptyError

    def advance(self, size: int) -> None:
        """Advance self.left once a full event is read (possible after multiple read statement)"""
        self.left += size

    def __len__(self):
        """Return the amount of data in the buffer."""
        return self.right - self.left


class ListModeDataReader:
    def __init__(self, reader: FileReader | StreamReader):
        self.reader = reader

    def pop(self) -> Event:
        """Pop the top event from queue"""

        # Read header (4 32-bit words = 16 bytes) and extract fields using bitwise operations
        header_data = self.reader.read(4)
        h = unpack_header(header_data)

        header_length = h["Header Length"]
        extra_header_length = header_length - 4
        event_length = h["Event Length"]

        # Read additional header fields if present
        if extra_header_length > 0:
            extra_data = self.reader.read(extra_header_length, 4)
            # Will raise KeyError if extra_header_length is invalid (corrupt/out-of-order data)
            event_values = unpack_extra_header(extra_data, extra_header_length)
            h.update(event_values)

        # Read trace data if present
        trace_length = event_length - header_length
        if trace_length:
            trace_words = self.reader.read(trace_length, header_length)
            # Reinterpret uint32 array as uint16 - each 32-bit word contains two 16-bit samples
            trace = trace_words.view(np.uint16)
        else:
            trace = ()

        # if reader is a filereader, reader.read() will already advance the positions
        # in streamreader, we might still be waiting for more data from the pixie
        # The workaround is to only remove event once all read operation worked and
        # have read() not advance the buffer location.
        self.reader.advance(event_length)

        # Calculate derived fields
        CFD_bits = h["CFD trigger source bits"]
        CFD_error = bool(CFD_bits == 7)
        CFD_fractional_time = h["CFD Fractional Time"]
        CFD_fraction = (
            0 if CFD_bits == 7 else ((CFD_bits - 1) + CFD_fractional_time / 8192) * 2
        )

        timestamp = (h["EVTTIME_LO"] + h["EVTTIME_HI"] * 2**32) * 10

        # Build Event kwargs - start with always-present fields
        kwargs = {
            "channel": h["channel"],
            "crate": h["crate"],
            "slot": h["slot"],
            "energy": h["energy"],
            "timestamp": timestamp,
            "CFD_fraction": CFD_fraction,
            "trace": trace,
            "CFD_error": CFD_error,
            "pileup": h["pileup"],
            "trace_flag": h["trace_flag"],
        }

        # Add optional fields if present (avoids .get() overhead for missing keys)
        if "Esum_trailing" in h:
            kwargs["Esum_trailing"] = h["Esum_trailing"]
            kwargs["Esum_leading"] = h["Esum_leading"]
            kwargs["Esum_gap"] = h["Esum_gap"]
            kwargs["baseline"] = h["baseline"]

        if "QDCSum0" in h:
            kwargs["QDCSum0"] = h["QDCSum0"]
            kwargs["QDCSum1"] = h["QDCSum1"]
            kwargs["QDCSum2"] = h["QDCSum2"]
            kwargs["QDCSum3"] = h["QDCSum3"]
            kwargs["QDCSum4"] = h["QDCSum4"]
            kwargs["QDCSum5"] = h["QDCSum5"]
            kwargs["QDCSum6"] = h["QDCSum6"]
            kwargs["QDCSum7"] = h["QDCSum7"]

        if "Ext_TS_Lo" in h:
            kwargs["ext_timestamp"] = h["Ext_TS_Lo"] + h["Ext_TS_Hi"] * 2**32

        return Event(**kwargs)

    def iterevents(self):
        """Will raise an exception to exit loop."""
        while True:
            yield self.pop()

    def pop_all(self):
        out = []
        while True:
            try:
                event = self.pop()
            except (EmptyError, LeftoverBytesError):
                break
            out.append(event)
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


def timestamps_and_sizes_from_files_generator(files):
    """Yields (timestamp, event_length_words) for each event in binary files."""
    try:
        with FileReader(files) as r:
            while not r.done:
                header_data = r.read(4)
                event_header = unpack_header(header_data)

                header_length = event_header["Header Length"]
                extra_header_length = header_length - 4
                event_length = event_header["Event Length"]

                if extra_header_length > 0:
                    r.read(extra_header_length, 4)

                trace_length = event_length - header_length
                if trace_length:
                    r.read(trace_length, header_length)

                timestamp = (
                    event_header["EVTTIME_LO"] + event_header["EVTTIME_HI"] * 2**32
                ) * 10
                yield timestamp, event_length
    except (EmptyError, LeftoverBytesError):
        return


def data_rate_from_file(files):
    """
    Calculate the data rate in MB/s from a list of binary files.
    Returns a dictionary with the data rate for each second in the data set.
    """
    timestamps = []
    bits = []

    for timestamp, word in timestamps_and_sizes_from_files_generator(files):
        timestamps.append(timestamp)
        bits.append(word * 32)  # word size is 32 bits

    if not timestamps:
        return 0

    data = {}
    for t, b in zip(timestamps, bits):
        sec = math.floor(t * 1e-9)
        if sec not in data:
            data[sec] = 0
        data[sec] += b

    # Convert to MB/s
    data_rate = {sec: b / (8 * 1024 * 1024) for sec, b in data.items()}
    return data_rate


def to_tuple(obj):
    if isinstance(obj, str | Path):
        obj = [obj]
    else:
        try:
            obj = tuple(obj)
        except TypeError:
            obj = obj
    return obj


def read_list_mode_data(files, buffer_size=int(1e9)):
    """Loads a list of binary files into a pandas DataFrame.

    Note: the binary files need to be ordered correctly, in case an
    event is distributed across two files.

    """
    files = to_tuple(files)
    try:
        events = (e.to_list() for e in events_from_files_generator(files))
    except KeyError:
        print(
            "A possible reason for this error is that the files are not in the same"
            "order as received from the pixie."
        )
        raise
    return pd.DataFrame.from_records(events, columns=Event.__struct_fields__)


def read_list_mode_data_as_events(files, buffer_size=int(1e9), max_size=None):
    """Returns a list of at most max_size events from files.

    Note: the binary files need to be ordered correctly, in case an
    event is distributed across two files.

    """
    files = to_tuple(files)
    try:
        gen = events_from_files_generator(files)
        out = list(islice(gen, max_size))
    except KeyError:
        print(
            "A possible reason for this error is that the files are not in the same"
            "order as received from the pixie."
        )
        raise
    return out


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
