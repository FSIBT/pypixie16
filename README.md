# PyPixie16

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

# Known issues

We use revision F of the 500 MHz Pixie16 and the code has only been
tested for this module. It probably can be easily adapted for other
modules or even might work, but there is no garantee.

We also always use certain settings for some parameters and these
might also influence some of the analysis code (e.g. FastFilterRange).

# Contribution

Pull requests are welcome.

# Other libraries to control the pixie16 (non-python)

## Experimental Low Energy Nuclear Science Group at University of Tennessee

https://github.com/pixie16

## fork of pixie16

https://github.com/spaulaus/paass-lc
## Peking University

https://github.com/pkuNucExp/PKUXIADAQ



