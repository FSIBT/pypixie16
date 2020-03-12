# -*- coding: utf-8 -*-
from functools import wraps
import random
import numpy as np
from matplotlib import pyplot as plt
from matplotlib.colors import LogNorm
import datashader as ds
import datashader.transfer_functions as tf
from .analyze import calculate_CFD_using_FF
from .read import Event


DATA_POINTS_PER_FPGA_CYCLE = 5


def ensure_namedtuple(f):
    """This decorator makes sure that the first argument is an instant of Events.

    This way, we can guarantee that we can use things like e.channel inside the function

    We also print a warning if there are no events given
    """

    @wraps(f)
    def wrap(*args, **kwargs):
        try:
            event = args[0][0]
        except IndexError:
            print(f"[WARNING] {f.__name__}: no events")
            return
        if not isinstance(event, Event):
            events = [Event(e) for e in args[0]]
            args[0] = events
        return f(*args, **kwargs)

    return wrap


def filter_events(events, N=None, randomize=False):
    """Pick N (random) events from list of events"""

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


def create_title_page(title, pdf=None):
    """Helper function to create a title page

    The function will create a title centered in a plot.
    If pdf is given, it will save the figure inside the pdf (to be used with PdfPages)
    for multi page pdfs.

    Parameters
    ----------

    title :  str
       The title
    pdf : matplotlib.backends.backend_pdf.PdfPages
       The pdf where the title page should be added to.

    """
    fig = plt.figure()
    plt.axis("off")
    plt.text(0.5, 0.5, title, ha="center", va="center")
    if pdf:
        pdf.savefig()
    plt.close(fig)


def advindexing_roll(A, r):
    """Shift trace matrix A by r indices.
       traces and r must be > 1D numpy arrays"""

    if isinstance(A, np.ndarray) and isinstance(r, np.ndarray):
        rows, column_indices = np.ogrid[: A.shape[0], : A.shape[1]]
        r[r < 0] += A.shape[1]
        column_indices = column_indices - r[:, np.newaxis]
    else:
        raise TypeError("Wrong type. Need numpy arrays")
    return A[rows, column_indices]


def create_persistent_plot(traces, x_range=None, ax=None):
    """ Create persistence plot

    Parameters
    ----------

    traces :
        2D numpy array (N, M) where N is the number of traces and M the length of the traces

    x_range :
        desired range of time axis. If None, it goes from 0 to 2*M in ns

    ax :
        a matplotlib axes to plot on. If None, we create a new figure
        and show it at the end. Otherwise this needs to be an array of
        matplotlib axis objects: one axis for each channel present in
        events.

    """
    mytime = np.linspace(0, 2 * (traces.shape[1] - 1), traces.shape[1])  # in ns

    if x_range is None:
        x_range = [mytime[0], mytime[-1]]
    y_range = [traces.min(), traces.max()]

    # using datashader to create persistent plot
    cvs = ds.Canvas(plot_height=400, plot_width=1000, x_range=x_range, y_range=y_range)
    df = ds.utils.dataframe_from_multiple_sequences(mytime, traces)
    agg = cvs.line(df, "x", "y", agg=ds.count())
    img = tf.shade(agg, how="eq_hist")

    ax_orig = ax
    if ax_orig is None:
        fig, ax = plt.subplots(figsize=(12, 6))
    ax.imshow(
        img, extent=x_range + y_range, aspect="auto", origin="lower", norm=LogNorm()
    )
    ax.set_xlabel("Time [ns]")
    ax.set_ylabel("ADC units [a.u]")

    if ax_orig is None:
        plt.close(fig)


def find_sums(traces, SlowLength, SlowGap, trailsum, gapsum, leadsum):
    """Find the location of the 3 reported sums in a trace that are used to calculate the energy.

    For this to work, bit 12 of register A (CaptureSums) needs to be set for the channel.

    Parameters
    ----------

    traces :
        2D numpy array (N, M) where N is the number of traces and M the length of the traces.
    SlowLength : list
        List of the length of the Ls for each trace in traces.
    SlowGap : list
        List of the length of the Gs for each trace in traces.
    trailsum :
        Array/List of N values that contains the values of the first reported sum, which contains L values.
    gapsum :
        Array/List of N values that contains the values of the second reported sum, which contains G values.
    leadsum :
        Array/List of N values that contains the values of the third reported sum, which contains L values.


    Returns
    -------

    sumIDX :
        numpy array of position of the start of the first sumIDX
    Esums :
        numpy array of the three sums

    """
    sumIDX = []
    Esums = []
    for t, Ls, Gs, Tsum, Gsum, Lsum in zip(
        traces, SlowLength, SlowGap, trailsum, gapsum, leadsum
    ):
        for i in range(len(t) - 2 * Ls - Gs):
            s1 = np.sum(t[i : i + Ls])
            s2 = np.sum(t[i + Ls : i + Ls + Gs])
            s3 = np.sum(t[i + Ls + Gs : i + Ls + Gs + Ls])
            # print([s1, s2, s3], [Esum1, Esum2, Esum3])
            if [s1, s2, s3] == [Tsum, Gsum, Lsum]:
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
            raise IndexError

    sumIDX = np.array(sumIDX)
    Esums = np.array(Esums)
    return sumIDX, Esums


def MCA(data, ax=None, rebin=1, title=None, pdf=None):
    """Plot MCA spectra

    If pdf is given, it will save the figure inside the pdf (to be used with PdfPages)
    for multi page pdfs.

    Parameters
    ----------

    data :
       Data from ReadHistogramFromModule
    ax :
       The axis to plot on, if None, we create a new figure and axis
    rebin : int
       Rebin the data by summing over this amount of bins
    title : str
       Add this title to the plot
    pdf : matplotlib.backends.backend_pdf.PdfPages
       if present, we save the plot in the pdf

    """
    ax_orig = ax
    if ax is None:
        fig, ax = plt.subplots()
    data = data.reshape(-1, rebin).sum(axis=1)
    ax.plot(data)
    ax.set_xlabel("Channel")
    ax.set_ylabel("Counts")
    if title:
        ax.set_title(title)
    if pdf:
        pdf.savefig()
    if ax_orig is None:
        plt.close(fig)


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


def CFD(
    events,
    setting,
    w=0.3125,
    N=None,
    randomize=False,
    persistent=False,
    title=None,
    ax=None,
    pdf=None,
):
    """Plot CFD and FastFilter several traces

    Parameters
    ----------

    events :
        List of events (perhaps already filtered) from read.read_list_mode_data()
        Need to be from a single channel.
    setting : read.Settings
        A read.Settings object
    w : float
        The `w` used for the CFD calculation
    N : int
        Number of traces to plot, if `None` all traces will be plotted.
    randomize : bool
        if True and N is smaller than the total amount of traces, randomly pick traces
    persistent : bool
        Use datashader to plot traces
    title : str
        Title to add to plot
    ax : matplotlib.axes.Axes
        a matplotlib axes to plot on. If None, we create a new figure
        and show it at the end.
    pdf : matplotlib.backends.backend_pdf.PdfPages
       if present, we save the plot in the pdf

    """

    events = filter_events(events, N, randomize)

    channels = {e.channel for e in events}
    if len(channels) != 1:
        print(
            "[Error] Can only plot CFD for events from a single channel at the moment"
        )
        return
    channel = list(channels)[0]

    CFDth = setting.units.CFDThresh[channel]
    Lf = int(setting.FastLength[channel])
    Gf = int(setting.FastGap[channel])
    FFth = setting.units.FastThresh[channel]

    # parameters needed for CFD calculation
    w = [w]
    B = [5]
    D = [5]
    L = [1]

    traces = [e.trace for e in events]
    for t in traces:
        if t is None:
            print("[Error] Missing trace...skip plotting")
            return
    traces = np.asarray(traces)

    T = np.linspace(0, 2 * (traces.shape[1] - 1), traces.shape[1])  # in ns

    CFD, cfdtime, FF, IDXerr = calculate_CFD_using_FF(
        traces,
        t=T,
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

    Tcfd = T[B[0] + D[0] : traces.shape[1] - L[0] + 1]
    Tff = T[0 : FF.shape[1]]

    ax_orig = ax
    if ax_orig is None:
        fig, ax = plt.subplots()
    for t, c, ct, f in zip(traces, CFD, cfdtime, FF):
        ax.plot(T, t, label="Trace", lw=0.2)
        ax.plot(Tcfd, c, label="CFD", lw=0.2)
        ax.plot(Tff, f, label="Fast Filter", lw=0.2)
        ax.plot([T[0], T[-1]], [CFDth, CFDth], label="CFD Threshold", lw=0.2)
        ax.plot([T[0], T[-1]], [FFth, FFth], label="FF Threshold", lw=0.2)
        ax.plot(ct, 0, ".", ms=1, color="k")
    ax.legend(loc="upper right", fancybox=True, shadow=True, prop={"size": 4})

    if title:
        ax.set_title(title)
    if pdf:
        pdf.savefig()
    if ax_orig is None:
        plt.close(fig)


def energy_sums(
    events,
    setting,
    N=None,
    randomize=False,
    persistent=True,
    title=None,
    ax=None,
    pdf=None,
):
    """Plots traces aligned to position of the energy sums.

    Plots vertical lines at the position of the energy sums only if all events
    are from a single channel.

    Parameters
    ----------

    events :
        List of events (perhaps already filtered) from read.read_list_mode_data()
    setting : read.Settings
        A read.Settings object
    N : int
        Number of traces to plot, if `None` all traces will be plotted.
    randomize : bool
        if True and N is smaller than the total amount of traces, randomly pick traces
    persistent : bool
        Use datashader to plot traces
    title : str
        Title to add to plot
    ax : matplotlib.axes.Axes
        a matplotlib axes to plot on. If None, we create a new figure
        and show it at the end.
    pdf : matplotlib.backends.backend_pdf.PdfPages
       if present, we save the plot in the pdf

    """

    events = filter_events(events, N, randomize)

    channels = {e.channel for e in events}

    # create axis if it doesn't exist yet
    ax_orig = ax
    if ax_orig is None:
        fig, ax = plt.subplots()

    # align data
    Ls, Gs, ch, trace, trailsum, gapsum, leadsum = [], [], [], [], [], [], []

    slow_filter_range = setting.SlowFilterRange
    for e in events:
        if e.CFD_error == 0:
            # convert Ls and Gs into number of data points
            Ls.append(
                int(setting.SlowLength[e.channel] * (2 ** slow_filter_range) * 10 / 2)
            )
            Gs.append(
                int(setting.SlowGap[e.channel] * (2 ** slow_filter_range) * 10 / 2)
            )
            ch.append(e.channel)
            trace.append(e.trace)
            trailsum.append(e.Esum_trailing)
            gapsum.append(e.Esum_gap)
            leadsum.append(e.Esum_leading)

    trace = np.array(trace)
    try:
        t = np.linspace(0, 2 * (trace.shape[1] - 1), trace.shape[1])  # in ns
    except IndexError:
        return
    IDX = np.arange(0, trace.shape[0], 1)
    if len(trailsum) == 0:
        print("[ERROR] Raw energy sums must be anabled in the PIXIE-16")
        return

    sumIDX, Esum = find_sums(trace, Ls, Gs, trailsum, gapsum, leadsum)

    minsumIDX = sumIDX.min()
    shiftIDX = sumIDX - minsumIDX
    traceshift = advindexing_roll(trace, -shiftIDX)

    if persistent:
        create_persistent_plot(traceshift[IDX], ax=ax)
    else:
        for Y in traceshift:
            ax.plot(t, Y)

    # draw lines
    if len(channels) == 1:
        positions = [
            t[minsumIDX],
            t[minsumIDX + Ls[0]],
            t[minsumIDX + Ls[0] + Gs[0]],
            t[minsumIDX + Ls[0] + Gs[0] + Ls[0]],
        ]
        ax.vlines(
            positions,
            ymin=trace.min(),
            ymax=trace.max(),
            color="r",
            linestyle="--",
            label="Raw energy sums",
        )
        ch = list(channels)[0]
        ax.set_title(
            f"channel: {ch}; number of traces: {len(trace)}; live time: {setting.units.LiveTime[ch]}"
        )
    else:
        print(
            "[Warning] plot.energy_sums: more than one channel given, not drawing positions of sums"
        )
    ax.legend()
    ax.set_ylim(bottom=0)
    ax.legend()

    if title:
        ax.set_title(title)
    if pdf:
        pdf.savefig()

    if ax_orig is None:
        plt.close(fig)
