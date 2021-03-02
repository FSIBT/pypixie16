"""implementation of queues for parsing list mode data from the pixie16"""


from collections import namedtuple
from typing import Union

import pandas as pd

import bitstruct
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
    ],
)


# returns bytes correctly byteswapped and in word sizes
def bytes_to_words(bytes_data):
    n_words = len(bytes_data) // WORD_SIZE
    return tuple(bitstruct.byteswap(str(WORD_SIZE), bytes_data[i*WORD_SIZE: (i+1)*WORD_SIZE]) for i in range(n_words))


class EmptyError(Exception):
    """"To be raised if an empty queue is popped or peeked"""


class LeftoverBytesError(Exception):
    """To be raised if a queue with a partial word/event left is popped or peeked"""



class WordsIO:
    """A binary data FIFO queue/transformer. Put in binary data as any sized bytes or bytearray objects and take them
    out as Pixie16 word sized/formatted bytes (refer to user manual List Mode Data Structures section).
    """

    def __init__(self, binary_data: Union[bytes, bytearray] = b''):
        """Initialize queue"""
        self.binary_data = bytearray(binary_data)

    def __len__(self):
        """Number of words in queue"""
        return len(self.binary_data) // WORD_SIZE

    def is_empty(self):
        return len(self) == 0

    def put(self, additional_binary_data: Union[bytes, bytearray]):
        """Put more bytes into queue"""
        self.binary_data.extend(additional_binary_data)

    def pop(self, size):
        """Pop the top size words from queue"""
        res = self.peek(size)
        del self.binary_data[:size*WORD_SIZE]
        return res

    def peek(self, size):
        """Get the top size words from queue without removing them."""
        if self.is_empty():
            raise EmptyError()
        elif size > len(self):
            raise LeftoverBytesError(f'Requested {size} words, only {len(self)} words in object')
        return bytes_to_words(self.binary_data[:size*WORD_SIZE])


WORD_FORMATS = {
    0: ('b1u14u5u4u4u4', ('Finish Code', 'Event Length', 'Header Length', 'CrateID', 'SlotID', 'Chan#')),
    1: ('u32', ('EVTTIME_LO',)),
    2: ('u3u13u16', ('CFD trigger source bits', 'CFD Fractional Time', 'EVTTIME_HI')),
    3: ('b1u15u16', ('Trace Out-of-Range Flag', 'Trace Length', 'Event Energy')),
    4: ('u32', ('Energy sum trailing',)),
    5: ('u32', ('Energy sum leading',)),
    6: ('u32', ('Energy sum gap',)),
    7: ('u32', ('Baseline',)),
    8: ('u32', ('QDCSum0',)),
    9: ('u32', ('QDCSum1',)),
    10: ('u32', ('QDCSum2',)),
    11: ('u32', ('QDCSum3',)),
    12: ('u32', ('QDCSum4',)),
    13: ('u32', ('QDCSum5',)),
    14: ('u32', ('QDCSum6',)),
    15: ('u32', ('QDCSum7',)),
    16: ('u32', ('Ext_TS_Lo',)),
    17: ('p16u16', ('Ext_TS_Hi',)),
}

TRACE_FIELD_NAME_FORMAT = 'ADC Data #{:d}'


def trace_format(word_number):
    trace_number = word_number - 18
    field_names = tuple(TRACE_FIELD_NAME_FORMAT.format(i) for i in (trace_number + 1, trace_number))
    return 'p2u14p2u14', field_names


def unpack_word(word_data: Union[bytes, bytearray], word_number):
    if word_number > 17:
        fmt, field_names = trace_format(word_number)
    else:
        fmt, field_names = WORD_FORMATS[word_number]
    return bitstruct.unpack_dict(fmt, field_names, word_data)


def calc_cfd_error(cfd_trigger_source_bits):
    return cfd_trigger_source_bits == 7


def calc_cfd_fraction(cfd_trigger_source_bits, cfd_fractional_time):
    if calc_cfd_error(cfd_trigger_source_bits):
        return 0
    else:
        return ((cfd_trigger_source_bits-1) + cfd_fractional_time//8192) * 2


def calc_eventtime(evttime_lo, evvtime_hi):
    return (evttime_lo + evvtime_hi*2**32) * 10


def calc_external_timestamp(ext_ts_lo, ext_ts_hi):
    return ext_ts_lo + ext_ts_hi*2**32


class ListModeDataReader:
    """A binary data FIFO queue/transformer. Put in binary data as any sized bytes or bytearray objects and take them
    out as Pixie16 events (refer to user manual List Mode Data Structures section).
    """

    def __init__(self, binary_data: Union[bytes, bytearray] = b''):
        """Initialize queue"""
        self.words_stream = WordsIO(binary_data)

    def __len__(self):
        """Number of bytes in queue"""
        return len(self.words_stream) * WORD_SIZE

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
            event_values = unpack_word(self.words_stream.peek(1)[0], 0)
            _, *rest_of_event_words = self.words_stream.pop(event_values['Event Length'])
        except LeftoverBytesError:
            raise LeftoverBytesError('No more complete events')

        # unpack words into their field values
        for word_number, word_bytes in enumerate(rest_of_event_words, start=1):
            event_values.update(unpack_word(word_bytes, word_number))

        # calculate event values that need to be derived from field values
        CFD_error = calc_cfd_error(event_values['CFD Fractional Time'])
        CFD_fraction = calc_cfd_fraction(event_values['CFD trigger source bits'], event_values['CFD Fractional Time'])
        timestamp = calc_eventtime(event_values['EVTTIME_LO'], event_values['EVTTIME_HI'])

        # collect traces into a numpy array
        trace_keys = (TRACE_FIELD_NAME_FORMAT.format(i) for i in range(event_values['Trace Length']))
        trace = np.array([event_values[key] for key in trace_keys])

        return Event(
            event_values['Chan#'],
            event_values['CrateID'],
            event_values['SlotID'],
            timestamp,
            CFD_fraction,
            event_values['Event Energy'],
            trace,
            CFD_error,
            event_values['Finish Code'],
            event_values['Trace Out-of-Range Flag'],
            event_values.get('Energy sum trailing', 0),
            event_values.get('Energy sum leading', 0),
            event_values.get('Energy sum gap', 0),
            event_values.get('Baseline', 0.)
        )


class FilesIO:

    def __init__(self, files):
        self.files = files
        self.current_file_index = 0
        self.current_file = open(files[0], 'rb')
        self._is_empty = False

    def is_empty(self):
        return self._is_empty

    def go_to_next_file(self):
        if self.current_file_index == len(self.files)-1:
            self._is_empty = True
            raise EmptyError()
        else:
            self.current_file_index += 1
            self.current_file = open(self.files[self.current_file_index], 'rb')

    def pop(self, size):
        b = bytearray()
        while True:
            b.extend(self.current_file.read(size - len(b)))
            if len(b) < size:
                try:
                    self.go_to_next_file()
                except EmptyError:
                    return b
            else:
                return b


def read_list_mode_data(files, buffer_size=int(1e9)):
    reader = ListModeDataReader()
    bytes_stream = FilesIO(files)
    events = []
    while not bytes_stream.is_empty():
        try:
            events.append(reader.pop())
        except (EmptyError, LeftoverBytesError):
            reader.put(bytes_stream.pop(buffer_size))
    if not reader.is_empty():
        raise LeftoverBytesError()
    return pd.DataFrame.from_records(events, columns=Event._fields)
