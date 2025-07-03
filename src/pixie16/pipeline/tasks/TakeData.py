import time
import typing

import numpy as np

from .. import task
from ... import control


PAUSE: float = 0.5
THRESHOLD: int = 64 * 1024
BOOT_PATTERN: int = 0x7F
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
        Initializes the task.

        Notes:
            This methods extends ``Task.do_init``.
        """

        # Boot the pixie16
        control.init_and_boot(
            modules=self.modules, verbose=False, boot_pattern=BOOT_PATTERN
        )
        control.adjust_offsets()
        control.unset_sync_mode()
        control.empty_all_fifos()
        for module, _ in enumerate(self.modules):
            control.set_defaults_for_module(module)

        self.start_time = time.time()
        self.config = {
            "modules": DEFAULT_MODULES,
            "runtime": DEFAULT_RUNTIME,
        }

    def do_configure(self, config: dict):
        """
        Configures the task.

        Notes:
            This methods extends ``Task.do_configure``.
        """

        self.modules = config.get("modules", self.config["modules"])
        self.runtime = config.get("runtime", self.config["runtime"])

    def do_work(self, value: None) -> list[np.ndarray]:
        """
        Works for the task.

        Generates binary from the FPGA.

        Notes:
            This methods extends ``Task.do_work``.
        """

        control.start_list_mode_run()

        if time.time() - self.start_time > self.config["runtime"]:
            return control.read_list_mode_fifo(threshold=THRESHOLD)

    def do_quit(self) -> None:
        """
        Quits the task.

        Notes:
            This methods extends ``Task.do_quit``.
        """

        control.end_run()
        time.sleep(PAUSE)
