# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project tries to adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Python 3.14 added to CI
- new pixie16-scope: live view of data and ability to replay binary data files
- Tests: synthetic event tests, API coverage, and benchmarks for list-mode reader
- Pipeline: persistent tasks with ZMQ-based communication
- Pipeline: comprehensive status reporting with memory usage and CPU tracking
- Pipeline: heartbeat monitoring and error propagation
- Tasks: new DummyData and TakeData tasks for testing
- pixie16-daq: new Qt-based GUI application for data acquisition with
  pipeline management and real-time status monitoring
- Settings class now stores the original values, but uses the
  same values as used when settings values using a dict, e.g., units
  for times are in us, instead of raw FPGA values.
- When comparing settings, you can now compare either the derived
  values or the raw values.
- Ability to redirect logfile to a directory using an environmental
  variable (`PIXIE16_LOG_DIR`) or a "Logging"->"logdir" entry in the
  config file
- Function `data_rate_from_file` to get data rate in MB/s
- Function `timestamps_and_sizes_from_files_generator` for efficient event scanning

### Changed
- The repository moved from Bitbucket to https://github.com/FSIBT/pypixie16
- CI now runs on GitHub Actions and releases are published on `v*` tags
- List mode reader performance: 4.25x faster (51K → 217K events/sec)
- Updated copyright year to 2026
- Updated author list in pyproject.toml
- Switched to using ruff instead of pyupgrade and black
- Minimum python required: 3.10 (to stay in sync with numpy)
- Update for numpy 2.0: numpy.ndarray no longer uses newbyteorder directly
- Better error message if binary files are loaded out of order
- DataAcquisition UI: improved layout and status display
- Pipeline: refactored with better error handling and task lifecycle management
- Tasks: improved queue management and status reporting frequency

### Fixed
- Handling of output file numbering in `run_list_mode`
- Don't remove channels variable when using `change_setting_from_dict`
- ListModeDataReader in combination with Streamreader could get stuck
  when only a partial event was in the buffer that was longer than 4
  words
- Comparing settings did not print second value
- Progress bar display when taking MCA data with `take_MCA_spectra`
- Switch from docopt to docopt-ng

### Removed
- Dependency on bitstruct and cbitstruct packages

## [3.1.0] 2025-02-15

### Added
- Added config settings to set up multiplicity and coincidences
  easier, e.g. without binary encoding
- Added documentation on how to change settings and take data

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

