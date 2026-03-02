"""Benchmarks for list-mode data reading.

Run with:
    pytest tests/test_pixie16/test_read/test_benchmark.py -v

Save a baseline after reviewing results:
    pytest tests/test_pixie16/test_read/test_benchmark.py \
        --benchmark-save=baseline \
        --benchmark-storage=tests/test_pixie16/test_read/.benchmarks/

Compare against a saved baseline:
    pytest tests/test_pixie16/test_read/test_benchmark.py \
        --benchmark-compare=baseline \
        --benchmark-storage=tests/test_pixie16/test_read/.benchmarks/
"""

from pathlib import Path

import pytest

import pixie16.read

BENCHMARK_FILE = (
    Path(__file__).parent.parent.parent
    / "files"
    / "bin"
    / "pixie16_binary_data-full.bin"
)


@pytest.fixture(scope="module")
def benchmark_file():
    if not BENCHMARK_FILE.exists():
        pytest.skip(f"Benchmark file not found: {BENCHMARK_FILE}")
    return BENCHMARK_FILE


def test_read_list_mode_data_benchmark(benchmark, benchmark_file):
    result = benchmark(pixie16.read.read_list_mode_data, [benchmark_file])
    assert len(result) > 0


def test_events_generator_benchmark(benchmark, benchmark_file):
    result = benchmark(
        lambda: list(pixie16.read.events_from_files_generator([benchmark_file]))
    )
    assert len(result) > 0
