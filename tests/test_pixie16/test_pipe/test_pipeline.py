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

    def do_work(self, value) -> None:
        self.send_print("Hi", "Err")
        self.send_report({})


@pytest.fixture
def context() -> zmq.Context:
    context = zmq.Context()
    yield context
    context.term()


@pytest.fixture
def pull(context: zmq.Context) -> tuple[str, zmq.Socket]:
    socket = context.socket(zmq.PAIR)
    address = socket.bind_to_random_port("tcp://127.0.0.1")
    address = f"tcp://127.0.0.1:{address}"

    yield address, socket

    socket.close()


class Test_Pipeline:
    @staticmethod
    def test___init__():
        pixie16.pipeline.Pipeline()

    @staticmethod
    def test_create_task():
        pipeline = pixie16.pipeline.Pipeline()
        pipeline.create_task("DummyTask")
        pipeline._tasks_all["DummyTask"].kill()

    @staticmethod
    def test_handle_report_A():
        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init(["DummyTask"])
        pipeline.start()
        time.sleep(1)
        pipeline.stop()

    @staticmethod
    def test_handle_report_B():
        pipeline = pixie16.pipeline.Pipeline()
        with pytest.raises(ValueError):
            pipeline.handle_report("Nope", {})

    @staticmethod
    def test_handle_print_A():
        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init(["DummyTask"])
        pipeline.start()
        time.sleep(1)
        pipeline.stop()

    @staticmethod
    def test_handle_print_B():
        pipeline = pixie16.pipeline.Pipeline()
        with pytest.raises(ValueError):
            pipeline.handle_print("Nope", io.StringIO("out"), io.StringIO("err"))

    @staticmethod
    def test_send_connect_A(pull: tuple[str, zmq.Socket]):
        address_pull, socket_pull = pull

        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init(["DummyTask"])
        pipeline.start()
        pipeline.send_connect("DummyTask", address_pull, False, False)
        pipeline.stop()

    @staticmethod
    def test_send_connect_B(pull: tuple[str, zmq.Socket]):
        address_pull, socket_pull = pull

        pipeline = pixie16.pipeline.Pipeline()
        with pytest.raises(ValueError):
            pipeline.send_connect("Nope", address_pull, False, False)

    @staticmethod
    def test_send_disconnect_A():
        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init(["DummyTask"])
        pipeline.start()
        pipeline.send_disconnect("DummyTask")
        pipeline.stop()

    @staticmethod
    def test_send_disconnect_B(pull: tuple[str, zmq.Socket]):
        address_pull, socket_pull = pull

        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init(["DummyTask"])
        pipeline.start()
        pipeline.send_connect("DummyTask", address_pull, False, False)
        pipeline.send_disconnect("DummyTask")
        pipeline.stop()

    @staticmethod
    def test_send_disconnect_C():
        pipeline = pixie16.pipeline.Pipeline()
        with pytest.raises(ValueError):
            pipeline.send_disconnect("Nope")

    @staticmethod
    def test_send_start_A():
        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init(["DummyTask"])
        pipeline.start()
        pipeline.send_start("DummyTask")
        pipeline.stop()

    @staticmethod
    def test_send_start_B():
        pipeline = pixie16.pipeline.Pipeline()
        with pytest.raises(ValueError):
            pipeline.send_start("Nope")

    @staticmethod
    def test_send_pause_A():
        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init(["DummyTask"])
        pipeline.start()
        pipeline.send_pause("DummyTask")
        pipeline.stop()

    @staticmethod
    def test_send_pause_B():
        pipeline = pixie16.pipeline.Pipeline()
        with pytest.raises(ValueError):
            pipeline.send_pause("Nope")

    @staticmethod
    def test_send_stop_A():
        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init(["DummyTask"])
        pipeline.start()
        pipeline.send_stop("DummyTask")
        pipeline.stop()

    @staticmethod
    def test_send_stop_B():
        pipeline = pixie16.pipeline.Pipeline()
        with pytest.raises(ValueError):
            pipeline.send_stop("Nope")

    @staticmethod
    def test_send_configure_A():
        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init(["DummyTask"])
        pipeline.start()
        pipeline.send_configure("DummyTask", {})
        pipeline.stop()

    @staticmethod
    def test_send_configure_B():
        pipeline = pixie16.pipeline.Pipeline()
        with pytest.raises(ValueError):
            pipeline.send_configure("Nope", {})

    @staticmethod
    def test_init_A():
        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init(["DummyTask"])
        pipeline.stop()

    @staticmethod
    def test_init_B():
        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init([])
        pipeline.stop()

    @staticmethod
    def test_start():
        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init(["DummyTask"])
        pipeline.start()
        pipeline.stop()

    @staticmethod
    def test_pause():
        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init(["DummyTask"])
        pipeline.pause()
        pipeline.stop()

    @staticmethod
    def test_start():
        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init(["DummyTask"])
        pipeline.stop()

    @staticmethod
    def test_configure():
        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init(["DummyTask"])
        pipeline.configure({})
        pipeline.stop()

    @staticmethod
    def test_poll():
        pipeline = pixie16.pipeline.Pipeline()
        pipeline.init(["DummyTask"])
        pipeline.start()
        pipeline.poll()
        pipeline.stop()
