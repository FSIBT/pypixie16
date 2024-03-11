import numpy as np
from numpy.testing import assert_array_equal

import pixie16


class TestStreamer:
    def test_add_and_read(self):
        S = pixie16.read.StreamReader()

        x = np.arange(20, dtype=np.uint32)

        S.put(x)

        assert_array_equal(S.read(4), np.array([0, 1, 2, 3], dtype=np.uint32))

    def test_add_and_read_twice(self):
        S = pixie16.read.StreamReader()

        x = np.arange(20, dtype=np.uint32)

        S.put(x)

        S.read(4)
        assert_array_equal(S.read(4), np.array([4, 5, 6, 7], dtype=np.uint32))

    def test_buffer_size_doubling(self):
        S = pixie16.read.StreamReader(initial_buffer_size=1_000)

        data = np.arange(20, dtype=np.uint32)
        S.put(data)

        assert S.buffer_size == 1_000

        data = np.arange(1_200, dtype=np.uint32)
        S.put(data)

        assert S.buffer_size == 2_000

    def test_buffer_size_adjust_large_data(self):
        S = pixie16.read.StreamReader(initial_buffer_size=100)

        data = np.arange(600, dtype=np.uint32)
        S.put(data)

        assert S.buffer_size == 800

    def test_buffer_size_shrink_size(self):
        S = pixie16.read.StreamReader(initial_buffer_size=100)

        # force increase to 800
        data = np.arange(600, dtype=np.uint32)
        S.put(data)
        assert S.buffer_size == 800

        S.read(600)

        data = np.arange(10, dtype=np.uint32)
        S.put(data)

        assert S.buffer_size == 100
