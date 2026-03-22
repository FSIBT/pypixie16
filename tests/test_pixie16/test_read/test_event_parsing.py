"""Unit tests for Pixie16 list-mode event parsing.

Covers every supported header_length variant (4–18 words), the FileReader
and StreamReader paths, trace decoding, and cross-chunk stitching via
synthetic binary data built by the make_event_words conftest helper.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from pixie16.read.list_mode.list_mode_data_reader import (
    EmptyError,
    FileReader,
    ListModeDataReader,
    StreamReader,
)

# ---------------------------------------------------------------------------
# Shared test values
# ---------------------------------------------------------------------------

CHANNEL = 5
SLOT = 2
CRATE = 1
ENERGY = 1234
TIMESTAMP_NS = 1_000_000_000  # exactly 1 second; divisible by 10
CFD_BITS = 1
CFD_FRAC = 4096  # → CFD_fraction = ((1-1) + 4096/8192)*2 = 1.0

ESUM = SimpleNamespace(trailing=10_000, leading=20_000, gap=5_000, baseline=3.14)
QDC = [100, 200, 300, 400, 500, 600, 700, 800]
EXT_TS = 5_000_000_000  # requires more than 32 bits: 0x_0000_0001_2A05_F200


def _expected_timestamp():
    ts_units = TIMESTAMP_NS // 10
    lo = ts_units & 0xFFFFFFFF
    hi = (ts_units >> 32) & 0xFFFF
    return (lo + hi * 2**32) * 10


def _expected_cfd_fraction(cfd_bits=CFD_BITS, cfd_frac=CFD_FRAC):
    if cfd_bits == 7:
        return 0.0
    return ((cfd_bits - 1) + cfd_frac / 8192) * 2


# ---------------------------------------------------------------------------
# Parametrize over all supported header configurations
# ---------------------------------------------------------------------------

HEADER_CONFIGS = [
    pytest.param(None, None, None, id="hl4_none"),
    pytest.param(None, None, EXT_TS, id="hl6_ext_ts"),
    pytest.param(ESUM, None, None, id="hl8_esum"),
    pytest.param(ESUM, None, EXT_TS, id="hl10_esum_ext_ts"),
    pytest.param(None, QDC, None, id="hl12_qdc"),
    pytest.param(None, QDC, EXT_TS, id="hl14_qdc_ext_ts"),
    pytest.param(ESUM, QDC, None, id="hl16_esum_qdc"),
    pytest.param(ESUM, QDC, EXT_TS, id="hl18_esum_qdc_ext_ts"),
]


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def _assert_base_fields(event, *, trace=False):
    assert event.channel == CHANNEL
    assert event.slot == SLOT
    assert event.crate == CRATE
    assert event.energy == ENERGY
    assert event.timestamp == _expected_timestamp()
    assert event.CFD_fraction == pytest.approx(_expected_cfd_fraction())
    assert event.CFD_error == False  # noqa: E712
    assert event.pileup == False  # noqa: E712
    assert event.trace_flag == trace


def _assert_esum_fields(event, esum):
    assert event.Esum_trailing == esum.trailing
    assert event.Esum_leading == esum.leading
    assert event.Esum_gap == esum.gap
    assert event.baseline == pytest.approx(esum.baseline, abs=1e-3)


def _assert_qdc_fields(event, qdc):
    for i, v in enumerate(qdc):
        assert getattr(event, f"QDCSum{i}") == v, f"QDCSum{i} mismatch"


def _assert_ext_ts_field(event, ext_ts):
    assert event.ext_timestamp == ext_ts


def _assert_optional_fields(event, esum, qdc, ext_ts):
    if esum is not None:
        _assert_esum_fields(event, esum)
    if qdc is not None:
        _assert_qdc_fields(event, qdc)
    if ext_ts is not None:
        _assert_ext_ts_field(event, ext_ts)


# ---------------------------------------------------------------------------
# Helper: write words to a temp binary file
# ---------------------------------------------------------------------------


def _write_bin(tmp_path, *arrays, name="events.bin"):
    p = tmp_path / name
    np.concatenate(arrays).tofile(str(p))
    return p


# ---------------------------------------------------------------------------
# FileReader path — one event per header variant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("esum,qdc,ext_ts", HEADER_CONFIGS)
def test_header_variants_via_filereader(tmp_path, make_event_words, esum, qdc, ext_ts):
    words = make_event_words(
        channel=CHANNEL,
        slot=SLOT,
        crate=CRATE,
        energy=ENERGY,
        timestamp_ns=TIMESTAMP_NS,
        cfd_bits=CFD_BITS,
        cfd_frac=CFD_FRAC,
        esum=esum,
        qdc=qdc,
        ext_ts=ext_ts,
    )
    p = _write_bin(tmp_path, words)
    with FileReader([p]) as r:
        reader = ListModeDataReader(r)
        event = reader.pop()

    _assert_base_fields(event)
    _assert_optional_fields(event, esum, qdc, ext_ts)


# ---------------------------------------------------------------------------
# StreamReader path — one event per header variant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("esum,qdc,ext_ts", HEADER_CONFIGS)
def test_header_variants_via_streamreader(make_event_words, esum, qdc, ext_ts):
    words = make_event_words(
        channel=CHANNEL,
        slot=SLOT,
        crate=CRATE,
        energy=ENERGY,
        timestamp_ns=TIMESTAMP_NS,
        cfd_bits=CFD_BITS,
        cfd_frac=CFD_FRAC,
        esum=esum,
        qdc=qdc,
        ext_ts=ext_ts,
    )
    sr = StreamReader()
    sr.put(words)
    reader = ListModeDataReader(sr)
    event = reader.pop()

    _assert_base_fields(event)
    _assert_optional_fields(event, esum, qdc, ext_ts)


# ---------------------------------------------------------------------------
# Trace decoding
# ---------------------------------------------------------------------------


def test_trace_parsing(tmp_path, make_event_words):
    trace = list(range(100))  # 100 uint16 ADC samples
    words = make_event_words(
        channel=CHANNEL,
        slot=SLOT,
        crate=CRATE,
        energy=ENERGY,
        timestamp_ns=TIMESTAMP_NS,
        cfd_bits=CFD_BITS,
        cfd_frac=CFD_FRAC,
        trace=trace,
    )
    p = _write_bin(tmp_path, words)
    with FileReader([p]) as r:
        reader = ListModeDataReader(r)
        event = reader.pop()

    _assert_base_fields(event, trace=True)
    assert list(event.trace) == trace


def test_trace_parsing_via_streamreader(make_event_words):
    trace = list(range(50))  # 50 uint16 ADC samples
    words = make_event_words(
        channel=CHANNEL,
        slot=SLOT,
        crate=CRATE,
        energy=ENERGY,
        timestamp_ns=TIMESTAMP_NS,
        cfd_bits=CFD_BITS,
        cfd_frac=CFD_FRAC,
        trace=trace,
    )
    sr = StreamReader()
    sr.put(words)
    reader = ListModeDataReader(sr)
    event = reader.pop()

    _assert_base_fields(event, trace=True)
    assert list(event.trace) == trace


# ---------------------------------------------------------------------------
# Special flag fields
# ---------------------------------------------------------------------------


def test_pileup_flag(tmp_path, make_event_words):
    words = make_event_words(
        channel=CHANNEL,
        slot=SLOT,
        crate=CRATE,
        energy=ENERGY,
        timestamp_ns=TIMESTAMP_NS,
        pileup=True,
    )
    p = _write_bin(tmp_path, words)
    with FileReader([p]) as r:
        reader = ListModeDataReader(r)
        event = reader.pop()

    assert event.pileup == True  # noqa: E712


def test_cfd_error_flag(tmp_path, make_event_words):
    """cfd_bits=7 should produce CFD_error=True and CFD_fraction=0."""
    words = make_event_words(
        channel=CHANNEL,
        slot=SLOT,
        crate=CRATE,
        energy=ENERGY,
        timestamp_ns=TIMESTAMP_NS,
        cfd_bits=7,
        cfd_frac=0,
    )
    p = _write_bin(tmp_path, words)
    with FileReader([p]) as r:
        reader = ListModeDataReader(r)
        event = reader.pop()

    assert event.CFD_error == True  # noqa: E712
    assert event.CFD_fraction == 0


# ---------------------------------------------------------------------------
# Multiple events in sequence
# ---------------------------------------------------------------------------


def test_multiple_events_in_sequence(tmp_path, make_event_words):
    n = 5
    all_words = np.concatenate(
        [
            make_event_words(
                channel=i,
                slot=SLOT,
                crate=CRATE,
                energy=ENERGY + i,
                timestamp_ns=TIMESTAMP_NS + i * 1_000,
            )
            for i in range(n)
        ]
    )
    p = _write_bin(tmp_path, all_words)
    with FileReader([p]) as r:
        reader = ListModeDataReader(r)
        events = reader.pop_all()

    assert len(events) == n
    for i, e in enumerate(events):
        assert e.channel == i
        assert e.energy == ENERGY + i


# ---------------------------------------------------------------------------
# Cross-chunk stitching via StreamReader
# ---------------------------------------------------------------------------


def test_cross_chunk_stitching(make_event_words):
    """An event split at every possible word boundary is still parsed correctly."""
    words = make_event_words(
        channel=CHANNEL,
        slot=SLOT,
        crate=CRATE,
        energy=ENERGY,
        timestamp_ns=TIMESTAMP_NS,
        cfd_bits=CFD_BITS,
        cfd_frac=CFD_FRAC,
    )
    event_length = len(words)

    for split_point in range(1, event_length):
        sr = StreamReader()
        reader = ListModeDataReader(sr)

        # First chunk — incomplete event, pop() must not succeed
        sr.put(words[:split_point])
        with pytest.raises(EmptyError):
            reader.pop()

        # Second chunk completes the event
        sr.put(words[split_point:])
        event = reader.pop()

        assert event.channel == CHANNEL, f"split_point={split_point}"
        assert event.energy == ENERGY, f"split_point={split_point}"
        assert event.timestamp == _expected_timestamp(), f"split_point={split_point}"


def test_cross_chunk_stitching_with_extras(make_event_words):
    """Same stitching test for an event with energy sums (header_length=8)."""
    words = make_event_words(
        channel=CHANNEL,
        slot=SLOT,
        crate=CRATE,
        energy=ENERGY,
        timestamp_ns=TIMESTAMP_NS,
        esum=ESUM,
    )
    event_length = len(words)

    for split_point in range(1, event_length):
        sr = StreamReader()
        reader = ListModeDataReader(sr)

        sr.put(words[:split_point])
        with pytest.raises(EmptyError):
            reader.pop()

        sr.put(words[split_point:])
        event = reader.pop()

        assert event.channel == CHANNEL, f"split_point={split_point}"
        assert event.energy == ENERGY, f"split_point={split_point}"
        _assert_esum_fields(event, ESUM)
