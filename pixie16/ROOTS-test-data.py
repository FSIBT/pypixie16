"""
Usage:
  ROOTS-test-data.py <binFile> <channel> [options]
  
options:
  --persistence   persistence plot of traces
  --own_cfd       perform own CFD calculation and plot traces amd thresholds
  --energy        plot energy histogram, filter, and peakSample
      
Functions to help test PIXIE-16 data
Need to have traces and raw energy sums enabled      
"""

# test file alpha det: 2019-08-16-test-alpha-det0018_mod00.bin

import docopt
commands = docopt.docopt(__doc__)
print(commands)

ch = int(commands['<channel>'])

import numpy as np
from ROOTS.helper import find_file
from pixie16 import read
from collections import Counter, namedtuple
import datashader as ds
import datashader.transfer_functions as tf
from matplotlib.colors import LogNorm
import matplotlib.pyplot as plt
from pixie16.analyze import calculate_CFD_using_FF, calculate_filter
import sys


# test files
fname0 = commands['<binFile>']
setfile0 = fname0[0:-10]+'.set'

if fname0[-3:] != 'bin':
    print('Error: Need a PIXIE-16 binary file')
    sys.exit()
    
fname = find_file(fname0)
print(fname)
setfile = find_file(setfile0)
module = 0



trace, energy, trailsum, gapsum, leadsum, baseline, all_channels = [], [], [], [], [], [], []
cfderror, clipped, pileup, time = [], [], [], []
data = list(read.read_list_mode_data(fname, keep_trace=True))
print('Total number of events: ', len(data))
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
#IDXcfderror = IDX[cfderror]
#IDXgood = IDX[~cfderror]
IDXgood = IDX
t = np.linspace(0, 2*(trace.shape[1]-1), trace.shape[1])  # in ns
data_count = Counter(all_channels)
print('Channels used and ocurrences: ', data_count)
if len(trailsum) == 0:
    print('Error: Raw energy sums must be anabled in the PIXIE-16')
    sys.exit()

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
    parameters = namedtuple('parameters', ['Gs', 'Ls', 'Lf', 'FFth',
                             'CFDth', 'CFDdelay', 'Gf', 'liveTime', 'PeakSample'])
    S = read.Settings(file, module)
    liveTime = round(S['LiveTime'][ch],2) # seconds
    l = S['TraceLength'][ch]
    assert l == len(trace[0]), f'{l} {len(trace[0])}'
    Gs = S['SlowGap'][ch]*2/100 # us
    Ls = S['SlowLength'][ch]*2/100 # us
    Lf = S['FastLength'][ch]/100 # us
    Gf =  S['FastGap'][ch]/100
    FFth = S['FastThresh'][ch]*2/100  # ADC units
    CFDth = S['CFDThresh'][ch] # ADC units 
    CFDdelay = S['CFDDelay'][ch] # us
    PeakSample = S['PeakSample'][ch]
    return parameters(Gs, Ls, Lf, FFth, CFDth, CFDdelay, Gf, liveTime, PeakSample)

def advindexing_roll(A, r):
    ''' Roll rows of a 2D matrix independently
    A must be a 2D numpy array and r a 1D numpy array'''
    if len(A.shape) != 2:
        print('Error: The trace input must be a 2D numpy array')
        sys.exit()
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
    
    #plt.show()
    
def persistence(trace, plot=True):
    '''find the index where the raw energy sums are caluclated and plot all
       traces in persistence mode. This can take a long time, so don't run 
       for too long'''
    print('Creating persistence plot...')   
    setting = read_settings(setfile)
    sumIDX = []
    Ls = int(setting.Ls*1000/2)
    Gs = int(setting.Gs*1000/2)
    for j in range(len(trace)):
        for i in range(len(trace[j])-2*Ls - Gs):
            s1 = np.sum(trace[j][i:i+Ls])
            s2 = np.sum(trace[j][i+Ls:i+Ls+Gs])
            s3 = np.sum(trace[j][i+Ls+Gs:i+Ls+Gs+Ls])
            #print([s1, s2, s3], [Esum1, Esum2, Esum3])
            if [s1, s2, s3] == [trailsum[j],gapsum[j] , leadsum[j]]:
                sumIDX.append(i)
                #print(f'found it at {sumIDX}')
                break
        else:
            print('Error: Could not find sums!')
            print('Error: Try increasing trace length and/or trace delay and run again')
            sys.exit()
    
    sumIDX = np.array(sumIDX)        
    #gapIDX = sumIDX + Ls
    minsumIDX = sumIDX.min()
    shiftIDX = sumIDX - minsumIDX
    traceshift = advindexing_roll(trace,-shiftIDX)
    
    if plot:
        create_plot(traceshift[IDXgood])
        plt.plot([t[minsumIDX],t[minsumIDX]],[trace.min(),trace.max()],'r--', label='raw energy sums')
        plt.plot([t[minsumIDX+Ls],t[minsumIDX+Ls]],[trace.min(),trace.max()],'r--')
        plt.plot([t[minsumIDX+Ls + Gs], t[minsumIDX+Ls + Gs]],[trace.min(),trace.max()],'r--')
        plt.plot([t[minsumIDX+Ls + Gs+ Ls],t[minsumIDX + Ls + Gs + Ls]],[trace.min(),
                 trace.max()],'r--')
        plt.legend()
        plt.title(f'channel: {ch}; number of traces: {data_count[ch]}; live time: {setting.liveTime}s') 
        plt.show()
        
    return sumIDX


def own_CFD(w,num_traces):
    # perform own CFD calculation
    setting = read_settings(setfile)
    CFDth = setting.CFDth
    Lf = int(setting.Lf*100)
    Gf = int(setting.Gf*100)
    FFth = setting.FFth 
    
    w = [w]
    B = [5]
    D = [5]
    L = [1]
    
    CFD, cfdtime, FF, IDXerr = calculate_CFD_using_FF(trace, t=t, CFD_threshold=CFDth, FF_threshold=FFth, Lf=Lf, Gf=Gf,
                                                          w=w[0], B=B[0], D=D[0], L=L[0], Nbkgd=10, FF_delay=20, CFD_delay=0)
 
    cfdtime = cfdtime[cfdtime != np.array(None)] # throw away CFD errors    
    tcfd = t[B[0]+D[0]:trace.shape[1]-L[0]+1]
    tff = t[0:FF.shape[1]]
    
    for i in range(num_traces):
        plt.figure()
        plt.plot(t,trace[i],label='Trace')
        plt.plot(tcfd,CFD[i],label='CFD')
        plt.plot(tff,FF[i],label='Fast Filter')
        plt.plot([t[0],t[-1]],[CFDth,CFDth], label='CFD Threshold')
        plt.plot([t[0],t[-1]],[FFth,FFth], label='FF Threshold')
        plt.plot(cfdtime[i],0,'.', ms=10)
        plt.legend() 
        plt.show()
    return CFD, CFDth

def energy_filter(num_traces):
    '''calculate energy filter and plot a certain number 
    (num_traces). Also plots the trace, FF, and peak sample'''
    setting = read_settings(setfile)
    Ls1 = int(setting.Ls*1000/2)
    Gs1 = int(setting.Gs*1000/2)
    Lf1 = int(setting.Lf*1000/2)
    Gf1 = int(setting.Gf*1000/2)
    PS = setting.PeakSample*10 # in FPGA cycles (pp. 85)
    
    SF = calculate_filter(trace, L=Ls1, G=Gs1)
    FF = calculate_filter(trace, L=Lf1, G=Gf1)
    
    FFshift = trace.shape[1]-FF.shape[1]
    SFshift = trace.shape[1]-SF.shape[1]
    tff = np.arange(FFshift, trace.shape[1], 1)
    tsf = np.arange(SFshift, trace.shape[1], 1)
    
    for i in range(num_traces):
        idxth = np.where(FF[i]>setting.FFth)[0][0]  # idx where FF threshold is crossed
        Esample = PS + idxth + FFshift # sampling location
        plt.figure()
        plt.plot(trace[i], label='Trace')
        plt.plot(tff,FF[i], label='Fast filter')
        plt.plot(tsf,SF[i], label='Slow filter')
        plt.plot([trace[i].min(),trace[i].max()],[setting.FFth, setting.FFth], 'r--', label = 'FF threshold')
        plt.plot([Esample, Esample],[FF[i].min(), FF[i].max()], 'k--', label='E sample')
        plt.legend()
        plt.show()
    

if commands['--persistence']:
    persistence(trace)
    
if commands['--own_cfd']:
    CFD, CFDth = own_CFD(1,2)
    sumIDX = persistence(trace, plot=False)
    shiftIDX = sumIDX.min()
    CFDshift = advindexing_roll(CFD,-shiftIDX)
    setting = read_settings(setfile)
    CFDth = setting.CFDth
    create_plot(CFDshift)
    plt.plot([0, 2*(CFD.shape[1]-1)],[CFDth, CFDth], 'r--', label=f'CFD Threshold = {CFDth}')
    plt.title('CFD Trace')
    plt.title(f'channel: {ch}; number of CFD traces: {CFD.shape[0]}') 
    plt.legend()
    plt.show()

if commands['--energy']:
    
    
#    energy = np.array(energy)
#    
#    plt.hist(energy,500, edgecolor='k');
#    plt.xlabel('Energy [a.u]')
#    plt.ylabel('cts')
#    plt.title(f'Channel: {ch}; no. of events: {len(energy)}; live time: {setting.liveTime}s')
#    plt.show()
    
    
