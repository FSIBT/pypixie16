import typing

from .. import task


DEFAULT_SIZE: int = 1_000_000


class GatherEvents(task.Task):
    """
    Chuncks data.
    """

    def do_init(self):
        """
        Initializes the task.

        Note:
            This method extends ``Task.do_init``.
        """

        self.config = {
            "size": DEFAULT_SIZE,
        }

    def do_configure(self, config: dict):
        """
        Configures the task.

        Note:
            This method extends ``Task.do_configure``.
        """

        self.size = config.get("size", self.config["size"])

    def do_start(self):
        """
        Starts the task.

        Note:
            This method extends ``Task.do_start``.
        """

        self.count = 0
        self.queue = []

    def do_work(self, datum: typing.Any):
        """
        Works for the task.

        Note:
            This method extends ``Task.do_work``.
        """

        self.queue.extend(datum)

        if len(self.queue) >= self.size:
            out = self.queue
            self.queue = []
            self.count += 1

            self.report(
                {
                    "gathered data": self.count,
                    "gathered queue": len(self.queue),
                }
            )

            return out

    def do_stop(self):
        """
        Stops the task.

        Note:
            This method extends ``Task.do_stop``.
        """

        if self.queue:
            self.send(self.queue)
            self.report(
                {
                    "gathered data": self.count,
                    "gathered queue": len(self.queue),
                }
            )
