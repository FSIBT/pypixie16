import ROOTS


sample_run = ('2021-04-08', 0)
p = ROOTS.helper.get_data_path(*sample_run)
settings_path = p / 'settings'

import datetime
import parse

import pixie16


settings = {}

settings_filename_fmt = 'RUN-{date}-settings-{date_time}.set'
initial_settings_filename_fmt = 'RUN-{date}-settings-{date_time}-initial.set'
date_time_fmt = '%Y-%m-%d-%H-%M-%S'
for child in settings_path.iterdir():
    filename = child.name
    if res := parse.parse(initial_settings_filename_fmt, filename):
        settings['initial'] = pixie16.read.load_settings(child)
    elif res := parse.parse(settings_filename_fmt, filename):
        datetime_str = res['date_time']
        settings[datetime.datetime.strptime(datetime_str, date_time_fmt)] = pixie16.read.load_settings(child)
    else:
        raise ValueError()

s = next(iter(settings.values()))
s.RealTime
