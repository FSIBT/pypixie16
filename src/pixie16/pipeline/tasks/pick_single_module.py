import typing

from .. import task


class PickSingleModule(task.Task):
    """Task to pick events from a single module.

    Takes output from, e.g., ConvertToEvents and outputs only the data
    for a single module.
    """

    def do_startup(self):
        self.config |= {
            "pick_module": 2
        }

    def do_work(self, value: typing.Any):
        return {k: v for k, v in values.items() if k == self.config['pick_module']}
