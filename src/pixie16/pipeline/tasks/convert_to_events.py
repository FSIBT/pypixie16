from .. import task
from ... import read


class ConvertToEvents(task.Task):
    """Task to convert data stream to events."""

    def do_setup(self):
        self.list_mode_readers = {}

    def do_work(self):
        value_dict = self.queue.popleft()

        for key, val in value_dict.items():
            if key not in self.list_mode_readers:
                reader = read.StreamReader()
                self.list_mode_readers[key] = read.ListModeDataReader(reader)
            self.list_mode_readers[key].reader.put(val)

        return {mod: reader.pop_all() for mod, reader in self.list_mode_readers.items()}
