from bisect import bisect
from dataclasses import dataclass
from itertools import accumulate
import os

import bitstruct
import numpy as np
import parse


WORD_SIZE = 4


@dataclass
class Event:
    channel: int
    crate: int
    slot: int
    timestamp: int
    CFD_fraction: int
    energy: int
    trace: np.ndarray
    CFD_error: bool
    pileup: bool
    trace_flag: bool
    Esum_trailing: int
    Esum_leading: int
    Esum_gap: int
    baseline: float


def bytes_to_words(bytes_data):
    n_words = len(bytes_data) // WORD_SIZE
    return tuple(bitstruct.byteswap(str(WORD_SIZE), bytes_data[i*WORD_SIZE: (i+1)*WORD_SIZE]) for i in range(n_words))


class WordsIO:

    def __init__(self, binary_data):
        self.binary_data = bytearray(binary_data)

    # in words
    def __len__(self):
        return len(self.binary_data) // WORD_SIZE

    def put(self, additional_binary_data):
        self.binary_data.extend(additional_binary_data)

    def read(self, size):
        res = self.peek(size)
        del self.binary_data[:size*WORD_SIZE]
        return res

    def peek(self, size):
        if size > len(self):
            raise IndexError(f'Requested {size} words, only {len(self)} words in object')
        return bytes_to_words(self.binary_data[:size*WORD_SIZE])


class ListModeData:

    def __init__(self, binary_data):
        self.words_stream = WordsIO(binary_data)

    # in bytes
    def __len__(self):
        return len(self.words_stream) * WORD_SIZE

    def put(self, additional_binary_data):
        self.words_stream.put(additional_binary_data)

    def read(self):
        try:
            event_values = unpack_word(self.words_stream.peek(1), 0)
            _, *rest_of_event_words = self.words_stream.read(event_values['Event Length'])
        except IndexError:
            raise IndexError('No more complete events')
        for word_number, word_bytes in enumerate(rest_of_event_words, start=1):
            event_values.update(unpack_word(word_bytes, word_number))
        CFD_error = calc_CFD_error(event_values['CFD Fractional Time'])
        CFD_fraction = calc_CFD_fraction(event_values['CFD trigger source bits'], event_values['CFD Fractional Time'])
        timestamp = calc_eventtime(event_values['EVTTIME_LO'], event_values['EVTTIME_HI'])
        trace_keys = (trace_field_name_format.format(i) for i in range(event_values['Trace Length']))
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
            event_values.get('Baseline', 0)
        )


word_formats = {
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

trace_field_name_format = 'ADC Data #{:d}'


def trace_format(word_number):
    trace_number = word_number - 18
    field_names = tuple(trace_field_name_format.format(i) for i in (trace_number + 1, trace_number))
    return 'p2u14p2u14', field_names


def unpack_word(word_data, word_number):
    if word_number > 17:
        fmt, field_names = trace_format(word_number)
    else:
        fmt, field_names = word_formats[word_number]
    return bitstruct.unpack_dict(fmt, field_names, word_data)


def calc_CFD_error(cfd_trigger_source_bits):
    return cfd_trigger_source_bits == 7


def calc_CFD_fraction(cfd_trigger_source_bits, cfd_fractional_time):
    if calc_CFD_error(cfd_trigger_source_bits):
        return 0
    else:
        return ((cfd_trigger_source_bits-1) + cfd_fractional_time//8192) * 2


def calc_eventtime(evttime_lo, evvtime_hi):
    return (evttime_lo + evvtime_hi*2**32) * 10


def calc_external_timestamp(ext_ts_lo, ext_ts_hi):
    return ext_ts_lo + ext_ts_hi*2**32
