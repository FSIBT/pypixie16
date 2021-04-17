from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

import pixie16


@pytest.fixture(scope="module")
def full_list_mode_binary_file():
    return Path(__file__).parent / "pixie16_binary_data-full.bin"


@pytest.fixture(scope="module")
def split_list_mode_binary_files():
    files = [
        "pixie16_binary_data-00.bin",
        "pixie16_binary_data-01.bin",
        "pixie16_binary_data-02.bin",
        "pixie16_binary_data-03.bin",
        "pixie16_binary_data-04.bin",
    ]

    path = Path(__file__).parent
    return [path / f for f in files]


@pytest.fixture(scope="module")
def list_mode_data_events():
    path = Path(__file__).parent
    events_file = path / "pixie16-events.hdf"
    data = pd.read_hdf(events_file)
    # fix some data types
    for column in ["pileup", "trace_flag"]:
        data[column] = data[column].astype(bool)
    for column in ["Esum_trailing", "Esum_leading", "Esum_gap", "baseline"]:
        data[column] = data[column].replace([0], -1)
    return data


class TestReadListModeData:
    def test_read_full_binary_file(
        self, full_list_mode_binary_file, list_mode_data_events
    ):
        read_events = pixie16.read.read_list_mode_data([full_list_mode_binary_file])

        to_drop = list(set(read_events.columns) - set(list_mode_data_events.columns))
        read_events.drop(to_drop, axis=1, inplace=True)

        assert_frame_equal(read_events, list_mode_data_events)

    def test_read_split_binary_file(
        self, split_list_mode_binary_files, list_mode_data_events
    ):
        read_events = pixie16.read.read_list_mode_data(split_list_mode_binary_files)

        to_drop = list(set(read_events.columns) - set(list_mode_data_events.columns))
        read_events.drop(to_drop, axis=1, inplace=True)

        assert_frame_equal(read_events, list_mode_data_events)
