import pathlib

from .. import task
import datetime
from collections import defaultdict
import numpy as np


class GatherData(task.Task):
    """
    Creates larger data buckets out of the data directly from the FPGA.

    It has two buckets for (1) sending data to the next queue and (2) saving
    data to disk.
    """

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
                # Handle different data types safely
                if hasattr(element, "nbytes"):
                    size += element.nbytes
                elif np.isscalar(element):
                    # For scalar values, estimate size
                    size += 8  # Assume 8 bytes for a scalar
                elif isinstance(element, int | float):
                    size += 8  # 8 bytes for numeric types
                else:
                    # For other types, try to get size or use a default
                    try:
                        size += len(element) * 8  # Estimate
                    except:
                        size += 8  # Default fallback
            out.append(size)
        if out:
            return max(out)
        return 0

    def do_init(self):
        """
        Initialzies the task.

        Note:
            This method extends ``Task.do_init``.
        """

        self.mycounter = 0
        self.file_counter = 0

        # Initialize data structures here instead of in do_configure
        self.data_queue = defaultdict(list)
        self.data_disk = defaultdict(list)

        self.config = {
            "binary_save_size": 50e6,  # file size
            "binary_size": 5e6,  # to next Task
            "binary_save_path": pathlib.Path("."),
            "binary_save_data": True,
        }
        self.path = pathlib.Path(self.config.get("binary_save_path", "."))

    def do_configure(self, config: dict):
        """
        Configures the task.

        Note:
            This method extends ``Task.do_configure``.
        """

        # Getting configuration fields.
        self.binary_save_size = config.get(
            "binary_save_size", self.config["binary_save_size"]
        )
        self.binary_size = config.get("binary_size", self.config["binary_size"])
        self.binary_save_path = config.get(
            "binary_save_path", self.config["binary_save_path"]
        )
        self.binary_save_data = config.get(
            "binary_save_data", self.config["binary_save_data"]
        )

        # Only reset data structures if explicitly requested
        if config.get("reset_data_structures", False):
            from collections import defaultdict

            self.data_queue = defaultdict(list)
            self.data_disk = defaultdict(list)

    def do_work(self, value):
        """
        Works for the task.

        Note:
            This method extends ``Task.do_work``.
        """

        self.mycounter += 1

        for i, data in enumerate(value):
            self.data_queue[i].append(data)
            self.data_disk[i].append(data)

        # handle data for saving
        data_size = self.get_size(self.data_disk)
        data_save_size = data_size
        if data_size:
            if data_size > self.config["binary_save_size"]:
                out = {
                    k: self.safe_concatenate(v) for k, v in self.data_disk.items() if v
                }
                if self.config["binary_save_data"]:
                    self.save_data(out)
                self.data_disk = defaultdict(list)

        # handle data for queue
        data_size = self.get_size(self.data_queue)
        if not data_size:
            return

        self.send_report({"data_size": data_size, "data_save_size": data_save_size})
        if data_size > self.config.get("binary_size"):
            out = {k: self.safe_concatenate(v) for k, v in self.data_queue.items() if v}
            self.data_queue = defaultdict(list)
            return out

    def do_stop(self):
        """
        Stops the task.

        Note:
            This method extends ``Task.do_stop``.
        """

        out_queue = {
            k: self.safe_concatenate(v) for k, v in self.data_queue.items() if v
        }
        out_disk = {k: self.safe_concatenate(v) for k, v in self.data_disk.items() if v}
        if not self._is_final:
            self.send_data(out_queue)
        if out_disk:
            if self.config["binary_save_data"]:
                self.save_data(out_disk)
        self.data_queue = defaultdict(list)
        self.data_disk = defaultdict(list)
        self.send_report({"data_size": 0, "data_save_size": 0})

    def safe_concatenate(self, arrays):  # Add 'self' parameter
        """Safely concatenate arrays, handling zero-dimensional arrays."""
        if not arrays:
            return np.array([])

        safe_arrays = []
        for arr in arrays:
            if np.isscalar(arr):
                safe_arrays.append(np.array([arr]))
            elif isinstance(arr, np.ndarray) and arr.ndim == 0:
                safe_arrays.append(np.array([arr.item()]))
            else:
                safe_arrays.append(arr)

        return np.concatenate(safe_arrays)
