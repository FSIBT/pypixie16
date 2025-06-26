from .. import task


DEFAULT_SIZE = 1_000_000


class GatherEvents(task.Task):
    """Gather Events into larger chunks."""

    def do_startup(self):
        self.nr = 0
        self.data = []

        return {
            "size": DEFAULT_SIZE,
        }

    def do_configure(self, config: dict):
        self.size = config.get("size", self.config["size"])

    def do_report(self):
        return {
            "gathered events": self.nr,
            "gathered queue": len(self.data),
        }

    def do_work(self, value):
        self.data.extend(value)

        if len(self.data) > self.size:
            out = self.data

            self.data = []
            self.nr += 1

            self.send_report()

            return out

    def do_cleanup(self):
        if self.data:
            self.send_data(self.data)
            self.send_report()
