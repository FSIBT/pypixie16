"""
Usage:
  ROOTS-test-data.py <binFile> <channel> [options]
  
options:
  --persistence          persistence plot of traces
  --own_cfd              perform own CFD calculation and plot traces amd thresholds
  --energy_traces        plot calculated energy histogram, filters, and peakSample
  --energy_pixie         plot pixie energy histogram
  --save_pdf             Do all plots above and save them as pdf
      
Functions to help test PIXIE-16 data
Need to have traces and raw energy sums enabled      
"""

# tested files:
# alpha det: 2019-08-16-test-alpha-det0018_mod00.bin
# API:

import docopt

commands = docopt.docopt(__doc__)
print(commands)

ch = int(commands["<channel>"])

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
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.font_manager import FontProperties
import random
import datetime

fontP = FontProperties()
fontP.set_size("small")


# test files
fname0 = commands["<binFile>"]
setfile0 = fname0[0:-10] + ".set"

if fname0[-3:] != "bin":
    print("Error: Need a PIXIE-16 binary file")
    sys.exit()

fname = find_file(fname0)
print(fname)
setfile = find_file(setfile0)
module = 0


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
print("CFD errors = ", cfderror.count(1))
print("pileup events = ", pileup.count(1))
print("clipped events = ", clipped.count(1))
trace = np.array(trace)
cfderror = np.array(cfderror)
IDX = np.arange(0, trace.shape[0], 1)
# IDXcfderror = IDX[cfderror]
# IDXgood = IDX[~cfderror]
IDXgood = IDX
t = np.linspace(0, 2 * (trace.shape[1] - 1), trace.shape[1])  # in ns
data_count = Counter(all_channels)
print("Channels used and ocurrences: ", data_count)
if len(trailsum) == 0:
    print("Error: Raw energy sums must be anabled in the PIXIE-16")
    sys.exit()


def shift_traces(traces, r):
    """Shift traces by r indices.
    traces and r must be >1D numpy arrays
    """
    if isinstance(traces, np.ndarray) and isinstance(r, np.ndarray):
        rows, column_indices = np.ogrid[: traces.shape[0], : traces.shape[1]]
        r[r < 0] += traces.shape[1]
        column_indices = column_indices - r[:, np.newaxis]
    else:
        raise Exception("Wrong type. Need numpy arrays")
    return traces[rows, column_indices]


def read_settings(file):
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


def advindexing_roll(A, r):
    rows, column_indices = np.ogrid[: A.shape[0], : A.shape[1]]
    r[r < 0] += A.shape[1]
    column_indices = column_indices - r[:, np.newaxis]
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

    # plt.show()


def persistence(trace, plot=True, keep_sums=False):
    """find the index where the raw energy sums are caluclated and plot all
       traces in persistence mode. This can take a long time, so don't run 
       for too long"""
    print(
        "Calculating sums. If you are using too many traces, it might take"
        + " a long time..."
    )
    setting = read_settings(setfile)
    sumIDX = []
    Esums = []
    Ls = setting.Ls
    Gs = setting.Gs
    for j in range(len(trace)):
        for i in range(len(trace[j]) - 2 * Ls - Gs):
            s1 = np.sum(trace[j][i : i + Ls])
            s2 = np.sum(trace[j][i + Ls : i + Ls + Gs])
            s3 = np.sum(trace[j][i + Ls + Gs : i + Ls + Gs + Ls])
            # print([s1, s2, s3], [Esum1, Esum2, Esum3])
            if [s1, s2, s3] == [trailsum[j], gapsum[j], leadsum[j]]:
                sumIDX.append(i)
                if keep_sums == True:
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
    # gapIDX = sumIDX + Ls
    minsumIDX = sumIDX.min()
    shiftIDX = sumIDX - minsumIDX
    traceshift = advindexing_roll(trace, -shiftIDX)

    if plot:
        create_plot(traceshift[IDXgood])
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
            f"channel: {ch}; number of traces: {data_count[ch]}; live time: {setting.LiveTime}s"
        )
        # plt.show()

    if keep_sums == True:
        return sumIDX, Esums
    else:
        return sumIDX


def own_CFD(w, num_traces, pdf=False, persist=False):
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


def energy_filter(num_traces, pdf=False, calc_own_energy=False):
    """calculate energy filter and plot a certain number 
    (num_traces). Also plots the trace, FF, and peak sample"""
    setting = read_settings(setfile)
    Ls1 = int(setting.Ls)
    Gs1 = int(setting.Gs)
    Lf1 = int(setting.Lf)
    Gf1 = int(setting.Gf)
    PS = setting.PeakSample * 10  # in FPGA cycles (pp. 85)
    tau = setting.tau

    SF = calculate_filter(trace, L=Ls1, G=Gs1)
    FF = calculate_filter(trace, L=Lf1, G=Gf1)

    FFshift = trace.shape[1] - FF.shape[1]
    SFshift = trace.shape[1] - SF.shape[1]
    zeroFF = np.zeros([FF.shape[0], FFshift])
    zeroSF = np.zeros([SF.shape[0], SFshift])
    FF = np.concatenate((zeroFF, FF), axis=1)
    SF = np.concatenate((zeroSF, SF), axis=1)
    sumIDX, Esums = persistence(trace, plot=False, keep_sums=True)
    Esample = sumIDX + PS

    # doing it as described by Wolfgang for the pixie4
    q = np.exp(-0.002 / tau)
    Cg = 1 - q
    C1 = (1 - q) / (1 - q ** Ls1)
    C0 = -C1 * q ** Ls1
    # energies are shifted from 14 bits to 16 bits at one point, this is equal to multiplying by 4
    # the baseline sum seems to be given in units of shifted energy
    Eshift = trace.shape[1] - 2 * Ls1 - Gs1
    E_trace = np.zeros([trace.shape[0], Eshift])
    print("Calculating energy filter...")
    for k, tr in enumerate(trace):
        n = 0
        for i in range(0, Eshift, 10):
            s1 = tr[i : i + Ls1].sum()
            s2 = tr[i + Ls1 : i + Ls1 + Gs1].sum()
            s3 = tr[i + Ls1 + Gs1 : i + Ls1 + Gs1 + Ls1].sum()
            for j in range(10):
                # E_trace.append((C0*s1 + Cg*s2 + C1*s3)*4 - baseline[0])
                E_trace[k, n] = (C0 * s1 + Cg * s2 + C1 * s3) * 4 - baseline[k]
                n += 1
    zeroEF = np.zeros([E_trace.shape[0], trace.shape[1] - Eshift])
    EF = np.concatenate((zeroEF, E_trace), axis=1)

    if pdf:
        fig = plt.figure(figsize=(18, 10))
        fig.subplots_adjust(hspace=0.3, wspace=0.3)
        rows = 4
        columns = 5
        for i in range(1, num_traces + 1):
            rand = random.randint(0, trace.shape[0])
            idxth = np.where(FF[rand] > setting.FFth)[0][
                0
            ]  # idx where FF threshold is crossed
            EsampleFF = PS + idxth  # sampling location
            ax = fig.add_subplot(rows, columns, i)
            ax.plot(trace[rand], label="Trace", color="b", lw=0.2)
            ax.plot(FF[rand], label="Fast filter", color="orange", lw=0.2)
            ax.plot(SF[rand], label="Slow filter", color="green", lw=0.2)
            ax.plot(EF[rand], label="Energy filter", color="red", lw=0.2)
            ax.plot(
                [0, trace.shape[1]],
                [setting.FFth, setting.FFth],
                "r--",
                label="FF threshold",
                color="orange",
                lw=0.2,
            )
            ax.plot(
                [sumIDX[0], sumIDX[0]],
                [0, EF[rand].max()],
                "k--",
                label="Energy sums",
                lw=0.2,
            )
            ax.plot(
                [sumIDX[0] + Ls1, sumIDX[0] + Ls1], [0, EF[rand].max()], "k--", lw=0.2
            )
            ax.plot(
                [sumIDX[0] + Ls1 + Gs1, sumIDX[0] + Ls1 + Gs1],
                [0, EF[rand].max()],
                "k--",
                lw=0.2,
            )
            ax.plot(
                [sumIDX[0] + Ls1 + Gs1 + Ls1, sumIDX[0] + Ls1 + Gs1 + Ls1],
                [0, EF[rand].max()],
                "k--",
                lw=0.2,
            )
            ax.plot(
                [EsampleFF, EsampleFF],
                [0, EF[rand].max()],
                "m--",
                label="E samp, FF",
                lw=0.2,
            )
            ax.plot(
                [Esample[rand], Esample[rand]],
                [0, EF[i].max()],
                "g--",
                label="E samp, E sums",
                lw=0.2,
            )
            ax.legend(loc="upper right", fancybox=True, shadow=True, prop={"size": 3})
    else:

        for i in range(num_traces):
            idxth = np.where(FF[i] > setting.FFth)[0][
                0
            ]  # idx where FF threshold is crossed
            EsampleFF = PS + idxth  # sampling location
            plt.figure()
            plt.plot(trace[i], label="Trace", color="b")
            plt.plot(FF[i], label="Fast filter", color="orange")
            plt.plot(SF[i], label="Slow filter", color="green")
            plt.plot(EF[i], label="Energy filter", color="red")
            plt.plot(
                [0, trace.shape[1]],
                [setting.FFth, setting.FFth],
                "r--",
                label="FF threshold",
                color="orange",
            )
            plt.plot(
                [sumIDX[0], sumIDX[0]], [0, EF[i].max()], "k--", label="Energy sums"
            )
            plt.plot([sumIDX[0] + Ls1, sumIDX[0] + Ls1], [0, EF[i].max()], "k--")
            plt.plot(
                [sumIDX[0] + Ls1 + Gs1, sumIDX[0] + Ls1 + Gs1], [0, EF[i].max()], "k--"
            )
            plt.plot(
                [sumIDX[0] + Ls1 + Gs1 + Ls1, sumIDX[0] + Ls1 + Gs1 + Ls1],
                [0, EF[i].max()],
                "k--",
            )

            plt.plot(
                [EsampleFF, EsampleFF], [0, EF[i].max()], "m--", label="E samp, FF"
            )
            plt.plot(
                [Esample[i], Esample[i]],
                [0, EF[i].max()],
                "g--",
                label="E samp, E sums",
            )
            plt.legend()
            plt.title(f"Channel: {ch}; Trace No: {i}")
            # plt.show()

    if calc_own_energy:
        calc_E = []
        for j, samp in enumerate(Esample):
            calc_E.append(EF[j][samp])
        calc_E = np.array(calc_E)
        plt.figure()
        plt.hist(calc_E, 500, edgecolor="k", label="Calculated")
        plt.xlabel("Energy [a.u]")
        plt.ylabel("cts")
        plt.title(
            f"Channel: {ch}; no. of events: {len(energy)}; live time: {setting.LiveTime}s"
        )
        plt.legend()
        # plt.show()


def energy_hist_pixie(xbins):

    setting = read_settings(setfile)
    plt.figure()
    plt.hist(energy, xbins, edgecolor="k", label="PIXIE-16")
    plt.xlabel("Energy [a.u]")
    plt.ylabel("cts")
    plt.title(
        f"Channel: {ch}; no. of events: {len(energy)}; live time: {setting.LiveTime}s"
    )
    plt.legend()
    # plt.show()


if commands["--persistence"]:
    persistence(trace)

if commands["--own_cfd"]:
    own_CFD(0.3125, 10, persist=True)

if commands["--energy_traces"]:
    energy_filter(10, calc_own_energy=True)

if commands["--energy_pixie"]:
    energy_hist_pixie(500)

if commands["--save_pdf"]:
    now = datetime.datetime.now()
    tstring = now.strftime("%Y-%m-%d-%H.%M.%S")
    saveFile = tstring + "-PIXIE-test" + ".pdf"
    with PdfPages(saveFile) as pdf:
        persistence(trace)
        pdf.savefig()
        plt.close()

        own_CFD(0.3215, 20, pdf=True, persist=False)
        pdf.savefig()
        plt.close()

        energy_filter(20, pdf=True, calc_own_energy=False)
        pdf.savefig()
        plt.close()

        energy_hist_pixie(500)
        pdf.savefig()
        # plt.close()


#    energy = np.array(energy)
#
#    plt.hist(energy,500, edgecolor='k');
#    plt.xlabel('Energy [a.u]')
#    plt.ylabel('cts')
#    plt.title(f'Channel: {ch}; no. of events: {len(energy)}; live time: {setting.liveTime}s')
#    plt.show()
