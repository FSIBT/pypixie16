from functools import wraps
import random
from typing import Union, List, Tuple, Optional, Sequence, Iterable
import warnings

from fast_histogram import histogram2d
import numpy as np
import matplotlib
from matplotlib import pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.backends.backend_pdf import PdfPages

from .analyze import calculate_CFD_using_FF
from .read import Event, Settings


DATA_POINTS_PER_FPGA_CYCLE = 5


def filter_events(
    events: Iterable[Event], N: Optional[int] = None, randomize: bool = False
) -> Iterable[Event]:
    """Pick N (random) events from a list of events"""

    N_events = len(events)

    if N is None:
        return events

    if N_events > N:
        if randomize:
            return random.sample(events, N)
        return events[:N]

    print(
        f"[Warning] plotting: got less events than requested for plotting {N_events} < {N}"
    )
    return events


def create_title_page(
    title: Union[str, List[str]], pdf: Optional[PdfPages] = None
) -> None:
    """Helper function to create a title page

    The function will create a title centered in a plot.
    If pdf is given, it will save the figure inside the pdf (to be used with PdfPages)
    for multi page pdfs.

    Parameters
    ----------

    title
       The title, if a list of str, then each will be put on a single line
    pdf
       The pdf where the title page should be added to.

    """
    if isinstance(title, (list, tuple)):
        title = "\n".join(title)

    fig = plt.figure()
    plt.axis("off")
    plt.text(0.5, 0.5, title, ha="center", va="center")
    if pdf:
        pdf.savefig()
    plt.close(fig)


def advindexing_roll(A: np.ndarray, r: np.ndarray) -> np.ndarray:
    """Shift trace matrix A by r indices.

    Traces and r must be > 1D numpy arrays

    """

    for arg in [A, r]:
        if not isinstance(arg, np.ndarray):
            raise TypeError("Wrong type. Need numpy arrays")

    rows, column_indices = np.ogrid[: A.shape[0], : A.shape[1]]
    r[r < 0] += A.shape[1]
    column_indices = column_indices - r[:, np.newaxis]

    return A[rows, column_indices]


def create_persistent_plot(
    traces: np.ndarray,
    x_range: Optional[Sequence[float]] = None,
    ax: Optional[matplotlib.axes.Axes] = None,
) -> None:
    """Create persistence plot

    Parameters
    ----------

    traces
        2D numpy array (N, M) where N is the number of traces and M the length of the traces
    x_range
        desired range of time axis. If None, it goes from 0 to 2*M in ns
    ax
        a matplotlib axes to plot on. If None, we create a new figure
        and show it at the end. Otherwise this needs to be an array of
        matplotlib axis objects: one axis for each channel present in
        events.

    """
    N = len(traces)
    if not N:
        print("[Warning] no traces in persistince plot", flush=True)
    mytime = np.linspace(0, 2 * (traces.shape[1] - 1), traces.shape[1])  # in ns

    if x_range is None:
        x_range = [mytime[0], mytime[-1]]
    y_range = [traces.min() * 0.85, traces.max() * 1.15]

    # using datashader-like feature to create persistent plotxlim, ylims
    # height and width of the image
    Nx = traces.shape[1]
    Ny = 400

    data_points_x = mytime[np.newaxis, :].repeat(N, axis=0).flatten()
    data_points_y = traces.flatten()

    img = histogram2d(
        data_points_x, data_points_y, bins=(Nx, Ny), range=(x_range, y_range)
    ).T

    ax_orig = ax
    if ax_orig is None:
        fig, ax = plt.subplots(figsize=(12, 6))
    ax.imshow(
        img + 1e-3,  # add 1e-3 to avoid problems with 0 in LogNorm
        extent=x_range + y_range,
        aspect="auto",
        origin="lower",
        norm=LogNorm(),
        cmap="inferno",
    )
    ax.set_xlabel("Time [ns]")
    ax.set_ylabel("ADC units [a.u]")

    if ax_orig is None:
        plt.show()
        plt.close(fig)

    return img


def find_sums(
    traces: np.ndarray,
    SlowLength: Iterable[int],
    SlowGap: Iterable[int],
    trailsum: Iterable[int],
    gapsum: Iterable[int],
    leadsum: Iterable[int],
) -> Tuple[np.ndarray, np.ndarray]:
    """Find the location of the 3 reported sums in a trace that are used to calculate the energy.

    For this to work, bit 12 of register A (CaptureSums) needs to be set for the channel.

    Parameters
    ----------

    traces
        2D numpy array (N, M) where N is the number of traces and M the length of the traces.
    SlowLength
        List of the length of the Ls for each trace in traces.
    SlowGap
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
            print("[ERROR] Could not find sums!")
            print(
                "[ERROR] Try increasing trace length and/or trace delay and run again"
            )
            print(
                "Ideal settings for offline computation: trace length > 2*Ls+Gs"
                + " pretrigger length > 3*Ls+Gs (p.69, rev. 01/2019)"
            )
            raise IndexError

    sumIDX = np.array(sumIDX)
    Esums = np.array(Esums)
    return sumIDX, Esums


def MCA(
    data: np.ndarray,
    ax: Optional[matplotlib.axes.Axes] = None,
    rebin: int = 1,
    title: Optional[str] = None,
    label: Optional[str] = None,
    pdf: Optional[PdfPages] = None,
    log: bool = False,
) -> None:
    """Plot MCA spectra

    If pdf is given, it will save the figure inside the pdf (to be used with PdfPages)
    for multi page pdfs.

    Parameters
    ----------

    data :
       Data from ReadHistogramFromModule
    ax
       The axis to plot on, if None, we create a new figure and axis
    rebin
       Rebin the data by summing over this amount of bins
    title
       Add this title to the plot
    pdf
       if present, we save the plot in the pdf
    log
       plot y-axis in log scale

    """
    ax_orig = ax
    if ax is None:
        fig, ax = plt.subplots()
    data = data.reshape(-1, rebin).sum(axis=1)
    ax.plot(data, label=label)
    if log:
        ax.set_yscale("log")
    ax.set_xlabel("Channel")
    ax.set_ylabel("Counts")
    if title:
        ax.set_title(title)
    if pdf:
        pdf.savefig(fig)
    if ax_orig is None:
        plt.close(fig)


def CFD(
    events: Iterable[Event],
    setting: Settings,
    w: float = 0.3125,
    N: Optional[int] = None,
    randomize: bool = False,
    persistent: bool = False,
    title: Optional[str] = None,
    ax: Optional[matplotlib.axes.Axes] = None,
    pdf: Optional[PdfPages] = None,
) -> None:
    """Plot CFD and FastFilter several traces

    Parameters
    ----------

    events
        List of events (perhaps already filtered) from read.read_list_mode_data()
        Need to be from a single channel.
    setting
        A read.Settings object
    w
        The `w` used for the CFD calculation
    N
        Number of traces to plot, if `None` all traces will be plotted.
    randomize
        if True and N is smaller than the total amount of traces, randomly pick traces
    persistent
        Use datashader-like plot of traces
    title
        Title to add to plot
    ax
        a matplotlib axes to plot on. If None, we create a new figure
        and show it at the end.
    pdf
       if present, we save the plot in the pdf

    """

    events = filter_events(events, N, randomize)

    channels = {e.channel for e in events}
    if len(channels) != 1:
        print(
            "[ERROR] Can only plot CFD for events from a single channel at the moment"
        )
        return
    channel = list(channels)[0]

    CFDth = setting.CFDThresh[channel]
    Lf = int(setting.FastLength[channel])
    Gf = int(setting.FastGap[channel])
    FFth = setting.FastThresh[channel]  # TODO: check scaling, perhaps x/L*5

    # parameters needed for CFD calculation
    w = [w]
    B = [5]
    D = [5]
    L = [1]

    traces = [e.trace for e in events]
    for t in traces:
        if t is None:
            print("[ERROR] Missing trace...skip plotting")
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
    events: Iterable[Event],
    setting: Settings,
    N: Optional[int] = None,
    randomize: bool = False,
    persistent: bool = True,
    title: Optional[str] = None,
    ax: Optional[matplotlib.axes.Axes] = None,
    pdf: Optional[PdfPages] = None,
) -> None:
    """Plots traces aligned to position of the energy sums.

    Plots vertical lines at the position of the energy sums only if all events
    are from a single channel.

    Parameters
    ----------

    events
        List of events (perhaps already filtered) from read.read_list_mode_data()
    setting
        A read.Settings object
    N
        Number of traces to plot, if `None` all traces will be plotted.
    randomize
        if True and N is smaller than the total amount of traces, randomly pick traces
    persistent
        Use datashader-like plot of traces
    title
        Title to add to plot
    ax
        a matplotlib axes to plot on. If None, we create a new figure
        and show it at the end.
    pdf
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

    try:
        sumIDX, Esum = find_sums(trace, Ls, Gs, trailsum, gapsum, leadsum)
    except IndexError:
        for Y in trace:
            ax.plot(t, Y)
        if title:
            ax.set_title(title + " Error in find sums")
        if pdf:
            pdf.savefig()

        if ax_orig is None:
            plt.close(fig)
        return

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
            f"channel: {ch}; number of traces: {len(trace)};"
            f" live time: {setting.get('LiveTime', channel=ch, as_pint=True)}"
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
