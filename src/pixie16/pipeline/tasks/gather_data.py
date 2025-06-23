from .. import task


class GatherData(task.Task):
    """Task to create larger data buckets out of the data directly from the FPGA.

    It has two different buckets: one for sending data to the next queue
    and one for saving data to disk.
    """

    def __init__(self, pipeline_address):
        maxsize = 50e6
        save_size = None
        path = None

        super().__init__(pipeline_address)
        self.name = "Gather Data"

        self.data_queue = defaultdict(list)
        self.data_disk = defaultdict(list)
        self.maxsize = None
        self.save_size = None
        self.save_binary = False

    def configure(self):
        self.data_queue = defaultdict(list)
        self.data_disk = defaultdict(list)
        self.maxsize = self.state.get("maxsize") or 50_000_000
        self.save_size = self.state.get("save size") or self.maxsize
        self.save_binary = self.save_size is not None
        self.maxsize = self.state.get("maxsize") or 50_000_000
        self.path = Path(self.state.get("path")) or Path(".")
        self.mycounter = 0
        self.file_counter = 0

    def save_data(self, out):
        timestamp = datetime.today().strftime("%Y-%m-%d-%H-%M-%S")
        for k, v in out.items():
            file = self.path / f"data-mod{k}-{timestamp}-{self.file_counter:05d}.bin"
            v.tofile(str(file))
        self.file_counter += 1

    def get_size(self, data):
        out = []
        for data_list in data.values():
            size = 0
            for element in data_list:
                size += element.nbytes
            out.append(size)
        if out:
            return max(out)
        return 0

    def user_status(self, d: dict):
        d["data size queue"] = self.get_size(self.data_queue)
        d["data size disk"] = self.get_size(self.data_disk)
        return d

    def do_work(self, value):
        self.mycounter += 1

        if value["type"] != "data":
            return

        value = value["data"]

        for i, data in enumerate(value):
            self.data_queue[i].append(data)
            self.data_disk[i].append(data)

        # handle data for saving
        data_size = self.get_size(self.data_disk)
        if data_size:
            if data_size > self.save_size:
                out = {k: np.concatenate(v) for k, v in self.data_disk.items() if v}
                if self.save_binary:
                    self.save_data(out)
                self.data_disk = defaultdict(list)

        # handle data for queue
        data_size = self.get_size(self.data_queue)

        if not data_size:
            return

        if data_size > self.maxsize:
            out = {k: np.concatenate(v) for k, v in self.data_queue.items() if v}
            self.data_queue = defaultdict(list)
            return {"type": "data", "data": out}

    def cleanup(self):
        """Send data still in buffer."""
        out_queue = {k: np.concatenate(v) for k, v in self.data_queue.items() if v}
        out_disk = {k: np.concatenate(v) for k, v in self.data_disk.items() if v}
        if self.output_queue:
            self.push.send_pyobj({"type": MessageType.DATA, "data": out})
        if out_disk and not self.is_final_task:
            if self.save_binary:
                self.save_data(out_disk)
