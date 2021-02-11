from datetime import datetime
from pathlibe import Path
import sys
import time

import numpy as np

from .pipeline import Task
from . import control
from . import read


class TakeData(Task):
    """Task to aquire data, each binary blob from the FPGA will be put in the queue."""

    def custom_init(self):
        print("save settings")
        self.start_time = time.time()
        control.start_listmode_run()

    def do_work(self, value):
        return control.read_list_mode_fifo(threshold=64 * 1024)

    def cleanup(self):
        print("save settings")


class GatherData(Task):
    """Task to create larger data buckets out of the data directly from the FPGA."""

    def custom_init(self):
        self.data = []
        self.maxsize = 10e6  # in bytes
        self.save_binary = False

    def do_work(self, value):
        self.data.extend(value)
        if sys.getsizeof(self.data) > self.maxsize:
            # TODO: check if this is the correct way to flatten or if
            # we need to transpose
            out = np.array(self.data).flatten()
            if self.save_binary:
                timestamp = datetime.today().strftime("%Y-%m-%d-%H-%M-%S")
                i = 0
                file = Path(f"data-{timestamp}-{i:03d}.bin")
                while file.exists():
                    i += 1
                    file = Path(f"data-{timestamp}-{i:03d}.bin")
                    if i > 999:
                        print("[ERROR] GatherData Task: too many binary files")
                        break
                out.tofile(str(file))
            self.data = []
            return out

    def cleanup(self):
        self.output_queue.put(self.data)


class ConvertToEvents(Task):
    """Task to convert data stream to events"""

    def custom_init(self):
        read.buffer.clear()

    def do_work(self, value):
        data = read.myIO(value.tobytes())
        out = list(
            read.read_list_mode_data(data, return_namedtuple=True, clear_buffer=False)
        )
        return out


class SortEvents(Task):
    """Task to sort events by timestamp."""

    def custom_init(self):
        self.data = []
        self.maxsize = 10_000
        self.N_to_sort = 8_000

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
