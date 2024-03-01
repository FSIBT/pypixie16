# PyPixie16

[![Docs](https://readthedocs.org/projects/pypixie16/badge/?version=latest&style=plastic)](https://readthedocs.org/projects/pypixie16)
[![PyPI version](https://badge.fury.io/py/pypixie16.svg)](https://badge.fury.io/py/pypixie16)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)


This module can be used to control, read, and analyze data from
Pixie16 modules from XIA [https://www.xia.com/DGF_Pixie-16.html] using python. To achieve this we provide
cytpes interface to the C-libraries provided by XIA. These libraries
need to be downloaded and installed from XIA-website for these python
modules to run.

We use a config.ini file to let the python file know where those
libraries can be found. If this file doesn't exist, the program will
prompt you with instructions on how to create one.

# Licence and Copyright

See Licence.txt and Copyright.txt for more information.

# Installation

You can install the package using

   pip install pypixie16

or after you cloned the repository and are inside the repo,

   pip install .

or

   pip install -e .

If you want to run tests, you should specify

   pip install .[test]

If you want to build the documentation

   pip install .[docs]

If you want to speed up binary parsing, you should install the `cbitstruct` library or use

   pip install .[fast]

# Documentation

Documentation is hosted on Read The Docs: https://readthedocs.org/projects/pypixie16/

# Known issues

We use revision F of the 500 MHz Pixie16 and the code has only been
tested for this module. It probably can be easily adapted for other
modules or even might work, but there is no garantee.

We also always use certain settings for some parameters and these
might also influence some of the analysis code (e.g. FastFilterRange).

# Tests

We should have a lot more of them ;)

Use

   python -m pytest

to run tests.

# Contribution

Pull requests are welcome.

We use black to format the code. Once you cloned the repo, please run

   pip install pre-commit

and

   pre-commit install

# Other libraries to control the pixie16 (non-python)

## Experimental Low Energy Nuclear Science Group at University of Tennessee

https://github.com/pixie16

## Fork of pixie16

https://github.com/spaulaus/paass-lc

## Peking University

https://github.com/pkuNucExp/PKUXIADAQ



