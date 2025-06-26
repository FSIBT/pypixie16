import typing

from .. import task


class PickSingleModule(task.Task):
    """Task to pick events from a single module.

    Takes output from, e.g., ConvertToEvents and outputs only the data
    for a single module.
    """

    def handle_configure(self, config: dict):
        super().handle_configure(config)
        self.pick_module = self.config.get("pick_module", 2)

    def do_startup(self):
        self.config |= {
            "pick_module": 2
        }

    def do_work(self, value: typing.Any):
        return {k: v for k, v in value.items() if k == self.pick_module}
