from .. import task
from ... import read
from ... import control


class DummyData(task.Task):
    """A class that will send dummy data into a pipeline.

    This can be used as a first task in a pipeline during testing and
    when the pixie16 is not online/available.

    """

    def __init__(self, pipeline_address):
        super().__init__(pipeline_address)
        self.name = "Data generator"

        self.runtime = 10
        self.time_done = 0
        self.filename = None

        self.data = None
        self.length = 0
        self.chunk_size = 20_000
        self.mycounter = 0
        self.pos = 0

        self.status_frequency = 1

    def configure(self):
        if (filename := self.state.get("filename")) is None:
            self.filename = files("pixie16") / "data" / "pixie16-data-01.bin"
        else:
            self.filename = Path(filename)

        self.data = np.fromfile(self.filename, dtype=np.uint8)
        self.length = len(self.data)
        self.chunk_size = self.state.get("chunk_size") or 20_000
        self.pos = 0
        if self.chunk_size > self.length:
            print("[red]ERROR[/] chunk_size too big")
        self.modules = self.state.get("modules", [2])
        self.runtime = self.state.get("runtime", 10)
        self.time_done = 0

    def add_user_status(self, stat):
        stat["runtime"] = self.runtime
        stat["filename"] = self.filename
        stat["time done"] = self.time_done
        return stat

    def do_work(self, value):
        dt = time.time() - self.start_time
        self.time_done = dt
        if self.time_done >= self.runtime:
            self.status = TaskStatus.FINISHED
            return {"type": MessageType.FINISHED}

        time.sleep(0.2)
        self.mycounter += 1
        if self.pos + self.chunk_size < self.length:
            out = self.data[self.pos : self.pos + self.chunk_size]
            self.pos += self.chunk_size
        else:
            out = self.data[self.pos :]
            self.pos = 0
        ret = {m: out for m in self.modules}
        return {"type": MessageType.DATA, "data": ret}
