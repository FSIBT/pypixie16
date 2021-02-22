from dataclasses import dataclass
import struct

MODULE_SIZE = 4 * 1280


@dataclass
class Settings:
    ModNum
    ModCSRA
    ModCSRB
    ModFormat
    RunTask
    ControlTask
    MaxEvents
    CoincPattern
    CoincWait
    SynchWait
    InSynch
    Resume
    SlowFilterRange
    FastFilterRange
    ChanNum
    HostIO
    UserIn
    FastTrigBackplaneEna
    CrateID
    SlotID
    ModID
    TrigConfig
    U00
    HostRunTimePreset
    PowerUpInitDone
    ChanCSRa
    ChanCSRb
    GainDAC
    OffsetDAC
    DigGain
    SlowLength
    SlowGap
    FastLength
    FastGap
    PeakSample
    PeakSep
    CFDThresh
    FastThresh
    ThreshWidth
    PAFlength
    TriggerDelay
    ResetDelay
    ChanTrigStretch
    TraceLength
    Xwait
    TrigOutLen
    EnergyLow
    Log2Ebin
    MultiplicityMaskL
    PSAoffset
    PSAlength
    Integrator
    BLcut
    BaselinePercent
    FtrigoutDelay
    Log2Bweight
    PreampTau
    Xavg
    MultiplicityMaskH
    FastTrigBackLen
    CFDDelay
    CFDScale
    ExtTrigStretch
    VetoStretch
    ExternDelayLen
    QDCLen0
    QDCLen1
    QDCLen2
    QDCLen3
    QDCLen4
    QDCLen5
    QDCLen6
    QDCLen7
    RealTimeA
    RealTimeB
    RunTimeA
    RunTimeB
    GSLTtime
    NumEventsA
    NumEventsB
    DSPerror
    SynchDone
    BufHeadLen
    EventHeadLen
    ChanHeadLen
    UserOut
    AOutBuffer
    LOutBuffer
    AECorr
    LECorr
    HardwareID
    HardVariant
    FIFOLength
    FippiID
    FippiVariant
    DSPrelease
    DSPbuild
    DSPVariant
    U20
    LiveTimeA
    LiveTimeB
    FastPeaksA
    FastPeaksB
    OverflowA
    OverflowB
    InSpecA
    InSpecB
    UnderflowA
    UnderflowB
    ChanEventsA
    ChanEventsB
    AutoTau
    U30

    @property
    def TriggerDelay(self):
        return tuple(calc_trigger_delay(self.SlowFilterRange, p) for p in self.PeakSep)


BIT_FIELD_SIZE_TBL = {
    'MultiplicityMaskL': 32,
    'MultiplicityMaskH': 32,
    'FastTrigBackplaneEna': 32,
    'TrigConfig': 32,
    'ChanCSRa': 22,
    'ChanCSRb': 22,
    'ModCSRA': 14,
    'ModCSRB': 14
}


AB_FIELDS = ('LiveTime', 'RealTime', 'RunTime', 'FastPeaks', 'Overflow', 'InSpec', 'Underflow', 'ChanEvents',
             'NumEvents')


def int_to_bits(i, bits_length):
    """Converts int values to binary (in the form of a tuple of 0's and 1's)"""
    bit_fmt = '{' + ':0' + bits_length + '}'
    return tuple(int(j) for j in bit_fmt.format(i))


def combine_AB(A, B):
    """Combines hi lo bit separated fields"""
    return A*2**32 + B


def calc_trigger_delay(slow_filter_range, peak_sep):
    return (peak_sep - 1) * 2 ** slow_filter_range


def calc_trace_delay(paf_length, trigger_delay):
    return paf_length - trigger_delay


def calc_offset_voltage(offset_dac):
    return 1.5 * ((32768 - offset_dac)/32768)



SETTINGS_FILE_FORMAT = {
    'ModNum': (0, '<1L'),
    'ModCSRA': (4, '<1L'),
    'ModCSRB': (8, '<1L'),
    'ModFormat': (12, '<1L'),
    'RunTask': (16, '<1L'),
    'ControlTask': (20, '<1L'),
    'MaxEvents': (24, '<1L'),
    'CoincPattern': (28, '<1L'),
    'CoincWait': (32, '<1L'),
    'SynchWait': (36, '<1L'),
    'InSynch': (40, '<1L'),
    'Resume': (44, '<1L'),
    'SlowFilterRange': (48, '<1L'),
    'FastFilterRange': (52, '<1L'),
    'ChanNum': (56, '<1L'),
    'HostIO': (60, '<16L'),
    'UserIn': (124, '<16L'),
    'FastTrigBackplaneEna': (188, '<1L'),
    'CrateID': (192, '<1L'),
    'SlotID': (196, '<1L'),
    'ModID': (200, '<1L'),
    'TrigConfig': (204, '<4L'),
    'U00': (220, '<7L'),
    'HostRunTimePreset': (248, '<1f'),
    'PowerUpInitDone': (252, '<1L'),
    'ChanCSRa': (256, '<16L'),
    'ChanCSRb': (320, '<16L'),
    'GainDAC': (384, '<16L'),
    'OffsetDAC': (448, '<16L'),
    'DigGain': (512, '<16L'),
    'SlowLength': (576, '<16L'),
    'SlowGap': (640, '<16L'),
    'FastLength': (704, '<16L'),
    'FastGap': (768, '<16L'),
    'PeakSample': (832, '<16L'),
    'PeakSep': (896, '<16L'),
    'CFDThresh': (960, '<16L'),
    'FastThresh': (1024, '<16L'),
    'ThreshWidth': (1088, '<16L'),
    'PAFlength': (1152, '<16L'),
    'TriggerDelay': (1216, '<16L'),
    'ResetDelay': (1280, '<16L'),
    'ChanTrigStretch': (1344, '<16L'),
    'TraceLength': (1408, '<16L'),
    'Xwait': (1472, '<16L'),
    'TrigOutLen': (1536, '<16L'),
    'EnergyLow': (1600, '<16L'),
    'Log2Ebin': (1664, '<16L'),
    'MultiplicityMaskL': (1728, '<16L'),
    'PSAoffset': (1792, '<16L'),
    'PSAlength': (1856, '<16L'),
    'Integrator': (1920, '<16L'),
    'BLcut': (1984, '<16L'),
    'BaselinePercent': (2048, '<16L'),
    'FtrigoutDelay': (2112, '<16L'),
    'Log2Bweight': (2176, '<16L'),
    'PreampTau': (2240, '<16f'),
    'Xavg': (2304, '<16L'),
    'MultiplicityMaskH': (2368, '<16L'),
    'FastTrigBackLen': (2432, '<16L'),
    'CFDDelay': (2496, '<16L'),
    'CFDScale': (2560, '<16L'),
    'ExtTrigStretch': (2624, '<16L'),
    'VetoStretch': (2688, '<16L'),
    'ExternDelayLen': (2752, '<16L'),
    'QDCLen0': (2816, '<16L'),
    'QDCLen1': (2880, '<16L'),
    'QDCLen2': (2944, '<16L'),
    'QDCLen3': (3008, '<16L'),
    'QDCLen4': (3072, '<16L'),
    'QDCLen5': (3136, '<16L'),
    'QDCLen6': (3200, '<16L'),
    'QDCLen7': (3264, '<16L'),
    'RealTimeA': (3328, '<1L'),
    'RealTimeB': (3332, '<1L'),
    'RunTimeA': (3336, '<1L'),
    'RunTimeB': (3340, '<1L'),
    'GSLTtime': (3344, '<1L'),
    'NumEventsA': (3348, '<1L'),
    'NumEventsB': (3352, '<1L'),
    'DSPerror': (3356, '<1L'),
    'SynchDone': (3360, '<1L'),
    'BufHeadLen': (3364, '<1L'),
    'EventHeadLen': (3368, '<1L'),
    'ChanHeadLen': (3372, '<1L'),
    'UserOut': (3376, '<16L'),
    'AOutBuffer': (3440, '<1L'),
    'LOutBuffer': (3444, '<1L'),
    'AECorr': (3448, '<1L'),
    'LECorr': (3452, '<1L'),
    'HardwareID': (3456, '<1L'),
    'HardVariant': (3460, '<1L'),
    'FIFOLength': (3464, '<1L'),
    'FippiID': (3468, '<1L'),
    'FippiVariant': (3472, '<1L'),
    'DSPrelease': (3476, '<1L'),
    'DSPbuild': (3480, '<1L'),
    'DSPVariant': (3484, '<1L'),
    'U20': (3488, '<23L'),
    'LiveTimeA': (3580, '<16L'),
    'LiveTimeB': (3644, '<16L'),
    'FastPeaksA': (3708, '<16L'),
    'FastPeaksB': (3772, '<16L'),
    'OverflowA': (3836, '<16L'),
    'OverflowB': (3900, '<16L'),
    'InSpecA': (3964, '<16L'),
    'InSpecB': (4028, '<16L'),
    'UnderflowA': (4092, '<16L'),
    'UnderflowB': (4156, '<16L'),
    'ChanEventsA': (4220, '<16L'),
    'ChanEventsB': (4284, '<16L'),
    'AutoTau': (4348, '<16L'),
    'U30': (4412, '<16L')
}


def load_settings(file, module=0):

    # get bytes from file
    with open(file, 'rb') as fp:
        binary_data = memoryview(fp.read())
    binary_data = binary_data[module*MODULE_SIZE: (module+1)*MODULE_SIZE]

    # unpack field values from bytes
    settings_values = {}
    for field, (offset, fmt) in SETTINGS_FILE_FORMAT.items():
        settings_values[field] = struct.unpack_from(fmt, binary_data, offset)

    # convert mask/bit valued fields to tuples of 0's and 1's
    for field, size in BIT_FIELD_SIZE_TBL.items():
        settings_values[field] = tuple(int_to_bits(i, size) for i in settings_values[field])

    # combine hi lo bit separated fields
    for field in AB_FIELDS:
        settings_values[field] = tuple(combine_AB(a, b) for a, b in
                                       zip(settings_values[field+'A'], settings_values[field+'B']))

    # calculate settings values that need to be derived from field values
    settings_values['TriggerDelay'] = tuple(calc_trigger_delay(settings_values['SlowFilterRange'][0], p)
                                            for p in settings_values['PeakSep'])
    settings_values['TraceDelay'] = tuple(calc_trace_delay(p, t)
                                          for p, t in zip(settings_values['PAFlength'],
                                                          settings_values['TriggerDelay']))
    settings_values['OffsetVoltage'] = tuple(calc_offset_voltage(odac) for odac in settings_values['OffsetDAC'])

    # unpack singletons
    for key, value in settings_values.items():
        if len(value) == 1:
            settings_values[key] = value[0]
        else:
            settings_values[key] = value

    return Settings(settings_values)
