"""
Usage:
  change_setting.py set <name> <value> <module> <channel> <file> [<outfile>]
  change_setting.py read <name> <module> <file>
  change_setting.py load <file>
  change_setting.py list

"""

import docopt

commands = docopt.docopt(__doc__)
# print(commands)

name = commands["<name>"]
value = commands["<value>"]
module = commands["<module>"]
channel = commands["<channel>"]

# slots in the crate that have pixie16 cards
SLOTS = [2]
modules = [0]

import pixie16
import pixie16.control
import sys
import time
from pathlib import Path

settingfile = Path(commands["<file>"])
# r'E:\ROOTS\XIA-pulse-shape\2019-04-08-API-Cblock0013.set'
outfile = Path(commands["<outfile>"])

if commands["set"]:
    if not name in pixie16.variables.settings:
        print(f"name {name} not a valid settings name")
        sys.exit(1)

    value = int(value)
    if "-" in channel:
        start, stop = channel.split("-")
        channel = list(range(int(start), int(stop) + 1))
    else:
        channel = [int(channel)]
    module = int(module)

    if outfile:
        out = Path(outfile)
        if out.exists():
            print("Error: outfile exists already")
            sys.exit(2)

    pixie16.control.init_and_boot(
        offline_mode=False,
        section_name="default",
        modules=SLOTS,
    )
    settings = pixie16.control.read_settings_from_file(settingfile)
    for c in channel:
        pixie16.control.change_setting(settings, name, value, c, module)
    pixie16.control.write_settings(settings)
    if outfile:
        pixie16.control.save_dsp_parameters_as_json(outfile)
    pixie16.control.exit_system()

elif commands["read"]:
    if not name in pixie16.variables.settings:
        print(f"name {name} not a valid settings name")
        sys.exit(1)

    module = int(module)

    pixie16.control.init_and_boot(
        offline_mode=False,
        section_name="default",
        modules=SLOTS,
    )
    pixie16.control.load_dsp_parameters_from_file(settingfile)
    A = pixie16.control.read_settings_from_file(module)
    offset, nr = pixie16.variables.settings[name]
    print(f"Name: {name}")
    if nr > 1:
        print(f"Channel, value")
        for i in range(nr):
            print(f"    {i}  {A[offset+i]}")
    else:
        print(f"Module setting")
        print(f"      {A[offset]}")

    pixie16.control.exit_system()

elif commands["load"]:
    print(f"Loading settingfile {settingfile}")
    pixie16.control.init_and_boot(
        offline_mode=False,
        section_name="default",
        modules=SLOTS,
    )
    pixie16.control.load_dsp_parameters_from_file(settingfile)
    pixie16.control.exit_system()

elif commands["list"]:
    for n in sorted(pixie16.variables.settings):
        print(n)
