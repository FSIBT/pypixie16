"""Read data files from XIA pixie16 instruments"""

import mpmath
import ctypes
import struct
import json
import numpy as np
from contextlib import contextmanager
from collections import namedtuple
from pathlib import Path
import sys
import logging

from .variables import settings

# logger = logging.logger(__name__)

Event = namedtuple('Event', ['channel', 'crate', 'slot', 'time', 'clock_time',
                             'energy', 'trace', 'CFD_error', 'pileup', 'trace_flag', 'Esum_trailing',
                             'Esum_leading', 'Esum_gap', 'baseline'])


def iterate_pairs(mylist):
    '''Go through an iterable and return the current item and the next'''

    if len(mylist) < 2:
        return
    for i, d in enumerate(mylist[:-1]):
        yield mylist[i], mylist[i+1]
    return


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


class myIO():
    """Class to use for read_list_mode_data when all data is in memory

    This might speed up reading from a HD, but it hasn't really
    changed the speed on a solid state drive.

    The only function that needs to be implemented is the read function.

    We also make it work as a drop in replacement for files
    in a contexmanager with open-calls, e.g.

    >>> data = myIO(data)
    >>> with open(data, 'rb') as f:
          f.read()


    """

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read(self, N):
        out = self.data[self.pos:self.pos+N]
        self.pos += N
        return out

    def seek(self, N, pos):
        if pos == 0:
            self.pos = N
        elif pos == 1:
            self.pos += N
        else:
            raise NotImplementedError

    @contextmanager
    def open(self, modus):
        """This enables the use of myIO.open('rb')so this can be a drop in for a pathlib object"""
        yield self


class PixieTime():
    """Class to keep the 48 bit timestamp and the CFD time information without losing precision

    Using our own class instead of mpmath directly makes things about 5x faster.
    """

    def __init__(self, low, hi, CFD):
        """Store everything internally as multiples of 2 ns time steps."""

        self.TS = (low + (hi << 32))*5
        self.CFD = CFD

    def as_float(self):
        return self.__float__()

    def __float__(self):
        return (self.TS+self.CFD)*2.0

    def as_mpmath(self):
        """Return a high precision mpmath.mpf object

        using *2/1e9 gives better precision than using 2e-9

        """
        return (mpmath.mpf(self.TS)+mpmath.mpf(self.CFD))*2.0

    def __add__(self, x):
        res = PixieTime(0, 0, 0)
        res.TS = self.TS + x.TS
        res.CFD = self.CFD + x.CFD
        return res

    def __sub__(self, x):
        res = PixieTime(0, 0, 0)
        res.TS = self.TS - x.TS
        res.CFD = self.CFD - x.CFD
        return res

#    def __mul__(self, x):
#        res = PixieTime(0, 0, 0)
#        res.TS = self.TS*x
#        res.CFD = self.CFD*x
#        return res

    def __repr__(self):
        return f'(PixieTime: {self.TS} {self.CFD})'
        return f'(PixieTime: {self.as_mpmath()})'


def read_list_mode_data(filename, keep_trace=False, trailing_sums=False):
    """Read list mode data from binary file

    See section 4.4.2 in Manual, page 70

    filename can be either a pathlib.Path object or a myIO object defined in pixie16.read.
    """

    if not (isinstance(filename, Path) or isinstance(filename, myIO)):
        print(f'Error: filename {filename} needs to be a pathlib.Path or myIO object')
        return

    in_memory = isinstance(filename, myIO)

    all_event = []
    nr_event = 0

    with filename.open('rb') as f:
        while True:
            nr_event += 1
            try:
                [pileup_bits, eventtime_lo, eventtime_hi,
                 cfd_bits, event_energy, trace_bits] = struct.unpack_from('<IIHHHH', f.read(4*4))

                s = pileup_bits
                pileup = (s & (1 << 31)) >> 31  # 1 if pile-up event
                event_length = (s & ((1 << 14)-1) << 17) >> 17
                header_length = (s & (0b11111 << 12)) >> 12
                crate_id = (s & (0b1111 << 8)) >> 8
                slot_id = (s & (0b1111 << 4)) >> 4
                channel_nr = s & 0b1111

                s = cfd_bits
                cfd_trigger_bits = (s & (0b111 << 13)) >> 13
                cfd_fractional = s & ((1 << 13)-1)

                s = trace_bits
                trace_flag = (s & (1 << 15)) >> 15  # 1 if trace out of ADC range (clipped)
                trace_length = s & ((1 << 16) - 1)

                if header_length == 4:
                    # already read all information
                    Esum_trailing, Esum_leading, Esum_gap, baseline = 0, 0, 0, 0.0
                elif header_length == 8:
                    # energy sums
                    if trailing_sums:
                        [Esum_trailing, Esum_leading, Esum_gap,
                         baseline] = struct.unpack_from('<IIIf', f.read(4*4))
                    else:
                        Esum_trailing, Esum_leading, Esum_gap, baseline = 0, 0, 0, 0.0
                        f.seek(4, 1)
                else:
                    raise NotImplementedError

            except struct.error:
                # no more data available
                break

            trace_data_length = event_length-header_length
            if trace_data_length > 0:
                if keep_trace:
                    if in_memory:
                        data = f.read(4*trace_data_length)
                        trace = np.frombuffer(data, f'({trace_data_length},2)<u2', count=1)[0, :, :]
                    else:
                        # read the whole trace in one go to make reading faster than reading byte by byte
                        # about 300x faster than multiple f.read(2)
                        trace = np.fromfile(f, f'({trace_data_length},2)<u2', count=1)[0, :, :]
                    trace = trace.flatten()
                else:
                    f.seek(4*trace_data_length, 1)
                    trace = []
            else:
                trace = []

            CFD_error = False
            TS = PixieTime(eventtime_lo, eventtime_hi, 0)
            if cfd_trigger_bits == 7:
                CFD_error = True
                CFD = PixieTime(eventtime_lo, eventtime_hi, 0)
            else:
                CFD = PixieTime(eventtime_lo, eventtime_hi, cfd_trigger_bits-1 + cfd_fractional/8192)

            yield Event(channel_nr, crate_id, slot_id, CFD, TS, event_energy, trace, CFD_error, pileup, trace_flag,
                        Esum_trailing, Esum_leading, Esum_gap, baseline)
    return


def read_all_list_mode_data(filename, keep_trace=False):
    return list(read_list_mode_data(filename, keep_trace))


def read_mca_mode_data(filename):
    """Read MCA data files: 32k 32bit words for 16 channels"""

    results = {}
    with open(filename, 'rb') as f:
        for channel in range(16):
            spectrum = []
            for i in range(32*1024):
                spectrum.append(int.from_bytes(f.read(4), byteorder='little'))
            spectrum = np.array(spectrum)
            results[channel] = spectrum
    return results


class XIASetting():
    def __init__(self, filename: str, modulenr=None):
        self.filename = filename
        self.modulenr = modulenr
        self.writeable = None
        self.readable = None
        self.read_setting(filename)

    def __repr__(self):
        return self.writeable.__repr__() + self.readable.__repr__()

    def read_setting(self, filename: str):
        """Read setting data files: 24 x 1280 data points, each 32 bit

        We return a list with data for each of the 24 modules. The list contains
        two dictionaries. The first one has all the settings that are writebale,
        the second one contains all the read_only settings.
        """

        # all numbers are stored as ulong (32bit unsigned integer) but
        # some should be read back as IEEE754 floats. Keep a list of
        # variables, where we need to convert
        FLOATS = ['PreampTau']

        results_w = []
        results_r = []

        names = settings

        rawmodules = []
        with open(filename, 'rb') as f:
            for module in range(24):
                rawsetting = []
                for i in range(1280):
                    rawsetting.append(int.from_bytes(f.read(4), byteorder='little'))
                rawmodules.append(rawsetting)

        for mod in rawmodules:
            outsetting = {}
            outread = {}
            for n, [pos, length] in names.items():
                if n in FLOATS:
                    value = [converter_ulong_to_IEEE754(mod[pos+k]) for k in range(length)]
                else:
                    value = [mod[pos+k] for k in range(length)]
                if length == 1:
                    if pos < 832:
                        outsetting[n] = value[0]
                    else:
                        outread[n] = value[0]
                else:
                    if pos < 832:
                        outsetting[n] = value
                    else:
                        outread[n] = value
            outread['LiveTime'] = [(outread['LiveTimeA'][i] * 2**32 + outread['LiveTimeB']
                                    [i]) * 16 * 10e-9 for i in range(16)]
            outread['FastPeaks'] = [outread['FastPeaksA'][i] * 2 **
                                    32 + outread['FastPeaksB'][i] for i in range(16)]
            outread['RealTime'] = (outread['RealTimeA'] * 2**32 + outread['RealTimeB']) * 10e-9
            outread['RunTime'] = (outread['RunTimeA'] * 2**32 + outread['RunTimeB']) * 10e-9

            outsetting['OffsetVoltage'] = [
                1.5 * ((32768-outsetting['OffsetDAC'][i]) / 32768) for i in range(16)]
            results_w.append(outsetting)
            results_r.append(outread)

        self.writeable_list = results_w
        self.readable_list = results_r

        if self.modulenr is not None:
            self.writeable = results_w[self.modulenr]
            self.readable = results_r[self.modulenr]

    def __repr__(self):
        return f'XIASetting: {self.filename}'


def compare_module_setting(modA, modB, quiet=False):
    """Compare the settings of two modules

    Print the difference.

    If quiet is True, then just return True/False

    The functions assumes that both settings have the same structure.
    """

    # list of settings that save binary data, list the start points of each group of bits
    hex = {'ChanCSRa': [21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
           'MultiplicityMaskH': [31, 30, 27, 24, 21, 16, 15],
           'MultiplicityMaskL': [31, 15],
           'TrigConfig': [[31, 27, 25, 23, 19, 15, 14, 11, 7, 3],
                          [31, 27, 23, 19, 15, 11, 7, 3],
                          [31, 27, 26, 25, 24, 23, 21, 19, 17, 15, 11, 7, 3],
                          []]}

    if type(modA) != type(modB):
        print(f'compare_module_setting: both items need to have the same type')
        return None

    if type(modA) == XIASetting:
        OrigA = modA
        OrigB = modB

        # check if we have settings for all modules or for just one
        if modA.writeable is not None:
            modA = [modA.writeable, modA.readable]
            modB = [modB.writeable, modB.readable]
        else:
            modA = [val for sublist in zip(modA.writeable_list, modA.readable_list) for val in sublist]
            modB = [val for sublist in zip(modB.writeable_list, modB.readable_list) for val in sublist]

    if not quiet:
        modulesA = OrigA.modulenr if OrigA.modulenr else 'all'
        modulesB = OrigB.modulenr if OrigB.modulenr else 'all'
        print('Comparing settings:')
        print(f'  a: {OrigA.filename.name} {modulesA}')
        print(f'  b: {OrigB.filename.name} {modulesB}')
        print('')
        for nr, [A, B] in enumerate(zip(modA, modB)):
            print(f'Module {nr//2} ---------------- ')
            for k in A.keys():
                if type(A[k]) == list:
                    if len(A[k]) == 16:
                        prefix = 'CH'
                    else:
                        prefix = '#'
                    if not all([x == y for x, y in zip(A[k], B[k])]):
                        print('{} differs:'.format(k))
                        for i, (x, y) in enumerate(zip(A[k], B[k])):
                            if x != y:
                                if k in hex:
                                    if k == 'TrigConfig':
                                        print(f'  {prefix}{i:02d}:    a:{x:#011_x} <-> b:{y:#011_x}')
                                        print('            ', end='')
                                        bin_string = '10987654321098765432109876543210'
                                        for pos, next_pos in iterate_pairs(hex[k][i]):
                                            print(bin_string[31-pos:31-next_pos]+' ', end='')
                                        print(bin_string[31-next_pos:])
                                        for v, name in zip([x, y], ['a', 'b']):
                                            bin_string = bin(v)[2:]
                                            l = len(bin_string)
                                            if l < 32:
                                                bin_string = '0'*(32-l)+bin_string
                                            print(f'          {name}:', end='')
                                            for pos, next_pos in iterate_pairs(hex[k][i]):
                                                print(bin_string[31-pos:31-next_pos]+' ', end='')
                                            print(bin_string[31-next_pos:])
                                    else:
                                        print(f'  {prefix}{i:02d}:   a:{x:#011_x} <-> b:{y:#011_x}')
                                        print('            ', end='')
                                        bin_string = '10987654321098765432109876543210'
                                        for pos, next_pos in iterate_pairs(hex[k]):
                                            print(bin_string[31-pos:31-next_pos]+' ', end='')
                                        print(bin_string[31-next_pos:])
                                        for v, name in zip([x, y], ['a', 'b']):
                                            bin_string = bin(v)[2:]
                                            l = len(bin_string)
                                            if l < 32:
                                                bin_string = '0'*(32-l)+bin_string
                                            print(f'          {name}:', end='')
                                            for pos, next_pos in iterate_pairs(hex[k]):
                                                print(bin_string[31-pos:31-next_pos]+' ', end='')
                                            print(bin_string[31-next_pos:])
                                else:
                                    print(f'{prefix}{i:02d}:   a:{x} <-> b:{y}')
                else:
                    if A[k] != B[k]:
                        print('{} differs: a:{} != b:{}'.format(k, A[k], B[k]))

    # convert to a sorted json string to make deep comparison possible
    return [json.dumps(A, sort_keys=True) == json.dumps(B, sort_keys=True) for A, B in zip(modA, modB)]
