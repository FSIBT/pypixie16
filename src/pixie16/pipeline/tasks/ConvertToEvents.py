from .. import task
from ... import read


class ConvertToEvents(task.Task):
    """
    Convert data to events.
    """

    def do_init(self):
        """
        Initializes the task.

        Note:
            This method extends ``Task.do_init``.
        """

        self.list_mode_readers = {}

    def do_work(self, data):
        """
        Works for the task.

        Note:
            This method extends ``Task.do_work``.
        """

        for key, val in data.items():
            if key not in self.list_mode_readers:
                reader = read.StreamReader()
                self.list_mode_readers[key] = read.ListModeDataReader(reader)
            self.list_mode_readers[key].reader.put(val)

        tmp = {mod: reader.pop_all() for mod, reader in self.list_mode_readers.items()}

        return tmp
