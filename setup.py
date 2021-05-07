from setuptools import setup
from os import path


this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="pypixie16",
    description="Python library to control a pixie16 module from XIA",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://bitbucket.org/berkeleylab/pypixie16",
    author="Arun Persaud",
    author_email="apersaud@lbl.gov",
    license="BSD-3-Clause-LBNL",
    packages=["pixie16"],
    install_requires=[
        "appdirs",
        "cbitstruct",
        "docopt",
        "fast-histogram",
        "matplotlib",
        "more_itertools",
        "numpy",
        "pandas",
        "PyQt5",
        "sphinx",
        "sphinxcontrib-napoleon",
    ],
    scripts=["pixie16-parameter-scan", "pixie16-binary-browser", "pixie16-coincidence"],
    setup_requires=["pytest-runner"],
    tests_require=["pytest"],
    python_requires=">=3.7",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "License :: OSI Approved :: BSD License",
        "Intended Audience :: Science/Research",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Topic :: Scientific/Engineering :: Physics",
    ],
    include_package_data=True,
    zip_safe=False,
)
