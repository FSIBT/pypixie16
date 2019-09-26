"""
Functions to help analyze PIXIE-16 data
"""

import numpy as np


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

    if len(traces.shape) == 1:
        traces = traces[np.newaxis, :]
        one_dim = True
    else:
        one_dim = False

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

    if one_dim:
        cfdtrigger = cfdtrigger[0]
        CFD = CFD[0]
        errors = errors[0]

    return CFD, cfdtime, errors


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

    if len(traces.shape) == 1:
        traces = traces[np.newaxis, :]
        one_dim = True
    else:
        one_dim = False

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

    if one_dim:
        cfdtime = cfdtime[0]
        CFD = CFD[0]

    print("Calculated CFD errors = ", CFDerror)
    print("Events with noise above fast filter threshold = ", low)

    return CFD, cfdtime, fast_filter, IDXerr


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

    if len(traces.shape) == 1:
        traces = traces[np.newaxis, :]
        one_dim = True
    else:
        one_dim = False

    assert (L % 5 == 0) and (
        G % 5 == 0
    ), "Filter settings needs to be multiple of 5 (FPGA clock cycles)"

    traces = traces.astype(np.int64)
    NR_traces, length = traces.shape

    assert length % 5 == 0, "Filter trace length needs to be a multiple of 5"

    # scale to 10 ns FPGA clock cycles, e.g. 5 time steps per cycle
    L = L // 5
    G = G // 5
    traces = np.reshape(traces, (NR_traces, length // 5, 5))
    traces = traces.sum(axis=2)
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

    if one_dim:
        result = result[0]

    return result
