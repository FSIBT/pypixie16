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
            elif isinstance(out, (list, tuple)):
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

    group = 5 * 2 ** filter_range

    if M % group != 0:
        raise ValueError(
            f"The trace length is not a multiple of 5*2^filter_range, for filter_range={filter_range}"
        )

    return traces.reshape(N, M // group, group).sum(axis=2)


@ensure_2d_array
def calculate_CFD(traces, t=None, CFD_threshold=None, w=1, B=5, D=5, L=1, Nbkgd=100):
    """Calculate the CFD trace as is done by the PIXIE

    Also provide the option to change parameters used in the calculations
    (The calculations we do here is for the 500 MHz version).

    The input can be 1d or 2d in which case the output will be also 1d or 2d.

    input:
       traces   (N, M) numpy array: N= number of traces, M=number of data points
       t        (M, 1) numpy arrray, the time axes for the traces

    output:
       CFD  (N, M-B-D-L+1)  numpy array
       zero_crossing        (N, 1) numpy array: the time of the zero crossing
       errors               True/False array if CFD could be established or not

    """
    traces = traces.astype(np.int64)
    NR_traces, length = traces.shape
    errors = np.zeros(NR_traces, dtype=np.bool)
    cfdtrigger = np.zeros(NR_traces)

    # we are skipping the first B+D data points, so the CFD array will
    # be shorter, adjusting the time array accordingly
    if t is None:
        t2 = np.arange(0, length - B - D) * 2e-9
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
    for i, CFDtrace in enumerate(CFD):
        # check that the first N points (noise) is below threshold
        # 100 is an arbitrary number here, but the PIXIE should always record some noise first
        if CFDtrace[:Nbkgd].max() > CFD_threshold:
            print("Warning: CFD analysis theshold too low?", CFDtrace[:Nbkgd].max())

        try:
            # all zero crossings
            zero_crossings = np.where(np.diff(np.signbit(CFDtrace)))[0]

            # find first index where the CFD signal is above the threshold
            CFD_trigger_index = np.where(CFDtrace >= CFD_threshold)[0][0]

            # first zero crossing at later time than the threshold
            left = zero_crossings[zero_crossings > CFD_trigger_index][0]
            right = left + 1

            # sanity check
            if CFDtrace[left] > CFDtrace[right]:
                zer = t2[left] + CFDtrace[left] * (t2[right] - t2[left]) / (
                    CFDtrace[left] - CFDtrace[right]
                )
            else:
                print(
                    "CFD Error: not at a zero crossing from positive to negative values "
                )
                print("   This should not happen!!")
                print("   Trace index:", i)
                print("   CFD values:", CFDtrace[left], CFDtrace[right])
                zer = t2[left]
        except IndexError:
            errors[i] = True
        else:
            cfdtrigger[i] = zer

    return CFD, cfdtime, errors


@ensure_2d_array
def calculate_CFD_using_FF(
    traces,
    t=None,
    CFD_threshold=None,
    FF_threshold=None,
    Lf=10,
    Gf=10,
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

    input:
       traces   (N, M) numpy array: N= number of traces, M=number of data points
       t        (M, 1) numpy arrray, the time axes for the traces

    output:
       CFD  (N, M-B-D-L+1)  numpy array
       cfdtime        (N, 1) numpy array: the time of the zero crossing
       FF       numpy array: fast filter used for the calculation
       IDXerr   numpy array: index of CFD errors

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
        zero_crossings = np.where(np.diff(np.signbit(CFDtrace).astype(np.int)) > 0)[0]
        if zero_crossings.size == 0:
            CFDerror += 1
            cfdtime.append(None)
            IDXerr.append(i)
            continue

        # find first index where the CFD trace is above the threshold
        try:
            FF_trigger_index = np.where(FFtrace >= FF_threshold)[0][0]
            CFD_trigger_index = (
                np.where(np.diff(CFDtrace >= CFD_threshold).astype(np.int) > 0)[0] + 1
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
def calculate_fast_filter(
    traces: np.ndarray, L: int = 1, G: int = 1, filter_range: int = 0
) -> np.ndarray:
    """Calculate the fast filter response.

    Parameters
    ----------
    traces
       1D or 2D array of 1 or N traces of lengths M.
    L
       in FPGA units, 1 = 10 ns
    G
       in FPGA units, 1 = 10 ns
    filter_range
       number of FPGA steps in 2^filter_range that are summed up

    Returns
    -------
    np.ndarray
       The calculated fast filter response of the whole trace.

    """
    assert isinstance(L, int)
    assert L > 0
    assert isinstance(G, int)
    assert G > 0

    traces = traces.astype(np.int64)

    traces = convert_trace_to_FPGA(traces, filter_range=filter_range)
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

    return result


@ensure_2d_array
def get_fast_trigger_index(traces, threshold):
    """Return the indices where the trace value is >= threshold."""

    trigger_pos = [
        np.argwhere((trace[:-1] < threshold) & (trace[1:] > threshold)).flatten() + 1
        for trace in traces
    ]
    return trigger_pos


@ensure_2d_array
def calculate_filter(traces, L=10, G=10):
    """Calculate the fast and slow filter response from the PIXIE

    This implements the filter response as discribted on page 81 in
    section 6.1 of the manual.

    The input can be 1d or 2d in which case the output will be also 1d or 2d.

    input:
       traces   (N, M) numpy array. N traces with a length of M
       L        integer: length of the integration time
       G        integer: gap between the two integration region

    output:
       result   (N, M-2L-G+1)
    """
    assert (L % 5 == 0) and (
        G % 5 == 0
    ), "Filter settings needs to be multiple of 5 (FPGA clock cycles)"

    traces = traces.astype(np.int64)
    NR_traces, length = traces.shape

    assert length % 5 == 0, "Filter trace length needs to be a multiple of 5"

    # scale to 10 ns FPGA clock cycles, e.g. 5 time steps per cycle
    L = L // 5
    G = G // 5
    traces = convert_trace_to_FPGA(traces, filter_range=0)
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

    # scale back to 2 ns timesteps
    result = np.repeat(result, 5, axis=1)
    result = result / L

    return result
