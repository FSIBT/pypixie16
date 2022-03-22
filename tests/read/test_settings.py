from pathlib import Path

import pytest

import pixie16


@pytest.fixture
def setting():
    return pixie16.read.Settings.from_file(Path(__file__).parent / "settings_file.json")


@pytest.fixture
def stats():
    return pixie16.read.Stats.from_file(Path(__file__).parent / "stats_file.json")


class TestSettings:
    def test_standard_access(self, setting):
        assert setting["channel"]["input"]["BLcut"][0] == 223
        assert setting["channel"]["input"]["BLcut"][1] == 242

    def test_flat_access(self, setting):
        assert setting.get_by_name("BLcut")[0] == 223
        assert setting.get_by_name("BLcut")[1] == 242

    def test_setting_value(self, setting):
        setting["channel"]["input"]["BLcut"][0] = 2
        assert setting["channel"]["input"]["BLcut"][0] == 2

    def test_setting_by_flat_access(self, setting):
        setting.set_by_name("BLcut", list(range(16)))
        assert setting["channel"]["input"]["BLcut"][0] == 0
        assert setting["channel"]["input"]["BLcut"][4] == 4


class TestStats:
    def test_standard_access(self, stats):
        assert stats["real_time"][0] == 1.0
        assert stats["real_time"][1] == 2.0

    def test_flat_access(self, stats):
        assert stats.get_by_name("real_time")[0] == 1.0
        assert stats.get_by_name("real_time")[1] == 2.0
