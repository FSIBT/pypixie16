"""implementation of queues for parsing list mode data from the pixie16"""


from collections import namedtuple
from itertools import islice
import pathlib
from typing import Union

import pandas as pd

import cbitstruct as bitstruct
import numpy as np


WORD_SIZE = 4


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
    ],
)


def bytes_to_words(bytes_data):
    """returns bytes correctly byteswapped and in word sizes"""
    n_words = len(bytes_data) // WORD_SIZE
    return tuple(
        bitstruct.byteswap(
            str(WORD_SIZE), bytes_data[i * WORD_SIZE : (i + 1) * WORD_SIZE]
        )
        for i in range(n_words)
    )


class EmptyError(Exception):
    """"To be raised if an empty queue is popped or peeked"""


class LeftoverBytesError(Exception):
    """To be raised if a queue with a partial word/event left is popped or peeked"""


class WordsIO:
    """A binary data FIFO queue/transformer. Put in binary data as any sized bytes or bytearray objects and take them
    out as Pixie16 word sized/formatted bytes (refer to user manual List Mode Data Structures section).
    """

    def __init__(self, binary_data: Union[bytes, bytearray] = b""):
        """Initialize queue"""
        self.binary_data = bytearray(binary_data)

    def __len__(self):
        """Number of bytes in queue"""
        return len(self.binary_data)

    def is_empty(self):
        """Utility function to indicate if there is no bytes left in the queue"""
        return len(self) == 0

    def put(self, additional_binary_data: Union[bytes, bytearray]):
        """Put more bytes into queue"""
        self.binary_data.extend(additional_binary_data)

    def pop(self, size, raw=False):
        """Pop the top size words from queue"""
        res = self.peek(size, raw=raw)
        del self.binary_data[: size * WORD_SIZE]
        return res

    def peek(self, size, raw=False):
        """Get the top size words from queue without removing them.

        Return either tuple of WORD-sized, byte-swapped data (raw==True)
        or bytearraw (raw==False).
        """
        if self.is_empty():
            raise EmptyError()
        elif size > len(self):
            raise LeftoverBytesError(
                f"Requested {size} words, only {len(self)} words in object"
            )
        if raw:
            return self.binary_data[: size * WORD_SIZE]
        else:
            return bytes_to_words(self.binary_data[: size * WORD_SIZE])


HEADER_FORMATS = {
    0: (
        "b1u14u5u4u4u4",
        ("Finish Code", "Event Length", "Header Length", "CrateID", "SlotID", "Chan#"),
    ),
    1: ("u32", ("EVTTIME_LO",)),
    2: ("u3u13u16", ("CFD trigger source bits", "CFD Fractional Time", "EVTTIME_HI")),
    3: ("b1u15u16", ("Trace Out-of-Range Flag", "Trace Length", "Event Energy")),
    4: ("u32", ("Energy sum trailing",)),
    5: ("u32", ("Energy sum leading",)),
    6: ("u32", ("Energy sum gap",)),
    7: ("f32", ("Baseline",)),
    8: ("u32", ("QDCSum0",)),
    9: ("u32", ("QDCSum1",)),
    10: ("u32", ("QDCSum2",)),
    11: ("u32", ("QDCSum3",)),
    12: ("u32", ("QDCSum4",)),
    13: ("u32", ("QDCSum5",)),
    14: ("u32", ("QDCSum6",)),
    15: ("u32", ("QDCSum7",)),
    16: ("u32", ("Ext_TS_Lo",)),
    17: ("p16u16", ("Ext_TS_Hi",)),
}


def unpack_header_word(word_data: Union[bytes, bytearray], word_number):
    fmt, field_names = HEADER_FORMATS[word_number]
    return bitstruct.unpack_dict(fmt, field_names, word_data)


def calc_cfd_error(cfd_trigger_source_bits):
    return cfd_trigger_source_bits == 7


def calc_cfd_fraction(cfd_trigger_source_bits, cfd_fractional_time):
    if calc_cfd_error(cfd_trigger_source_bits):
        return 0
    else:
        return ((cfd_trigger_source_bits - 1) + cfd_fractional_time / 8192) * 2


def calc_eventtime(evttime_lo, evvtime_hi):
    return (evttime_lo + evvtime_hi * 2 ** 32) * 10


def calc_external_timestamp(ext_ts_lo, ext_ts_hi):
    return ext_ts_lo + ext_ts_hi * 2 ** 32


class ListModeDataReader:
    """A binary data FIFO queue/transformer. Put in binary data as any sized bytes or bytearray objects and take them
    out as Pixie16 events (refer to user manual List Mode Data Structures section).
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
            event_values = unpack_header_word(self.words_stream.peek(1)[0], 0)
            header_length = event_values["Header Length"]
            event_length = event_values["Event Length"]

            _, *rest_of_event_words = self.words_stream.pop(header_length)
            trace_length = event_length - header_length
            if trace_length:
                trace_data = self.words_stream.pop(trace_length, raw=True)
            else:
                trace_data = None
        except LeftoverBytesError:
            raise LeftoverBytesError("Partial event left at the end of queue")

        # unpack words/trace into their field values
        for word_number, word_bytes in enumerate(rest_of_event_words, start=1):
            event_values.update(unpack_header_word(word_bytes, word_number))

        if trace_data:
            trace = np.frombuffer(trace_data, f"({trace_length},2)<u2", count=1)[
                0, :, :
            ]
            trace = trace.flatten()
        else:
            trace = []

        # calculate event values that need to be derived from field values
        CFD_error = calc_cfd_error(event_values["CFD trigger source bits"])
        CFD_fraction = calc_cfd_fraction(
            event_values["CFD trigger source bits"], event_values["CFD Fractional Time"]
        )
        timestamp = calc_eventtime(
            event_values["EVTTIME_LO"], event_values["EVTTIME_HI"]
        )

        return Event(
            event_values["Chan#"],
            event_values["CrateID"],
            event_values["SlotID"],
            timestamp,
            CFD_fraction,
            event_values["Event Energy"],
            trace,
            CFD_error,
            event_values["Finish Code"],
            event_values["Trace Out-of-Range Flag"],
            event_values.get("Energy sum trailing", -1),
            event_values.get("Energy sum leading", -1),
            event_values.get("Energy sum gap", -1),
            event_values.get("Baseline", -1.0),
            event_values.get("QDCSum0", -1),
            event_values.get("QDCSum1", -1),
            event_values.get("QDCSum2", -1),
            event_values.get("QDCSum3", -1),
            event_values.get("QDCSum4", -1),
            event_values.get("QDCSum5", -1),
            event_values.get("QDCSum6", -1),
            event_values.get("QDCSum7", -1),
        )

    def iterevents(self):
        while True:
            try:
                yield self.pop()
            except (EmptyError, LeftoverBytesError):
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
        raise LeftoverBytesError()


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
