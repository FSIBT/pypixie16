# -*- coding: utf-8 -*-
from matplotlib import pyplot as plt
from pixie16 import read
from .read import Event
from functools import wraps
import random
import numpy as np
import sys
from collections import Counter, namedtuple
import datashader as ds
import datashader.transfer_functions as tf
from matplotlib.colors import LogNorm
import matplotlib.pyplot as plt
from pixie16.analyze import calculate_CFD_using_FF, calculate_filter

def ensure_namedtuple(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        event = args[0][0]
        if not isinstance(event, Event):
            events = [Event(e) for e in args[0]]
            args[0] = events
        return f(*args, **kwargs)

    return wrap


def filter_events(events, N=None, randomize=False):
    """Pick N (random) events from list"""

    Nevents = len(events)

    if N is not None:
        if Nevents > N:
            if randomize:
                events = random.sample(events, N)
            else:
                events = events[:N]
        else:
            print(
                f"[WARNING] plotting: got less events than requested for plotting {Nevents} < {N}"
            )
    return events

def read_settings(setfile, channel, module):
    parameters = namedtuple(
        "parameters",
        [
            "Gs",
            "Ls",
            "Lf",
            "FFth",
            "CFDth",
            "CFDdelay",
            "Gf",
            "LiveTime",
            "PeakSample",
            "tau",
        ],
    )
    ch = channel
    S = read.Settings(setfile, module)
    Gs = S.SlowGap[ch]  *10
    Ls = S.SlowLength[ch]   *10
    Gf = S.FastGap[ch] # *5
    Lf = S.FastLength[ch]  # *5
    FFth = S.units.FastThresh[ch]
    CFDth = S.units.CFDThresh[ch]
    CFDdelay = S.CFDDelay[ch]
    LiveTime = S.units.LiveTime[ch]
    PeakSample = S.PeakSample[ch]
    tau = S.PreampTau[ch]
    return parameters(Gs, Ls, Lf, FFth, CFDth, CFDdelay, Gf, LiveTime, PeakSample, tau)

def advindexing_roll(A, r):
    """Shift trace matrix A by r indices.
       traces and r must be > 1D numpy arrays"""
       
    if isinstance(A, np.ndarray) and isinstance(r, np.ndarray):
        rows, column_indices = np.ogrid[: A.shape[0], : A.shape[1]]
        r[r < 0] += A.shape[1]
        column_indices = column_indices - r[:, np.newaxis]
    else:
        raise Exception("Wrong type. Need numpy arrays")
    return A[rows, column_indices]

# persistent plot
def create_plot(traces, x_range=None):
    x_range = None
    data = traces
    mytime = np.linspace(0, 2 * (traces.shape[1] - 1), traces.shape[1])  # in us

    if x_range is None:
        x_range = [mytime[0], mytime[-1]]
    y_range = [data.min(), data.max()]
    cvs = ds.Canvas(plot_height=400, plot_width=1000, x_range=x_range, y_range=y_range)
    df = ds.utils.dataframe_from_multiple_sequences(mytime, data)
    agg = cvs.line(df, "x", "y", agg=ds.count())
    img = tf.shade(agg, how="eq_hist")
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.imshow(
        img,
        extent=[x * 1 for x in x_range] + [y * 1 for y in y_range],
        aspect="auto",
        origin="lower",
        norm=LogNorm(),
    )
    ax.set_xlabel("Time [ns]")
    ax.set_ylabel("ADC units [a.u]")
    
def find_sums(traces, setting, trailsum, gapsum, leadsum):
    sumIDX = []
    Esums = []
    Ls = setting.Ls
    Gs = setting.Gs
    for j in range(len(traces)):
        for i in range(len(traces[j]) - 2 * Ls - Gs):
            s1 = np.sum(traces[j][i : i + Ls])
            s2 = np.sum(traces[j][i + Ls : i + Ls + Gs])
            s3 = np.sum(traces[j][i + Ls + Gs : i + Ls + Gs + Ls])
            # print([s1, s2, s3], [Esum1, Esum2, Esum3])
            if [s1, s2, s3] == [trailsum[j], gapsum[j], leadsum[j]]:
                sumIDX.append(i)
                Esums.append([s1, s2, s3])
                # print(f'found it at {sumIDX}')
                break
        else:
            print("Error: Could not find sums!")
            print("Error: Try increasing trace length and/or trace delay and run again")
            print(
                "Ideal settings for offline computation: trace length > 2*Ls+Gs"
                + " pretrigger length > 3*Ls+Gs (p.69, rev. 01/2019)"
            )
            sys.exit()

    sumIDX = np.array(sumIDX)
    Esums = np.array(Esums)
    return sumIDX, Esums

@ensure_namedtuple    
def persistence(events, setfile, plot=True, keep_sums=False):
    """find the index where the raw energy sums are caluclated and plot all
       traces in persistence mode. This can take a long time, so don't run 
       for too long"""
       
    print("Calculating sums. Do not use many traces...")
    print("Total number of events: ", len(events))
    
    # figure out all channels form events
    all_channels = [e.channel for e in events]
    count_ch = Counter(all_channels)
    print('Channels used and occurences: ', count_ch)
    channels = list(count_ch.keys()) # unique set of channels used
    
    setting = read_settings(setfile, channels[0], 0)
    Ls = int(setting.Ls)
    Gs = int(setting.Gs)
    
    ch, trace, trailsum, gapsum, leadsum = [], [], [], [], []
    for e in events:
        if e.channel == channels[0] and e.CFD_error == 0:
            ch.append(ch)
            trace.append(e.trace)
            trailsum.append(e.Esum_trailing)
            gapsum.append(e.Esum_gap)
            leadsum.append(e.Esum_leading)
            
    trace = np.array(trace)
    t = np.linspace(0, 2 * (trace.shape[1] - 1), trace.shape[1])  # in ns
    IDX = np.arange(0, trace.shape[0], 1)
    if len(trailsum) == 0:
        print("Error: Raw energy sums must be anabled in the PIXIE-16")
        sys.exit()
    
    sumIDX, Esum = find_sums(trace, setting, trailsum, gapsum, leadsum)
    
    # gapIDX = sumIDX + Ls
    minsumIDX = sumIDX.min()
    shiftIDX = sumIDX - minsumIDX
    traceshift = advindexing_roll(trace, -shiftIDX)

    if plot:
        create_plot(traceshift[IDX])
        plt.plot(
            [t[minsumIDX], t[minsumIDX]],
            [trace.min(), trace.max()],
            "r--",
            label="raw energy sums",
        )
        plt.plot(
            [t[minsumIDX + Ls], t[minsumIDX + Ls]], [trace.min(), trace.max()], "r--"
        )
        plt.plot(
            [t[minsumIDX + Ls + Gs], t[minsumIDX + Ls + Gs]],
            [trace.min(), trace.max()],
            "r--",
        )
        plt.plot(
            [t[minsumIDX + Ls + Gs + Ls], t[minsumIDX + Ls + Gs + Ls]],
            [trace.min(), trace.max()],
            "r--",
        )
        plt.legend()
        plt.title(
            f"channel: {channels[0]}; number of traces: {count_ch[channels[0]]}; live time: {setting.LiveTime}"
        )
        # plt.show()


def print_timing():
    pass


def histogram_FF():
    pass


def histogram_CFD():
    pass


def histogram_helper(Y, **kwargs):
    plt.hist(Y, **kwargs)
    pass


@ensure_namedtuple
def histogram_energy(events, **kwargs):
    # filter events
    E = [e.energy for e in events]
    histogram_helper(E, xlabel="E [MeV]", **kwargs)


def histogram_arrival_times():
    pass


def histogram_times():
    pass


def FF():
    pass


def CFD(traces, setfile, channel, module, w=0.3125, num_traces=20):
    # perform own CFD calculation
    setting = read_settings(setfile, channel, module)
    CFDth = setting.CFDth
    Lf = int(setting.Lf)
    Gf = int(setting.Gf)
    FFth = setting.FFth

    w = [w]
    B = [5]
    D = [5]
    L = [1]
    
    t = np.linspace(0, 2 * (traces.shape[1] - 1), traces.shape[1])  # in ns

    CFD, cfdtime, FF, IDXerr = calculate_CFD_using_FF(
        traces,
        t=t,
        CFD_threshold=CFDth,
        FF_threshold=FFth,
        Lf=Lf,
        Gf=Gf,
        w=w[0],
        B=B[0],
        D=D[0],
        L=L[0],
        Nbkgd=10,
        FF_delay=20,
        CFD_delay=0,
    )

    cfdtime = cfdtime[cfdtime != np.array(None)]

    tcfd = t[B[0] + D[0] : traces.shape[1] - L[0] + 1]
    tff = t[0 : FF.shape[1]]


    fig = plt.figure(figsize=(18, 10))
    fig.subplots_adjust(hspace=0.3, wspace=0.3)
    rows = 4
    columns = 5
    for i in range(1, num_traces + 1):
        rand = random.randint(0, traces.shape[0])
        ax = fig.add_subplot(rows, columns, i)
        ax.plot(t, traces[rand], label="Trace", lw=0.2)
        ax.plot(tcfd, CFD[rand], label="CFD", lw=0.2)
        ax.plot(tff, FF[rand], label="Fast Filter", lw=0.2)
        ax.plot([t[0], t[-1]], [CFDth, CFDth], label="CFD Threshold", lw=0.2)
        ax.plot([t[0], t[-1]], [FFth, FFth], label="FF Threshold", lw=0.2)
        ax.plot(cfdtime[rand], 0, ".", ms=1, color="k")
        ax.legend(loc="upper right", fancybox=True, shadow=True, prop={"size": 4})




def energy_sums(events, setting, N=None, randomize=False, persistent=True, ax=None):
    """Plots traces


    Parameters
    ----------

    events :
        List of events (perhaps already filtered) from read.read_list_mode_data()
    setting :
        A read.Settings object
    N : int
        Number of traces to plot, if `None` all traces will be plotted.
    randomize : bool
        if True and N is smaller than the total amount of traces, randomly pick traces
    persistent : bool
        use datashader to plot traces

    ax :
        a matplotlib axes to plot on. If None, we create a new figure
        and show it at the end. Otherwise this needs to be an array of
        matplotlib axis objects: one axis for each channel present in
        events.

    Example
    -------

    with multipagePDF(file) as f:
        fig, ax = plot.subplots()
        pixie16.plot.energy_sums(...,ax=ax)
        f.savefig()
        fig.close()

    """

    # figure out all channels form events
    channels = set([e.channel for e in events])

    # filter events
    events = filter_events(events, N, randomize)

    # create axis if it doesn't exist yet
    orig_ax = ax
    if ax is None:
        fig, ax = plt.subplots(1, len(channels))
    # do datashader

    # make sure we can iterate of ax
    try:
        iter(ax)
    except TypeError:
        ax = [ax]

    for i, (c, a) in enumerate(zip(channels, ax)):
        if persistent:
            pass
        else:
            for e in events:
                # need to align traces
                # TODO: convert e.trace to V
                a.plot(e.trace)
        a.set_xlabel("Time in datapoints every 2 ns")
        a.set_ylabel("Voltage [V]")
        a.set_title(f"Aligned energy sums for channel {c}")
    if orig_ax is None:
        plt.show()
