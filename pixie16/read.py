"""Read data files from XIA pixie16 instruments"""

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


Event = namedtuple('Event', ['channel', 'crate', 'slot', 'timestamp', 'CFD_fraction',
                             'energy', 'trace', 'CFD_error', 'pileup', 'trace_flag',
                             'Esum_trailing', 'Esum_leading', 'Esum_gap', 'baseline'])


def converter_IEEE754_to_ulong(x):
    a = (ctypes.c_float*1)(x)
    b = ctypes.cast(a, ctypes.POINTER(ctypes.c_ulong))
    return b.contents


def converter_ulong_to_IEEE754(x):
    a = (ctypes.c_ulong*1)(x)
    b = ctypes.cast(a, ctypes.POINTER(ctypes.c_float))
    return b.contents.value


def iterate_pairs(mylist):
    '''Go through an iterable and return the current item and the next'''

    if len(mylist) < 2:
        return
    for i, d in enumerate(mylist[:-1]):
        yield mylist[i], mylist[i+1]
    return


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


class Buffer():
    """A class that can buffer leftover data from a previous file for cases where the FIFO buffer of the pixie only contains a partial event"""

    def __init__(self):
        self.clear()

    def add_file(self, filename, f):
        self.file = f
        self.filename = filename
        self.file_position = 0
        if isinstance(filename, Path):
            self.file_size = filename.stat().st_size
        elif isinstance(filename, myIO):
            self.file_size = len(f.data)
        else:
            raise NotImplementedError(
                f'Buffer must be either a pathlb Path object or a in memory object(myIO): {f}')

    def add_split_event(self):
        """An incomplete event was found

        his means we already parsed the first 16 bytes, so we need to
        add those and the remainig data in the file to the buffer.

        """
        self.leftover = self.last_data + self.file.read(self.file_size-self.file_position)
        self.leftover_size = len(self.leftover)
        self.leftover_position = 0

    def add_leftover(self):
        """A small amount of data is left over

        Not enought to even parse the first 16 bytes. This gets triggered before the first 16 bytes are read.

        """
        self.leftover = self.file.read(self.file_size-self.file_position)
        self.leftover_size = len(self.leftover)
        self.leftover_position = 0

    def clear(self):
        self.file = None
        self.filename = None
        self.file_size = 0
        self.file_position = 0
        self.leftover = None
        self.leftover_size = 0
        self.leftover_position = 0
        self.last_data = None

    def read(self, nr_bytes):
        """Read nr_bytes from the file or if present the leftover data"""
        if self.leftover_size == 0:
            data = self.file.read(nr_bytes)
            self.file_position += nr_bytes
        elif nr_bytes <= self.leftover_size:
            self.leftover_size -= nr_bytes
            data = self.leftover[self.leftover_position:self.leftover_position+nr_bytes]
            self.leftover_position += nr_bytes
        elif nr_bytes > self.leftover_size:
            diff = nr_bytes - self.leftover_size
            data = self.leftover[self.leftover_position:] + self.file.read(diff)
            self.leftover_size = 0
            self.leftover_position += self.leftover_size
            self.file_position += diff
        self.last_data = data
        return data

    def read_trace(self, length):
        data = self.read(length)  # this will take care of reading from the leftover data iff needed
        trace = np.frombuffer(data, f'({length//4},2)<u2', count=1)[0, :, :]
        return trace.flatten()

    def skip_trace(self, length):
        # here we need to take care of reading from the leftover data explicitly
        if self.leftover_size == 0:
            self.file.seek(length, 1)
            self.file_position += length
        elif length <= self.leftover_size:
            self.leftover_size -= length
            self.leftover_position += length
        elif length > self.leftover_size:
            diff = length - self.leftover_size
            self.leftover_size = 0
            self.leftover_position += self.leftover_size
            self.file_position += diff
            self.file.seek(diff, 1)

    def __repr__(self):
        return f'{self.filename} size: {self.file_size} position: {self.file_position} leftover in file: {self.file_size-self.file_position} leftover in buffer: {self.leftover_size}'


# create a single buffer for reading list mode data that is persistent between opening different files
buffer = Buffer()


def read_list_mode_data(filename, keep_trace=False, return_namedtuple=True, clear_buffer=False):
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

    HEADER = struct.Struct('<2I4H')
    SUMS = struct.Struct('<3If')

    if clear_buffer:
        buffer.clear()

    with filename.open('rb') as f:
        buffer.add_file(filename, f)
        while True:
            nr_event += 1
            try:
                # check if we have enough data to read 16 bytes
                if buffer.file_size - buffer.file_position < 16:
                    buffer.add_leftover()
                    break

                [pileup_bits, eventtime_lo, eventtime_hi,
                 cfd_bits, event_energy, trace_bits] = HEADER.unpack_from(buffer.read(4*4))

                s = pileup_bits
                pileup = s >> 31   # 1 if pile-up event
                event_length = (s >> 17) & ((1 << 14)-1)
                header_length = (s >> 12) & 0b11111
                crate_id = (s >> 8) & 0b1111
                slot_id = (s >> 4) & 0b1111
                channel_nr = s & 0b1111

                # current file position will be 16 ahead, since we already read those
                # is there enough data in the file to read the rest of the event?
                if 4*event_length + buffer.leftover_size + buffer.file_position - 16 > buffer.file_size:
                    buffer.add_split_event()
                    break

                s = cfd_bits
                cfd_trigger_bits = (s >> 13) & 0b111
                cfd_fractional = s & ((1 << 13)-1)

                s = trace_bits
                trace_flag = s >> 15  # 1 if trace out of ADC range (clipped)
                trace_length = s & ((1 << 16) - 1)

                if header_length == 4:
                    # already read all information
                    Esum_trailing, Esum_leading, Esum_gap, baseline = 0, 0, 0, 0.0
                elif header_length == 8:
                    # energy sums
                    [Esum_trailing, Esum_leading, Esum_gap, baseline] = SUMS.unpack_from(buffer.read(4*4))
                else:
                    raise NotImplementedError(f'Do not know what to do with header_length {header_length}')
            except struct.error:
                # no more data available
                break

            trace_data_length = event_length - header_length
            if trace_data_length > 0:
                if keep_trace:
                    trace = buffer.read_trace(4*trace_data_length)
                else:
                    buffer.skip_trace(4*trace_data_length)  # advances the file position by the correct amount
                    trace = []
            else:
                trace = []

            CFD_error = False
            TS = (eventtime_lo + (eventtime_hi << 32))*10  # in ns
            if cfd_trigger_bits == 7:
                CFD_error = True
                CFD_fraction = 0
            else:
                CFD_fraction = (cfd_trigger_bits-1 + cfd_fractional/8192)*2  # in ns

            if return_namedtuple:
                yield Event(channel_nr, crate_id, slot_id, TS, CFD_fraction, event_energy, trace, CFD_error, pileup, trace_flag,
                            Esum_trailing, Esum_leading, Esum_gap, baseline)
            else:
                yield (channel_nr, crate_id, slot_id, TS, CFD_fraction, event_energy, trace, CFD_error, pileup, trace_flag,
                       Esum_trailing, Esum_leading, Esum_gap, baseline)

    return


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
            outread['FastPeaks'] = [outread['FastPeaksA'][i] * 2
                                    ** 32 + outread['FastPeaksB'][i] for i in range(16)]
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


def compare_module_setting(modA, modB, quiet=False, writeable_only=True):
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
        if writeable_only:
            if modA.writeable is not None:
                modA = [modA.writeable]
                modB = [modB.writeable]
            else:
                modA = [val for sublist in modA.writeable_list for val in sublist]
                modB = [val for sublist in modB.writeable_list for val in sublist]
        else:
            if modA.writeable is not None:
                modA = [modA.writeable]
                modB = [modB.writeable]
            else:
                modA = [val for sublist in modA.writeable_list for val in sublist]
                modB = [val for sublist in modB.writeable_list for val in sublist]

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
