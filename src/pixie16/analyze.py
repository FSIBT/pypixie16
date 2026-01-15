"""
Functions to help analyze PIXIE-16 data
"""

from functools import wraps

import numpy as np


def ensure_2d_array(f):
    """Convert 1D numpy array to 2D arrays and back.

    Using this decorator ensures that the first argument is always a 2d array.
    This way all functions below only need to handle that case.

    """

    @wraps(f)
    def wrap(*args, **kwargs):
        # check if first argument is accessible and a numpy array
        try:
            array = args[0]
        except IndexError:
            raise TypeError(
                f"[ERROR] {f.__name__}: first argument needs to be a numpy array"
            )
        if not isinstance(array, np.ndarray):
            raise TypeError(
                f"[ERROR] {f.__name__}: first argument needs to be a numpy array"
            )

        # convert 1D to 2D if needed
        if len(array.shape) == 1:
            array = array[np.newaxis, :]
            args = list(args)
            args[0] = array
            one_dim = True
        else:
            one_dim = False

        # call orginal function now with a 2D array
        out = f(*args, **kwargs)

        # convert 2D array back to 1D if needed
        if one_dim:
            if isinstance(out, np.ndarray):
                out = out[0]
            elif isinstance(out, list | tuple):
                out = (o[0] for o in out)
        return out

    return wrap


@ensure_2d_array
def convert_trace_to_FPGA(traces: np.ndarray, filter_range: int = 0):
    """Sum up 2**filter_range steps in trace to match FPGA clock cycle.

    The FPGA (100 MHz = 10 ns) always handels at least 5 data points
    (2ns) at a time. It does this by adding up 5 data points into a
    single point.

    For some calculations the FPGA sums up more data points (up to
    2^filter_range), for example, for the energy calculations the minimum
    filter_range setting is 1.

    Parameters
    ----------
    traces
        A 1D or 2D array of 2 ns time step data. For 1D, the number of
        data points, M, needs to be a multiple of 5*2^filter_range. For 2D, the
        size N,M of the array needs to confirm to N traces with a
        length of M, where M needs to fulfill the same constraints as
        in the 1D case.
    filter_range
        5*2^filter_range points will be added up

    Result
    ------
        For the 1D case, return a ndarray with size M/(5*2^filter_range) and
        for the 2D case, return a N,M/(5*2^filter_range) array

    """
    N, M = traces.shape

    if filter_range < 0:
        raise ValueError("The filter_range parameter needs to be >= 0")

    group = 5 * 2**filter_range

    if M % group != 0:
        raise ValueError(
            f"The trace length is not a multiple of 5*2^filter_range, for filter_range={filter_range}"
        )

    return traces.reshape(N, M // group, group).sum(axis=2)


@ensure_2d_array
def calculate_CFD(
    traces,
    t=None,
    CFD_threshold=None,
    FF_threshold=None,
    Lf=0.02,
    Gf=0.02,
    w=1,
    B=5,
    D=5,
    L=1,
    Nbkgd=10,
    FF_delay=0,
    CFD_delay=0,
):
    """Calculate the CFD trace as is done by the PIXIE

    Also provide the option to change parameters used in the calculations
    (The calculations we do here is for the 500 MHz version).

    The input can be 1d or 2d in which case the output will be also 1d or 2d.

    Parameters
    ----------
       traces        (N, M) numpy array: N= number of traces, M=number of data points
       t             (M, 1) numpy arrray, the time axes for the traces
       Lf            integer: length of the integration time, microseconds
       Gf            integer: gap between the two integration regions, microseconds
       L, D, B, w    unchangeable parameters of FPGA!!

    Result
    ------
       CFD        (N, M-B-D-L+1)  numpy array
       cfdtime    (N, 1) numpy array: the time of the zero crossing
       FF         numpy array: fast filter used for the calculation
       IDXerr     numpy array: index of CFD errors

    """

    traces = traces.astype(np.int64)
    NR_traces, length = traces.shape

    # we are skipping the first B+D data points, so the CFD array will
    # be shorter, adjusting the time array accordingly
    if t is None:
        t2 = np.linspace(0, 2 * (traces.shape[1] - 1), traces.shape[1])  # in ns
        t2 = t2[B + D :]
    else:
        t2 = t[B + D :]

    # create an empty array of the correct length
    CFD = np.zeros((NR_traces, length - B - D - L + 1))
    cfdtime = []
    # calculate the CFD, see section 3.3.8.2, page 47 of the PIXIE
    # manual do as much as possible using numpy, one probably can and
    # should get rid of the for-loop here too, just not sure at the
    # moment how to do it
    for k in range(B + D, length - L):
        CFD[:, k - B - D] = w * (
            traces[:, k : k + L + 1].sum(axis=1)
            - traces[:, k - B : k - B + L + 1].sum(axis=1)
        ) - (
            traces[:, k - D : k - D + L + 1].sum(axis=1)
            - traces[:, k - D - B : k - D - B + L + 1].sum(axis=1)
        )

    # now find the zero crossing
    low = 0
    CFDerror = 0
    IDXerr = []
    cfdtimeIDX = []

    # Lf and Gf go into fast_filter, we now want them in microseconds!
    fast_filter = calculate_filter(traces, Lf, Gf)
    for i, (CFDtrace, FFtrace) in enumerate(zip(CFD, fast_filter)):
        FFtrace = FFtrace[FF_delay:]
        CFDtrace = CFDtrace[CFD_delay:]

        # check that the first N points of the fast filter (noise) is below threshold
        # 30 is an arbitrary number here, but the PIXIE should always record some noise first
        if (
            FFtrace[:Nbkgd].max() > FF_threshold
            or CFDtrace[:Nbkgd].max() > CFD_threshold
        ):
            # print('Warning: CFD analysis theshold too low?', CFDtrace[:Nbkgd].max(),i)
            low += 1

        # all zero crossings from poitive to negative
        zero_crossings = np.where(np.diff(np.signbit(CFDtrace).astype(int)) > 0)[0]
        if zero_crossings.size == 0:
            CFDerror += 1
            cfdtime.append(None)
            IDXerr.append(i)
            continue

        # find first index where the CFD trace is above the threshold
        try:
            FF_trigger_index = np.where(FFtrace >= FF_threshold)[0][0]
            CFD_trigger_index = (
                np.where(np.diff(CFDtrace >= CFD_threshold).astype(int) > 0)[0] + 1
            )
            CFD_trigger_index = CFD_trigger_index[CFD_trigger_index > FF_trigger_index][
                0
            ]
            left = zero_crossings[zero_crossings > CFD_trigger_index][0]
            right = left + 1
            zer = t2[left] + CFDtrace[left] * (t2[right] - t2[left]) / (
                CFDtrace[left] - CFDtrace[right]
            )
        except IndexError:
            CFDerror += 1
            cfdtime.append(None)
            IDXerr.append(i)
            continue

        cfdtime.append(zer)
        cfdtimeIDX.append(i)
    cfdtime = np.array(cfdtime)

    print("Calculated CFD errors = ", CFDerror)
    print("Events with noise above fast filter threshold = ", low)

    return CFD, cfdtime, fast_filter, IDXerr


@ensure_2d_array
def get_fast_trigger_index(traces, threshold):
    """Return the indices where the trace value is >= threshold."""

    trigger_pos = [
        np.argwhere((trace[:-1] < threshold) & (trace[1:] > threshold)).flatten() + 1
        for trace in traces
    ]
    return trigger_pos


@ensure_2d_array
def calculate_filter(traces, L=0.02, G=0.02, filter_range=0):
    """Calculate the fast and slow filter response from the PIXIE

    This implements the filter response as discribted on page 81 in
    section 6.1 of the manual.

    The input can be 1d or 2d in which case the output will be also 1d or 2d.

    input:
       traces   (N, M) numpy array. N traces with a length of M
       L        integer: length of the integration time, microseconds
       G        integer: gap between the two integration regions, microseconds

    output:
       result   (N, M-2L-G+1)
    """

    # import traces, structure into 2D array
    traces = traces.astype(np.int64)
    NR_traces, length = traces.shape
    assert length % 5 == 0, "Filter trace length needs to be a multiple of 5"

    # convert microseconds to FPGA clock cycles:
    # dimensional analysis: Xmicrosec x 1000ns/1microsecond x 1FPGAclockcycle/10ns
    # Note 2ns/datapoint, if microsec--> datapoints: L*=500, G*=500
    L *= 100
    G *= 100

    # Ensure a length of integration: L,G>0
    assert L > 0 and G > 0

    # L,G must be integers
    # such that they can be used in setting lengths, and divided by
    L, G = int(L), int(G)

    # Ensure traces are in appropriate configuration for FPGA cycles too
    filter_range = int(filter_range)
    traces = convert_trace_to_FPGA(traces, filter_range)

    # Reassert shape here until I verify that convert_trace_to_FPGA doesn't change it
    NR_traces, length = traces.shape

    # create an empty array of the correct length
    result = np.zeros((NR_traces, length - 2 * L - G + 1))

    # do as much as possible using numpy, one probably can and should
    # get rid of the for-loop here too, just not sure at the moment
    # how to do it
    for k in range(2 * L + G - 1, length):
        result[:, k - 2 * L - G + 1] = traces[:, k - L + 1 : k + 1].sum(
            axis=1
        ) - traces[:, k - 2 * L - G + 1 : k - L - G + 1].sum(axis=1)

    # scale to 2 ns timesteps
    result = np.repeat(result, 5, axis=1)
    result = result / L

    return result


@ensure_2d_array
def compute_fast_trigger_validation(
    traces: np.ndarray, L: int, G: int, threshold: int, baseline_index: int = None
) -> dict[str, any]:
    """
    Compute fast trigger validation from trace_analysis.py update_fasttrigger()

    Parameters
    ----------
    traces : np.ndarray
        Raw trace data (converted to FPGA cycles)
    L : int
        Fast filter L parameter in FPGA units
    G : int
        Fast filter G parameter in FPGA units
    threshold : int
        Trigger threshold value
    baseline_index : int, optional
        Index for baseline calculation

    Returns
    -------
    Dict containing fast trigger results matching trace_analysis.py output
    """

    # Convert L, G from FPGA units to microseconds for calculate_filter
    L_us = L * 0.01  # Convert FPGA units to microseconds
    G_us = G * 0.01

    if traces.max() == 0:
        return {
            "fast_triggers": None,
            "trigger_indices": None,
            "baseline_stats": None,
            "validation_passed": False,
        }

    length = len(traces[0])

    # Calculate fast triggers using existing function
    fast_triggers = calculate_filter(traces, L=L_us, G=G_us)

    # Get trigger indices
    trigger_indices = get_fast_trigger_index(fast_triggers, threshold)

    # Calculate noise level (matching trace_analysis.py logic exactly)
    try:
        first_trigger_offset = int(
            min(t[0] for t in trigger_indices if len(t) > 0) - 10
        )
    except (ValueError, IndexError):
        print(
            "[orange3]WARNING[/] No trigger found, using the first 20% of the trace to estimate baseline",
            flush=True,
        )
        first_trigger_offset = int(length * 0.2)

    if baseline_index is None:
        baseline_index = first_trigger_offset

    baseline_stats = {}
    if first_trigger_offset > 0:
        average_noise = [r[:first_trigger_offset].std() for r in fast_triggers]
        average_noise = np.asarray(average_noise).mean()

        max_noise = [r[:first_trigger_offset].max() for r in fast_triggers]
        max_noise = np.asarray(max_noise).max()

        baseline_stats = {
            "baseline_index": baseline_index,
            "average_noise": average_noise,
            "max_noise": max_noise,
            "first_trigger_offset": first_trigger_offset,
            "title": f"Fast Trigger: noise level $\\sigma$={average_noise:.1f} max={max_noise:.1f} before x={first_trigger_offset}",
        }
        validation_passed = True
    else:
        baseline_stats = {
            "baseline_index": 1,
            "title": "Fast Trigger: cannot calculate noise level",
        }
        validation_passed = False

    return {
        "fast_triggers": fast_triggers,
        "trigger_indices": trigger_indices,
        "baseline_stats": baseline_stats,
        "validation_passed": validation_passed,
    }


@ensure_2d_array
def compute_energy_filter(
    traces_fpga: np.ndarray,
    R: int,
    L: int,
    G: int,
    P: int,
    decay_ns: float,
    trigger_indices: list,
    baseline_index: int,
) -> dict[str, any]:
    """
    Compute energy filter from trace_analysis.py update_energies()

    Parameters
    ----------
    traces_fpga : np.ndarray
        Traces already converted to FPGA cycles
    R : int
        Range parameter (slow filter range = 2**R)
    L : int
        Energy filter L parameter in energy steps
    G : int
        Energy filter G parameter in energy steps
    P : int
        Peak sample parameter in energy steps
    decay_ns : float
        Decay time in nanoseconds
    trigger_indices : List
        Trigger positions from fast trigger
    baseline_index : int
        Baseline calculation index

    Returns
    -------
    Dict containing energy filter results
    """

    q = np.exp(-2 / decay_ns)
    slow_filter_range = 2**R

    # Check trace length and padding (exact logic from trace_analysis.py)
    length = len(traces_fpga[0]) // slow_filter_range
    pad_data = False

    if length - 2 * L - G + 1 <= 0:
        print(
            "[orange3]WARNING[/] L, G for energy filter are too large for the supplied trace length and slowfilter range. Padding data",
            flush=True,
        )
        pad_data = True
        pad_length = 2 * (L + G)
        length += 2 * pad_length
    elif length - 2 * L - G + 1 <= 20:
        print(
            "[orange3]WARNING[/] L, G for energy filter are large for the supplied trace length and slowfilter range. Padding data",
            flush=True,
        )
        pad_data = True
        pad_length = L + G
        length += 2 * pad_length

    # Energy calculation coefficients (exact from trace_analysis.py)
    qL = q ** (5 * L * slow_filter_range)
    c2 = 1 - q
    c3 = (1 - q) / (1 - qL)
    c1 = c3 * qL

    # Baseline calculation (exact from trace_analysis.py)
    baseline = [t[:baseline_index].mean() for t in traces_fpga]
    baseline_pad = np.asarray(baseline).mean() * slow_filter_range
    baseline = baseline_pad * (L + G) * 4 * c2

    energy_values = np.zeros(len(traces_fpga))
    energy_traces = []

    for i, trace in enumerate(traces_fpga):
        # Convert to avoid overflows (exact from trace_analysis.py)
        trace = trace.astype(np.int64)

        # Handle slow filter range grouping
        N = (trace.shape[0] // slow_filter_range) * slow_filter_range
        trace = trace[:N].reshape(
            trace.shape[0] // slow_filter_range, slow_filter_range
        )
        trace = trace.sum(axis=1)

        if pad_data:
            pad = np.ones(pad_length) * int(baseline_pad)
            trace = np.concatenate([pad, trace, pad])

        result = np.zeros(length - 2 * L - G + 1)

        # Calculate trigger position in new time units
        trigger_pos = None
        if len(trigger_indices[i]):
            trigger_pos = (
                int(trigger_indices[i][0]) // slow_filter_range - 2 * L - G + P
            )
            if pad_data:
                trigger_pos += pad_length

        # Energy filter calculation (exact from trace_analysis.py)
        for k in range(2 * L + G - 1, length):
            S1 = trace[k - 2 * L - G + 1 : k - L - G + 1].sum()
            S2 = trace[k - L - G + 1 : k - L + 1].sum()
            S3 = trace[k - L + 1 : k + 1].sum()

            result[k - 2 * L - G + 1] = 4 * (-c1 * S1 + c2 * S2 + c3 * S3) - baseline

            if trigger_pos is not None and k - 2 * L - G + 1 == trigger_pos:
                energy_values[i] = result[k - 2 * L - G + 1]

        energy_traces.append(
            {"result": result, "trigger_pos": trigger_pos, "trace_index": i}
        )

    return {
        "energy_traces": energy_traces,
        "energy_values": energy_values,
        "baseline": baseline,
        "slow_filter_range": slow_filter_range,
        "coefficients": {"c1": c1, "c2": c2, "c3": c3, "qL": qL},
    }


def compute_three_sums(traces_fpga, R, L, G, baseline_index=50):
    """
    Compute individual S1, S2, S3 sums from trapezoidal energy filter
    
    This returns the raw sum values (not combined energy) for debugging
    
    Parameters
    ----------
    traces_fpga : np.ndarray
        Traces already converted to FPGA cycles
    R : int
        Range parameter (slow filter range = 2**R)
    L : int
        Energy filter L parameter in energy steps
    G : int
        Energy filter G parameter in energy steps
    baseline_index : int
        Baseline calculation index
        
    Returns
    -------
    Dict containing S1, S2, S3 traces for each input trace
    """
    slow_filter_range = 2**R
    
    # Check trace length and padding
    length = len(traces_fpga[0]) // slow_filter_range
    pad_data = False
    pad_length = 0
    
    if length - 2 * L - G + 1 <= 0:
        pad_data = True
        pad_length = 2 * (L + G)
        length += 2 * pad_length
    elif length - 2 * L - G + 1 <= 20:
        pad_data = True 
        pad_length = L + G
        length += 2 * pad_length
    
    # Baseline calculation
    baseline = [t[:baseline_index].mean() for t in traces_fpga]
    baseline_pad = np.asarray(baseline).mean() * slow_filter_range
    
    three_sums_results = []
    
    for i, trace in enumerate(traces_fpga):
        trace = trace.astype(np.int64)
        
        # Handle slow filter range grouping
        N = (trace.shape[0] // slow_filter_range) * slow_filter_range
        trace = trace[:N].reshape(
            trace.shape[0] // slow_filter_range, slow_filter_range
        )
        trace = trace.sum(axis=1)
        
        if pad_data:
            pad = np.ones(pad_length) * int(baseline_pad)
            trace = np.concatenate([pad, trace, pad])
        
        # Initialize result arrays
        result_length = length - 2 * L - G + 1
        S1_trace = np.zeros(result_length)
        S2_trace = np.zeros(result_length)  
        S3_trace = np.zeros(result_length)
        
        # Calculate S1, S2, S3 for each position
        for k in range(2 * L + G - 1, length):
            pos = k - 2 * L - G + 1
            
            # Raw sums (not weighted)
            S1 = trace[k - 2 * L - G + 1 : k - L - G + 1].sum()
            S2 = trace[k - L - G + 1 : k - L + 1].sum()  
            S3 = trace[k - L + 1 : k + 1].sum()
            
            S1_trace[pos] = S1
            S2_trace[pos] = S2
            S3_trace[pos] = S3
        
        three_sums_results.append({
            "S1": S1_trace,
            "S2": S2_trace, 
            "S3": S3_trace,
            "trace_index": i,
            "original_length": len(traces_fpga[i])
        })
    
    return {"three_sums_results": three_sums_results}


def compute_energy_linearity(
    traces_fpga: np.ndarray,
    trigger_indices: list,
    energy_values: np.ndarray,
    baseline_index: int,
    integration_length: int,
) -> dict[str, any]:
    """
    Compute energy linearity from trace_analysis.py update_energy_linearity()

    Parameters
    ----------
    traces_fpga : np.ndarray
        FPGA converted traces
    trigger_indices : List
        Trigger positions
    energy_values : np.ndarray
        Calculated energy values
    baseline_index : int
        Baseline index
    integration_length : int
        Integration length L parameter

    Returns
    -------
    Dict containing linearity analysis results
    """

    baseline = [t[:baseline_index].mean() for t in traces_fpga]
    baseline = np.asarray(baseline).mean()

    N = len(traces_fpga)
    energy = np.zeros(N)

    for i, trace in enumerate(traces_fpga):
        try:
            trigger_pos = int(trigger_indices[i][0])
        except IndexError:
            trigger_pos = 0
        if trigger_pos:
            if trigger_pos + integration_length < len(trace):
                energy[i] = (
                    trace[trigger_pos : trigger_pos + integration_length].sum()
                    - baseline * integration_length
                )

    # Linearity analysis (exact from trace_analysis.py)
    X = energy
    Y = energy_values

    if len(X) == 0 or len(Y) == 0:
        return {"validation_passed": False, "error": "No data for linearity analysis"}

    fit = np.poly1d(np.polyfit(X, Y, 1))
    F = fit(X)
    mask = X > 0

    if mask.sum() == 0:
        return {"validation_passed": False, "error": "No valid data points"}

    X = X[mask]
    Y = Y[mask]
    F = F[mask]

    r2 = ((F - Y.mean()) ** 2).sum() / ((Y - Y.mean()) ** 2).sum()

    return {
        "X": X,
        "Y": Y,
        "F": F,
        "r2": r2,
        "fit": fit,
        "mask": mask,
        "validation_passed": True,
    }
