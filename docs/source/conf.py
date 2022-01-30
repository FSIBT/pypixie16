# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys

sys.path.insert(0, os.path.abspath("../.."))
on_rtd = os.environ.get("READTHEDOCS") == "True"

# ctypes doesn't seem to work with autodoc_mock_imports...and we have
# to manually import it so that it doesn't try to import the dll
from unittest.mock import MagicMock


class Mock(MagicMock):
    @classmethod
    def __getattr__(cls, name):
        return MagicMock()


MOCK_MODULES = [
    "ctypes",
]
sys.modules.update((mod_name, Mock()) for mod_name in MOCK_MODULES)

# for all other libraries we can let autodoc know to mock them.
autodoc_mock_imports = [
    "cbitstruct",
    "fast_histogram",
    "numpy",
    "pandas",
    "pint",
    "matplotlib",
    "tqdm",
    "PyQt5",
]
# -- Project information -----------------------------------------------------

project = "pixie16"
copyright = "2019-2022, The Regents of the University of California through Lawrence Berkeley National Laboratory (subject to receipt of any required approvals from the U.S. Dept. of Energy). All rights reserved"
author = "Arun Persaud et al."

# The full version, including alpha/beta/rc tags
from pkg_resources import get_distribution, DistributionNotFound

try:
    release = get_distribution("pixie16").version
except DistributionNotFound:
    release = "unkown"

# -- General configuration ---------------------------------------------------

# seems to be needed for RTD
master_doc = "index"

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = ["sphinx.ext.autodoc", "sphinx.ext.napoleon"]

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "alabaster"

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

from recommonmark.parser import CommonMarkParser


class CustomCommonMarkParser(CommonMarkParser):
    def visit_document(self, node):
        pass


def setup(app):
    app.add_source_parser(CustomCommonMarkParser)
