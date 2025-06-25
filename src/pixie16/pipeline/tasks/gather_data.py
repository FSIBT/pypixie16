from .. import task


class GatherData(task.Task):
    """Task to create larger data buckets out of the data directly from the FPGA.

    It has two different buckets: one for sending data to the next queue
    and one for saving data to disk.
    """

    def __init__(self):
        super().__init__()
        self.name = "Gather Data"

        self.config |= {
            "binary_save_size": None,
            "binary_size": 50e6,
            "binary_save_path": None,
            "binary_save_data": True,
        }

        self.data_queue = defaultdict(list)
        self.data_disk = defaultdict(list)

    def handle_configure(self, config_dict: dict):
        super().handle_configure(config_dict)

        self.data_queue = defaultdict(list)
        self.data_disk = defaultdict(list)

        self.path = Path(self.config["binary_save_path"]) or Path(".")

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

    def do_report(self):
        d = {
            "data size queue": self.get_size(self.data_queue),
            "data size disk": self.get_size(self.data_disk),
        }
        return d

    def do_work(self, value):
        self.mycounter += 1

        for i, data in enumerate(value):
            self.data_queue[i].append(data)
            self.data_disk[i].append(data)

        # handle data for saving
        data_size = self.get_size(self.data_disk)
        if data_size:
            if data_size > self.config["binary_save_size"]:
                out = {k: np.concatenate(v) for k, v in self.data_disk.items() if v}
                if self.config["binary_save_data"]:
                    self.save_data(out)
                self.data_disk = defaultdict(list)

        # handle data for queue
        data_size = self.get_size(self.data_queue)

        if not data_size:
            return

        if data_size > self.config.get("binary_size"):
            out = {k: np.concatenate(v) for k, v in self.data_queue.items() if v}
            self.data_queue = defaultdict(list)
            return out

    def cleanup(self):
        """Send data still in buffer."""
        out_queue = {k: np.concatenate(v) for k, v in self.data_queue.items() if v}
        out_disk = {k: np.concatenate(v) for k, v in self.data_disk.items() if v}
        if not self.config["is_final"]:
            self.send_data(out_queue)
        if out_disk:
            if self.config["binary_save_data"]:
                self.save_data(out_disk)
