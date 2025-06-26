import io
import abc
import sys
import time
import typing
import pickle
import contextlib
import collections
import multiprocessing

import zmq
import psutil

from .status import Status
from .message import Message


class Task(multiprocessing.Process, abc.ABC):
    """
    Represents pausable, custom processes that intergrate into ``Pipeline``.

    Since ``Task`` extends ``multiprocessing.Process``, tasks behave like state
    machines. They have the following states:

    * ▶️ RUNNING: Processing data.
    * ⏸️ PAUSED: Waiting to process data.
    * 🆒 DONE: Done processing data.
    * ✅ READY: Process initialized.
    * 🆘 ERROR: Failing to process data.

    Tasks uses ZMQ Push/Pull sockets to get and send messages between other
    tasks and the pipeline. Tasks send and recieve the following kinds of
    messages between themselves and the pipeline.

    * PIPELINE-TO-TASK:
        * 🔁 CONNECT: Connect to given ZMQ push queue.
        * 🔀 DISCONNECT: Disconnect from the ZMQ push queue.
        * ▶️ START: Change status to RUNNING.
        * ⏸️ PAUSE: Change status to PAUSED.
        * ⏹️ STOP: Change status to FINISHED.
        * ℹ️ CONFIGURE: Update parameters.
    * TASK-TO-PIPELINE:
        * 🆗 REPORT: Transmit status to pipeline.
        * 🔣 PRINT: Print to stdout/stderr.
    * TASK-TO-TASK:
        * 📶 DATA: Transmit data to next task.

    Since ``Task`` extends ``abc.ABC``, it has methods that must be
    overwritten, i.e. the "do" methods:

    * ``do_work``: Tasks call this function continuously in RUNNING status when
    there the queue has data. This function runs in a parallel subthread.
    * ``do_startup``: Before running and initializing the ZMQ sockets, tasks
    call this function to open files, call ``init_and_boot``.
    * ``do_cleanup``: Before sending their final report, tasks call this
    function to close files, etc.

    Tasks are meant to be created at the beginning of a program and then
    re-used.  You can daisychain them together in different ways for
    each run by reassigning the push/pull connections.

    Attributes:
        name: Task alias.
        queue: Task buffer.
        config: Task parameters.
        status: Task state.
        context: ZMQ context.
        socket_pull: ZMQ pull socket.
        socket_push: ZMQ push socket.
        socket_dealer: ZMQ dealer socket.
        address_pull: ZMQ pull socket address.
        address_push: ZMQ push socket address.
        address_router: ZMQ dealer socket address.
        class_registry: Registry of subclasses.

    Notes:
        The ``tasks`` subpackage contains specific, concrete, generic tasks,
        such as ``GatherData`` and ``DummyData``.

        Tasks caputre output to ``sys.stdout`` or ``sys.stderr`` in
        ``do_work``, ``startup``, and ``cleanup`` and PRINT messages them to
        the pipeline.
    """

    class_registry = {}

    def __init_subclass__(cls, **kwargs):
        """
        Stores subclasses in ``class_registry``.
        """

        super().__init_subclass__(**kwargs)
        Task.class_registry[cls.__name__] = cls

    def __init__(self):
        """
        Initializes ``Task``.

        Parameters:
            name: Task name.
            address_pull: ZMQ pull socket address.

        Note:
            This function runs in the main process.
        """

        super().__init__()

        self.name: str = self.__class__.__name__
        self.error: Exception = None
        self._kill: bool = False
        self.queue: collections.deque = collections.deque()
        self.status: Status = Status.READY
        self.config: dict[str, typing.Any] = {
            "is_final": False,
            "is_start": False,
        }

        # ZMQ fields:
        self.context: zmq.Context = None
        self.socket_pull: zmq.Socket = None
        self.socket_push: zmq.Socket = None
        self.socket_dealer: zmq.Socket = None
        self.address_pull: str = None
        self.address_push: str = None
        self.address_router: str = None

    def do_report(self) -> dict:
        """
        Generates reports to the pipeline.

        Note:
            This function runs in the subprocess, and should be overwritten.
        """

        return {}

    def do_startup(self) -> None:
        """
        Called after initialization.

        Note:
            This function runs in the subprocess, and should be overwritten.
        """

        pass

    def do_cleanup(self) -> None:
        """
        Called after termination.

        Note:
            This function runs in the subprocess, and should be overwritten.
        """

        pass

    @abc.abstractmethod
    def do_work(self, value: typing.Any = None) -> None:
        """
        Performs the task and processes data.

        When finished, update ``self.status`` to FINISHED and return. To pause
        change the status to PAUSED and return. To throw an exception, raise
        errors as usual or update ``self.status`` to ERROR and return.

        Warning:
            Tasks use cooperative multitasking, so return to recieve
            communications from other tasks and the pipeline: pop data
            off the queue, processes it, and return. Task runtimes will call
            ``do_work`` repeatedly while the task has the RUNING status and the
            queue has data.

        Note:
            This function runs in the subprocess.
        """

        raise NotImplementedError

    def handle_connect(self, address_pull: str) -> None:
        """
        Handles ``CONNECT`` messages from the pipeline.

        Parameters:
            address_pull: ZMQ pull socket address.
        """

        self.socket_pull.connect(address_pull)
        self.address_pull = address_pull

    def handle_disconnect(self) -> None:
        """
        Handles ``DISCONNECT`` messages from the pipeline.

        Note:
            This function runs in the subprocess.
        """

        if self.address_pull:
            self.socket_pull.disconnect(self.address_pull)
        self.address_pull = None

    def handle_start(self) -> None:
        """
        Handles ``START`` messages from the pipeline.

        Note:
            This function runs in the subprocess.
        """

        self.status = Status.RUNNING

    def handle_pause(self) -> None:
        """
        Handles ``PAUSE`` messages from the pipeline.

        Note:
            This function runs in the subprocess.
        """

        self.status = Status.PAUSED

    def handle_stop(self) -> None:
        """
        Handles ``STOP`` messages from the pipeline.

        Note:
            This function runs in the subprocess.
        """

        self._kill = True

    def handle_configure(self, config: dict[str, typing.Any]) -> None:
        """
        Handles ``CONFIGURE`` messages from the pipeline.

        Parameters:
            config: Recieved parameters.

        Note:
            This function runs in the subprocess.
        """

        self.config |= config

    def handle_data(self, data: typing.Any) -> None:
        """
        Handles ``DATA`` message from the pervious task.

        Parameter:
            data: Recieved data.
        """

        self.queue.append(data)

    def handle_finished(self) -> None:
        """
        Handles ``FINISHED`` messages from the previous task.
        """

        while self.queue:
            self.poll()

            try:
                val = self.queue.popleft() if self.queue else None
                ret = self.do_work(val)
                self.send_data(ret)
            except Exception as err:
                self.status = Status.ERROR
                self.error = err

        self.send_finished()

    def send_report(self) -> None:
        """
        Sends ``REPORT`` messages to the pipeline.

        Note:
            This function runs in the subprocess.
        """

        report = self.do_report()
        report |= {
            "name": self.name,
            "error": self.error,
            "config": self.config,
            "status": self.status,
            "address_pull": self.address_pull,
            "address_push": self.address_push,
            "address_router": self.address_router,
            "sys_cpu_count": psutil.cpu_count(),
            "sys_cpu_times": psutil.cpu_times(),
            "sys_cpu_percent": psutil.cpu_percent(interval=0.1),
            "sys_cpu_stats": psutil.cpu_stats(),
            "sys_mem_virtual": psutil.virtual_memory(),
            "sys_mem_swap": psutil.swap_memory(),
            "ps": psutil.Process().as_dict(),
        }

        msg = pickle.dumps(Message.REPORT(report), protocol=pickle.HIGHEST_PROTOCOL)
        self.socket_dealer.send(msg)

    def send_print(self, stdout: str, stderr: str) -> None:
        """
        Sends ``PRINT`` messages to the pipeline.

        Parameters:
            stdout: Captured stdout to send.
            stderr: Captured stderr to send.

        Note:
            This function runs in the subprocess.
        """

        msg = pickle.dumps(
            Message.PRINT(stdout, stderr), protocol=pickle.HIGHEST_PROTOCOL
        )
        self.socket_dealer.send(msg)

    def send_data(self, data: typing.Any) -> None:
        """
        Sends ``DATA`` messages to the next task.

        Parameters:
            data: Sent data.

        Note:
            This function runs in the subprocess.
        """

        msg = Message.DATA(data)
        if not self.config["is_final"] and data:
            self.socket_push.send_pyobj(msg)

    def send_finished(self) -> None:
        """
        Sends ``FINISHED`` messages to the next task.

        Note:
            This function runs in the subprocess.
        """

        self.status = Status.FINISHED
        self.send_report()

        msg = Message.FINISHED
        if not self.config["is_final"]:
            self.socket_push.send_pyobj(msg)

    def poll(self, is_noblock: bool = True) -> None:
        """
        Polls the sockets, checking for and processing messages, without blocking.

        Parameter:
            is_noblock: Block/no block flag.
        """

        # Processing messages from pipeline.
        try:
            if is_noblock:
                msg = self.socket_dealer.recv(flags=zmq.NOBLOCK)
            else:
                msg = self.socket_dealer.recv()

            msg = pickle.loads(msg)

            if type(msg) == Message.CONNECT:
                self.handle_connect(*msg())
            elif msg == Message.DISCONNECT:
                self.handle_disconnect()
            elif msg == Message.START:
                self.handle_start()
            elif msg == Message.PAUSE:
                self.handle_pause()
            elif msg == Message.STOP:
                self.handle_stop()
            elif type(msg) == Message.CONFIGURE:
                self.handle_configure(*msg())
            else:
                assert False

            self.send_report()
        except zmq.Again:
            pass

        # Processing messages from tasks.
        try:
            msg = self.socket_pull.recv_pyobj(flags=zmq.NOBLOCK)

            if type(msg) == Message.DATA:
                self.handle_data(*msg())
            elif msg == Message.FINISHED:
                self.handle_finished()
            else:
                assert False
        except zmq.Again:
            pass

    def run(self):
        """
        Runs the process.

        This function initializes ZMQ sockets, dispatches interprocess
        communication, implements the state machine, and calls the
        user-implemented "do" methods.

        Note:
            This function is the subprocess
        """

        self.status = Status.PAUSED

        # Opening ZMQ sockets.
        self.context = zmq.Context()
        self.socket_dealer = self.context.socket(zmq.DEALER)
        self.socket_push = self.context.socket(zmq.PUSH)
        self.socket_pull = self.context.socket(zmq.PULL)
        self.socket_dealer.setsockopt(zmq.IDENTITY, self.name.encode())
        self.socket_dealer.connect(self.address_router)
        self.address_push = self.socket_push.bind_to_random_port("tcp://127.0.0.1")
        self.address_push = f"tcp://127.0.0.1:{self.address_push}"

        # Doing startup and collecting stdout/stderr
        try:
            self.do_startup()
        except Exception as err:
            self.status = Status.ERROR
            self.error = err

        self.send_report()

        while not self._kill:
            self.poll()

            try:
                if self.status == Status.RUNNING:
                    if self.queue or self.config["is_start"]:
                        val = self.queue.popleft() if self.queue else None
                        ret = self.do_work(val)
                        self.send_data(ret)
                    else:
                        continue
                elif self.status == Status.PAUSED:
                    time.sleep(0.1)
                elif self.status == Status.ERROR:
                    time.sleep(1)
                elif self.status == Status.FINISHED:
                    time.sleep(0.1)
                else:
                    raise RuntimeError
            except Exception as err:
                self.status = Status.ERROR
                self.error = err

        self.send_report()

        # Doing cleanup and collecting stdout/stderr
        try:
            self.do_cleanup()
        except Exception as err:
            self.status = Status.ERROR
            self.error = err

        self.status = Status.DONE
        self.send_report()

        # Closing ZMQ sockets.
        if self.socket_pull:
            self.socket_pull.setsockopt(zmq.LINGER, 0)
            self.socket_pull.close()
        if self.socket_push:
            self.socket_push.setsockopt(zmq.LINGER, 0)
            self.socket_push.close()
        if self.socket_dealer:
            self.socket_dealer.setsockopt(zmq.LINGER, 0)
            self.socket_dealer.close()
        if self.context:
            self.context.term()
