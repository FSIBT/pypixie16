from .. import task
from ... import read

FILE_LIST = None
BATCH_SIZE: int = 1_000
BUFFER_SIZE: int = 1_000_000


class LoadFiles(task.Task):
    """Load events from a list of files,"""

    def do_init(self):
        """
        Initializes the task.

        Note:
            This method extends ``Task.do_init``.
        """

        self.config = {
            "files": FILE_LIST or (),
            "batch_size": BATCH_SIZE,
            "buffer_size": BUFFER_SIZE,
        }

        self.files = self.config["files"]
        self.batch_size = self.config["batch_size"]
        self.buffer_size = self.config["buffer_size"]

        self.byte_stream = None
        self.reader = None
        self.count = 0

    def do_configure(self, config: dict):
        """
        Configures the task.

        Note:
            This method extends ``Task.do_configure``.
        """

        self.files = config.get("files", self.config["files"])
        self.batch_size = config.get("batch_size", self.config["batch_size"])
        self.buffer_size = config.get("buffer_size", self.config["buffer_size"])

    def do_start(self):
        """
        Starts the task.

        Note:
            This method extends ``Task.do_Start``.
        """

        if not self.files:
            raise ValueError("LoadFiles requires a non-empty 'files' list")

        self.byte_stream = read.FileReader(self.files)
        self.byte_stream.open_files()
        self.reader = read.ListModeDataReader(self.byte_stream)
        self.count = 0

    def do_work(self, datum: None):
        """
        Works for the task.

        Note:
            This method extends ``Task.do_work``.
        """

        events = []
        eof = False  # End-of-File

        for _ in range(self.batch_size):
            try:
                events.append(self.reader.pop())
            except (read.EmptyError, read.LeftoverBytesError, StopIteration):
                eof = True
                break

        self.count += len(events)
        self.report(
            {
                "count": self.count,
                "runtime": self.byte_stream.current_file,
            }
        )

        if events:
            return events

        if eof:
            if self.byte_stream is not None:
                self.byte_stream.close_files()
            self.send_finished()

    def do_stop(self):
        """
        Stops the task.

        Note:
            This method extends ``Task.do_stop``.
        """

        if self.byte_stream:
            self.byte_stream.close_files()

    def do_quit(self):
        """
        Quits the task.

        Note:
            This method extends ``Task.do_quit``.
        """

        if self.byte_stream is not None:
            self.byte_stream.close_files()
