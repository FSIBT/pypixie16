import time
import typing
import pathlib

import numpy as np

from .. import task
from ... import read
from .. import status
from .. import message
from ... import control


WORK_PAUSE = 0.2
DEFAULT_MODULES = [2]
DEFAULT_RUNTIME = 10
DEFAULT_CHUNK_SIZE = 20_000


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

    def do_startup(self):
        self.filename = (
            pathlib.Path(__file__).parent.parent.parent.parent.parent
            / "tests"
            / "files"
            / "bin"
            / "pixie16-data-01.bin"
        )
        self.pos = 0
        self.time_done = 0
        self.time_start = time.time()
        self.data = np.fromfile(self.filename, dtype=np.uint8)

        self.config = {
            "modules": DEFAULT_MODULES,
            "runtime": DEFAULT_RUNTIME,
            "chunk_size": DEFAULT_CHUNK_SIZE,
        }

    def do_configure(self, config: dict):
        self.modules = config.get("modules", self.config["modules"])
        self.runtime = config.get("runtime", self.config["runtime"])
        self.chunk_size = config.get("chunk_size", self.config["chunk_size"])

    def do_work(self, value: typing.Any):
        # Checking runtime.
        self.time_done = time.time() - self.time_start
        if self.time_done >= self.runtime:
            self.send_finished()

        time.sleep(WORK_PAUSE)

        # Chuncking dummy data.
        if self.pos + self.chunk_size < len(self.data):
            ret = self.data[self.pos : self.pos + self.chunk_size]
            self.pos += self.chunk_size
        else:
            ret = self.data[self.pos :]
            self.pos = 0

        return {m: ret for m in self.modules}

    def add_user_status(self, stat):
        stat["runtime"] = self.runtime
        stat["filename"] = self.filename
        stat["time done"] = self.time_done
        return stat
