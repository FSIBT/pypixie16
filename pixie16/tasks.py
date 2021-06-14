from collections import defaultdict
from datetime import datetime
from pathlib import Path
import sys
import time

import numpy as np

from .pipeline import Task
from . import control
from . import read


class DummyData(Task):
    def __init__(self, runtime, filename=None):
        super().__init__()
        self.runtime = runtime
        self.filename = filename

        self.name = "Data generator"
        if filename is None:
            file = Path(__file__).parent.parent / "tests/pixie16-data-01.bin"
        else:
            file = Path(filename)
        self.data = np.fromfile(file, dtype=np.uint8)
        self.length = len(self.data)
        self.chunk_size = 20_000
        self.pos = 0
        if self.chunk_size > self.length:
            print("[ERROR] chunk_size too big")
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
    """Task to aquire data, each binary blob from the FPGA will be put in the queue.

    Note: this does not work as is. The Task must also call InitSys
    and BootModule to be able to talk to the pixie16.

    """

    def __init__(self):
        super().__init__()
        print("save settings")
        self.name = "Take Data"

        control.start_listmode_run()

    def do_work(self, value):
        return control.read_list_mode_fifo(threshold=64 * 1024)

    def cleanup(self):
        print("save settings")


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
            i = 0
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
    """Task to convert data stream to events"""

    def __init__(self):
        super().__init__()
        self.list_mode_readers = {}
        self.name = "Convert to events"

    def do_work(self, value_dict):
        for i, v in value_dict.items():
            if i not in self.list_mode_readers:
                self.list_mode_readers[i] = read.ListModeDataReader()
            self.list_mode_readers[i].put(v.tobytes())
        return {mod: reader.pop_all() for mod, reader in self.list_mode_readers.items()}


class PickSingleModule(Task):
    """Task to pick events from a single module.

    Takes output from, e.g., ConvertToEvents and outputs only the data for a single module.
    """

    def __init__(self, module=0):
        super().__init__()
        self.module = module
        self.name = f"Reduce to module {module}"

    def do_work(self, value):
        return value[self.module]


class SortEvents(Task):
    """Task to sort events by timestamp."""

    def __init__(self, maxsize=10_000, number_to_sort=8_000):
        super().__init__()
        self.data = []
        assert (
            number_to_sort < maxsize
        ), "The number_to_sort needs to be smaller than maxisze"
        self.maxsize = maxsize
        self.N_to_sort = number_to_sort
        self.name = "Sort events"
        self.nr_sorted = 0

    def do_work(self, value):
        out = []
        self.data.extend(value)
        while len(self.data) > self.maxsize:
            self.data.sort(key=lambda x: x.timestamp)
            out = self.data[: self.N_to_sort]
            self.data = self.data[self.N_to_sort :]
            if out and self.output_queue:
                self.output_queue.put(out)
                self.nr_sorted += 1
        self.send_status({"sorted blocks": self.nr_sorted})

    def cleanup(self):
        self.data.sort(key=lambda x: x.timestamp)
        if self.output_queue:
            self.output_queue.put(self.data)
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
        self.byte_stream = read.FilesIO(self.files)
        self.buffer_size = 1_000_000
        self.reader = read.ListModeDataReader()
        self.number_of_events_to_read = batch_size
        self.nr_of_events = 0
        self.name = "Loading binary data from files"

    def do_work(self, value):
        try:
            events = []
            for i in range(self.number_of_events_to_read):
                event = None
                try:
                    event = self.reader.pop()
                except (read.LeftoverBytesError, read.EmptyError):
                    if not self.byte_stream.is_empty():
                        self.reader.put(self.byte_stream.pop(self.buffer_size))
                        continue
                    else:
                        self.done = True
                        break
                events.append(event)
            if events and self.output_queue:
                self.output_queue.put(events)
                self.nr_of_events += len(events)
        except StopIteration as e:
            self.done = True

        self.send_status(
            {
                "read events": f"{self.nr_of_events:.2e}",
                "runtime": self.byte_stream.current_file_index,
            }
        )
