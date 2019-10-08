# -*- coding: utf-8 -*-
from matplotlib import pyplot as plt
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


def advindexing_roll(A, r):
    """Shift trace matrix A by r indices.
       traces and r must be >1D numpy arrays"""
       
    if isinstance(A, np.ndarray) and isinstance(r, np.ndarray):
        rows, column_indices = np.ogrid[: A.shape[0], : A.shape[1]]
        r[r < 0] += A.shape[1]
        column_indices = column_indices - r[:, np.newaxis]
    else:
        raise Exception("Wrong type. Need numpy arrays")
    return A[rows, column_indices]

def read_settings(file, ch):
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
    S = read.Settings(file, module)
    LiveTime = round(S["LiveTimeB"][ch] * 1e-8, 2)  # seconds
    l = S["TraceLength"][ch]
    assert l == len(trace[0]), f"{l} {len(trace[0])}"
    Gs = S["SlowGap"][ch] * 5 * 2 ** S["SlowFilterRange"]  # *2/100 # us
    Ls = S["SlowLength"][ch] * 5 * 2 ** S["SlowFilterRange"]  # *2/100 # us
    Lf = S["FastLength"][ch] * 5 * 2 ** S["FastFilterRange"]  # /100 # us
    Gf = S["FastGap"][ch] * 5 * 2 ** S["FastFilterRange"]  # /100
    FFth = S["FastThresh"][ch] * 2 / 100  # ADC units
    CFDth = S["CFDThresh"][ch]  # ADC units
    CFDdelay = S["CFDDelay"][ch]  # us
    PeakSample = S["PeakSample"][ch]
    tau = tau = S["PreampTau"][ch]
    return parameters(Gs, Ls, Lf, FFth, CFDth, CFDdelay, Gf, LiveTime, PeakSample, tau)

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


def CFD(w, num_traces, pdf=False, persistence=False):
    # perform own CFD calculation
    setting = read_settings(setfile)
    CFDth = setting.CFDth
    Lf = int(setting.Lf)
    Gf = int(setting.Gf)
    FFth = setting.FFth

    w = [w]
    B = [5]
    D = [5]
    L = [1]

    CFD, cfdtime, FF, IDXerr = calculate_CFD_using_FF(
        trace,
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

    tcfd = t[B[0] + D[0] : trace.shape[1] - L[0] + 1]
    tff = t[0 : FF.shape[1]]

    if pdf:
        fig = plt.figure(figsize=(18, 10))
        fig.subplots_adjust(hspace=0.3, wspace=0.3)
        rows = 4
        columns = 5
        for i in range(1, num_traces + 1):
            rand = random.randint(0, trace.shape[0])
            ax = fig.add_subplot(rows, columns, i)
            ax.plot(t, trace[rand], label="Trace", lw=0.2)
            ax.plot(tcfd, CFD[rand], label="CFD", lw=0.2)
            ax.plot(tff, FF[rand], label="Fast Filter", lw=0.2)
            ax.plot([t[0], t[-1]], [CFDth, CFDth], label="CFD Threshold", lw=0.2)
            ax.plot([t[0], t[-1]], [FFth, FFth], label="FF Threshold", lw=0.2)
            ax.plot(cfdtime[rand], 0, ".", ms=1, color="k")
            ax.legend(loc="upper right", fancybox=True, shadow=True, prop={"size": 4})
    else:
        for i in range(num_traces):
            rand = random.randint(0, trace.shape[0])
            plt.figure()
            plt.plot(t, trace[rand], label="Trace")
            plt.plot(tcfd, CFD[rand], label="CFD")
            plt.plot(tff, FF[rand], label="Fast Filter")
            plt.plot([t[0], t[-1]], [CFDth, CFDth], label="CFD Threshold")
            plt.plot([t[0], t[-1]], [FFth, FFth], label="FF Threshold")
            plt.plot(cfdtime[rand], 0, ".", ms=10)
            plt.legend()
            # plt.show()

        if persist:
            sumIDX = persistence(trace, plot=False)
            minsumIDX = sumIDX.min()
            shiftIDX = sumIDX - minsumIDX
            CFDshift = advindexing_roll(CFD, -shiftIDX)
            create_plot(CFDshift)
            plt.plot(
                [0, 2 * (CFD.shape[1] - 1)],
                [CFDth, CFDth],
                "r--",
                label=f"CFD Threshold = {CFDth}",
            )
            plt.title("CFD Trace")
            plt.title(f"channel: {ch}; number of CFD traces: {CFD.shape[0]}")
            plt.legend()
            # plt.show()




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
