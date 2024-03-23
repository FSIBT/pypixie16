# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project tries to adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.0] - 2024-03-23

The main change it a new and improved list mode data reader.

### Changed
- switched from pk_resources to importlib.metadata
- switched from setup.cfg to pyproject.toml
- removed setup.py
- changed source layout to move package into src/ directory
- updated copyright year
- updated minimum requirement to python >= 3.9 and run py-update
  (mostly because of numpy)
- Support pixie16 SDK 4.0.0
- Improved list mode data reader (faster and code refactoring)

### Fixed
- fix loading of default settings
- fix binary-browser: qt5->qt6 transition
- fix binary-browser: loading list mode data
- fix pyproject.toml urls to work better with PyPi
- fix streaming dummy data

## [2.0.0] - 2023-02-18

Mostly small changes, the main reason for the 2.0.0 release is the update to
pyqt6 which can break user interfaces.

### Changed
- Updated Qt widgets to PyQt6
- switch to platformdirs (on mac the user config location changes, so we
  still keep appdirs around and move files to the new location)
- updated versions used by pre-commit
- use rich more to format output

### Added
- Added py.typed marker file for better type hint support
- error check when loading settings files
- new functions that takes list of events and returns a dictionary with lists
  sorted by channel number

### Fixed
- When sorting raw events in a data pipeline, fix handling of event
  timestamps (e.g. set timestamp to the approximately correct time in
  unix-time). Ability to handle data that got taken from several runs,
  e.g. list mode runs that get interrupted by MCA runs where the FPGA
  counter for the time gets reset

## [1.0.0] - 2022-07-26

### Changed
- Renamed 'master' branch to 'main'
- The library does not keep track of the boot or init status anymore
- Swapped out tqdm for rich for better terminal support
- Only load C-library when needed (useful if, e.g., looking at binary
  data on a different computer without the C-library installed)
- `change_setting_from_dict` now calls `write_single_parameter` and therefore
  also does checks and other side effects (e.g. set Peaksample). If you want
  to overwrite these values and avoid checks/side-effects, use `change_raw_setting_from_dict`
- Moved command line scripts into pixie16/cli and use entry points for installation

### Added
- Support for new SDK from XIA (>= 3.3). In the process we made some
  function names more pythonic and clearer and added better
  documentation. One big change is the way settings files are saved
  now (two instead of one and the format changed from binary to json)
- Quick way to run a whole pipline (by calling .execute())

### Removed
- Support for old XIA library (Some low level functions also got removed)

### Fixed
- Building of docs
- Reading of binary data when traces are enabled.

## [0.7] - 2022-01-29
### Added
- Function that empties the FIFO
- pipeline & tasks: add names to some predefined tasks
- binary browser: captures some more errors when calculating fast_triggers

### Changed
- remove unused argument from `start_listmode_run`

### Fixed
- fix type in `ListModeDataReader`
- pipeline & tasks: fix status updates
- building docs (missing mock for cbitstruct)

## [0.6] - 2021-05-25
### Added
- added 1d and 2d parameter scan functionality
- added a Qt-based browser for binary files: pixie16-binary-browser
- added a Qt-based program to test/plot coincidence conditions: pixie16-coincidence
- add python 3.9 to setup.py
- pyproject.toml for black, pylint, and setuptools_scm config
- config.py: path to firmware, etc
- control.py: more high level functions to run data acquisition
- pipeline.py/tasks.py: multiprocess classes to run data acquisition pipeline in parallel
- updated tests, e.g., for code in pixie16/analysis.py and new settings and list-data reader

### Changed
- dropped python 3.6 (since we are using dataclasses, a 3.7 feature)
- replaced datashader with fast-histograms to speed up import
- switched to setuptools_scm
- moved low level C-library interface to their own files
- lots of cleanup across the code base
- replaced read_list_mode_data and reading of settings with new implementation.
  Settings can now be read with units using `pint` which makes transforming of units easier.
- updated documentation

## [0.5] - 2020-04-06
### Added
- added this CHANGELOG.md
- when plotting MCA spectra add option to rebin
- add python 3.8 to setup.py

### Changed
- fixed missing parameters in control.py
- fixed up more doc-strings
- fixed calculations of L for internal filters
- code cleanup (flake8)
- fixed plotting of energy sums
- add missing close statements to matplotib figures
- read_list_mode_data: allow strings for file name instead of only Path objects

