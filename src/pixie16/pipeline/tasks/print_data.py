from .. import task


class PrintData(task.Task):
    def do_work(self, value: str):
        print(value)
