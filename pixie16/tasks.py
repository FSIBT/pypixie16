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
        self.start_time = time.time()

    def custom_init(self):
        file = Path(__file__).parent.parent / "tests/pixie16-data-01.bin"
        self.data = file.read_bytes()
        self.length = len(self.data)
        self.chunk_size = 20_000
        self.pos = 0
        if self.chunk_size > self.length:
            print("[ERROR] chunk_size too big")
        self.modules = [2, 8]
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
    """Task to aquire data, each binary blob from the FPGA will be put in the queue."""

    def custom_init(self):
        print("save settings")
        self.start_time = time.time()
        self.name = "Take Data"

        control.start_listmode_run()

    def do_work(self, value):
        return control.read_list_mode_fifo(threshold=64 * 1024)

    def cleanup(self):
        print("save settings")


class GatherData(Task):
    """Task to create larger data buckets out of the data directly from the FPGA."""

    def custom_init(self):
        self.data = defaultdict(list)
        self.maxsize = 10e6  # in bytes
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

    def do_work(self, value):
        self.mycounter += 1

        for i, data in enumerate(value):
            self.data[i].extend(data)

        data_size = max(sys.getsizeof(d) for d in self.data.values())
        if data_size > self.maxsize:
            # TODO: check if this is the correct way to flatten or if
            # we need to transpose
            out = {k: np.array(v).flatten() for k, v in self.data.items()}
            if self.save_binary:
                self.save_data(out)
            self.data = defaultdict(list)
            return out

    def cleanup(self):
        out = {k: np.array(v).flatten() for k, v in self.data.items()}
        if self.save_binary:
            self.save_data(out)
        if self.output_queue:
            self.output_queue.put(self.out)


class ConvertToEvents(Task):
    """Task to convert data stream to events"""

    def custom_init(self):
        read.buffer.clear()
        self.name = "Convert to events"

    def do_work(self, value_dict):
        out = []
        for v in value_dict.values():
            data = read.myIO(v.tobytes())
            # this is currenlty only workiong for a single
            # module... for multiple modules, we would need to have a
            # buffer for each module
            out += list(
                read.read_list_mode_data(
                    data, return_namedtuple=True, clear_buffer=False
                )
            )
        return out


class SortEvents(Task):
    """Task to sort events by timestamp."""

    def custom_init(self):
        self.data = []
        self.maxsize = 10_000
        self.N_to_sort = 8_000
        self.name = "Sort events"

    def do_work(self, value):
        self.data.extend(value)
        if len(self.data) > self.maxsize:
            out = self.data[: self.N_to_sort]
            self.data = self.data[self.N_to_sort :]
            out.sort(key=lambda x: x.timestamp)
            return out

    def cleanup(self):
        out = self.data
        out.sort(key=lambda x: x.timestamp)
        self.output_queue.put(out)
