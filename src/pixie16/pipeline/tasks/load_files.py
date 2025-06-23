from .. import task


class LoadFiles(task.Task):
    """Load events from a list of files,"""

    def __init__(self, event, pipeline_address):
        file_list = None
        batch_size = 1_000
        super().__init__(event, pipeline_address)
        self.files = file_list
        self.byte_stream = read.FileReader(self.files)
        self.byte_stream.open_files()
        self.buffer_size = 1_000_000
        self.reader = read.ListModeDataReader(self.byte_stream)
        self.number_of_events_to_read = batch_size
        self.nr_of_events = 0
        self.name = "Loading binary data from files"

    def cleanup(self):
        self.byte_stream.close_files()

    def do_work(self, value):
        try:
            events = []
            for _ in range(self.number_of_events_to_read):
                event = None
                try:
                    event = self.reader.pop()
                except read.EmptyError:
                    self.done = True
                    break
                except read.LeftoverBytesError:
                    self.done = True
                    print(f"[red]ERROR[/] Left over Bytes in files")
                    break
                events.append(event)
            if events and self.output_queue:
                self.output_queue.put(events)
                self.nr_of_events += len(events)
                events = []
        except StopIteration:
            self.done = True
            if events and self.output_queue:
                self.output_queue.put(events)
                self.nr_of_events += len(events)
                events = []

        self.send_status(
            {
                "read events": f"{self.nr_of_events:.2e}",
                "runtime": self.byte_stream.current_file,
            }
        )
