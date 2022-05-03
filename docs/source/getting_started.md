# Getting started

## Installation

Pypixie16 is available on [PyPi](https://pypi.org/project/pypixie16/)
and can therefore easily be installed using pip.

```
pip install pypixie16
```

or updated

```
pip install -U pypixie16
```


Alternatively you can also install clone the git repository using
```
git clone https://bitbucket.org/berkeleylab/pypixie16.git
```

You can then install the module in developer mode using
```
pip install -e .
```
from within the git repository.

If you want to run tests or build the docs locally, you need to add
these as extras during the pip install:
```
pip install -e ".[test,docs]"
```


## Configuration

To use it the module for data acquisition and talking to the Pixie16,
you need to let pypixie16 know where the C-library files are
located. We store this information in a `config.ini` file in the
appropiate directory depending on the operating system. If it doesn't
exist, the module will let you know the path and content for the file.

As an example, the following config file sets all the required variables:
```
[Libraries]
sdk = c:\Users\experiment\pixie16-software\PixieAppDll.dll

[Data]
datadir = c:\Users\experiment\data

[Firmware.default]
ComFPGAConfigFile = c:\Users\experiment\pixie16-software\syspixie16
SPFPGAConfigFile = c:\Users\experiment\pixie16-software\fippixie16
DSPCodeFile = c:\Users\experiment\pixie16-software\Pixie16DSP.ldr
DSPVarFile = c:\Users\experiment\pixie16-software\Pixie16DSP.var
SettingFile = c:\Users\experiment\default-setting-file.json
```

Apart from the path to the library, the config file also includes the
path to the firmware that should be used (here multiple configuration
can be saved by using "Firmware.\<name\>" as additional header and the
path to where the data should be stored.

## Using the module

Once installed, the modules can be imported using
```
import pixie16
```
