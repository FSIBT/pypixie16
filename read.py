"""Read data files from XIA pixie16 instruments"""

import numpy as np
from collections import namedtuple
import sys
import logging

# logger = logging.logger(__name__)

Event = namedtuple('Event', ['channel', 'crate', 'slot', 'time', 'energy', 'trace'])


def read_list_mode_data(filename, progress=False, keep_trace=False):
    """Read list mode data from binary file

    See section 4.4.2 in Manual, page 70
    """

    all_event = []
    nr_event = 0
    with open(filename, 'rb') as f:
        while True:
            nr_event += 1
            if progress and nr_event % 10000 == 0:
                print('.', end='')
            data = f.read(4)
            if data == b'':
                # no more data available
                break
            s = (((((data[3] << 8) + data[2]) << 8) + data[1]) << 8) + data[0]
            finish_code = (s & (1 << 31)) >> 31
            event_length = (s & ((1 << 14)-1) << 17) >> 17
            header_length = (s & (0b11111 << 12)) >> 12
            crate_id = (s & (0b1111 << 8)) >> 8
            slot_id = (s & (0b1111 << 4)) >> 4
            channel_nr = s & 0b1111
            data = f.read(4)
            eventtime_lo = (((((data[3] << 8) + data[2]) << 8) + data[1]) << 8) + data[0]
            data = f.read(4)
            s = (data[3] << 8) + data[2]
            cfd_trigger_bits = (s & (0b111 << 13)) >> 13
            cfd_fractional = s & ((1 << 12)-1)
            eventtime_hi = (data[1] << 8) + data[0]
            data = f.read(4)
            s = (data[3] << 8) + data[2]
            trace_flag = (s & (1 << 15)) >> 15
            trace_length = s & ((1 << 16) - 1)
            event_energy = (data[1] << 8) + data[0]
            for i in range(header_length-4):
                data = f.read(4)
            if event_length-header_length > 0:
                # read the whole trace in one go to make reading faster than reading byte by byte
                # about 300x faster than multiple f.read(2)
                trace = np.fromfile(f, '({},2)<u2'.format(event_length-header_length), count=1)[0, :, :]
                # need to swap columns and flatten array
                if not keep_trace:
                    trace[:, 0], trace[:, 1] = trace[:, 1], trace[:, 0].copy()
                    trace = trace.flatten()
            else:
                trace = []
            if not keep_trace:
                trace = []
            evt = 2**32 * eventtime_hi + eventtime_lo
            if cfd_trigger_bits == 7:
                TS = evt*1e-8
            else:
                TS = (evt*5 + cfd_trigger_bits-1 + cfd_fractional/8192)*2e-9
            yield Event(channel_nr, crate_id, slot_id, TS, event_energy, trace)
    return

def read_all_list_mode_data(filename, progress=False, keep_trace=False):
    return list(read_list_mode_data(filename, progress, keep_trace))

def read_mca_mode_data(filename):
    """Read MCA data files: 32k 32bit words for 16 channels"""

    results = {}
    with open(filename, 'rb') as f:
        for channel in range(16):
            spectrum = []
            for i in range(32*1024):
                data = f.read(4)
                s = (((((data[3] << 8) + data[2]) << 8) + data[1]) << 8) + data[0]
                spectrum.append(s)
            spectrum = np.array(spectrum)
            results[channel] = spectrum
    return results


def read_setting(filename):
    """Read setting data files: 24 x 1280 data points, each 32 bit"""

    results = {}
    with open(filename, 'rb') as f:
        for module in range(24):
            setting = []
            for i in range(1280):
                data = f.read(4)
                s = (((((data[3] << 8) + data[2]) << 8) + data[1]) << 8) + data[0]
                setting.append(s)
            results[module] = setting
    return results
