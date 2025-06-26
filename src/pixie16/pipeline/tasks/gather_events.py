from .. import task


class GatherEvents(task.Task):
    """Gather Events into larger chunks."""

    def handle_configure(self, config: dict):
        super().handle_configure(config)
        self.size = self.config.get("size", 1_000_000)

    def do_startup(self):
        self.data = []
        self.nr = 0
        self.config |= {
            "size": 1_000_000,
        }

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
