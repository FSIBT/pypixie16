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
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime

        file = Path(__file__).parent.parent / "tests/pixie16-data-01.bin"
        self.data = file.read_bytes()
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
            self.pos = 0
            out = self.data[self.pos : self.pos + self.chunk_size]
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
    """Task to create larger data buckets out of the data directly from the FPGA."""

    def __init__(self):
        super().__init__()
        self.data = defaultdict(list)
        self.maxsize = 50e6  # in bytes
        self.save_binary = False
        self.name = "Gather Data"
        self.mycounter = 0

    def save_data(self, out):
        timestamp = datetime.today().strftime("%Y-%m-%d-%H-%M-%S")
        for k, v in out.items():
            i = 0
            file = Path(f"data-mod{k}-{timestamp}-{i:03d}.bin")
            while file.exists():
                i += 1
                file = Path(f"data-mod{k}-{timestamp}-{i:03d}.bin")
                if i > 999:
                    print("[ERROR] GatherData Task: too many binary files")
                    break
            v.tofile(str(file))

    def get_size(self):
        out = []
        for data_list in self.data.values():
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
            self.data[i].append(data)

        data_size = self.get_size()
        if not data_size:
            return

        self.send_status({"data size": data_size})

        if data_size > self.maxsize:
            # TODO: check if this is the correct way to flatten or if
            # we need to transpose
            out = {k: np.concatenate(v) for k, v in self.data.items() if v}
            if self.save_binary:
                self.save_data(out)
            self.data = defaultdict(list)
            return out

    def cleanup(self):
        out = {k: np.concatenate(v) for k, v in self.data.items() if v}
        if out:
            if self.save_binary:
                self.save_data(out)
            if self.output_queue:
                self.output_queue.put(out)


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
        self.module = 0

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

    def do_work(self, value):
        out = []
        self.data.extend(value)
        self.send_status({"sort queue": len(self.data)})
        while len(self.data) > self.maxsize:
            self.data.sort(key=lambda x: x.timestamp)
            out = self.data[: self.N_to_sort]
            self.data = self.data[self.N_to_sort :]
            if out and self.output_queue:
                self.output_queue.put(out)

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
                "read events": self.nr_of_events,
                "runtime": self.byte_stream.current_file_index,
                "file": self.byte_stream.current_file_index,
            }
        )
