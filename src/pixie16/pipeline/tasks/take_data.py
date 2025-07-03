import time
import typing

import numpy as np

from .. import task
from ... import control


THRESHOLD: int = 64 * 1024
CLEANUP_PAUSE: float = 0.5
DEFAULT_RUNTIME: int = 10
DEFAULT_MODULES: list[int] = [2]


class TakeData(task.Task):
    """
    Example Task to aquire data, each binary blob from the FPGA
    will be put in the queue.

    A second task can then convert the binary blob to events and from
    there perhaps another task can convert to pandas.
    """

    def do_init(self) -> None:
        """
        Initializes and boots the FPGA.
        """

        # Boot the pixie16
        control.init_and_boot(modules=self.modules, verbose=False, boot_pattern=0x7F)
        control.adjust_offsets()
        control.unset_sync_mode()
        control.empty_all_fifos()
        for m, _ in enumerate(self.modules):
            control.set_defaults_for_module(m)

        self.start_time = time.time()

        self.config = {
            "modules": DEFAULT_MODULES,
            "runtime": DEFAULT_RUNTIME,
        }

    def do_configure(self, config: dict):
        """
        Extends the configuration.
        """

        self.modules = config.get("modules", self.config["modules"])
        self.runtime = config.get("runtime", self.config["runtime"])

    def do_work(self, value: typing.Any) -> list[np.ndarray]:
        """
        Generates binary from the FPGA.

        Parameters:
            value: Anything.
        """

        control.start_list_mode_run()
        now = time.time()
        if now - self.start_time > self.config["runtime"]:
            return control.read_list_mode_fifo(threshold=THRESHOLD)

    def do_cleanup(self) -> None:
        """
        Closed connection to the FPGA.
        """

        control.end_run()
        time.sleep(CLEANUP_PAUSE)
