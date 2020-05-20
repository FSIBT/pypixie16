import sys
from ..constants import *


def decode(settings):
    settings = decode_bits(settings)
    settings = decode_times(settings)
    settings = decode_FastPeaks(settings)
    settings = decode_TriggerDelay(settings)
    settings = decode_TraceDelay(settings)
    settings = decode_OffsetVoltage(settings)
    return settings


def test_bit(x, k):
    return x >> k & 1


def to_bits(x):
    n = sys.getsizeof(x)
    return tuple(test_bit(x, k) for k in range(n))


def decode_bits(settings):
    for item in ['ChanCSRa', 'ChanCSRb', 'MultiplicityMaskH', 'MultiplicityMaskL', 'TrigConfig']:
        settings[item] = tuple(to_bits(x) for x in settings[item])
    return settings


def decode_times(settings):
    for item, itemA, itemB in ((item, '{}A'.format(item), '{}B'.format(item))
                               for item in ['LiveTime', 'RealTime', 'RunTime']):
        settings[item] = tuple((A * 2 ** 32 + B) for A, B in zip(settings[itemA], settings[itemB]))
    return settings


def decode_FastPeaks(settings):
    settings['FastPeaks'] = tuple((A * 2 ** 32 + B) for A, B in zip(settings['FastPeaksA'], settings['FastPeaksA']))
    return settings


def decode_TriggerDelay(settings):
    filter_range = settings['SlowFilterRange'][0]
    settings['TriggerDelay'] = tuple((p - 1) * 2 ** filter_range for p in settings['PeakSep'])
    return settings


def decode_TraceDelay(settings):
    settings['TraceDelay'] = tuple((p - t) for p, t in zip(settings['PAFlength'], settings['TriggerDelay']))
    return settings


def decode_OffsetVoltage(settings):
    settings['OffsetVoltage'] = tuple(1.5 * ((32768 - odac) / 32768) for odac in settings['OffsetDAC'])
    return settings
