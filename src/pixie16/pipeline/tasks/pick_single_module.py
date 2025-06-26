import typing

from .. import task


DEFAULT_PICK_MODULE = 2


class PickSingleModule(task.Task):
    """Task to pick events from a single module.

    Takes output from, e.g., ConvertToEvents and outputs only the data
    for a single module.
    """

    def do_startup(self):
        return {"pick_module": DEFAULT_PICK_MODULE}

    def do_configure(self, config: dict):
        self.pick_module = config.get("pick_module", self.config["pick_module"])

    def do_work(self, value: typing.Any):
        return {k: v for k, v in value.items() if k == self.pick_module}
