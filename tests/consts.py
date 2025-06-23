import pixie16


class DummyTask(pixie16.pipeline.Task):
    def do_startup(self) -> None:
        pass

    def do_cleanup(self) -> None:
        pass

    def do_work(self) -> None:
        if len(self.queue):
            self.queue.popleft()


def do_work_report(self):
    self.send_report({})


def do_work_print(self):
    self.send_print("Hi", "Err")


def do_work_data(self):
    self.send_data([0, 1, 2])
