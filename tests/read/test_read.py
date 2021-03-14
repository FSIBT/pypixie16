import pandas as pd
import pytest

import pixie16
import old_read


@pytest.fixture(scope='module')
def full_list_mode_binary_file():
    return 'pixie16_binary_data-full.bin'


@pytest.fixture(scope='module')
def split_list_mode_binary_files():
    return ['pixie16_binary_data-00.bin',
            'pixie16_binary_data-01.bin',
            'pixie16_binary_data-02.bin',
            'pixie16_binary_data-03.bin',
            'pixie16_binary_data-04.bin']


@pytest.fixture(scope='module')
def list_mode_data_events():
    events_file = 'pixie16-events.hdf'
    return pd.read_hdf(events_file)


class TestReadListModeData:

    def test_read_full_binary_file(self, full_list_mode_binary_file, list_mode_data_events):
        read_events = pixie16.read.read_list_mode_data([full_list_mode_binary_file])
        for column in read_events:
            assert read_events[column] == list_mode_data_events[column]

    def test_read_split_binary_file(self, split_list_mode_binary_files, list_mode_data_events):
        read_events = pixie16.read.read_list_mode_data(split_list_mode_binary_files)
        for column in read_events:
            assert read_events[column] == list_mode_data_events[column]


@pytest.fixture(scope='module')
def settings_file():
    return 'pixie16-settings.set'


class TestReadSettingsData:

    def test_read_settings(self, settings_file):
        old_settings = old_read.Settings(settings_file, modulenr=0)
        new_settings = pixie16.read.load_settings(settings_file)
        for field in dir(old_settings):
            try:
                assert getattr(old_settings, field) == getattr(new_settings, field)
            except ValueError:
                assert all(getattr(old_settings, field) == getattr(new_settings, field))
