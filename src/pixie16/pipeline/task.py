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

from . import status
from . import message


class Task(multiprocessing.Process, abc.ABC):
    """
    Represents pausable, custom processes that intergrate into ``Pipeline``.

    Since ``Task`` extends ``multiprocessing.Process``, tasks behave like state
    machines. They have the following states:

    * ▶️ RUNNING: Processing data.
    * ⏸️ PAUSED: Waiting to process data.
    * ✅ FINISHED: Done processing data.
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

    def __init__(self, name: str, address_router: str):
        """
        Initializes ``Task``.

        Parameters:
            name: Task name.
            address_pull: ZMQ pull socket address.
        """

        super().__init__()

        self.name: str = name
        self.address_router: str = address_router

        self.queue: collections.deque = collections.deque()
        self.config: dict[str, typing.Any] = dict()
        self.status: status.Status = status.Status.PAUSED

        self.context: zmq.Context = None
        self.socket_pull: zmq.Socket = None
        self.socket_push: zmq.Socket = None
        self.socket_dealer: zmq.Socket = None
        self.address_pull: str = None
        self.address_push: str = None

    def do_startup(self) -> None:
        """
        Called after initialization.
        """

        pass

    def do_cleanup(self) -> None:
        """
        Called after termination.
        """

        pass

    @abc.abstractmethod
    def do_work(self) -> None:
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

        self.send_report({})

    def handle_disconnect(self) -> None:
        """
        Handles ``DISCONNECT`` messages from the pipeline.
        """

        if self.address_pull:
            self.socket_pull.disconnect(self.address_pull)
        self.address_pull = None

        self.queue = collections.deque()

        self.send_report({})

    def handle_start(self) -> None:
        """
        Handles ``START`` messages from the pipeline.
        """

        self.status = status.Status.RUNNING
        self.send_report({})

    def handle_pause(self) -> None:
        """
        Handles ``PAUSE`` messages from the pipeline.
        """

        self.status = status.Status.PAUSED
        self.send_report({})

    def handle_stop(self) -> None:
        """
        Handles ``STOP`` messages from the pipeline.
        """

        self.status = status.Status.FINISHED
        self.send_report({})

    def handle_configure(self, config: dict[str, typing.Any]) -> None:
        """
        Handles ``CONFIGURE`` messages from the pipeline.

        Parameters:
            config: Recieved parameters.
        """

        self.config = config
        self.send_report({})

    def send_report(self, report: dict[str, typing.Any]) -> None:
        """
        Sends ``REPORT`` messages to the pipeline.
        """

        report |= {
            "name": self.name,
            "config": self.config,
            "status": self.status,
            "address_pull": self.address_pull,
            "address_push": self.address_push,
            "address_router": self.address_router,
        }

        msg = pickle.dumps(
            message.Message.REPORT(report), protocol=pickle.HIGHEST_PROTOCOL
        )
        self.socket_dealer.send(msg)

    def send_print(self, stdout: str, stderr: str) -> None:
        """
        Sends ``PRINT`` messages to the pipeline.

        Parameters:
            stdout: Captured stdout to send.
            stderr: Captured stderr to send.
        """

        msg = pickle.dumps(
            message.Message.PRINT(stdout, stderr), protocol=pickle.HIGHEST_PROTOCOL
        )
        self.socket_dealer.send(msg)

    def send_data(self, data: typing.Any) -> None:
        """
        Sends ``DATA`` messages to the next task.

        Parameters:
            data: Sent data.
        """

        msg = message.Message.DATA(data)
        self.socket_push.send_pyobj(msg)

    def run(self):
        """
        Runs the process.

        This function initializes ZMQ sockets, dispatches interprocess
        communication, implements the state machine, and calls the
        user-implemented "do" methods.
        """

        # Creating ZMQ sockets.
        self.context = zmq.Context()
        self.socket_dealer = self.context.socket(zmq.DEALER)
        self.socket_push = self.context.socket(zmq.PUSH)
        self.socket_pull = self.context.socket(zmq.PULL)

        # Configuring ZMQ sockets.
        self.socket_dealer.setsockopt(zmq.IDENTITY, self.name.encode())
        self.socket_dealer.connect(self.address_router)

        self.address_push = self.socket_push.bind_to_random_port("tcp://127.0.0.1")
        self.address_push = f"tcp://127.0.0.1:{self.address_push}"

        # Doing startup and collecting stdout/stderr
        try:
            self.do_startup()
            # self.send_print(f.read(), g.read())
        except Exception as err:
            print(err)
            exit(1)

        self.send_report({})

        while True:
            # Processing messages from pipeline.
            try:
                msg = self.socket_dealer.recv(flags=zmq.NOBLOCK)
                msg = pickle.loads(msg)

                if type(msg) == message.Message.CONNECT:
                    self.handle_connect(*msg())
                elif msg == message.Message.DISCONNECT:
                    self.handle_disconnect()
                elif msg == message.Message.START:
                    self.handle_start()
                elif msg == message.Message.PAUSE:
                    self.handle_pause()
                elif msg == message.Message.STOP:
                    self.handle_stop()
                elif type(msg) == message.Message.CONFIGURE:
                    self.handle_configure(*msg())
                else:
                    self.status = status.Status.ERROR
                    self.send_report({"error": msg})
            except zmq.Again:
                pass

            # Processing messages from tasks.
            try:
                msg = self.socket_pull.recv_pyobj(flags=zmq.NOBLOCK)
                self.queue.append(*msg())
            except zmq.Again:
                pass

            # Proceeding according to state.
            if self.status == status.Status.RUNNING:
                try:
                    # Doing work and collecting stdout/stderr
                    self.do_work()
                    # self.send_print(f.read(), g.read())
                except Exception as err:
                    self.status = status.Status.ERROR
                    self.send_report({"error": err})
            elif self.status == status.Status.PAUSED:
                time.sleep(0.1)
            elif self.status == status.Status.FINISHED:
                time.sleep(0.1)
                self.send_report({})
                break
            elif self.status == status.Status.ERROR:
                time.sleep(0.1)
            else:
                self.status = status.Status.ERROR
                self.send_report({"error": msg})

        # Doing cleanup and collecting stdout/stderr
        try:
            self.do_cleanup()
            # self.send_print(f.read(), g.read())
        except Exception as err:
            print(err)
            exit(1)

        # Closing ZMQ sockets.
        if self.socket_pull:
            self.socket_pull.close()
        if self.socket_push:
            self.socket_push.close()
        if self.socket_dealer:
            self.socket_dealer.close()
        if self.context:
            self.context.term()
