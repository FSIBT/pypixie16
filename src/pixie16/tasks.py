"""A collection of tasks that can be used in a pipeline.

These tasks can also easily by sub-classed to create custom ones or
used as an example on how to write your own.

"""

from collections import defaultdict
from datetime import datetime
from importlib.resources import files
from pathlib import Path
import time
from typing import Optional, Union

import numpy as np
from rich import print

from .pipeline import Task
from . import control
from . import read


class DummyData(Task):
    """A class that will send dummy data into a pipeline.

    This can be used as a first task in a pipeline during testing and
    when the pixie16 is not online/available.

    """

    def __init__(self, runtime, filename=None):
        super().__init__()
        self.runtime = runtime
        self.filename = filename

        self.name = "Data generator"
        if filename is None:
            file = files("pixie16") / "data" / "pixie16-data-01.bin"
        else:
            file = Path(filename)
        self.data = np.fromfile(file, dtype=np.uint8)
        self.length = len(self.data)
        self.chunk_size = 20_000
        self.pos = 0
        if self.chunk_size > self.length:
            print("[red]ERROR[/] chunk_size too big")
        self.modules = [2]
        self.mycounter = 0

    def do_work(self, value):
        if time.time() - self.start_time > self.runtime:
            self.done = True
        time.sleep(0.2)
        self.mycounter += 1
        if self.pos + self.chunk_size < self.length:
            out = self.data[self.pos : self.pos + self.chunk_size]
        else:
            out = self.data[self.pos :]
            self.pos = 0
        self.pos += self.chunk_size
        ret = [out for m in self.modules]
        return ret


class TakeData(Task):
    """Example Task to aquire data, each binary blob from the FPGA will be put in the queue.

    A second task can then convert the binary blob to events and from
    there perhaps another task can convert to pandas.

    One tricky part is that we also need to initialize and boot the
    pixie, since this will run in another process. However, we cannot
    do this in the init, since the init will still be executed in the
    main thread, so this has to happen in `do_work`.

    We also check the runtime in `do_work` and then stop the process
    and end the run during the cleanup phase. We also read out the
    remaining events from the buffer and send them on during cleanup.

    """

    def __init__(self, runtime):
        super().__init__()
        self.name = "Take Data"
        # keep track if we called init
        self.started_acquisition = False
        self.start_time = None
        self.runtime = runtime

    def do_work(self, value):
        if not self.started_acquisition:
            control.init_and_boot(modules=[2], verbose=False, boot_pattern=0x7F)
            control.adjust_offsets()
            control.unset_sync_mode()  # assume only one module
            control.empty_all_fifos()
            # this would be a good spot to save the initial settings
            self.start_time = time.time()
            control.start_list_mode_run()

            self.started_acquisition = True

        now = time.time()
        if now - self.start_time > self.runtime:
            self.done = True
        return control.read_list_mode_fifo(threshold=64 * 1024)

    def cleanup(self):
        control.end_run()
        time.sleep(0.5)

        # read remainig data in queue
        tmp = control.read_list_mode_fifo(check=False)
        if tmp and self.output_queue:
            self.output_queue.put(tmp)

        # should save the settings and stats here


class SetDefaults(Task):
    """Set defaults for parameters in the pixie."""

    def __init__(self, modules: list):
        super().__init__()
        self.name = "Set defaults"
        self.modules = modules

    def do_work(self, value):
        self.done = True
        control.init_and_boot(modules=self.modules)
        for m, _ in enumerate(self.modules):
            control.set_defaults_for_module(m)


class GatherData(Task):
    """Task to create larger data buckets out of the data directly from the FPGA.

    It has two different buckets: one for sending data to the next queue
    and one for saving data to disk.
    """

    def __init__(self, maxsize=50e6, save_size=None, path=None):
        super().__init__()
        self.data_queue = defaultdict(list)
        self.data_disk = defaultdict(list)
        self.maxsize = maxsize  # in bytes
        self.save_size = save_size or maxsize
        self.save_binary = save_size is not None
        self.name = "Gather Data"
        self.mycounter = 0
        self.file_counter = 0
        self.path = path or Path(".")

    def save_data(self, out):
        timestamp = datetime.today().strftime("%Y-%m-%d-%H-%M-%S")
        for k, v in out.items():
            file = self.path / f"data-mod{k}-{timestamp}-{self.file_counter:05d}.bin"
            v.tofile(str(file))
        self.file_counter += 1

    def get_size(self, data):
        out = []
        for data_list in data.values():
            size = 0
            for element in data_list:
                size += element.nbytes
            out.append(size)
        if out:
            return max(out)
        return 0

    def do_work(self, value):
        self.mycounter += 1

        for i, data in enumerate(value):
            self.data_queue[i].append(data)
            self.data_disk[i].append(data)

        # handle data for saving
        data_size = self.get_size(self.data_disk)
        if data_size:
            self.send_status({"data disk size": data_size})
            if data_size > self.save_size:
                out = {k: np.concatenate(v) for k, v in self.data_disk.items() if v}
                if self.save_binary:
                    self.save_data(out)
                self.data_disk = defaultdict(list)

        # handle data for queue
        data_size = self.get_size(self.data_queue)
        self.send_status({"data queue size": data_size})

        if not data_size:
            return

        if data_size > self.maxsize:
            out = {k: np.concatenate(v) for k, v in self.data_queue.items() if v}
            self.data_queue = defaultdict(list)
            return out

    def cleanup(self):
        out_queue = {k: np.concatenate(v) for k, v in self.data_queue.items() if v}
        out_disk = {k: np.concatenate(v) for k, v in self.data_disk.items() if v}
        if out_queue:
            if self.output_queue:
                self.output_queue.put(out_queue)
        if out_disk:
            if self.save_binary:
                self.save_data(out_disk)


class ConvertToEvents(Task):
    """Task to convert data stream to events."""

    def __init__(self):
        super().__init__()
        self.list_mode_readers = {}
        self.name = "Convert to events"

    def do_work(self, value_dict):
        for i, v in value_dict.items():
            if i not in self.list_mode_readers:
                reader = read.StreamReader()
                self.list_mode_readers[i] = read.ListModeDataReader(reader)
            self.list_mode_readers[i].reader.put(v)
        return {mod: reader.pop_all() for mod, reader in self.list_mode_readers.items()}


class PickSingleModule(Task):
    """Task to pick events from a single module.

    Takes output from, e.g., ConvertToEvents and outputs only the data
    for a single module.
    """

    def __init__(self, module: int = 0):
        super().__init__()
        self.module = module
        self.name = f"Reduce to module {module}"

    def do_work(self, value):
        return value[self.module]


class SortEvents(Task):
    """Task to sort events by timestamp.

    This task, takes as input list of events that have already been
    converted from the binary format to namedtuples. It then populates
    an additionl column `chunk time` in the namedtuple which will
    roughly be the unix time stamp of the event. For a run that wasn't
    paused, the `chunk timestamp` will just be the normal time stamp
    plus the unix timestamp from the beginning of the run.

    The task will add incoming events to an internal list and once a
    certain number, M, of events has been reached, it will sort the
    events and send the first N off. Normally N<M, so that some events
    are held back since they might need to be sorted together with new
    events that will come in next.

    In case the event input stream comes from a run that has been
    paused and restarted, the timestamps in the event stream might
    have reset to start counting again at zero. However, we want the
    chunk time to be roughly the real time, so we have to add special
    code to handle this.

    For this to work, we detect whenever the timestamps go back to
    zero (our proxy for this is to test if the current event's timestamp
    is more than 20s before the last event, which should only happen
    if the counter did reset).

    We supply several options through the init variable
    `all_start_times` to handle the chunk time:

    1. `all_start_times` is None
       In this case, we just use the system time.time() for this event
       and calculate the following events `chunk time` by adding the
       delta t calculated from the pixie timestamp.
       This mode should be used during data acquisition.
       If one starts/stops the data acquisition, one should also write
       down all the start time, so that one can rerun the binary convertion
       later by using the next mode.
    2. `all_start_times` is a list of unix time stamps
       In this case, we use a value from the list whenever we notice a
       reset in the timestamps and otherwise handle delta t's as above.
       This mode can be used when binary data as to be converted again and
       the original time stamps should be recreated.
    3. `all_start_times` is a float > 0
       This mode can be used to estimate times when binary data needs to be
       converted again, but start times for b) are not available.
       In this case, we just ignore the negative dt at the point of
       the reset and keep adding positive dt to the `chunk time` and also
       add the value of `all_start_times` at the time of the reset. The value
       should be an estimate of how long it took between stopping and re-starting
       the data acquisition.

    """

    def __init__(
        self,
        start_time: float,
        maxsize: int = 10_000,
        number_to_sort: int = 8_000,
        all_start_times: Optional[Union[list[float], float]] = None,
    ):
        super().__init__()
        self.data = []
        assert (
            number_to_sort < maxsize
        ), "The number_to_sort needs to be smaller than maxisze"
        self.maxsize = maxsize
        self.N_to_sort = number_to_sort
        self.name = "Sort events"
        self.nr_sorted = 0
        # unix time of start of the current list mode run. Either the
        # timestamp of the first events or the time stamp of the last
        # detected reset
        self.start_time = start_time
        # timestamp of first and current event in binary data in s
        self.first_event_timestamp = None
        self.last_event_timestamp = 0
        # in case the the aqcuisition was stopped and restarted this
        # should either be a list of all start times or a float
        # estimating the average time of the break in acquisitioin
        self.all_start_times = all_start_times
        # if all_start_times are not known, we estimate them and report them back
        # if a special queue was put in place
        self.report_times = [start_time]
        self.report_time_queue = None
        # keep track how many resets we have detected
        self.number_of_resets = 0

    def do_work(self, events_lst):
        """Does the sorting, time reset recognition and handling.

        Whenever we reach `self.maxsize` events, sort them by time and
        pass the first `self.N_to_sort` events to the next `Task`. We keep
        the a few events behind, since they might need to be sorted with
        the next incoming batch.

        """
        new_events_lst = []
        if self.first_event_timestamp is None and events_lst:
            self.first_event_timestamp = events_lst[0].timestamp * 1e-9
        for event in events_lst:
            ts = event.timestamp * 1e-9  # in s
            if ts + 20 < self.last_event_timestamp:
                # detected a reset of the FPGA counter on the pixie16
                self.number_of_resets += 1
                if self.all_start_times is None:
                    self.start_time = time.time()
                elif isinstance(self.all_start_times, (list, tuple)):
                    if self.number_of_resets >= len(self.all_start_times):
                        print(
                            "[red]ERROR[/] SortEventTask: detected more list mode starts than given timestamps. Estimating time offset"
                        )
                        self.start_time += (
                            self.last_event_timestamp - self.first_event_timestamp
                        ) + 35  # estimate of time of break
                    else:
                        self.start_time = self.all_start_times[self.number_of_resets]
                elif isinstance(self.all_start_times, (int, float)):
                    self.start_time += (
                        self.last_event_timestamp - self.first_event_timestamp
                    ) + self.all_start_times
                    self.report_times.append(self.start_time)
                else:
                    print(
                        "[red]ERROR[/] unknown type for all_start_times in SortEvents... cannot continue!!! "
                    )
                self.first_event_timestamp = ts
            event.chunk_timestamp = self.start_time + ts - self.first_event_timestamp
            new_events_lst.append(event)
            self.last_event_timestamp = ts

        # Sort events according to UNIX timestamp
        out = []
        self.data.extend(new_events_lst)
        while len(self.data) > self.maxsize:
            self.data.sort(key=lambda x: x.chunk_timestamp)
            out = self.data[: self.N_to_sort]
            self.data = self.data[self.N_to_sort :]
            if out and self.output_queue:
                self.output_queue.put(out)
                self.nr_sorted += 1
        self.send_status({"sorted blocks": self.nr_sorted})

    def cleanup(self):
        self.data.sort(key=lambda x: x.chunk_timestamp)
        if self.output_queue:
            self.output_queue.put(self.data)
        if self.report_time_queue:
            self.report_time_queue.put(self.report_times)
        self.data = []


class GatherEvents(Task):
    """Gather Events into larger chunks."""

    def __init__(self, size=1_000_000):
        super().__init__()
        self.data = []
        self.size = size
        self.nr = 0
        self.name = f"Gather events (size={size})"

    def do_work(self, value):
        self.data.extend(value)
        if len(self.data) > self.size:
            out = self.data
            self.data = []
            self.nr += 1
            return out

        self.send_status({"gathered events": self.nr, "gathered queue": len(self.data)})

    def cleanup(self):
        if self.output_queue and self.data:
            self.output_queue.put(self.data)
        self.data = []
        self.nr += 1
        self.send_status({"gathered events": self.nr, "gathered queue": len(self.data)})


class LoadFiles(Task):
    """Load events from a list of files,"""

    def __init__(self, file_list, batch_size=1_000):
        super().__init__()
        self.files = file_list
        self.byte_stream = read.FileReader(self.files)
        self.byte_stream.open_files()
        self.buffer_size = 1_000_000
        self.reader = read.ListModeDataReader(self.byte_stream)
        self.number_of_events_to_read = batch_size
        self.nr_of_events = 0
        self.name = "Loading binary data from files"

    def cleanup(self):
        self.byte_stream.close_files()

    def do_work(self, value):
        try:
            events = []
            for _ in range(self.number_of_events_to_read):
                event = None
                try:
                    event = self.reader.pop()
                except read.EmptyError:
                    self.done = True
                    break
                except read.LeftoverBytesError:
                    self.done = True
                    print(f"[red]ERROR[/] Left over Bytes in files")
                    break
                events.append(event)
            if events and self.output_queue:
                self.output_queue.put(events)
                self.nr_of_events += len(events)
                events = []
        except StopIteration:
            self.done = True
            if events and self.output_queue:
                self.output_queue.put(events)
                self.nr_of_events += len(events)
                events = []

        self.send_status(
            {
                "read events": f"{self.nr_of_events:.2e}",
                "runtime": self.byte_stream.current_file,
            }
        )
