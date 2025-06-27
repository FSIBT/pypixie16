import io
import time
import typing
import pickle

import zmq
import pytest

import pixie16


class DummyTask(pixie16.pipeline.Task):
    def do_work(self, value):
        if len(self.queue):
            self.queue.popleft()


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
def push(context: zmq.Context) -> tuple[str, zmq.Socket]:
    socket = context.socket(zmq.PAIR)
    address = socket.bind_to_random_port("tcp://127.0.0.1")
    address = f"tcp://127.0.0.1:{address}"

    yield address, socket

    socket.close()


@pytest.fixture
def pull(context: zmq.Context) -> tuple[str, zmq.Socket]:
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
def task(
    router: tuple[str, zmq.Socket],
    dealer: tuple[str, zmq.Socket],
    pull: tuple[str, zmq.Socket],
    push: tuple[str, zmq.Socket],
) -> pixie16.pipeline.Task:
    address_router, socket_router = router
    address_dealer, socket_dealer = dealer
    address_pull, socket_pull = pull
    address_push, socket_push = push

    task = DummyTask()
    task.socket_dealer = socket_dealer
    task.address_router = address_router
    task.socket_pull = socket_pull
    task.address_pull = address_pull
    task.socket_push = socket_push
    task.address_push = address_push

    return task


class Test_Task:
    @staticmethod
    def test___init__():
        DummyTask()

    @staticmethod
    def test_do_startup(task: pixie16.pipeline.Task):
        task.do_startup()

    @staticmethod
    def test_do_cleanup(task: pixie16.pipeline.Task):
        task.do_cleanup()

    @staticmethod
    def test_do_work(task: pixie16.pipeline.Task):
        task.do_work(None)

    @staticmethod
    def test_handle_connect(task: pixie16.pipeline.Task, pull: tuple[str, zmq.Socket]):
        address_pull, socket_pull = pull

        task.handle_connect(address_pull, False, False)

    @staticmethod
    def test_handle_disconnect_A(
        task: pixie16.pipeline.Task, pull: tuple[str, zmq.Socket]
    ):
        address_pull, socket_pull = pull

        task.handle_disconnect()

    @staticmethod
    def test_handle_disconnect_B(
        task: pixie16.pipeline.Task, pull: tuple[str, zmq.Socket]
    ):
        address_pull, socket_pull = pull

        task.handle_connect(address_pull, False, False)
        task.handle_disconnect()

    @staticmethod
    def test_handle_start(task: pixie16.pipeline.Task):
        task.handle_start()

    @staticmethod
    def test_handle_pause(task: pixie16.pipeline.Task):
        task.handle_pause()

    @staticmethod
    def test_handle_stop(task: pixie16.pipeline.Task):
        task.handle_stop()

    @staticmethod
    def test_handle_configure(task: pixie16.pipeline.Task):
        task.handle_configure({})

    # @staticmethod
    # def test_send_report(task: pixie16.pipeline.Task):
    # task.send_report()

    # @staticmethod
    # def test_send_print(task: pixie16.pipeline.Task):
    # task.send_print('Hi', 'Hi')

    # @staticmethod
    # def test_send_data(task: pixie16.pipeline.Task):
    # task.send_data('Hi')
