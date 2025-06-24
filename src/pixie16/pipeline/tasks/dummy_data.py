import time
import pathlib

import numpy as np

from .. import task
from ... import read
from .. import status
from .. import message
from ... import control


class DummyData(task.Task):
    """
    Sends dummy data into a chain.

    This task goes first in a chain and stands in for a pixie16. It helps
    during testing, debugging, and whenever a pixie16 is offline/unavaliable.

    Attributes:
        pos: Stream position.
        runtime: Desired runtime.
        time_done: Current runtime.
        time_start: Run start time.
        data: Dummy data.
        filename: Path to dummy data.
    """

    def __init__(self, name: str):
        """
        Iniailzies ``DummyData``.

        Parameters:
            name: Task name.
        """

        super().__init__(name)

        self.pos = 0
        self.runtime = 10
        self.time_done = 0
        self.filename = (
            pathlib.Path(__file__).parent.parent.parent.parent.parent
            / "tests"
            / "files"
            / "bin"
            / "pixie16-data-01.bin"
        )

        self.config = {
            "modules": None,
            "runtime": None,
            "chunk_size": None,
        }

    def do_startup(self):
        """
        Prepares the data and configuration.
        """

        # Load data & metadata.
        self.data = np.fromfile(self.filename, dtype=np.uint8)
        self.time_start = time.time()

        # Load configuration.
        self.chunk_size = self.config.get("chunk_size") or min(20_000, len(self.data))
        self.modules = self.config["modules"] or [2]
        self.runtime = self.config["runtime"] or 10

    def do_work(self):
        """
        Simulates data acqusition.
        """

        # Checking runtime.
        self.time_done = time.time() - self.time_start
        if self.time_done >= self.runtime:
            self.send_report({"finished": True})
            return

        # Chuncking dummy data.
        time.sleep(0.2)
        if self.pos + self.chunk_size < len(self.data):
            ret = self.data[self.pos : self.pos + self.chunk_size]
            self.pos += self.chunk_size
        else:
            ret = self.data[self.pos :]
            self.pos = 0

        self.send_data({m: ret for m in self.modules})

    def add_user_status(self, stat):
        stat["runtime"] = self.runtime
        stat["filename"] = self.filename
        stat["time done"] = self.time_done
        return stat
