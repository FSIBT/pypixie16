import typing

from .. import task


class PickSingleModule(task.Task):
    """Task to pick events from a single module.

    Takes output from, e.g., ConvertToEvents and outputs only the data
    for a single module.
    """

    def do_init(self):
        """
        Initializes the task.

        Notes:
            This method extends ``Task.do_init``.
        """

        self.config = {"module": 2}

        # Set default values directly as attributes
        self.module = 2

    def do_configure(self, config: dict):
        """
        Configures the task.

        Notes:
            This method extends ``Task.do_configure``.
        """

        self.module = config.get("module", self.config["module"])

    def do_work(self, datum: typing.Any):
        """
        Works for the task.

        Notes:
            This method extends ``Task.do_work``.
        """

        return {k: v for k, v in datum.items() if k == self.module}
