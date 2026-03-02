"""Shared fixtures and helpers for list-mode data reader tests."""

import struct
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# make_event_words — builds a valid Pixie16 binary event as a uint32 array
# ---------------------------------------------------------------------------


def make_event_words(
    channel,
    slot,
    crate,
    energy,
    timestamp_ns,
    cfd_bits=1,
    cfd_frac=0,
    pileup=False,
    trace=None,
    esum=None,
    qdc=None,
    ext_ts=None,
):
    """Build a numpy array of uint32 words for one synthetic Pixie16 event.

    The encoding matches the XIA Pixie16 list-mode binary format exactly:
    little-endian uint32 words, bit-packed per the hardware manual.

    Parameters
    ----------
    channel : int  — 0-15
    slot : int     — 0-15
    crate : int    — 0-15
    energy : int   — 0-65535
    timestamp_ns : int — Pixie16 timestamp in nanoseconds (must be a multiple of 10)
    cfd_bits : int — 0-7 (7 = CFD error)
    cfd_frac : int — 0-8191 (CFD fractional time)
    pileup : bool
    trace : array-like of uint16 | None  — ADC samples (one sample per entry)
    esum : object with .trailing/.leading/.gap (int) and .baseline (float) | None
    qdc : sequence of 8 ints | None  — QDCSum0 through QDCSum7
    ext_ts : int | None  — external timestamp (raw integer counts)

    Returns
    -------
    np.ndarray, dtype=uint32, length=event_length
    """
    # --- Timestamp ---
    ts_units = int(timestamp_ns) // 10
    EVTTIME_LO = ts_units & 0xFFFFFFFF
    EVTTIME_HI = (ts_units >> 32) & 0xFFFF

    # --- Determine header_length ---
    # Base header is always 4 words.
    # Extra words are appended in fixed order: esum (+4), qdc (+8), ext_ts (+2).
    header_length = 4
    if esum is not None:
        header_length += 4
    if qdc is not None:
        header_length += 8
    if ext_ts is not None:
        header_length += 2

    # --- Trace ---
    # trace_length in the header = number of uint16 ADC samples.
    # Samples are packed two-per-uint32 word in little-endian order.
    if trace is not None:
        trace_arr = np.asarray(trace, dtype=np.uint16)
        trace_length_samples = len(trace_arr)
        if trace_length_samples % 2 != 0:
            trace_arr = np.append(trace_arr, np.uint16(0))
        trace_words = trace_arr.view(np.uint32).copy()
        trace_flag = True
    else:
        trace_arr = np.array([], dtype=np.uint16)
        trace_length_samples = 0
        trace_words = np.array([], dtype=np.uint32)
        trace_flag = False

    event_length = header_length + len(trace_words)

    # --- Word 0 ---
    A = (
        (int(pileup) << 31)
        | ((event_length & 0x3FFF) << 17)
        | ((header_length & 0x1F) << 12)
        | ((crate & 0xF) << 8)
        | ((slot & 0xF) << 4)
        | (channel & 0xF)
    )
    # --- Word 1: EVTTIME_LO ---
    B = EVTTIME_LO
    # --- Word 2 ---
    C = ((cfd_bits & 0x7) << 29) | ((cfd_frac & 0x1FFF) << 16) | EVTTIME_HI
    # --- Word 3 ---
    D = (
        (int(trace_flag) << 31)
        | ((trace_length_samples & 0x7FFF) << 16)
        | (energy & 0xFFFF)
    )

    words = [np.uint32(A), np.uint32(B), np.uint32(C), np.uint32(D)]

    # --- Energy sums (4 words): trailing, leading, gap (u32), baseline (f32) ---
    if esum is not None:
        words.append(np.uint32(int(esum.trailing) & 0xFFFFFFFF))
        words.append(np.uint32(int(esum.leading) & 0xFFFFFFFF))
        words.append(np.uint32(int(esum.gap) & 0xFFFFFFFF))
        # f32 stored as raw bytes in native (little-endian) byte order
        baseline_bytes = struct.pack("<f", float(esum.baseline))
        words.append(np.frombuffer(baseline_bytes, dtype=np.uint32)[0])

    # --- QDC sums (8 words): QDCSum0 through QDCSum7 ---
    if qdc is not None:
        for v in qdc:
            words.append(np.uint32(int(v) & 0xFFFFFFFF))

    # --- External timestamp (2 words): Ext_TS_Lo, [pad16][Ext_TS_Hi] ---
    if ext_ts is not None:
        ext_lo = int(ext_ts) & 0xFFFFFFFF
        ext_hi = (int(ext_ts) >> 32) & 0xFFFF
        words.append(np.uint32(ext_lo))
        words.append(np.uint32(ext_hi))  # upper 16 bits are zero (padding)

    result = np.array(words, dtype=np.uint32)
    if len(trace_words) > 0:
        result = np.concatenate([result, trace_words])

    assert len(result) == event_length, (
        f"make_event_words: expected {event_length} words, got {len(result)}"
    )
    return result


@pytest.fixture(name="make_event_words")
def make_event_words_fixture():
    """Pytest fixture returning the make_event_words helper function."""
    return make_event_words


# ---------------------------------------------------------------------------
# Benchmark baseline hint
# ---------------------------------------------------------------------------


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    baseline_dir = Path(__file__).parent / ".benchmarks"
    has_baseline = baseline_dir.exists() and any(baseline_dir.rglob("*.json"))
    if not has_baseline:
        terminalreporter.write_sep("-", "benchmark baseline hint")
        terminalreporter.write_line(
            "No baseline saved yet. After reviewing results, run:"
        )
        terminalreporter.write_line(
            "  pytest tests/test_pixie16/test_read/test_benchmark.py"
            " --benchmark-save=baseline"
            " --benchmark-storage=tests/test_pixie16/test_read/.benchmarks/"
        )
        terminalreporter.write_line("To compare against a saved baseline:")
        terminalreporter.write_line(
            "  pytest tests/test_pixie16/test_read/test_benchmark.py"
            " --benchmark-compare=baseline"
            " --benchmark-storage=tests/test_pixie16/test_read/.benchmarks/"
        )
