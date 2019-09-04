"""
Functions to help test PIXIE-16 data

"""

import numpy as np
from ROOTS.helper import find_file
from pixie16 import read
from collections import Counter, namedtuple
import datashader as ds
import datashader.transfer_functions as tf
from matplotlib.colors import LogNorm
import matplotlib.pyplot as plt


# test files
fname0 = '2019-08-16-test-alpha-det0018_mod00.bin'
setfile0 = fname0[0:-10]+'.set'
fname = find_file(fname0)
setfile = find_file(setfile0)
ch = 4
module = 0

if fname0[-3:] == 'bin':
    binary_file = True
else:
    binary_file = False

if binary_file:
    trace, energy, trailsum, gapsum, leadsum, baseline, all_channels = [], [], [], [], [], [], []
    cfderror, clipped, pileup, time = [], [], [], []
    data = list(read.read_list_mode_data(fname, keep_trace=True))
    for d0 in data:
        all_channels.append(d0.channel)
    for d in data:
        if (d.channel == ch):
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
    print('CFD errors = ', cfderror.count(1))  
    print('pileup events = ', pileup.count(1))
    print('clipped events = ', clipped.count(1))
    trace = np.array(trace)
    cfderror = np.array(cfderror)
    IDX = np.arange(0,trace.shape[0],1)  
    IDXcfderror = IDX[cfderror]
    IDXgood = IDX[~cfderror]
    t = np.linspace(0, 2*(trace.shape[1]-1), trace.shape[1])  # in ns
    data_count = Counter(all_channels)
    print('Channels used and ocurrences: ', data_count)

def shift_traces(traces, r):
    '''Shift traces by r indices.
    traces and r must be >1D numpy arrays
    '''
    if isinstance(traces,np.ndarray) and isinstance(r,np.ndarray):
        rows, column_indices = np.ogrid[:traces.shape[0], :traces.shape[1]]    
        r[r < 0] += traces.shape[1]
        column_indices = column_indices - r[:,np.newaxis]
    else:
        raise Exception('wrong type. Need numpy arrays')
    return traces[rows, column_indices]

def read_settings(file):
    parameters = namedtuple('parameters', ['Gs', 'Ls', 'Lf', 'ADCth', 'FFth',
                             'CFDth', 'Gf', 'liveTime'])
    setting = read.XIASetting(file, module)
    S = setting.writeable
    Sr = setting.readable
    liveTime = round(Sr['LiveTime'][ch],2)
    l = S['TraceLength'][ch]
    assert l == len(trace[0]), f'{l} {len(trace[0])}'
    Gs = S['SlowGap'][ch]*10
    Ls = S['SlowLength'][ch]*10
    Lf = S['FastLength'][ch]*5
    ADCth = S['FastThresh'][ch]/Lf
    FFth = S['FastThresh'][ch]
    CFDth = S['CFDThresh'][ch] 
    Gf =  S['FastGap'][ch]
    return parameters(Gs, Ls, Lf, ADCth, FFth, CFDth, Gf, liveTime)

def advindexing_roll(A, r):
        rows, column_indices = np.ogrid[:A.shape[0], :A.shape[1]]    
        r[r < 0] += A.shape[1]
        column_indices = column_indices - r[:,np.newaxis]
        return A[rows, column_indices]
    
# persistent plot
def create_plot(traces, x_range=None):
    x_range = None
    data = traces
    mytime = np.linspace(0, 2*(traces.shape[1]-1), traces.shape[1])  # in us
    
    if x_range is None:
        x_range = [mytime[0], mytime[-1]]
    y_range = [data.min(), data.max()]
    cvs = ds.Canvas(plot_height=400, plot_width=1000, x_range=x_range,
                    y_range=y_range)
    df = ds.utils.dataframe_from_multiple_sequences(mytime, data)
    agg = cvs.line(df, 'x', 'y', agg=ds.count())
    img = tf.shade(agg, how='eq_hist')
    fig, ax = plt.subplots(figsize=(12,6))
    ax.imshow(img, extent=[x*1 for x in x_range]+[y*1 for y in
              y_range], aspect='auto', origin='lower', norm=LogNorm())
    ax.set_xlabel('Time [ns]')
    ax.set_ylabel('ADC units [a.u]')
    
    plt.show()
    
def persistence():
    '''find the index where the raw energy sums are caluclated and plot all
       traces in persistence mode. This can take a long time, so don't run 
       for too long'''
    setting = read_settings(setfile)
    sumIDX = []
    for j in range(len(trace)):
        for i in range(len(trace[j])-2*setting.Ls-setting.Gs):
            s1 = np.sum(trace[j][i:i+setting.Ls])
            s2 = np.sum(trace[j][i+setting.Ls:i+setting.Ls+setting.Gs])
            s3 = np.sum(trace[j][i+setting.Ls+setting.Gs:i+setting.Ls+setting.Gs+setting.Ls])
            #print([s1, s2, s3], [Esum1, Esum2, Esum3])
            if [s1, s2, s3] == [trailsum[j],gapsum[j] , leadsum[j]]:
                sumIDX.append(i)
                #print(f'found it at {sumIDX}')
                break
        else:
            print('Could not find sums!')
            print('Try increasing trace length and/or trace delay and run again')
    
    sumIDX = np.array(sumIDX)        
    gapIDX = sumIDX + setting.Ls
    minsumIDX = sumIDX.min()
    shiftIDX = sumIDX - minsumIDX
    traceshift = advindexing_roll(trace,-shiftIDX)
    
    create_plot(traceshift[IDXgood])
    plt.plot([t[minsumIDX],t[minsumIDX]],[trace.min(),trace.max()],'r--', label='raw energy sums')
    plt.plot([t[minsumIDX+setting.Ls],t[minsumIDX+setting.Ls]],[trace.min(),trace.max()],'r--')
    plt.plot([t[minsumIDX+setting.Ls + setting.Gs], t[minsumIDX+setting.Ls +setting.Gs]],[trace.min(),trace.max()],'r--')
    plt.plot([t[minsumIDX+setting.Ls + setting.Gs+ setting.Ls],t[minsumIDX + setting.Ls + setting.Gs + setting.Ls]],[trace.min(),
             trace.max()],'r--')
    plt.legend()
    plt.title(f'channel: {ch}; number of traces: {data_count[ch]}; live time: {setting.liveTime}s') 

    
 