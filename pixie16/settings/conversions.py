from math import ceil

from ..constants import *


def identity(x):
    return x


conversions = {}


def conversion(units_from, units_to):
    if units_from not in conversions:
        conversions[units_from] = {}
        conversions[units_from][units_from] = identity

    def decorate(func):
        conversions[units_from][units_to] = func
        return func

    return decorate


@conversion('ns', 's')
def _(x):
    return x / 1e9


@conversion('ns', 'ms')
def _(x):
    return x / 1e6


@conversion('ns', 'us')
def _(x):
    return x / 1e3


@conversion('us', 'ns')
def _(x):
    return 1e3 * x


@conversion('s', 'm')
def _(x):
    return x / 60


@conversion('m', 'h')
def _(x):
    return x / 60


@conversion('h', 'd')
def _(x):
    return x / 24


@conversion('FPGA_cycles', 'ADC_cycles')
def _(x):
    return x * ADC_CYCLES_PER_FPGA_CYCLE


@conversion('ADC_cycles', 'ns')
def _(x):
    return x * NS_PER_ADC_CYCLE


@conversion('slow_filter_cycles', 'FPGA_cycles')
def _(x, SlowFilterRange):
    return x * 2 ** SlowFilterRange


@conversion('fast_filter_cycles', 'FPGA_cycles')
def _(x, FastFilterRange):
    return x * 2 ** FastFilterRange


@conversion('FPGA_cycles', 'fast_filter_cycles')
def _(x, FastFilterRange):
    return x // 2 ** FastFilterRange


@conversion('FPGA_cycles', 'slow_filter_cycles')
def _(x, SlowFilterRange):
    return x // 2 ** SlowFilterRange


@conversion('fast_filter_amplitude', 'ADC_amplitude')
def _(x, FastLength):
    return x / FastLength / ADC_CYCLES_PER_FPGA_CYCLE
