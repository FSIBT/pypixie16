import io
import time
import typing
import pickle
import collections

import zmq
import pytest

import pixie16


class DummyTask(pixie16.pipeline.Task):
    def do_work(self, value):
        pass


class ErrorTask(pixie16.pipeline.Task):
    def do_cleanup(self):
        raise Exception

    def do_init(self):
        raise Exception

    def do_report(self):
        raise Exception

    def do_configure(self):
        raise Exception

    def do_work(self, value):
        raise Exception


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
def task_a(
    router: tuple[str, zmq.Socket],
    dealer: tuple[str, zmq.Socket],
    pull: tuple[str, zmq.Socket],
    push: tuple[str, zmq.Socket],
) -> pixie16.pipeline.Task:
    address_router, socket_router = router
    address_dealer, socket_dealer = dealer
    address_pull, socket_pull = pull
    address_push, socket_push = push

    task_a = DummyTask()

    task_a.socket_dealer = socket_dealer
    task_a.address_router = address_router
    task_a.socket_pull = socket_pull
    task_a.socket_push = socket_push
    task_a.address_push = address_push

    return task_a


@pytest.fixture
def task_b(
    router: tuple[str, zmq.Socket],
    dealer: tuple[str, zmq.Socket],
    pull: tuple[str, zmq.Socket],
    push: tuple[str, zmq.Socket],
) -> pixie16.pipeline.Task:
    address_router, socket_router = router
    address_dealer, socket_dealer = dealer
    address_pull, socket_pull = pull
    address_push, socket_push = push

    task_b = ErrorTask()

    task_b.socket_dealer = socket_dealer
    task_b.address_router = address_router
    task_b.socket_pull = socket_pull
    task_b.socket_push = socket_push
    task_b.address_push = address_push

    return task_b


class Test_Task:
    # @staticmethod
    # def test___init_subclass__():
    # pass

    def test___init__(self):
        DummyTask()
