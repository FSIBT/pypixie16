Welcome to pixie16's documentation!
===================================

Pypixie16 is an open-source python package that allows the control of
`XIA`_'s `Pixie-16`_ 16-channel PXI Digital Pulse Processor.

For controlling the data acquisition the package provides an interface
to XIA's C-library that needs to be available for the package to
function. Furthermore, for controlling the instrument, a 32-bit python
needs to be used, since the C-libraries are 32-bit only.
This library provides some low level adapters to the C-library, as
well as, some higher level function and classes to make data
acquisition more pythonic and easy.

To acuire data a multiprocessing pipeline can be created easily that
will take binary data and transform it for example to pandas
dataframes.

Furthermore, the library also provides methods to read settings file,
and binary data. These work on either 32-bit or 64 bit platforms.

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
.. _Pixie-16: https://xia.com/dgf_pixie-16.html
