# -*- coding: utf-8 -*-
from matplotlib import pyplot as plt
from .read import Event
from functools import wraps
import random
import numpy as np


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


def CFD():
    pass


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
