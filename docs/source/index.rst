Welcome to pypixie16's documentation!
=====================================

Pypixie16 is an open-source python package that allows the control of
`XIA`_'s `Pixie16`_ 16-channel PXI Digital Pulse Processor.

For controlling the Pixie16 the package provides an interface
to XIA's C-library `SDK`_ that needs to be installed and compiled for
the package to function. This python library provides all functions of
the C-library as python functions, as well as, some higher level
functions and classes to make data acquisition more pythonic and easy.
Furthermore, this module also provides some Qt user interfaces to
browse binary data files and helper functions to analyze data and tune parameters.

Pypixie16 has been tested using the 64-bit version of XIA's library (>=3.3)
complied with Visual Studio 2022 on Windows.

To acquire data a multiprocessing pipeline can be created easily that
will take binary data and transform it, for example, to pandas
dataframes.

Furthermore, the library also provides methods to read settings file (old style and new),
and binary data.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   getting_started
   pixie16
   contributing

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`


.. _XIA: https://xia.com/
.. _Pixie16: https://xia.com/dgf_pixie-16.html
.. _SDK: https://docs.pixie16.xia.com/
