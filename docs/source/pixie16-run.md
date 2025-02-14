# Taking data

Pypixie16 provides several ways to take data.

Normally, the following steps need to be taken:

- initialize using `pixie16.control.init_and_boot()`
- change settings (see previous section)
- set run time `pixie16.control.set_run_time(...)`
- take histogram or list mode data using 'pixie16.control.start_histogram_run()' or
  `pixie16.control.start_list_mode_run()`
- for list mode runs: have a for loop to check runtime and status and download and save data. Pypixie16 also provides `pixie16.control.run_list_mode()` and `pixie16.control.take_list_mode_data()` for this use case.
- for histograms one can also use `pixie16.control.take_MCA_spectra()`
- save settings and stats using `pixie16.control.save_dsp_parameters_as_json()` and `pixie16.control.save_stats_to_file()`
- end the run `pixie16.contro.end_run()
- finally one can also exit the system completely using `pixie16.control.exit_system()`

It is worth browsing `pixie16.control` to see what other functions are provided to make this easier.
Examples can be seen in the exectubales, for example, `pixie16.cli.parameter_scan`

## More complex scenarios

If the data needs to be operated on while taking data, for example,
finding channels in list mode data that belong to a single coincidence
event and generate custom plots in live mode, pypixie16 provides data
pipelines in `pixie16.pipeline`. Here, single tasks can be defined and put together into a
data pipeline. Data can be easily moved from one tasks to the next and
each tasks runs in a separate process to parallelize operation and to
not impeded the rate at which data is taken.

Pypixie16 comes already with some predifined tasks in `pixie16.tasks`. These include:

* taking data
* providing dummy data from a file (no Pixi16 needed), this is useful for debugging
* saving data to disk in larger chunks
* convert list mode data to python structures
* sort events by time and add a UTC time stamp from the local computer



