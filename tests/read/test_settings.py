from pathlib import Path

import pytest

import pixie16


@pytest.fixture(scope="module")
def settings_file():
    return Path(__file__).parent / "pixie16-settings.set"


class TestReadSettingsData:
    def test_read_settings(self, settings_file):
        s = pixie16.read.load_settings(settings_file)

        livetime = s.get("LiveTime", channel=3, as_pint=True)

        assert round(livetime.to("seconds").magnitude, 2) == 599.82
        assert s["LiveTime"][9] == 59981879462
        assert s.FastGap[3] == 10
        assert s.Log2Ebin[3] == 4294967295
