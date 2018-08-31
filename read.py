"""Read data files from XIA pixie16 instruments"""

import mpmath
import ctypes
import json
import numpy as np
from collections import namedtuple
import sys
import logging

# logger = logging.logger(__name__)

Event = namedtuple('Event', ['channel', 'crate', 'slot', 'time', 'energy', 'trace', 'CFD_error'])

# set precision to 30 digits
mpmath.mp.dps = 30

def converter_IEEE754_to_ulong(x):
    a = (ctypes.c_float*1)(x)
    b = ctypes.cast(a, ctypes.POINTER(ctypes.c_ulong))
    return b.contents.value

def converter_ulong_to_IEEE754(x):
    a = (ctypes.c_ulong*1)(x)
    b = ctypes.cast(a, ctypes.POINTER(ctypes.c_float))
    return b.contents.value


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
            TS = 2**32 * mpmath.mpf(eventtime_hi) + mpmath.mpf(eventtime_lo)
            TS*= 10e-9
            CFD_error = False
            if cfd_trigger_bits == 7:
                CFD_error = True
            else:
                TS += mpmath.mpf(cfd_trigger_bits-1 + cfd_fractional/8192)*2e-9
            yield Event(channel_nr, crate_id, slot_id, TS, event_energy, trace, CFD_error)
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


def read_setting(filename: str):
    """Read setting data files: 24 x 1280 data points, each 32 bit

    We return a list with data for each of the 24 modules. The list contains
    two dictionaries. The first one has all the settings that are writebale,
    the second one contains all the read_only settings.
    """

    # all numbers are stored as ulong (32bit unsigned integer) but
    # some should be read back as IEEE754 floats. Keep a list of
    # variables, where we need to convert
    FLOATS = ['PreampTau']

    results = []
    setting_description = 'Pixie16DSP_revfgeneral_14b500m_r35207.var'
    names = []  # list of names, and lenght of setting
    with open(setting_description, 'r') as f:
        for i, l in enumerate(f):
            position, name = l.split()
            position = int(position, 0)
            if i == 0:
                oldpos = 0x0004a000
                length = 1
            else:
                length = position-oldpos
                names[-1][1] = length
                oldpos = position
            names.append([name, None])
        names[-1][1] = length

    rawmodules = []
    with open(filename, 'rb') as f:
        for module in range(24):
            rawsetting = []
            for i in range(1280):
                data = f.read(4)
                s = (((((data[3] << 8) + data[2]) << 8) + data[1]) << 8) + data[0]
                rawsetting.append(s)
            rawmodules.append(rawsetting)

    for mod in rawmodules:
        outsetting = {}
        outread = {}
        i = 0  # index in rawsetting
        for n, length in names:
            if n in FLOATS:
                value =  [converter_ulong_to_IEEE754(mod[i+k]) for k in range(length)]
            else:
                value =  [mod[i+k] for k in range(length)]
            if length == 1:
                if i < 832:
                    outsetting[n] = value[0]
                else:
                    outread[n] = value[0]
            else:
                if i < 832:
                    outsetting[n] = value
                else:
                    outread[n] = value
            i += length
        outread['LiveTime'] = [(outread['LiveTimeA'][i] * 2**32 + outread['LiveTimeB'][i]) * 16 *10e-9 for i in range(16)]
        outread['FastPeaks'] = [outread['FastPeaksA'][i] * 2**32 + outread['FastPeaksB'][i] for i in range(16)]
        outread['RealTime'] = (outread['RealTimeA'] * 2**32 + outread['RealTimeB']) * 10e-9
        outread['RunTime'] = (outread['RunTimeA'] * 2**32 + outread['RunTimeB']) * 10e-9

        outsetting['OffsetVoltage'] = [1.5 * ((32768-outsetting['OffsetDAC'][i]) / 32768) for i in range(16)]
        results.append([outsetting, outread])

    return results

def compare_module_setting(modA, modB, quiet=False):
    """Compare the settings of two modules

    Print the difference.

    If quiet is True, then just return True/False

    The functions assumes that both settings have the same structure.
    """

    assert type(modA)== dict, 'The inputs need to be dictionaries'
    assert type(modB)== dict, 'The inputs need to be dictionaries'
    
    if not quiet:
        for k in modA.keys():
            if type(modA[k]) == list:
                if not all([x==y for x, y in zip(modA[k], modB[k])]):
                    print('{} differs:'.format(k))
                    for x, y in zip(modA[k], modB[k]):
                        print('   {} <-> {}'.format(x, y))
            else:
                if modA[k] != modB[k]:
                    print('{} differs: {} != {}'.format(k, modA[k], modB[k]))
                
    # convert to a sorted json string to make deep comparison possible
    return json.dumps(modA, sort_keys=True) == json.dumps(modB, sort_keys=True)
