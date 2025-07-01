import io
import time

import zmq
import pytest

import pixie16


class DummyTask(pixie16.pipeline.Task):
    def do_work(self, value):
        self.send_report({})


class ErrorTask(pixie16.pipeline.Task):
    def do_work(self, value):
        raise Exception


class PrintTask(pixie16.pipeline.Task):
    def do_work(self, value):
        self.send_print("Hi", "Err")


@pytest.fixture
def context() -> zmq.Context:
    context = zmq.Context()
    yield context
    context.term()


@pytest.fixture
def router(context: zmq.Context) -> tuple[str, zmq.Socket]:
    socket = context.socket(zmq.PAIR)
    address = socket.bind_to_random_port("tcp://127.0.0.1")
    address = f"tcp://127.0.0.1:{address}"

    yield address, socket

    socket.close()


@pytest.fixture
def dealer(
    context: zmq.Context, router: tuple[str, zmq.Socket]
) -> tuple[str, zmq.Socket]:
    socket = context.socket(zmq.PAIR)
    address = socket.bind_to_random_port("tcp://127.0.0.1")
    address = f"tcp://127.0.0.1:{address}"

    yield address, socket

    socket.close()


@pytest.fixture
def push(context: zmq.Context) -> tuple[str, zmq.Socket]:
    socket = context.socket(zmq.PAIR)
    address = socket.bind_to_random_port("tcp://127.0.0.1")
    address = f"tcp://127.0.0.1:{address}"

    yield address, socket

    socket.close()


@pytest.fixture
def pipeline_base() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    yield pipe
    for task in pipe._tasks_all.values():
        task.kill()


@pytest.fixture
def pipeline_created() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.create_task("DummyTask")
    yield pipe
    for task in pipe._tasks_all.values():
        task.kill()


@pytest.fixture
def pipeline_dummy() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.create_task("DummyTask")
    pipe.init(["DummyTask"])
    yield pipe
    for task in pipe._tasks_all.values():
        task.kill()


@pytest.fixture
def pipeline_print() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.create_task("PrintTask")
    pipe.init(["PrintTask"])
    yield pipe
    for task in pipe._tasks_all.values():
        task.kill()


@pytest.fixture
def pipeline_error() -> pixie16.pipeline.Pipeline:
    pipe = pixie16.pipeline.Pipeline()
    pipe.create_task("ErrorTask")
    pipe.init(["ErrorTask"])
    yield pipe
    for task in pipe._tasks_all.values():
        task.kill()


class Test_Pipeline:
    @staticmethod
    def test___init__():
        pipe = pixie16.pipeline.Pipeline()
        assert pipe.status == pixie16.pipeline.Status.READY
        assert pipe.tasks_active == []
        assert pipe._tasks_all == {}
        assert pipe.reports == {}
        assert pipe.context is not None
        assert pipe.socket_router is not None
        assert pipe.address_router is not None
        assert pipe.address_router is not None

    @staticmethod
    def test_create_task_valid(pipeline_base: pixie16.pipeline.Pipeline):
        assert pipeline_base._tasks_all == {}
        pipeline_base.create_task("DummyTask")
        assert "DummyTask" in pipeline_base._tasks_all

    @staticmethod
    def test_create_task_invalid_A(pipeline_base: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_base.create_task(" ")

    @staticmethod
    def test_create_task_invalid_B(pipeline_base: pixie16.pipeline.Pipeline):
        pipeline_base.create_task("DummyTask")
        with pytest.raises(ValueError):
            pipeline_base.create_task("DummyTask")

    @staticmethod
    def test_handle_error(pipeline_base: pixie16.pipeline.Pipeline):
        assert pipeline_base.status == pixie16.pipeline.Status.READY
        pipeline_base.handle_error(Exception)
        assert pipeline_base.status == pixie16.pipeline.Status.ERROR

    @staticmethod
    def test_handle_finished(pipeline_base: pixie16.pipeline.Pipeline):
        assert pipeline_base.status == pixie16.pipeline.Status.READY
        pipeline_base.handle_finished()
        assert pipeline_base.status == pixie16.pipeline.Status.FINISHED

    @staticmethod
    def test_handle_report_valid(pipeline_created: pixie16.pipeline.Pipeline):
        assert "DummyTask" not in pipeline_created.reports
        pipeline_created.handle_report("DummyTask", {})
        assert "DummyTask" in pipeline_created.reports

    @staticmethod
    def test_handle_report_invalid(pipeline_base: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_base.handle_report("DummyTask", {})

    @staticmethod
    def test_handle_print_edge(pipeline_created: pixie16.pipeline.Pipeline):
        pipeline_created.handle_print("DummyTask", "", "")

    @staticmethod
    def test_handle_print_valid(pipeline_created: pixie16.pipeline.Pipeline):
        pipeline_created.handle_print("DummyTask", "A", "B")

    @staticmethod
    def test_handle_print_invalid(pipeline_base: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_base.handle_print("DummyTask", "", "")

    @staticmethod
    def test_send_connect_valid(
        pipeline_created: pixie16.pipeline.Pipeline, push: tuple[str, zmq.Socket]
    ):
        address_push, socket_push = push
        pipeline_created.send_connect("DummyTask", address_push, False, False)

    @staticmethod
    def test_send_connect_invalid(
        pipeline_base: pixie16.pipeline.Pipeline, push: tuple[str, zmq.Socket]
    ):
        address_push, socket_push = push
        with pytest.raises(ValueError):
            pipeline_base.send_connect("DummyTask", address_push, False, False)

    @staticmethod
    def test_send_disconnect_valid(pipeline_created: pixie16.pipeline.Pipeline):
        pipeline_created.send_disconnect("DummyTask")

    @staticmethod
    def test_send_disconnect_invalid(pipeline_base: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_base.send_disconnect("DummyTask")

    @staticmethod
    def test_send_start_valid(pipeline_created: pixie16.pipeline.Pipeline):
        pipeline_created.send_start("DummyTask")

    @staticmethod
    def test_send_start_invalid(pipeline_base: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_base.send_start("DummyTask")

    @staticmethod
    def test_send_pause_valid(pipeline_created: pixie16.pipeline.Pipeline):
        pipeline_created.send_pause("DummyTask")

    @staticmethod
    def test_send_pause_invalid(pipeline_base: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_base.send_pause("DummyTask")

    @staticmethod
    def test_send_stop_valid(pipeline_created: pixie16.pipeline.Pipeline):
        pipeline_created.send_stop("DummyTask")

    @staticmethod
    def test_send_stop_invalid(pipeline_base: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_base.send_stop("DummyTask")

    @staticmethod
    def test_send_configure_valid(pipeline_created: pixie16.pipeline.Pipeline):
        pipeline_created.send_configure("DummyTask", {})

    @staticmethod
    def test_send_configure_invalid(pipeline_base: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_base.send_configure("DummyTask", {})

    @staticmethod
    def test_send_finished_valid(pipeline_created: pixie16.pipeline.Pipeline):
        pipeline_created.send_finished("DummyTask")

    @staticmethod
    def test_send_finished_invalid(pipeline_base: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_base.send_finished("DummyTask")

    @staticmethod
    def test_init_edge(pipeline_base: pixie16.pipeline.Pipeline):
        pipeline_base.init([])

    @staticmethod
    def test_init_valid(pipeline_created: pixie16.pipeline.Pipeline):
        pipeline_created.init(["DummyTask"])

    @staticmethod
    def test_init_invalid(pipeline_base: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_base.init([" "])

    @staticmethod
    def test_start(pipeline_dummy: pixie16.pipeline.Pipeline):
        pipeline_dummy.start()

    @staticmethod
    def test_pause(pipeline_dummy: pixie16.pipeline.Pipeline):
        pipeline_dummy.pause()

    @staticmethod
    def test_stop(pipeline_dummy: pixie16.pipeline.Pipeline):
        pipeline_dummy.stop()

    @staticmethod
    def test_configure(pipeline_dummy: pixie16.pipeline.Pipeline):
        pipeline_dummy.configure({})

    @staticmethod
    def test_poll_dummy(pipeline_dummy: pixie16.pipeline.Pipeline):
        pipeline_dummy.poll(is_block=False)

    @staticmethod
    def test_poll_print(pipeline_print: pixie16.pipeline.Pipeline):
        pipeline_print.poll(is_block=False)

    # @staticmethod
    # def test_poll_error(pipeline_error: pixie16.pipeline.Pipeline):
    # pipeline_error.poll(is_block=False)
