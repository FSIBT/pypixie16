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
        t2 = np.arange(0, length-B-D)*2e-9
    else:
        t2 = t[B+D:]

    # create an empty array of the correct length
    CFD = np.zeros((NR_traces, length-B-D-L+1))
    cfdtime = []
    # calculate the CFD, see section 3.3.8.2, page 47 of the PIXIE
    # manual do as much as possible using numpy, one probably can and
    # should get rid of the for-loop here too, just not sure at the
    # moment how to do it
    for k in range(B+D, length-L):
        CFD[:, k-B-D] = (w*(traces[:, k:k+L+1].sum(axis=1)-traces[:, k-B:k-B+L+1].sum(axis=1)) -
                         (traces[:, k-D:k-D+L+1].sum(axis=1)-traces[:, k-D-B:k-D-B+L+1].sum(axis=1)))
#        fastf = calculate_filter(traces[k])
#        FF.append(fastf)
#    FF = np.array(FF)

    # now find the zero crossing
    low = 0
    FF = []
    CFDerror = 0
    for i, CFDtrace in enumerate(CFD):
        FF0 = calculate_filter(traces[i])
        FF0 = FF0[B+D+L-1:]
        FF.append(FF0)
        # check that the first N points of the fast filter (noise) is below threshold
        # 100 is an arbitrary number here, but the PIXIE should always record some noise first
        # if CFDtrace[:Nbkgd].max() > CFD_threshold:
        if FF0[:Nbkgd].max() > CFD_threshold:
            #print('Warning: CFD analysis theshold too low?', CFDtrace[:Nbkgd].max(),i)
            low += 1

        # all zero crossings
        zero_crossings = np.where(np.diff(np.signbit(CFDtrace)))[0]
        # find first index where the fast filter signal is above the threshold
        CFD_trigger_index = np.where(FF0 >= CFD_threshold)[0][0]
        # first zero crossing at later time than the threshold
        left = zero_crossings[zero_crossings > CFD_trigger_index][0]
        right = left+1
#        if i < 10 :
#            print('left: ', left)
#            print('right: ', right)

        # sanity check
        if CFDtrace[left] > CFDtrace[right]:
            zer = t2[left] + CFDtrace[left] * (t2[right]-t2[left])/(CFDtrace[left]-CFDtrace[right])
        else:
            #            print('CFD Error: not at a zero crossing from positive to negative values ')
            #            print('   This should not happen!!')
            #            print('   Trace index:', i)
            #            print('   CFD values:', CFDtrace[left], CFDtrace[right])
            zer = t2[left]
            CFDerror += 1
        cfdtime.append(zer)

    cfdtime = np.array(cfdtime)
    FF = np.array(FF)

    if one_dim:
        cfdtime = cfdtime[0]
        CFD = CFD[0]

    return CFD, cfdtime, FF, low


def calculate_filter(traces, L=5, G=5):
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

    assert (L % 5 == 0) and (G % 5 == 0), 'Filter settings needs to be multiple of 5 (FPGA clock cycles)'

    traces = traces.astype(np.int64)
    NR_traces, length = traces.shape

    assert length % 5 == 0, 'Filter trace length needs to be a multiple of 5'

    # scale to 10 ns FPGA clock cycles, e.g. 5 time steps per cycle
    L = L//5
    G = G//5
    traces = np.reshape(traces, (NR_traces, length//5, 5))
    traces = traces.sum(axis=2)
    NR_traces, length = traces.shape

    # create an empty array of the correct length
    result = np.zeros((NR_traces, length - 2*L-G+1))

    # do as much as possible using numpy, one probably can and should
    # get rid of the for-loop here too, just not sure at the moment
    # how to do it
    for k in range(2*L+G-1, length):
        result[:, k-2*L-G+1] = traces[:, k-L+1:k+1].sum(axis=1)-traces[:, k-2*L-G+1:k-L-G+1].sum(axis=1)

    # scale back to 2 ns timesteps
    result = np.repeat(result, 5, axis=1)

    if one_dim:
        result = result[0]

    return result
