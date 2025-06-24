from .. import task


class PrintData(task.Task):
    def do_work(self):
        if self.queue:
            print(self.queue.popleft())

    def do_startup(self):
        pass

    def do_cleanup(self):
        pass
