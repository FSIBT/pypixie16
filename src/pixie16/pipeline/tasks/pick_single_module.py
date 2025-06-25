from .. import task


class PickSingleModule(task.Task):
    """Task to pick events from a single module.

    Takes output from, e.g., ConvertToEvents and outputs only the data
    for a single module.
    """

    def do_startup(self):
        self.config |= {"pick_module": 2}

    def handle_configure(self, config_dict: dict):
        super().handle_configure(config_dict)
        self.module = self.config["pick_module"]

    def do_work(self, values):
        return {k: v for k, v in values.items() if k == self.module}
