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

    def do_startup(self):
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

    @staticmethod
    def test___init__():
        task = DummyTask()
        assert task.name == task.__class__.__name__
        assert task.error is None
        assert not task._kill
        assert task.queue == collections.deque()
        assert task.status == pixie16.pipeline.Status.WAITING
        assert task.config == {}
        assert not task.is_start
        assert not task.is_final
        assert task.context is None
        assert task.socket_pull is None
        assert task.socket_push is None
        assert task.socket_dealer is None
        assert task.address_pull is None
        assert task.address_push is None
        assert task.address_router is None

    @staticmethod
    def test_do_report(task_a: pixie16.pipeline.Task):
        task_a.do_report()

    @staticmethod
    def test_do_configure(task_a: pixie16.pipeline.Task):
        task_a.do_configure({})

    @staticmethod
    def test_do_startup(task_a: pixie16.pipeline.Task):
        task_a.do_startup()

    @staticmethod
    def test_do_cleanup(task_a: pixie16.pipeline.Task):
        task_a.do_cleanup()

    # @staticmethod
    # def test_do_work(task_a: pixie16.pipeline.Task):
    # task_a.do_work()

    @staticmethod
    def test_handle_connect_valid_A(
        task_a: pixie16.pipeline.Task, push: tuple[str, zmq.Socket]
    ):
        address_push, socket_push = push
        assert task_a.address_pull is None
        assert not task_a.is_start
        assert not task_a.is_final
        task_a.handle_connect(address_push, True, True)
        assert task_a.address_pull == address_push
        assert task_a.is_start
        assert task_a.is_final

    @staticmethod
    def test_handle_connect_valid_B(
        task_a: pixie16.pipeline.Task, push: tuple[str, zmq.Socket]
    ):
        address_push, socket_push = push
        assert task_a.address_pull is None
        assert not task_a.is_start
        assert not task_a.is_final
        task_a.handle_connect(None, True, True)
        assert task_a.address_pull is None
        assert task_a.is_start
        assert task_a.is_final

    @staticmethod
    def test_handle_disconnect_valid_A(
        task_a: pixie16.pipeline.Task, push: tuple[str, zmq.Socket]
    ):
        address_push, socket_push = push
        task_a.handle_connect(address_push, True, True)
        assert task_a.address_pull == address_push
        assert task_a.is_start
        assert task_a.is_final
        task_a.handle_disconnect()
        assert task_a.address_pull is None
        assert not task_a.is_start
        assert not task_a.is_final

    @staticmethod
    def test_handle_disconnect_valid_B(task_a: pixie16.pipeline.Task):
        assert task_a.address_pull is None
        assert not task_a.is_start
        assert not task_a.is_final
        task_a.handle_disconnect()
        assert task_a.address_pull is None
        assert not task_a.is_start
        assert not task_a.is_final

    @staticmethod
    def test_handle_start(task_a: pixie16.pipeline.Task):
        assert task_a.status == pixie16.pipeline.Status.WAITING
        task_a.handle_start()
        assert task_a.status == pixie16.pipeline.Status.RUNNING

    @staticmethod
    def test_handle_stop(task_a: pixie16.pipeline.Task):
        assert not task_a._kill
        task_a.handle_stop()
        assert task_a._kill

    @staticmethod
    def test_handle_configure_valid_A(task_a: pixie16.pipeline.Task):
        assert task_a.config == {}
        task_a.handle_configure({"Hi": "Hello"})
        assert task_a.config == {"Hi": "Hello"}

    @staticmethod
    def test_handle_configure_valid_B(task_b: pixie16.pipeline.Task):
        assert task_b.status == pixie16.pipeline.Status.WAITING
        assert task_b.error is None
        assert task_b.config == {}
        task_b.handle_configure({"Hi": "Hello"})
        assert task_b.status == pixie16.pipeline.Status.PANICKING
        assert task_b.error is not None
        assert task_b.config == {"Hi": "Hello"}

    @staticmethod
    def test_handle_data(task_a: pixie16.pipeline.Task):
        assert len(task_a.queue) == 0
        task_a.handle_data("Hi")
        assert len(task_a.queue) == 1

    # @staticmethod
    # def test_handle_finished(task_a: pixie16.pipeline.Task):
    # task_a.handle_finished()

    # @staticmethod
    # def test_send_report(task_a: pixie16.pipeline.Task):
    # task_a.send_report()

    # @staticmethod
    # def test_send_print(task_a: pixie16.pipeline.Task):
    # task_a.send_print()

    # @staticmethod
    # def test_send_data(task_a: pixie16.pipeline.Task):
    # task_a.send_data()

    # @staticmethod
    # def test_send_finished(task_a: pixie16.pipeline.Task):
    # task_a.send_finished()

    # @staticmethod
    # def test_poll(task_a: pixie16.pipeline.Task):
    # task_a.poll()

    # @staticmethod
    # def test_run(task_a: pixie16.pipeline.Task):
    # task_a.run()
