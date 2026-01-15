from .. import task


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

        self.byte_stream = read.FileReader(FILE_LIST)
        self.byte_stream.open_files()
        self.reader = read.ListModeDataReader(self.byte_stream)
        self.count = count

    def do_work(self, datum: None):
        """
        Works for the task.

        Note:
            This method extends ``Task.do_work``.
        """

        events = []
        for _ in range(BATCH_SIZE):
            try:
                events.append(self.reader.pop())
            except read.EmptyError:
                self.stop()
                break
            except read.LeftoverBytesError:
                self.stop()
                break
            except StopIteration:
                self.stop()

        self.count += len(events)
        self.report(
            {
                "count": self.count,
                "runtime": self.byte_stream.current_file,
            }
        )

        if events:
            return events

    def do_quit(self):
        """
        Quits the task.

        Note:
            This method extends ``Task.do_quit``.
        """

        self.byte_stream.close_files()
