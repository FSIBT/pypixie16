import pytest
from pathlib import Path

import pixie16


@pytest.fixture(scope="module")
def data():
    filename = Path('.') / 'tests' / 'pixie16-data-01.bin'
    data = list(pixie16.read.read_list_mode_data(filename.absolute()))
    return data


class TestXIAread():

    def test_read(self, data):
        assert len(data) == 24598

    def test_element(self, data):
        event = data[10]
        assert event.channel == 9
        assert event.crate == 0
        assert event.slot == 2
        assert event.energy == 26517
        assert event.timestamp == 585288073600
