import pytest
from pathlib import Path

import pixie16


@pytest.fixture(scope="module")
def data():
    filename = Path(".") / "tests" / "pixie16-data-01.bin"
    data = list(pixie16.read.read_list_mode_data(filename.absolute()))
    return data


class TestXIAread:
    def test_read(self, data):
        assert len(data) == 24598

    def test_element(self, data):
        event = data[10]
        assert event.channel == 9
        assert event.crate == 0
        assert event.slot == 2
        assert event.energy == 26517
        assert event.timestamp == 1170576147200

    def test_split(self):
        filename = Path(".") / "tests" / "split-all.bin"
        events1 = list(pixie16.read.read_list_mode_data(filename.absolute()))

        events2 = []
        for f in [
            Path(".") / "tests" / "split-01.bin",
            Path(".") / "tests" / "solit-02.bin",
        ]:
            for e in pixie16.read.read_list_mode_data(filename.absolute()):
                events2.append(e)

        for e1, e2 in zip(events1, events2):
            assert e1 == e2
