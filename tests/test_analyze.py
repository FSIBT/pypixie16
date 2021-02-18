import numpy as np
import pytest

import pixie16


def calculate_groups(N, groupsize):
    result = []
    j = 0
    n = 0
    for i in range(N):
        n += i
        j += 1
        if j == groupsize:
            result.append(n)
            j = 0
            n = 0
            continue
    return np.array(result)


class Ensure2DArray:
    def no_arg(self):
        @pixie16.analyze.ensures_2d_array
        def f():
            return True

        with pytest.raises(TypeError) as execinfo:
            f()

    def wrong_arg(self):
        @pixie16.analyze.ensures_2d_array
        def f(x):
            return True

        with pytest.raises(TypeError) as execinfo:
            f(0)

    def convert(self):
        @pixie16.analyze.ensures_2d_array
        def f(x):
            return len(x.shape) == 2

        assert f(np.arange(4))

    def no_convert(self):
        @pixie16.analyze.ensures_2d_array
        def f(x):
            return len(x.shape) == 2

        assert f(np.arange(10).reshape(5, 2))


class TestConvertTraceToFPGA:
    def test_group_of_1D(self):
        N = 100
        input = np.arange(N)
        for filter_range, groupsize in enumerate([5, 10, 20]):
            out = pixie16.analyze.convert_trace_to_FPGA(
                input, filter_range=filter_range
            )
            result = calculate_groups(N, groupsize)
            assert np.array_equal(out, result)

    def test_group_of_2D(self):
        M = 100
        N = 20
        input_1D = np.arange(M)
        input = np.array([input_1D for i in range(N)])
        for filter_range, groupsize in enumerate([5, 10, 20]):
            out = pixie16.analyze.convert_trace_to_FPGA(
                input, filter_range=filter_range
            )
            result_1D = calculate_groups(M, groupsize)
            result = np.array([result_1D for i in range(N)])
            assert np.array_equal(out, result)

    def test_wrong_length(self):
        with pytest.raises(ValueError) as execinfo:
            N = 99
            input = np.arange(N)
            out = pixie16.analyze.convert_trace_to_FPGA(input)
        with pytest.raises(ValueError) as execinfo:
            M = 99
            N = 20
            input_1D = np.arange(M)
            input = np.array([input_1D for i in range(N)])
            out = pixie16.analyze.convert_trace_to_FPGA(input)
        with pytest.raises(ValueError) as execinfo:
            N = 90
            input = np.arange(N)
            out = pixie16.analyze.convert_trace_to_FPGA(input, filter_range=2)

    def test_wrong_filter_range(self):
        with pytest.raises(ValueError) as execinfo:
            N = 100
            input = np.arange(N)
            out = pixie16.analyze.convert_trace_to_FPGA(input, filter_range=-1)
