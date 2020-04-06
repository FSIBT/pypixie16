from setuptools import setup
from os import path
import versioneer


this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

with open("requirements.txt") as f:
    required = f.read().splitlines()

setup(
    name="pypixie16",
    version=versioneer.get_version(),
    description="Python library to control a pixie16 module from XIA",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://bitbucket.org/berkeleylab/pypixie16",
    author="Arun Persaud",
    author_email="apersaud@lbl.gov",
    license="modified BSD",
    packages=["pixie16"],
    install_requires=required,
    setup_requires=["pytest-runner"],
    tests_require=["pytest"],
    python_requires=">=3.6",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: BSD License",
        "Intended Audience :: Science/Research",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Topic :: Scientific/Engineering :: Physics",
    ],
    include_package_data=True,
    zip_safe=False,
)
