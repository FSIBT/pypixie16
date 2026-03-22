from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

import pixie16


@pytest.fixture(scope="module")
def full_list_mode_binary_file():
    return (
        Path(__file__).parent.parent.parent
        / "files"
        / "bin"
        / "pixie16_binary_data-full.bin"
    )


@pytest.fixture(scope="module")
def split_list_mode_binary_files():
    files = [
        "pixie16_binary_data-00.bin",
        "pixie16_binary_data-01.bin",
        "pixie16_binary_data-02.bin",
        "pixie16_binary_data-03.bin",
        "pixie16_binary_data-04.bin",
    ]

    path = Path(__file__).parent.parent.parent / "files" / "bin"
    return [path / f for f in files]


@pytest.fixture(scope="module")
def split_list_mode_binary_files_out_of_order():
    files = [
        "pixie16_binary_data-00.bin",
        "pixie16_binary_data-02.bin",  # wrong order
        "pixie16_binary_data-01.bin",
        "pixie16_binary_data-03.bin",
        "pixie16_binary_data-04.bin",
    ]

    path = Path(__file__).parent.parent.parent / "files" / "bin"
    return [path / f for f in files]


@pytest.fixture(scope="module")
def list_mode_data_events():
    path = Path(__file__).parent.parent.parent / "files" / "parquet"
    events_file = path / "pixie16-events.parquet"
    data = pd.read_parquet(events_file)
    # fix some data types
    for column in ["pileup", "trace_flag"]:
        data[column] = data[column].astype(bool)
    for column in ["Esum_trailing", "Esum_leading", "Esum_gap", "baseline"]:
        data[column] = data[column].replace([0], -1)
    return data


@pytest.fixture(scope="module")
def split_all_binary_file():
    return Path(__file__).parent.parent.parent / "files" / "bin" / "split-all.bin"


@pytest.fixture(scope="module")
def split_binary_files_with_energy_sums_and_traces():
    path = Path(__file__).parent.parent.parent / "files" / "bin"
    return [path / "split-01.bin", path / "split-02.bin"]


class TestReadListModeData:
    def test_read_full_binary_file(
        self, full_list_mode_binary_file, list_mode_data_events
    ):
        read_events = pixie16.read.read_list_mode_data([full_list_mode_binary_file])

        # drop QDC columns and others
        to_drop = list(set(read_events.columns) - set(list_mode_data_events.columns))
        read_events = read_events.drop(to_drop, axis=1)

        assert_frame_equal(read_events, list_mode_data_events)

    def test_read_split_binary_file(
        self, split_list_mode_binary_files, list_mode_data_events
    ):
        read_events = pixie16.read.read_list_mode_data(split_list_mode_binary_files)

        # drop QDC columns and others
        to_drop = list(set(read_events.columns) - set(list_mode_data_events.columns))

        read_events = read_events.drop(to_drop, axis=1)

        assert len(read_events) > 0
        assert_frame_equal(read_events, list_mode_data_events)

    def test_read_split_binary_file_out_of_order(
        self, split_list_mode_binary_files_out_of_order, list_mode_data_events
    ):
        with pytest.raises(KeyError):
            read_events = pixie16.read.read_list_mode_data(
                split_list_mode_binary_files_out_of_order
            )

    def test_read_split_with_energy_sums_and_traces(
        self,
        split_binary_files_with_energy_sums_and_traces,
        split_all_binary_file,
    ):
        """[split-01.bin, split-02.bin] must equal [split-all.bin].

        Exercises header_length=8 (energy sums), trace decoding, and
        cross-file event stitching (the 6th event spans the file boundary).
        """
        from pandas.testing import assert_frame_equal

        split_result = pixie16.read.read_list_mode_data(
            split_binary_files_with_energy_sums_and_traces
        )
        all_result = pixie16.read.read_list_mode_data([split_all_binary_file])

        assert len(split_result) == len(all_result)
        assert_frame_equal(
            split_result.reset_index(drop=True), all_result.reset_index(drop=True)
        )


class TestAPICoverage:
    """Smoke tests for functions that previously had no test coverage."""

    def test_read_list_mode_data_as_events_returns_event_objects(
        self, full_list_mode_binary_file
    ):
        events = pixie16.read.read_list_mode_data_as_events(
            [full_list_mode_binary_file]
        )
        assert len(events) > 0
        e = events[0]
        assert hasattr(e, "channel")
        assert hasattr(e, "energy")
        assert hasattr(e, "timestamp")

    def test_read_list_mode_data_as_events_max_size(self, full_list_mode_binary_file):
        max_size = 10
        events = pixie16.read.read_list_mode_data_as_events(
            [full_list_mode_binary_file], max_size=max_size
        )
        assert len(events) == max_size

    def test_timestamps_and_sizes_from_files_generator(
        self, full_list_mode_binary_file
    ):
        pairs = list(
            pixie16.read.timestamps_and_sizes_from_files_generator(
                [full_list_mode_binary_file]
            )
        )
        assert len(pairs) > 0
        timestamps, sizes = zip(*pairs)
        # All timestamps should be non-negative
        assert all(t >= 0 for t in timestamps)
        # All event sizes should be positive words
        assert all(s > 0 for s in sizes)
        # Timestamps from pixie16_binary_data-full.bin have header_length=4 events
        assert all(s >= 4 for s in sizes)

    def test_timestamps_and_sizes_matches_event_count(self, full_list_mode_binary_file):
        n_events_df = len(
            pixie16.read.read_list_mode_data([full_list_mode_binary_file])
        )
        n_pairs = sum(
            1
            for _ in pixie16.read.timestamps_and_sizes_from_files_generator(
                [full_list_mode_binary_file]
            )
        )
        assert n_pairs == n_events_df

    def test_sort_events_by_channel_groups_correctly(self, full_list_mode_binary_file):
        events = pixie16.read.read_list_mode_data_as_events(
            [full_list_mode_binary_file]
        )
        by_channel = pixie16.read.sort_events_by_channel(events)

        # Every key is a channel number; every event in a bucket has that channel
        for ch, ch_events in by_channel.items():
            assert all(e.channel == ch for e in ch_events)

        # Total event count is preserved
        total = sum(len(v) for v in by_channel.values())
        assert total == len(events)

    def test_sort_events_by_channel_with_channel_list(self, full_list_mode_binary_file):
        events = pixie16.read.read_list_mode_data_as_events(
            [full_list_mode_binary_file]
        )
        # Pick the first two channels present in the data
        all_channels = sorted({e.channel for e in events})
        keep = all_channels[:2]

        by_channel = pixie16.read.sort_events_by_channel(events, channel_list=keep)
        assert set(by_channel.keys()) == set(all_channels)  # current impl keeps all
