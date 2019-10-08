# -*- coding: utf-8 -*-
"""
Created on Mon Oct  7 15:10:14 2019

@author: Mauricio
"""

from pixie16 import plot
from ROOTS.helper import find_file
from pixie16 import read
import numpy as np
from collections import Counter
import sys


# tested files:
# alpha det: 2019-08-16-test-alpha-det0018_mod00.bin
# API:

fname = find_file('2019-08-16-test-alpha-det0018_mod00.bin')
setfile = find_file('2019-08-16-test-alpha-det0018.set')

module = 0
ch = 2


trace, energy, trailsum, gapsum, leadsum, baseline, all_channels = (
    [],
    [],
    [],
    [],
    [],
    [],
    [],
)
cfderror, clipped, pileup, time = [], [], [], []
data = list(read.read_list_mode_data(fname, keep_trace=True))
print("Total number of events: ", len(data))
for d0 in data:
    all_channels.append(d0.channel)
for d in data:
    if d.channel == ch:
        trace.append(d.trace)
        energy.append(d.energy)
        trailsum.append(d.Esum_trailing)
        gapsum.append(d.Esum_gap)
        leadsum.append(d.Esum_leading)
        cfderror.append(d.CFD_error)
        clipped.append(d.trace_flag)
        pileup.append(d.pileup)
        baseline.append(d.baseline)
        time.append(d.timestamp)
        
data_count = Counter(all_channels)
print("CFD errors = ", cfderror.count(1))
print("pileup events = ", pileup.count(1))
print("clipped events = ", clipped.count(1))
print("Channels used and ocurrences: ", data_count)
trace = np.array(trace)
cfderror = np.array(cfderror)
t = np.linspace(0, 2 * (trace.shape[1] - 1), trace.shape[1])  # in ns
if len(trailsum) == 0:
    print("Error: Raw energy sums must be anabled in the PIXIE-16")
    sys.exit()
    

plot.CFD(trace, setfile, ch, module)

    

