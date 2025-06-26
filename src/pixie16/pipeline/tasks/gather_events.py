from .. import task


class GatherEvents(task.Task):
    """Gather Events into larger chunks."""

    def do_startup(self):
        self.data = []
        self.config |= {
            "size": 1_000_000,
        }
        self.nr = 0

    def do_report(self):
        return {
            'gathered events': self.nr,
            'gathered queue': len(self.data),
        }

    def do_work(self, value):
        self.data.extend(value)

        if len(self.data) > self.config['size']:
            out = self.data

            self.data = []
            self.nr += 1

            return out

        self.send_report()
