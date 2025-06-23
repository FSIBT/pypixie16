import io

import zmq
import pytest

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
    self.send_report({})


@pytest.fixture
def pipeline() -> pixie16.pipeline.Pipeline:
    return pixie16.pipeline.Pipeline()


@pytest.fixture
def task(pipeline: pixie16.pipeline.Pipeline) -> pixie16.pipeline.Task:
    return DummyTask("Hello", pipeline.address_router)


class Test_Pipeline:
    def test__init(self):
        pixie16.pipeline.Pipeline()

    def test_handle_report(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        task.do_work = do_work_report

        # Valid
        pipeline.task_append(task)
        pipeline.init(["Hello"])
        pipeline.start()
        pipeline.stop()

        # Invalid
        with pytest.raises(ValueError):
            pipeline.handle_report("Nope", {})

        pipeline.task_remove("Hello")

    def test_handle_print(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        task.do_work = do_work_print

        # Valid
        pipeline.task_append(task)
        pipeline.init(["Hello"])
        pipeline.start()
        pipeline.stop()

        # Invalid
        with pytest.raises(ValueError):
            pipeline.handle_print("Nope", io.StringIO("out"), io.StringIO("err"))

        pipeline.task_remove("Hello")

    def test_task_connect(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        context = zmq.Context()
        socket = context.socket(zmq.PUSH)
        address = socket.bind_to_random_port("tcp://127.0.0.1")
        address = f"tcp://127.0.0.1:{address}"

        pipeline.task_append(task)

        # Valid
        pipeline.task_connect("Hello", address)

        # Invalid
        with pytest.raises(ValueError):
            pipeline.task_connect("Nope", address)

        pipeline.task_remove("Hello")

    def test_task_disconnect(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        context = zmq.Context()
        socket = context.socket(zmq.PUSH)
        address = socket.bind_to_random_port("tcp://127.0.0.1")
        address = f"tcp://127.0.0.1:{address}"

        pipeline.task_append(task)

        # Valid A
        pipeline.task_disconnect("Hello")

        # Valid B
        pipeline.task_connect("Hello", address)
        pipeline.task_disconnect("Hello")

        # Invalid
        with pytest.raises(ValueError):
            pipeline.task_disconnect("Nope")

        pipeline.task_remove("Hello")

    def test_task_start(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        pipeline.task_append(task)

        # Valid
        pipeline.task_start("Hello")

        # Invalid
        with pytest.raises(ValueError):
            pipeline.task_start("Nope")

        pipeline.task_remove("Hello")

    def test_task_pause(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        pipeline.task_append(task)

        # Valid
        pipeline.task_pause("Hello")

        # Invalid
        with pytest.raises(ValueError):
            pipeline.task_pause("Nope")

        pipeline.task_remove("Hello")

    def test_task_stop(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        pipeline.task_append(task)

        # Valid
        pipeline.task_stop("Hello")

        # Invalid
        with pytest.raises(ValueError):
            pipeline.task_stop("Nope")

        pipeline.task_remove("Hello")

    def test_task_configure(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        pipeline.task_append(task)

        # Valid
        pipeline.task_configure("Hello", {})

        # Invalid
        with pytest.raises(ValueError):
            pipeline.task_configure("Nope", {})

        pipeline.task_remove("Hello")

    def test_task_append(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        # Valid
        pipeline.task_append(task)

        # Invalid
        with pytest.raises(ValueError):
            pipeline.task_append(task)

        pipeline.task_remove("Hello")

    def test_task_remove(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        # Valid
        pipeline.task_append(task)

        # Invalid
        with pytest.raises(ValueError):
            pipeline.task_remove("Nope")

        pipeline.task_remove("Hello")

    def test_init(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        pipeline.task_append(task)

        # Valid A
        pipeline.init(["Hello"])

        # Valid B
        pipeline.init(["Hello"])

        # Valid C
        pipeline.init([])

        # Valid D
        task = DummyTask("Hi", pipeline.address_router)
        pipeline.task_append(task)
        pipeline.init(["Hello", "Hi"])

        pipeline.task_remove("Hello")
        pipeline.task_remove("Hi")

    def test_start(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        pipeline.task_append(task)

        pipeline.init(["Hello"])
        pipeline.pause()

        pipeline.task_remove("Hello")

    def test_pause(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        pipeline.task_append(task)

        pipeline.init(["Hello"])
        pipeline.pause()

        pipeline.task_remove("Hello")

    def test_stop(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        pipeline.task_append(task)

        pipeline.init(["Hello"])
        pipeline.stop()

        pipeline.task_remove("Hello")

    def test_configure(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        pipeline.task_append(task)

        pipeline.init(["Hello"])
        pipeline.configure({})

        pipeline.task_remove("Hello")

    def test_poll(
        self, task: pixie16.pipeline.Task, pipeline: pixie16.pipeline.Pipeline
    ):
        pipeline.task_append(task)

        pipeline.init(["Hello"])
        pipeline.poll()

        pipeline.task_remove("Hello")
