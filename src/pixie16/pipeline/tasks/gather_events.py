from .. import task


class GatherEvents(task.Task):
    """Gather Events into larger chunks."""

    def __init__(self, pipeline_address):
        super().__init__(pipeline_address)
        self.data = []
        self.state = {
            "size": 1_000_000,
            "nr": 0,
        }
        self.name = "Gather events"

    def do_work(self, value):
        self.data.extend(value)
        if len(self.data) > self.size:
            out = self.data
            self.data = []
            self.nr += 1
            return out

        self.send_status({"gathered events": self.nr, "gathered queue": len(self.data)})

    def cleanup(self):
        if self.output_queue and self.data:
            self.output_queue.put(self.data)
        self.data = []
        self.nr += 1
        self.send_status({"gathered events": self.nr, "gathered queue": len(self.data)})
