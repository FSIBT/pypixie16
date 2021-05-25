# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project tries to adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

