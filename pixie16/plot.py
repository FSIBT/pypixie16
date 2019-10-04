# -*- coding: utf-8 -*-
from matplotlib import pyplot as plt
from .read import Event
from functools import wraps


def ensure_namedtuple(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        event = args[0][0]
        if not isinstance(event, Event):
            events = [Event(e) for e in args[0]]
            args[0] = events
        return f(*args, **kwargs)

    return wrap


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


def energy_sums(events, setting, N=None, random=False, persistent=True, ax=None):
    """
    Parameters
    ----------
    
    events :
        List of events (perhaps already filtered) from read.read_list_mode_data()
    setting : 
        A read.Settings object
    N : int
        Number of traces to plot, if `None` all traces will be plotted.
    random : bool
        if True and N is smaller than the total amount of traces, randomly pick traces
    persistent : bool
        use datashader to plot traces
    ax :
        a matplotlib axes to plot on. If None, we create a new figure and show it at the end

    Example
    -------     
        
    with multipagePDF(file) as f:
        fig, ax = plot.subplots()
        pixie16.plot.energy(...,ax=ax)
        f.save()
        fig.close()

    """
    # figure out all channels form events
    channels = set([e.channel for e in events])
    # get settings for channels

    # calc

    if ax is None:
        orig_ax = ax
        fig, ax = plt.subplots(1, len(channels))
    else:
        assert len(ax) == len(channels)
    # do datashader

    for i, c in enumerate(channels):
        # ax[i].imshow()
        pass

    if orig_ax is None:
        plt.show()
