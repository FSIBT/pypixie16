import io
import time
import typing
import pickle

import zmq
import pytest

import pixie16


class DummyTask(pixie16.pipeline.Task):
    def do_startup(self):
        pass

    def do_cleanup(self):
        pass

    def do_work(self):
        if len(self.queue):
            self.queue.popleft()


def do_work_report(self):
    self.send_report({})


def do_work_print(self):
    self.send_print("Hi", "Err")


def do_work_data(self):
    self.send_data([0, 1, 2])


@pytest.fixture
def socket() -> tuple[zmq.Socket, str]:
    context = zmq.Context()
    socket = context.socket(zmq.ROUTER)
    address = socket.bind_to_random_port("tcp://127.0.0.1")
    address = f"tcp://127.0.0.1:{address}"

    return socket, address


@pytest.fixture
def task(socket: tuple[zmq.Socket, str]) -> pixie16.pipeline.Task:
    socket, address = socket

    return DummyTask("Hello", address)


class Test_Task:
    def test__init(self):
        DummyTask("Hello", "tcp://127.0.0.1:1234")

    def test_do_startup(self, task: pixie16.pipeline.Task):
        task.do_startup()

    def test_do_cleanup(self, task: pixie16.pipeline.Task):
        task.do_cleanup()

    def test_do_work(self, task: pixie16.pipeline.Task):
        task.do_work()

    def test_handle_connect(
        self, task: pixie16.pipeline.Task, socket: tuple[zmq.Socket, str]
    ):
        task.start()
        socket, address = socket
        socket.recv_multipart()

        msg = pickle.dumps(pixie16.pipeline.Message.CONNECT("tcp://127.0.0.1:1534"))
        socket.send_multipart([task.name.encode(), msg])

        msg = pickle.dumps(pixie16.pipeline.Message.STOP)
        socket.send_multipart([task.name.encode(), msg])

        task.join()
        task.close()

    def test_handle_disconnect(
        self, task: pixie16.pipeline.Task, socket: tuple[zmq.Socket, str]
    ):
        task.start()
        socket, address = socket
        socket.recv_multipart()

        msg = pickle.dumps(pixie16.pipeline.Message.CONNECT("tcp://127.0.0.1:1534"))
        socket.send_multipart([task.name.encode(), msg])

        msg = pickle.dumps(pixie16.pipeline.Message.CONNECT("tcp://127.0.0.1:1534"))
        socket.send_multipart([task.name.encode(), msg])

        msg = pickle.dumps(pixie16.pipeline.Message.DISCONNECT)
        socket.send_multipart([task.name.encode(), msg])

        msg = pickle.dumps(pixie16.pipeline.Message.STOP)
        socket.send_multipart([task.name.encode(), msg])

        task.join()
        task.close()

    def test_handle_start(
        self, task: pixie16.pipeline.Task, socket: tuple[zmq.Socket, str]
    ):
        task.start()
        socket, address = socket
        socket.recv_multipart()

        msg = pickle.dumps(pixie16.pipeline.Message.START)
        socket.send_multipart([task.name.encode(), msg])

        msg = pickle.dumps(pixie16.pipeline.Message.STOP)
        socket.send_multipart([task.name.encode(), msg])

        task.join()
        task.close()

    def test_handle_pause(
        self, task: pixie16.pipeline.Task, socket: tuple[zmq.Socket, str]
    ):
        task.start()
        socket, address = socket
        socket.recv_multipart()

        msg = pickle.dumps(pixie16.pipeline.Message.PAUSE)
        socket.send_multipart([task.name.encode(), msg])

        msg = pickle.dumps(pixie16.pipeline.Message.STOP)
        socket.send_multipart([task.name.encode(), msg])

        task.join()
        task.close()

    def test_handle_stop(
        self, task: pixie16.pipeline.Task, socket: tuple[zmq.Socket, str]
    ):
        task.start()
        socket, address = socket
        socket.recv_multipart()

        msg = pickle.dumps(pixie16.pipeline.Message.STOP)
        socket.send_multipart([task.name.encode(), msg])

        task.join()
        task.close()

    def test_handle_configure(
        self, task: pixie16.pipeline.Task, socket: tuple[zmq.Socket, str]
    ):
        task.start()
        socket, address = socket
        socket.recv_multipart()

        msg = pickle.dumps(pixie16.pipeline.Message.CONFIGURE({}))
        socket.send_multipart([task.name.encode(), msg])

        msg = pickle.dumps(pixie16.pipeline.Message.STOP)
        socket.send_multipart([task.name.encode(), msg])

        task.join()
        task.close()

    def test_send_report(
        self, task: pixie16.pipeline.Task, socket: tuple[zmq.Socket, str]
    ):
        task.do_work = do_work_report
        task.queue.append("Hi")
        task.start()
        socket, address = socket
        socket.recv_multipart()

        msg = pickle.dumps(pixie16.pipeline.Message.START)
        task.do_work = do_work_report

        msg = pickle.dumps(pixie16.pipeline.Message.STOP)
        socket.send_multipart([task.name.encode(), msg])

        task.join()
        task.close()

    def test_send_print(
        self, task: pixie16.pipeline.Task, socket: tuple[zmq.Socket, str]
    ):
        task.do_work = do_work_print
        task.queue.append("Hi")
        task.start()
        socket, address = socket
        socket.recv_multipart()

        msg = pickle.dumps(pixie16.pipeline.Message.START)
        task.do_work = do_work_print

        msg = pickle.dumps(pixie16.pipeline.Message.STOP)
        socket.send_multipart([task.name.encode(), msg])

        task.join()
        task.close()

    def test_send_data(
        self, task: pixie16.pipeline.Task, socket: tuple[zmq.Socket, str]
    ):
        task.do_work = do_work_data
        task.queue.append("Hi")
        task.start()
        socket, address = socket
        socket.recv_multipart()

        msg = pickle.dumps(pixie16.pipeline.Message.START)
        task.do_work = do_work_data

        msg = pickle.dumps(pixie16.pipeline.Message.STOP)
        socket.send_multipart([task.name.encode(), msg])

        task.join()
        task.close()
