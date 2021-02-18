from bisect import bisect
from dataclasses import dataclass
from itertools import accumulate
import os

import bitstruct
import numpy as np
import parse


WORD_SIZE = 4


class WordsIO:

    def __init__(self, files):
        if isinstance(files, str):
            self.files = [files]
        else:
            self.files = files
        file_sizes_in_bytes = [os.stat(filename).st_size for filename in self.files]
        self.accumulated_file_sizes_in_bytes = [0].extend(accumulate(file_sizes_in_bytes))
        self.current_file_index = 0
        self.current_file = open(self.files[0], 'rb')

    def set_current_file(self, file_index):
        if self.current_file_index != file_index:
            self.current_file = open(self.files[file_index], 'rb')
            self.current_file_index = file_index

    def file_index_from_byte_index(self, byte_index):
        return bisect(self.accumulated_file_sizes_in_bytes, byte_index) - 1

    def seek(self, word_index):
        byte_index = word_index * WORD_SIZE
        file_index = self.file_index_from_byte_index(byte_index)
        self.set_current_file(file_index)
        self.current_file.seek(byte_index - self.accumulated_file_sizes_in_bytes[file_index])

    def read(self, size):
        size_in_bytes = size * WORD_SIZE
        binary_data = bytearray()
        while True:
            binary_data.extend(self.current_file.read(size_in_bytes - len(binary_data)))
            if len(binary_data) == size_in_bytes:
                break
            else:
                self.set_current_file(self.current_file_index+1)
        return tuple(bitstruct.byteswap(str(WORD_SIZE), binary_data[i*WORD_SIZE: (i+1)*WORD_SIZE]) for i in range(size))


@dataclass
class Event:



class ListModeData:

    def __init__(self, files):
        self.files = files
        self._words = WordsIO(files)
        self.event_indexes = []

    def seek(self, event_index):
        pass

    def read(self, size):
        if size < 1:
            raise ValueError('non positive size given')
        return tuple(self.read1() for _ in range(size))

    def read1(self):
        event_values = unpack_word(self._words.read(1), 0)
        for word_number, word_bytes in enumerate(self._words.read(event_values['Event Length']-1), start=1):
            event_values.update(unpack_word(word_bytes, word_number))
        event_values['time of arrival'] = calc_time_of_arrival(event_values['EVTTIME_LO'], event_values['EVTTIME_HI'],
                                                               event_values['CFD trigger source bits'],
                                                               event_values['CFD Fractional Time'])
        event_values['External Timestamp'] = calc_external_timestamp(event_values['Ext_TS_Lo'],
                                                                     event_values['Ext_TS_Hi'])
        trace_keys = filter(event_values, lambda k: parse.parse(trace_field_name_format, k))
        sorted_trace_keys = sorted(trace_keys, key=lambda k: parse.parse(trace_field_name_format, k))
        event_values['traces'] = np.array([event_values[key] for key in sorted_trace_keys])



    def iterevents(self):
        pass


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


def calc_time_of_arrival(evttime_lo, evvtime_hi, cfd_trigger_source_bits, cfd_fractional_time):
    evt = evttime_lo + evvtime_hi*2**32
    return (evt*5 + (cfd_trigger_source_bits-1) + cfd_fractional_time/8192)*2


def calc_external_timestamp(ext_ts_lo, ext_ts_hi):
    return ext_ts_lo + ext_ts_hi*2**32
