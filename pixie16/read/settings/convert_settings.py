#!/usr/bin/env python3
"""
Usage:
  convert_settings.py FILENAME [MODULE_LIST ...]
  convert_settings.py -h | --help

Arguments:
  FILENAME        Name of .set settings file to be converted
  MODULE_LIST     List of modules of interest

Options:
  -h --help     Show this screen.

Example:
  python convert_settings.py my_settings.set 0 2 3

The program converts a .set settings file to a .json settings file.
"""

import docopt
from pixie16.read.settings.old_settings_class import convert_old_settings

docopt_args = docopt.docopt(__doc__)

# Parse command line
filename = docopt_args["FILENAME"]
mod_list = docopt_args["MODULE_LIST"]
mod_list = list(map(int, mod_list))

set_filename, stat_filename = convert_old_settings(filename, mod_list)
