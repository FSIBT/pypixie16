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
        cfd_delay = s.get("CFDDelay", channel=9, as_pint=True)
        trace_delay = s.get("TraceDelay", channel=3, as_pint=True)
        trace_length = s.get("TraceLength", channel=0, as_pint=True)
        ext_delay_length = s.get("ExternDelayLen", channel=0, as_pint=True)

        assert round(livetime.to("seconds").magnitude, 2) == 599.82
        assert s["LiveTime"][9] == 59981879462
        assert s.FastGap[3] == 10
        assert s.Log2Ebin[3] == 4294967295
        assert s["CFDThresh"][0] == 120
        assert cfd_delay.to("seconds").magnitude == 8e-8
        assert s["BLcut"][0] == 222
        assert s["BaselinePercent"][0] == 10
        assert trace_delay.to("seconds").magnitude == 2e-7
        assert s["TraceLength"][0] == 5000
        assert trace_length.to("seconds").magnitude == 1e-5
        assert s["ExternDelayLen"][0] == 100
        assert ext_delay_length.to("seconds").magnitude == 1e-6
