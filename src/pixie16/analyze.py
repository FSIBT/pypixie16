"""Analysis functions for PIXIE-16 nuclear physics data.

This module provides functions for processing and analyzing data from PIXIE-16
digital signal processing modules, including trace analysis, filter calculations,
and timing measurements. All functions support both single traces (1D arrays)
and multiple traces (2D arrays) through automatic dimension handling.

Key Features
------------
- Trace preprocessing and FPGA simulation
- CFD (Constant Fraction Discriminator) calculations
- Trapezoidal filter implementations
- Trigger detection and timing analysis
- Automatic 1D/2D array handling via decorators

Typical Usage
-------------
>>> import pixie16.analyze as analyze
>>> filtered_traces = analyze.calculate_filter(raw_traces, L=0.5, G=0.1)
>>> cfd_data, timing = analyze.calculate_CFD(traces, Lf=0.02, Gf=0.02)
"""

from functools import wraps

import numpy as np


def ensure_2d_array(f):
    """Decorator to handle 1D/2D array conversions for analysis functions.

    This decorator ensures that the first argument is always a 2D array for processing,
    then converts back to 1D if the input was originally 1D. This allows analysis
    functions to work consistently with both single traces and multiple traces.

    Parameters
    ----------
    f : callable
        Function to wrap that expects 2D numpy arrays as first argument.

    Returns
    -------
    callable
        Wrapped function that handles automatic 1D/2D conversion.

    Raises
    ------
    TypeError
        If first argument is not a numpy array.

    Examples
    --------
    >>> @ensure_2d_array
    ... def process_traces(traces):
    ...     return traces.mean(axis=1)
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
    """Convert ADC traces to FPGA clock rate representation.

    The FPGA (100 MHz = 10 ns) always handels at least 5 data points
    (2ns) at a time. It does this by adding up 5 data points into a
    single point.

    For some calculations the FPGA sums up more data points (up to
    2^filter_range), for example, for the energy calculations the minimum
    filter_range setting is 1.

    Parameters
    ----------
    traces : np.ndarray
        Trace data with 2ns time steps. Shape (N, M) for N traces of M samples.
        M must be a multiple of 5*2^filter_range to match FPGA processing.
    filter_range : int, default=0
        FPGA decimation factor. 5*2^filter_range points are summed together
        to simulate FPGA clock grouping.

    Returns
    -------
    np.ndarray
        Decimated traces with shape (N, M//(5*2^filter_range)).

    Raises
    ------
    ValueError
        If filter_range < 0 or trace length not divisible by group size.

    Notes
    -----
    The FPGA processes data at 100MHz (10ns periods) by grouping ADC samples
    taken at 500MHz (2ns periods). This function simulates that grouping.

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
    """Calculate Constant Fraction Discriminator (CFD) traces.

    Implements the CFD algorithm used by PIXIE-16 modules for precise timing
    measurements. The CFD provides sub-sample timing resolution by finding
    zero-crossings in a processed trace signal.

    Parameters
    ----------
    traces : np.ndarray
        Input trace data, shape (N, M) for N traces of M samples.
    t : np.ndarray, optional
        Time axis for traces. If None, creates linear time axis in nanoseconds.
    CFD_threshold : float, optional
        CFD threshold for zero-crossing detection.
    FF_threshold : float, optional
        Fast filter threshold for event validation.
    Lf : float, default=0.02
        Fast filter integration time in microseconds.
    Gf : float, default=0.02
        Fast filter gap time in microseconds.
    w : int, default=1
        CFD weight parameter (FPGA constant).
    B : int, default=5
        CFD baseline parameter (FPGA constant).
    D : int, default=5
        CFD delay parameter (FPGA constant).
    L : int, default=1
        CFD length parameter (FPGA constant).
    Nbkgd : int, default=10
        Number of background samples for noise checking.
    FF_delay : int, default=0
        Fast filter delay offset.
    CFD_delay : int, default=0
        CFD delay offset.

    Returns
    -------
    tuple[np.ndarray, list, np.ndarray, list]
        CFD : CFD trace data, shape (N, M-B-D-L+1)
        cfdtime : List of zero-crossing times for each trace
        FF : Fast filter output used in calculation
        IDXerr : List of indices with CFD errors

    Notes
    -----
    This implementation follows the PIXIE-16 manual section 3.3.8.2 (page 47).
    The algorithm is optimized for the 500 MHz ADC version.
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
    """Find trigger indices where trace crosses threshold.

    Identifies the sample indices where traces transition from below to above
    the specified threshold value, indicating trigger events.

    Parameters
    ----------
    traces : np.ndarray
        1D or 2D array of trace data. For 2D arrays, shape should be (N, M)
        where N is number of traces and M is number of samples.
    threshold : float
        Threshold value for trigger detection.

    Returns
    -------
    list[np.ndarray]
        List of arrays containing trigger indices for each trace.
        Each array contains the sample indices where threshold crossing occurs.

    Examples
    --------
    >>> traces = np.array([[1, 2, 5, 3], [0, 1, 4, 2]])
    >>> triggers = get_fast_trigger_index(traces, threshold=3)
    >>> print(triggers)  # Indices where traces cross above 3
    """

    trigger_pos = [
        np.argwhere((trace[:-1] < threshold) & (trace[1:] > threshold)).flatten() + 1
        for trace in traces
    ]
    return trigger_pos


@ensure_2d_array
def calculate_filter(traces, L=0.02, G=0.02, filter_range=0):
    """Calculate PIXIE-16 fast/slow filter response.

    Implements the trapezoidal filter response as described in section 6.1
    of the PIXIE-16 manual (page 81). This filter is used for energy
    determination and timing analysis.

    Parameters
    ----------
    traces : np.ndarray
        Input trace data. Shape (N, M) for N traces of M samples each.
        Trace length M must be a multiple of 5.
    L : float, default=0.02
        Rise time (integration length) in microseconds.
    G : float, default=0.02
        Gap time between integration regions in microseconds.
    filter_range : int, default=0
        Filter range parameter (currently unused in implementation).

    Returns
    -------
    np.ndarray
        Filtered traces with shape (N, M-2L-G+1) where timing parameters
        are converted to FPGA clock cycles.

    Raises
    ------
    AssertionError
        If trace length is not a multiple of 5, or if L or G are not positive.

    Notes
    -----
    - Timing conversion: microseconds → FPGA cycles (100 MHz, 10ns period)
    - Uses 2ns sampling rate (500 MHz ADC)
    - Filter implements trapezoidal shaping for optimal energy resolution
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
