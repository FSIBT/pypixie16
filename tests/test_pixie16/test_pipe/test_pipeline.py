import io
import time

import zmq
import pytest

import pixie16


class DummyTask(pixie16.pipeline.Task):
    def do_startup(self) -> None:
        pass

    def do_cleanup(self) -> None:
        pass

    def do_work(self) -> None:
        self.send_print("Hi", "Err")
        self.send_report({})


@pytest.fixture
def context() -> zmq.Context:
    context = zmq.Context()
    yield context
    context.term()


@pytest.fixture
def task() -> pixie16.pipeline.Task:
    task = DummyTask("Hello")
    yield task
    task.kill()


@pytest.fixture
def pipeline_b(task: pixie16.pipeline.Task) -> pixie16.pipeline.Pipeline:
    pipeline = pixie16.pipeline.Pipeline(task)
    yield pipeline
    pipeline.stop()


@pytest.fixture
def pipeline_i(pipeline_b: pixie16.pipeline.Pipeline) -> pixie16.pipeline.Pipeline:
    pipeline_b.init(["Hello"])
    yield pipeline_b
    pipeline_b.stop()


@pytest.fixture
def pipeline_s(pipeline_i: pixie16.pipeline.Pipeline) -> pixie16.pipeline.Pipeline:
    pipeline_i.start()
    yield pipeline_i
    pipeline_i.stop()
    assert pipeline_i._status == pixie16.pipeline.Status.DONE


@pytest.fixture
def pull(context: zmq.Context) -> tuple[str, zmq.Socket]:
    socket = context.socket(zmq.PAIR)
    address = socket.bind_to_random_port("tcp://127.0.0.1")
    address = f"tcp://127.0.0.1:{address}"

    yield address, socket

    socket.close()


class Test_Pipeline:
    @staticmethod
    def test___init__(task: pixie16.pipeline.Task):
        pixie16.pipeline.Pipeline(task)

    @staticmethod
    def test_handle_report_A(pipeline_s: pixie16.pipeline.Pipeline):
        time.sleep(1)

    @staticmethod
    def test_handle_report_B(pipeline_s: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_s.handle_report("Nope", {})

    @staticmethod
    def test_handle_print_A(pipeline_s: pixie16.pipeline.Pipeline):
        time.sleep(1)

    @staticmethod
    def test_handle_print_B(pipeline_s: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_s.handle_print("Nope", io.StringIO("out"), io.StringIO("err"))

    @staticmethod
    def test_send_connect_A(
        pipeline_s: pixie16.pipeline.Pipeline, pull: tuple[str, zmq.Socket]
    ):
        address_pull, socket_pull = pull

        pipeline_s.send_connect("Hello", address_pull)

    @staticmethod
    def test_send_connect_B(
        pipeline_s: pixie16.pipeline.Pipeline, pull: tuple[str, zmq.Socket]
    ):
        address_pull, socket_pull = pull

        with pytest.raises(ValueError):
            pipeline_s.send_connect("Nope", address_pull)

    @staticmethod
    def test_send_disconnect_A(
        pipeline_s: pixie16.pipeline.Pipeline,
    ):
        pipeline_s.send_disconnect("Hello")

    @staticmethod
    def test_send_disconnect_B(
        pipeline_s: pixie16.pipeline.Pipeline, pull: tuple[str, zmq.Socket]
    ):
        address_pull, socket_pull = pull

        pipeline_s.send_connect("Hello", address_pull)
        pipeline_s.send_disconnect("Hello")

    @staticmethod
    def test_send_disconnect_C(pipeline_s: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_s.send_disconnect("Nope")

    @staticmethod
    def test_send_start_A(pipeline_s: pixie16.pipeline.Pipeline):
        pipeline_s.send_start("Hello")

    @staticmethod
    def test_send_start_B(pipeline_s: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_s.send_start("Nope")

    @staticmethod
    def test_send_pause_A(pipeline_s: pixie16.pipeline.Pipeline):
        pipeline_s.send_pause("Hello")

    @staticmethod
    def test_send_pause_B(pipeline_s: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_s.send_pause("Nope")

    @staticmethod
    def test_send_stop_A(pipeline_s: pixie16.pipeline.Pipeline):
        pipeline_s.send_stop("Hello")

    @staticmethod
    def test_send_stop_B(pipeline_s: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_s.send_stop("Nope")

    @staticmethod
    def test_send_configure_A(pipeline_s: pixie16.pipeline.Pipeline):
        pipeline_s.send_configure("Hello", {})

    @staticmethod
    def test_send_configure_B(pipeline_s: pixie16.pipeline.Pipeline):
        with pytest.raises(ValueError):
            pipeline_s.send_configure("Nope", {})

    @staticmethod
    def test_init_A(pipeline_b: pixie16.pipeline.Pipeline):
        pipeline_b.init(["Hello"])

    @staticmethod
    def test_init_B(pipeline_b: pixie16.pipeline.Pipeline):
        pipeline_b.init([])

    @staticmethod
    def test_start(pipeline_i: pixie16.pipeline.Pipeline):
        pipeline_i.start()

    @staticmethod
    def test_pause(pipeline_i: pixie16.pipeline.Pipeline):
        pipeline_i.pause()

    @staticmethod
    def test_start(pipeline_i: pixie16.pipeline.Pipeline):
        pipeline_i.stop()

    @staticmethod
    def test_configure(pipeline_i: pixie16.pipeline.Pipeline):
        pipeline_i.configure({})

    @staticmethod
    def test_poll(pipeline_i: pixie16.pipeline.Pipeline):
        pipeline_i.poll()
