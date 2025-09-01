import time
import pathlib

import numpy as np

from .. import task


PAUSE: float = 0.2
DEFAULT_MODULES: list[int] = [2]
DEFAULT_RUNTIME: int = 2
DEFAULT_CHUNK_SIZE: int = 20_000


class DummyData(task.Task):
    """
    Sends dummy data into the pipeline.
    """

    def do_init(self):
        """
        Initialzies the task.

        Note:
            This method extends ``Task.do_init``.
        """

        self.data = np.fromfile(
            pathlib.Path(__file__).parent.parent.parent.parent.parent
            / "tests"
            / "files"
            / "bin"
            / "pixie16-data-01.bin",
            dtype=np.uint8,
        )

        self.config = {
            "modules": DEFAULT_MODULES,
            "runtime": DEFAULT_RUNTIME,
            "chunk_size": DEFAULT_CHUNK_SIZE,
        }

        # Set default values directly as attributes
        self.modules = DEFAULT_MODULES
        self.runtime = DEFAULT_RUNTIME
        self.chunk_size = DEFAULT_CHUNK_SIZE

    def do_configure(self, config: dict):
        """
        Configures the task.

        Note:
            This method extends ``Task.do_configure``.
        """

        self.modules = config.get("modules", self.config["modules"])
        self.runtime = config.get("runtime", self.config["runtime"])
        self.chunk_size = config.get("chunk_size", self.config["chunk_size"])

    def do_start(self):
        """
        Starts the task.

        Note:
            This method extends ``Task.do_start``.
        """

        self.position = 0
        self.time_start = time.time()

    def do_work(self, datum: None):
        """
        Works for the task.

        Note:
            This method extends ``Task.do_work``.
        """

        # Checking runtime.
        if time.time() - self.time_start >= self.runtime:
            return self.stop()

        time.sleep(PAUSE)

        # Chuncking dummy data.
        if self.position + self.chunk_size < len(self.data):
            binary = self.data[self.position : self.position + self.chunk_size]
            self.position += self.chunk_size
        else:
            binary = self.data[self.position :]
            self.position = 0

        return {module: binary for module in self.modules}
