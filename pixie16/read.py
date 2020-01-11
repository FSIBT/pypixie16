"""Read data files from XIA pixie16 instruments"""

import ctypes
import struct
import json
import numpy as np
import pandas as pd
from contextlib import contextmanager
from collections import namedtuple
from pathlib import Path

from .variables import settings


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


def converter_IEEE754_to_ulong(x):
    a = (ctypes.c_float * 1)(x)
    b = ctypes.cast(a, ctypes.POINTER(ctypes.c_ulong))
    return b.contents


def converter_ulong_to_IEEE754(x):
    a = (ctypes.c_ulong * 1)(x)
    b = ctypes.cast(a, ctypes.POINTER(ctypes.c_float))
    return b.contents.value


def iterate_pairs(mylist):
    """Go through an iterable and return the current item and the next"""

    if len(mylist) < 2:
        return
    for i, d in enumerate(mylist[:-1]):
        yield mylist[i], mylist[i + 1]
    return


class myIO:
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
        out = self.data[self.pos : self.pos + N]
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


class Buffer:
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
                f"Buffer must be either a pathlb Path object or a in memory object(myIO): {f}"
            )

    def add_split_event(self):
        """An incomplete event was found

        his means we already parsed the first 16 bytes, so we need to
        add those and the remainig data in the file to the buffer.

        """
        self.leftover = self.last_data + self.file.read(
            self.file_size - self.file_position
        )
        self.leftover_size = len(self.leftover)
        self.leftover_position = 0

    def add_leftover(self):
        """A small amount of data is left over

        Not enought to even parse the first 16 bytes. This gets triggered before the first 16 bytes are read.

        """
        self.leftover = self.file.read(self.file_size - self.file_position)
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
            data = self.leftover[
                self.leftover_position : self.leftover_position + nr_bytes
            ]
            self.leftover_position += nr_bytes
        elif nr_bytes > self.leftover_size:
            diff = nr_bytes - self.leftover_size
            data = self.leftover[self.leftover_position :] + self.file.read(diff)
            self.leftover_size = 0
            self.leftover_position += self.leftover_size
            self.file_position += diff
        self.last_data = data
        return data

    def read_trace(self, length):
        data = self.read(
            length
        )  # this will take care of reading from the leftover data iff needed
        trace = np.frombuffer(data, f"({length//4},2)<u2", count=1)[0, :, :]
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
        return f"{self.filename} size: {self.file_size} position: {self.file_position} leftover in file: {self.file_size-self.file_position} leftover in buffer: {self.leftover_size}"


# create a single buffer for reading list mode data that is persistent between opening different files
buffer = Buffer()


def read_list_mode_data(
    filename, keep_trace=False, return_namedtuple=True, clear_buffer=True
):
    """Read list mode data from binary file

    See section 4.4.2 in Manual, page 70

    filename can be either a pathlib.Path object or a myIO object defined in pixie16.read.
    """

    if not (isinstance(filename, Path) or isinstance(filename, myIO)):
        try:
            filename_new = Path(filename)
        except TypeError:
            print(f"Error: cannot convert {filename} to Path object")
            print(
                f"Error: filename {filename} needs to be a pathlib.Path, str, or myIO object"
            )
            return
        filename = filename_new

    nr_event = 0

    HEADER = struct.Struct("<2I4H")
    SUMS = struct.Struct("<3If")

    if clear_buffer:
        buffer.clear()

    with filename.open("rb") as f:
        buffer.add_file(filename, f)
        while True:
            nr_event += 1
            try:
                # check if we have enough data to read 16 bytes
                if buffer.file_size - buffer.file_position < 16:
                    buffer.add_leftover()
                    break

                [
                    pileup_bits,
                    eventtime_lo,
                    eventtime_hi,
                    cfd_bits,
                    event_energy,
                    trace_bits,
                ] = HEADER.unpack_from(buffer.read(4 * 4))

                s = pileup_bits
                pileup = s >> 31  # 1 if pile-up event
                event_length = (s >> 17) & ((1 << 14) - 1)
                header_length = (s >> 12) & 0b11111
                crate_id = (s >> 8) & 0b1111
                slot_id = (s >> 4) & 0b1111
                channel_nr = s & 0b1111

                # current file position will be 16 ahead, since we already read those
                # is there enough data in the file to read the rest of the event?
                if (
                    4 * event_length + buffer.leftover_size + buffer.file_position - 16
                    > buffer.file_size
                ):
                    buffer.add_split_event()
                    break

                s = cfd_bits
                cfd_trigger_bits = (s >> 13) & 0b111
                cfd_fractional = s & ((1 << 13) - 1)

                s = trace_bits
                trace_flag = s >> 15  # 1 if trace out of ADC range (clipped)
                trace_length = s & ((1 << 16) - 1)

                if header_length == 4:
                    # already read all information
                    Esum_trailing, Esum_leading, Esum_gap, baseline = 0, 0, 0, 0.0
                elif header_length == 8:
                    # energy sums
                    [
                        Esum_trailing,
                        Esum_leading,
                        Esum_gap,
                        baseline,
                    ] = SUMS.unpack_from(buffer.read(4 * 4))
                else:
                    raise NotImplementedError(
                        f"Do not know what to do with header_length {header_length}"
                    )
            except struct.error:
                # no more data available
                break

            trace_data_length = event_length - header_length
            if trace_data_length > 0:
                if keep_trace:
                    trace = buffer.read_trace(4 * trace_data_length)
                else:
                    buffer.skip_trace(
                        4 * trace_data_length
                    )  # advances the file position by the correct amount
                    trace = []
            else:
                trace = []

            CFD_error = False
            TS = (eventtime_lo + (eventtime_hi << 32)) * 10  # in ns
            if cfd_trigger_bits == 7:
                CFD_error = True
                CFD_fraction = 0
            else:
                CFD_fraction = (
                    cfd_trigger_bits - 1 + cfd_fractional / 8192
                ) * 2  # in ns

            if return_namedtuple:
                yield Event(
                    channel_nr,
                    crate_id,
                    slot_id,
                    TS,
                    CFD_fraction,
                    event_energy,
                    trace,
                    CFD_error,
                    pileup,
                    trace_flag,
                    Esum_trailing,
                    Esum_leading,
                    Esum_gap,
                    baseline,
                )
            else:
                yield (
                    channel_nr,
                    crate_id,
                    slot_id,
                    TS,
                    CFD_fraction,
                    event_energy,
                    trace,
                    CFD_error,
                    pileup,
                    trace_flag,
                    Esum_trailing,
                    Esum_leading,
                    Esum_gap,
                    baseline,
                )

    return


def read_mca_mode_data(filename):
    """Read MCA data files: 32k 32bit words for 16 channels"""

    results = {}
    with open(filename, "rb") as f:
        for channel in range(16):
            spectrum = []
            for i in range(32 * 1024):
                spectrum.append(int.from_bytes(f.read(4), byteorder="little"))
            spectrum = np.array(spectrum)
            results[channel] = spectrum
    return results


class Units:
    """"Convert settings to units (seconds) for the appropiate values"""

    # list of settings that save binary data, list the start points of each group of bits
    hex = {
        "ChanCSRa": [
            21,
            20,
            19,
            18,
            17,
            16,
            15,
            14,
            13,
            12,
            11,
            10,
            9,
            8,
            7,
            6,
            5,
            4,
            3,
            2,
            1,
            0,
        ],
        "ChanCSRb": [14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 1, 0],
        "MultiplicityMaskH": [31, 30, 27, 24, 21, 16, 15, 0],
        "MultiplicityMaskL": [31, 15, 0],
        "TrigConfig": [
            [31, 27, 25, 23, 19, 15, 14, 11, 7, 3, 0],
            [31, 27, 23, 19, 15, 11, 7, 3, 0],
            [31, 27, 26, 25, 24, 23, 21, 19, 17, 15, 11, 7, 3, 0],
            [],
        ],
    }

    def __init__(self, parent):
        self.parent = parent

    def convert_to_units(self, name):
        if name not in self.parent.derived_keys:
            value = self.parent[name]

        FPGA_CYCLE = 10
        DATAPOINTS_PER_CYCLE = 5

        if name in [
            "FastLength",
            "FastGap",
            "ExtTrigStretch",
            "VetoStretch",
            "FastTrigBackLen",
            "ExtDelayLen",
        ]:
            return [self.to_sec(v * FPGA_CYCLE) for v in value]
        elif name == "PeakSample":
            return [v for v in value]
        elif name == "PeakSep":
            return [v for v in value]
        elif name in ["SlowLength", "SlowGap"]:
            filter_range = self.parent.SlowFilterRange
            return [self.to_sec(v * FPGA_CYCLE * 2 ** filter_range) for v in value]
        elif name == "FastThresh":
            L = self.parent["FastLength"]
            return [v / l / DATAPOINTS_PER_CYCLE for v, l in zip(value, L)]
        elif name == "CDFTresh":
            return [v for v in value]
        elif name == "TraceLength":
            return [v * FPGA_CYCLE / DATAPOINTS_PER_CYCLE for v in value]
        elif name == "OffsetDAC":
            return [v for v in value]
        elif name == "GainDAC":
            return [v for v in value]
        elif name == "ChanCSRb":
            return [v for v in value]
        elif name == "TrigConfig":
            out = []
            for k, pos in zip(value, Units.hex[name]):
                bin_value = f"{k:032b}"
                tmp = "-".join(
                    [f"{a-1}:{bin_value[32-a:32-b]}" for a, b in iterate_pairs(pos)]
                )
                out.append(tmp)
            return out
        elif name in Units.hex.keys():
            out = []
            for k in value:
                bin_value = f"{k:032b}"
                tmp = "-".join(
                    [
                        f"{a-1}:{bin_value[32-a:32-b]}"
                        for a, b in iterate_pairs(Units.hex[name])
                    ]
                )
                out.append(tmp)
            return out
        # derived values
        elif name == "LiveTime":
            return [
                self.to_sec(
                    (
                        self.parent["LiveTimeA"][i] * 2 ** 32
                        + self.parent["LiveTimeB"][i]
                    )
                    * FPGA_CYCLE
                )
                for i in range(16)
            ]
        elif name == "FastPeaks":
            return [
                self.parent["FastPeaksA"][i] * 2 ** 32 + self.parent["FastPeaksB"][i]
                for i in range(16)
            ]
        elif name == "RealTime":
            return self.to_sec(
                (self.parent["RealTimeA"] * 2 ** 32 + self.parent["RealTimeB"])
                * FPGA_CYCLE
            )
        elif name == "RunTime":
            return self.to_sec(
                (self.parent["RunTimeA"] * 2 ** 32 + self.parent["RunTimeB"])
                * FPGA_CYCLE
            )
        elif name == "TraceDelay":
            return [
                self.to_sec((p - t) * FPGA_CYCLE)
                for p, t in zip(self.parent["PAFlength"], self.parent["TriggerDelay"])
            ]
        elif name == "OffsetVoltage":
            return [
                1.5 * ((32768 - self.parent["OffsetDAC"][i]) / 32768) for i in range(16)
            ]
        return value

    @staticmethod
    def to_sec(ns):
        """Convert ns readable format"""

        USEC = 1000
        MSEC = 1000 * USEC
        SECONDS = 1000 * MSEC
        MINUTES = 60 * SECONDS
        HOURS = 60 * MINUTES
        DAY = 24 * HOURS

        out = []
        for t in [DAY, HOURS, MINUTES, SECONDS, MSEC, USEC]:
            tmp = 0
            while ns > t:
                ns -= t
                tmp += 1
            out.append(tmp)
        out.append(ns)

        t = " ".join(
            [
                f"{value}{label}"
                for value, label in zip(out, ["d", "h", "m", "s", "ms", "us", "ns"])
                if value > 0
            ]
        )

        return t

    def print(self, *args, **kwargs):
        kwargs.pop("units", None)
        self.parent.print(*args, **kwargs, units=True)

    def __getitem__(self, key):
        return self.convert_to_units(key)

    def __getattr__(self, attr):
        return self.convert_to_units(attr)

    def __dir__(self):
        keys = list(self.parent.readable.keys()) + list(self.parent.writeable.keys())
        keys = keys + Settings.derived_keys
        keys = [k for k in keys if k not in Settings.derived_from_keys]
        return keys


class Settings:
    """Capture all the settings from a single module """

    derived_keys = [
        "LiveTime",
        "FastPeaks",
        "RealTime",
        "RunTime",
        "TraceDelay",
        "OffsetVoltage",
    ]
    derived_from_keys = [
        "LiveTimeA",
        "LiveTimeB",
        "FastPeaksA",
        "FastPeaksB",
        "RealTimeA",
        "RealTimeB",
        "RunTimeA",
        "RunTimeB",
        "PAFlength",
        "TriggerDelay",
        "OffsetDAC",
    ]

    def __init__(self, filename: str, modulenr: int):
        self.filename = Path(filename)
        self.modulenr = modulenr
        self.writeable = {}
        self.readable = {}
        self.rawdata = None
        self.read_setting(filename)
        self.units = Units(self)

    def read_setting(self, filename: str):
        """Read setting data files: 24 x 1280 data points, each 32 bit

        We return a list with data for each of the 24 modules. The list contains
        two dictionaries. The first one has all the settings that are writebale,
        the second one contains all the read_only settings.
        """

        # all numbers are stored as ulong (32bit unsigned integer) but
        # some should be read back as IEEE754 floats. Keep a list of
        # variables, where we need to convert
        FLOATS = ["PreampTau", "HostRunTimePreset"]

        filename = Path(filename)
        size = filename.stat().st_size
        if size != 24 * 4 * 1280:
            raise TypeError(
                f"Error: {filename.name} does not seem to be a setting file (wrong size {size})...aborting"
            )

        with open(filename, "rb") as f:
            for module in range(24):
                rawsetting = []
                for i in range(1280):
                    rawsetting.append(int.from_bytes(f.read(4), byteorder="little"))
                if module == self.modulenr:
                    self.rawdata = rawsetting
                    break

        for n, [pos, length] in settings.items():
            if n in FLOATS:
                value = [
                    converter_ulong_to_IEEE754(self.rawdata[pos + k])
                    for k in range(length)
                ]
            else:
                value = [self.rawdata[pos + k] for k in range(length)]
            if length == 1:
                if pos < 832:
                    self.writeable[n] = value[0]
                else:
                    self.readable[n] = value[0]
            else:
                if pos < 832:
                    self.writeable[n] = value
                else:
                    self.readable[n] = value

        # some derived values
        self.readable["TriggerDelay"] = [
            (p - 1) * 2 ** self["SlowFilterRange"] for p in self["PeakSep"]
        ]

    def __getitem__(self, key):
        if key in self.readable:
            return self.readable[key]
        if key in self.writeable:
            return self.writeable[key]
        raise KeyError(f'Key "{key}" not in Settings')

    def __getattr__(self, attr):
        if attr in self.readable:
            return self.readable[attr]
        if attr in self.writeable:
            return self.writeable[attr]
        raise AttributeError

    def __dir__(self):
        return list(self.readable.keys()) + list(self.writeable.keys())

    def __str__(self):
        out = f"Pixie16 settings for {self.filename}\n"
        keys = sorted(list(self.readable.keys()) + list(self.writeable.keys()))
        for k in keys:
            ro = "(ro)" if k in self.readable else ""
            out += f"  {k}: {self[k]}  {ro}\n"
        return out

    def __repr__(self):
        return f"Pixie16 settings for {self.filename}"

    def print(self, channels=None, keys=None, units=False):
        """Pretty print the settings

        Optional the number of channels and settings names can be limited.

        This prints two groups: module parameters and channel parameters
        """
        if keys is None:
            keys = sorted(list(self.readable.keys()) + list(self.writeable.keys()))
            if units:
                keys = keys + Settings.derived_keys
                keys = [k for k in keys if k not in Settings.derived_from_keys]
        else:
            keys = sorted(keys)

        channel_keys = []
        for k in keys:
            if k in Settings.derived_keys:
                channel_keys.append(k)
            elif isinstance(self[k], list) and len(self[k]) == 16:
                channel_keys.append(k)

        print("Settings:")
        for k in keys:
            if k in channel_keys:
                continue
            ro = "(ro)" if k in self.readable else ""
            if units:
                value = self.units.convert_to_units(k)
            else:
                if k in Units.hex:
                    if isinstance(self[k], (list, tuple)):
                        value = [f"0x{v:09_x}" for v in self[k]]
                    else:
                        value = f"{self[k]:09_x}"
                else:
                    value = self[k]
            print(f"  {k}: {value}  {ro}")
        d = {}
        for k in channel_keys:
            ro = "(ro)" if k in self.readable else ""
            if units:
                d[f"{k}{ro}"] = self.units.convert_to_units(k)
            else:
                if k in Units.hex:
                    if isinstance(self[k], (list, tuple)):
                        d[f"{k}{ro}"] = [f"0x{v:09_x}" for v in self[k]]
                    else:
                        d[f"{k}{ro}"] = f"{self[k]:09_x}"
                else:
                    d[f"{k}{ro}"] = self[k]

        if d:
            # using pandas dataframe for easy printing, probably
            # should remove this, since this is the only place where
            # pandas is used at the moment
            d = pd.DataFrame(d).T
            if channels is not None:
                print(d[channels].to_string())
            else:
                print(d.to_string())


class XIASetting(Settings):
    """An alias for the settings class with a previous name"""

    def __init__(self, *args, **kwargs):
        print(
            'Pypixie: please update your code to use "Settings" instead of "XIASetting". Trying to use new code (this might not work)'
        )
        super().__init__(*args, **kwargs)


def compare_module_setting(
    A, B, quiet=False, writeable_only=True, units=True, channels=None
):
    """Compare the settings of two modules

    Print the difference.

    If quiet is True, then just return True/False

    The functions assumes that both settings have the same structure.
    """

    if type(A) != type(B):
        print(f"compare_module_setting: both items need to have the same type")
        return None

    if type(A) != Settings:
        print(f"compare_module_setting: both items need to be Setting classes")
        return None

    if not quiet:
        print("Comparing settings:")
        print(f"  a: {A.filename}")
        print(f"  b: {B.filename}")
        print("")

        if writeable_only:
            keys = [k for k in settings.keys() if settings[k][0] < 832]
        else:
            keys = list(settings.keys())

        if units:
            keys = keys + Settings.derived_keys
            keys = [k for k in keys if k not in Settings.derived_from_keys]

        for k in keys:
            if units:
                valueA = A.units[k]
                valueB = B.units[k]
            else:
                valueA = A[k]
                valueB = B[k]
            if isinstance(valueA, (int, str, float)):
                if valueA != valueB:
                    print(f"{k} differs:\n     a: {valueA}\n     b: {valueB}")
            elif isinstance(valueA, (list, tuple)):
                first = True
                for i, (a, b) in enumerate(zip(valueA, valueB)):
                    if channels:
                        if i not in channels:
                            continue
                    if a != b:
                        if first:
                            print(f"{k} differs:")
                            first = False
                        # if these are bit values, only show bits that are different
                        if isinstance(a, str) and "-" in a:
                            aa = a.split("-")
                            bb = b.split("-")
                            for x, y in zip(aa, bb):
                                if x != y:
                                    print(f"  ch:{i}\n     a: {x}\n     b: {y}")
                        else:
                            print(f"  ch:{i}\n     a: {a}\n     b: {b}")
            else:
                print("This shouldn't happen. type value A", type(valueA))

    # convert to a sorted json string to make deep comparison possible
    if writeable_only:
        return json.dumps(A.rawdata[:832], sort_keys=True) == json.dumps(
            B.rawdata[:832], sort_keys=True
        )
    else:
        return json.dumps(A.rawdata, sort_keys=True) == json.dumps(
            B.rawdata, sort_keys=True
        )
