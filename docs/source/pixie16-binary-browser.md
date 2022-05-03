pixie16-binary-browser
======================

A Qt-based program to show and explore the content of a binary file.

The program can be started on its own and a binary file can be loaded through the menu or a binary file can be specified on the command line. In the latter case, the program will parse the binary file and display a table of all the events showing all the available information for each event in the first tab.

Binary data tab
---------------

Displays all the events in a table. Furthermore, above the table a row of buttons will be added that can be used to show/hide certain channels. Below the table, some statistics are displayed, e.g. the number of events per channel and the file name.

![Image of main tab](/images/binary-browser-tab-1.jpg)


Trace tab
---------

You can select traces in the first tab and these will be then displayed over here. The program will create seperate plots for each channel.

MCA tab
-------

In the MCA tab, histograms of the energies for all events, seperated again by channel, are plotted.

Fast Trigger/CFD tab
--------------------

This allows playing with the Pixie16 configurtation settings, e.g. the FastTrigger Gap and Length, as well as the parameter for the energy. For this to work, the data must have traces enabled.
The program will use all selected events in the first tab, sort them by energy and then pick the 10% traces, e.g. 10%, 20%, 30%, ... and using these traces calculate the 'energy' or 'fast trigger' traces and also show the threshold for triggering or `peaksample` where the energies are read out. This allows for relative easy optimization of theses values.

Note: CFD is currently not supported but planned for future releases.

