from .. import task


class PickSingleModule(task.Task):
    """Task to pick events from a single module.

    Takes output from, e.g., ConvertToEvents and outputs only the data
    for a single module.
    """

    def __init__(self):
        super().__init__()
        self.module = 2

    def do_work(self, value_dict):
        if not value_dict["type"] == MessageType.DATA:
            return
        data = {k: v for k, v in value_dict.items() if k == self.module}
        return {"type": MessageType.DATA, "data": data}
