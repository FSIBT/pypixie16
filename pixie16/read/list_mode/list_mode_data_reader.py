"""implementation of queues for parsing list mode data from the pixie16"""


from collections import namedtuple, deque
from itertools import islice
from pathlib import Path
from typing import Union

import cbitstruct as bitstruct
import numpy as np
import pandas as pd
from rich import print

WORD_SIZE = 4

# chunk_timestamp is a field that doesn't come from the pixie
# it can be used to for example store a unix time stamp when the data was converted
# tasks/SortEvents uses it for example this way.
Event = namedtuple(
    "Event",
    [
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
    ],
    # note that defaults are aligned to the end and value without defaults are mandatory
    defaults=(-1, -1, -1, -1.0, -1, -1, -1, -1, -1, -1, -1, -1, -1.0, -1.0),
)


def byteswap_data(bytes_data):
    """returns bytes correctly byteswapped and in word sizes"""
    n_words = len(bytes_data) // WORD_SIZE
    data = bitstruct.byteswap(str(WORD_SIZE) * n_words, bytes_data)
    return data


class EmptyError(Exception):
    """To be raised if an empty queue is popped or peeked"""


class LeftoverBytesError(Exception):
    """To be raised if a queue with a partial word/event left is popped or peeked"""


class WordsIO:
    """A binary data FIFO queue/transformer.

    Put in binary data as any sized bytes or bytearray objects and
    take them out as Pixie16 word sized/formatted bytes (refer to user
    manual List Mode Data Structures section).

    """

    def __init__(self, binary_data: Union[bytes, bytearray] = b""):
        """Initialize queue"""
        self.binary_data = bytearray(binary_data)
        self.last_data = deque(maxlen=5)  # used for debugging

    def __len__(self):
        """Number of bytes in queue"""
        return len(self.binary_data)

    def is_empty(self):
        """Utility function to indicate if there is no bytes left in the queue"""
        return len(self) == 0

    def put(self, additional_binary_data: Union[bytes, bytearray]):
        """Put more bytes into queue"""
        self.binary_data.extend(additional_binary_data)

    def pop(self, size: int, raw=False):
        """Pop the top size words from queue"""
        res = self.peek(size, raw=raw)
        del self.binary_data[: size * WORD_SIZE]
        self.last_data.append(res)
        return res

    def assert_data_is_available(self, size: int):
        """Make sure `size` words are available."""
        if size * WORD_SIZE > len(self):
            raise LeftoverBytesError(
                f"Requested {size} words, only {len(self)//WORD_SIZE} words in object"
            )

    def peek(self, size: int, raw=False):
        """Get the top size words from queue without removing them.

        Return either tuple of WORD-sized, byte-swapped data (raw==False)
        or just raw bytes (raw==True).
        """
        if self.is_empty():
            raise EmptyError()

        self.assert_data_is_available(size)

        if raw:
            return self.binary_data[: size * WORD_SIZE]
        return byteswap_data(self.binary_data[: size * WORD_SIZE])


# Events in list mode consist of one mandatory group ("header") and 3 optional groups
# for energy sums, Qsums, and an external timestamp
# we define the corresponding bit patterns to be used with bitstruct here, see
# page 72 of the pixie16 manual, version 3.06
EVENTS_PARTS = {
    "first row": (
        "b1u14u5u4u4u4",
        ("pileup", "Event Length", "Header Length", "crate", "slot", "channel"),
    ),
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
HEADER_FORMATS = {
    0: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["first row"][0], EVENTS_PARTS["first row"][1]
    ),
    4: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["header"][0], EVENTS_PARTS["header"][1]
    ),
    6: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["header"][0] + EVENTS_PARTS["Ext Time"][0],
        EVENTS_PARTS["header"][1] + EVENTS_PARTS["Ext Time"][1],
    ),
    8: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["header"][0] + EVENTS_PARTS["energy"][0],
        EVENTS_PARTS["header"][1] + EVENTS_PARTS["energy"][1],
    ),
    12: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["header"][0] + EVENTS_PARTS["Qsums"][0],
        EVENTS_PARTS["header"][1] + EVENTS_PARTS["Qsums"][1],
    ),
    16: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["header"][0]
        + EVENTS_PARTS["energy"][0]
        + EVENTS_PARTS["Qsums"][0],
        EVENTS_PARTS["header"][1]
        + EVENTS_PARTS["energy"][1]
        + EVENTS_PARTS["Qsums"][1],
    ),
    10: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["header"][0]
        + EVENTS_PARTS["energy"][0]
        + EVENTS_PARTS["Ext Time"][0],
        EVENTS_PARTS["header"][1]
        + EVENTS_PARTS["energy"][1]
        + EVENTS_PARTS["Ext Time"][1],
    ),
    14: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["header"][0]
        + EVENTS_PARTS["Qsums"][0]
        + EVENTS_PARTS["Ext Time"][0],
        EVENTS_PARTS["header"][1]
        + EVENTS_PARTS["Qsums"][1]
        + EVENTS_PARTS["Ext Time"][1],
    ),
    18: bitstruct.CompiledFormatDict(
        EVENTS_PARTS["header"][0]
        + EVENTS_PARTS["energy"][0]
        + EVENTS_PARTS["Qsums"][0]
        + EVENTS_PARTS["Ext Time"][0],
        EVENTS_PARTS["header"][1]
        + EVENTS_PARTS["energy"][1]
        + EVENTS_PARTS["Qsums"][1]
        + EVENTS_PARTS["Ext Time"][1],
    ),
}


def calc_cfd_error(cfd_trigger_source_bits):
    return cfd_trigger_source_bits == 7


def calc_cfd_fraction(cfd_trigger_source_bits, cfd_fractional_time):
    if calc_cfd_error(cfd_trigger_source_bits):
        return 0
    else:
        return ((cfd_trigger_source_bits - 1) + cfd_fractional_time / 8192) * 2


class ListModeDataReader:
    """A binary data FIFO queue/transformer.

    Put in binary data as any sized bytes or bytearray objects and
    take them out as Pixie16 events (refer to user manual List Mode
    Data Structures section).

    """

    def __init__(self, binary_data: Union[bytes, bytearray] = b""):
        """Initialize queue"""
        self.words_stream = WordsIO(binary_data)

    def __len__(self):
        """Number of bytes in queue"""
        return len(self.words_stream)

    def is_empty(self):
        """Utility function to indicate if there is no bytes left in the queue"""
        return self.words_stream.is_empty()

    def put(self, additional_binary_data: Union[bytes, bytearray]):
        """Put more bytes into queue"""
        self.words_stream.put(additional_binary_data)

    def pop(self) -> Event:
        """Pop the top event from queue"""

        # try to get all the words for the next event
        # if the complete next event isn't in queue an exception is thrown but no data is discarded
        try:
            event_header = HEADER_FORMATS[0].unpack(self.words_stream.peek(1))
            header_length = event_header["Header Length"]
            event_length = event_header["Event Length"]

            # ensure we have enough data, this is needed, since we
            # have two separate pop-calls (header, trace) and we need
            # to make sure that both work. Otherwise we might get
            # enough data for a header but not for the trace, in which
            # case we would add more data an try again to read a
            # header although trace data is next in the input queue
            self.words_stream.assert_data_is_available(event_length)

            # it's now save to read both header and trace
            header_words = self.words_stream.pop(header_length)
            trace_length = event_length - header_length
            if trace_length:
                trace_data = self.words_stream.pop(trace_length, raw=True)
            else:
                trace_data = None
        except LeftoverBytesError:
            raise LeftoverBytesError("Partial event left at the end of queue")

        # unpack words/trace into their field values
        try:
            event_values = HEADER_FORMATS[header_length].unpack(header_words)
        except KeyError:
            print("Something went wrong with the binary data.")
            print("Debug information:")
            print(f"   Current event header: {event_length}")
            print(
                f"   Number of bytes remaining in IO buffer:  {len(self.words_stream)}"
            )
            if len(self.words_stream):
                filename = Path(".") / "pixie_binary_rest_debug.bin"
                with filename.open("wb") as f:
                    f.write(self.words_stream.binary_data)
                print(f"   Saved IO buffer to:  {filename.absolute()}")
            for i, data in enumerate(self.words_stream.last_data):
                filename = Path(".") / f"pixie_binary_last_{i}_debug.bin"
                with filename.open("wb") as f:
                    f.write(data)
                print(f"   Saved IO last elements to:  {filename.absolute()}")
            raise

        if trace_data:
            trace = np.frombuffer(trace_data, f"({trace_length},2)<u2", count=1)[
                0, :, :
            ]
            trace = trace.flatten()
        else:
            trace = []

        # calculate event values that need to be derived from field values
        CFD_bits = event_values.pop("CFD trigger source bits")
        CFD_error = calc_cfd_error(CFD_bits)
        CFD_fraction = calc_cfd_fraction(
            CFD_bits, event_values.pop("CFD Fractional Time")
        )
        timestamp = (
            event_values.pop("EVTTIME_LO") + event_values.pop("EVTTIME_HI") * 2 ** 32
        ) * 10

        if "Ext_TS_Lo" in event_values:
            ext_timestamp = (
                event_values.pop("Ext_TS_Lo") + event_values.pop("Ext_TS_Hi") * 2 ** 32
            )

            event_values.update({"ext_timestamp": ext_timestamp})

        for key in ["Event Length", "Header Length", "Trace Length"]:
            if key in event_values:
                del event_values[key]

        event_values.update(
            {
                "timestamp": timestamp,
                "CFD_fraction": CFD_fraction,
                "trace": trace,
                "CFD_error": CFD_error,
            }
        )

        return Event(**event_values)

    def iterevents(self):
        while True:
            try:
                yield self.pop()
            except (EmptyError, LeftoverBytesError):
                return
            except TypeError as e:
                print(f"TypeError: {e}", flush=True)
                return

    def pop_all(self):
        return tuple(self.iterevents())


class FilesIO:
    """An object to stream bytes from a list of files"""

    def __init__(self, files):
        self.files = files
        self.current_file_index = 0
        self.current_file = None
        self._is_empty = False

    def is_empty(self):
        """Utility function to indicate if there is no bytes left in the queue"""
        return self._is_empty

    def go_to_next_file(self):
        """Increments the current file/file index to the next file. Raises EmptyError if there are no more files."""
        if self.current_file_index == len(self.files) - 1:
            self._is_empty = True
            raise EmptyError()
        else:
            self.current_file_index += 1
            self.current_file.close()
            self.current_file = open(self.files[self.current_file_index], "rb")

    def pop(self, size):
        """Gets size bytes from the queue"""
        b = bytearray()

        if self.current_file is None:
            self.current_file = open(self.files[self.current_file_index], "rb")

        while True:
            b.extend(self.current_file.read(size - len(b)))
            if len(b) < size:
                try:
                    self.go_to_next_file()
                except EmptyError:
                    return b
            else:
                return b


def events_from_files_generator(files, buffer_size=int(1e9)):
    """Yields events from a list of binary files"""
    reader = ListModeDataReader()
    bytes_stream = FilesIO(files)
    while not bytes_stream.is_empty():
        reader.put(bytes_stream.pop(buffer_size))
        yield from reader.iterevents()
    if not reader.is_empty():
        print("[orange3]WARNING[/] Left over bytes in binary data stream.")


def to_list(obj):
    if isinstance(obj, str):
        obj = [obj]
    else:
        try:
            obj = list(obj)
        except TypeError:
            obj = [obj]
    return obj


def read_list_mode_data(files, buffer_size=int(1e9)):
    """Loads a list of binary files into a pandas DataFrame"""
    files = to_list(files)
    gen = events_from_files_generator(files, buffer_size)
    events = tuple(gen)
    return pd.DataFrame.from_records(events, columns=Event._fields)


def read_list_mode_data_as_events(files, buffer_size=int(1e9), max_size=None):
    """Returns a list of at most max_size events from files"""
    files = to_list(files)
    gen = events_from_files_generator(files, buffer_size)
    return list(islice(gen, max_size))
