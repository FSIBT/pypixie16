import sys
import copy
import typing
import pickle
import itertools

import zmq

from .task import Task
from .status import Status
from .message import Message


class Pipeline:
    """
    Represents linear daisychain of ``Tasks``.

    Pipelines uses ZMQ Push/Pull sockets to get and send messages to tasks.
    Pipeliens send and recieve the following kinds of messages to tasks:

    * PIPELINE-TO-TASK:
        * 🔁 CONNECT: Connect to given ZMQ push queue.
        * 🔀 DISCONNECT: Disconnect from the ZMQ push queue.
        * ▶️ START: Change status to RUNNING.
        * ⏸️ PAUSE: Change status to PAUSED.
        * ⏹️ STOP: Change status to FINISHED.
        * ℹ️ CONFIGURE: Update parameters.
    * TASK-TO-PIPELINE:
        * 🆗 REPORT: Transmit status to pipeline
        * 🔣 PRINT: Print to stdout/stderr.

    Attributes:
        tasks_active: Names of active tasks.
        tasks: Pools of tasks.
        reports: Task reports.
        context: ZMQ context.
        socket_router: ZMQ pull socket.
        address_router: ZMQ pull socket address.
        poller: ZMQ poller.
    """

    def __init__(self, *tasks: Task):
        """
        Initializes ``Pipeline``.
        """

        self._tasks_active = []
        self._tasks_all = {}
        self.reports = {}
        self.context = zmq.Context()
        self.socket_router = self.context.socket(zmq.ROUTER)
        self.address_router = self.socket_router.bind_to_random_port("tcp://127.0.0.1")
        self.address_router = f"tcp://127.0.0.1:{self.address_router}"

        for task in tasks:
            if task.status != Status.READY:
                raise RuntimeError

            self._tasks_all[task.name] = task
            task.address_router = self.address_router
            task.start()

            while task.name not in self.reports:
                self.poll()

    def handle_report(self, name: str, report: dict[str, typing.Any]) -> None:
        """
        Handles ``REPORT`` messages from some task.

        Parameters:
            name: Task name.
            report: Recieved report.
        """

        if name not in self._tasks_all:
            raise ValueError

        self.reports[name] = report

    def handle_print(self, name: str, stdout: str, stderr: str) -> None:
        """
        Handles ``PRINT`` messages from some task.

        Parameters:
            name: Task name.
            stdout: Recieved stdout.
            stderr: Recieved stderr.
        """

        if name not in self._tasks_all:
            raise ValueError

        if stdout:
            print(stdout, file=sys.stdout)
        if stderr:
            print(stderr, file=sys.stderr)

    def send_connect(self, name: str, address_pull: str) -> None:
        """
        Sends ``CONNECT`` messages to tasks.

        Parameters:
            name: Task name.
            address_pull: ZMQ pull socket address.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.CONNECT(address_pull))
        self.socket_router.send_multipart([name.encode(), msg])

    def send_disconnect(self, name: str) -> None:
        """
        Sends ``DISCONNECT`` messages to tasks.

        Parameters:
            name: Task name.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.DISCONNECT)
        self.socket_router.send_multipart([name.encode(), msg])

    def send_start(self, name: str) -> None:
        """
        Sends ``START`` messages to tasks.

        Parameters:
            name: Task name.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.START)
        self.socket_router.send_multipart([name.encode(), msg])

    def send_pause(self, name: str) -> None:
        """
        Sends ``PAUSE`` messages to tasks.

        Parameters:
            name: Task name.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.PAUSE)
        self.socket_router.send_multipart([name.encode(), msg])

    def send_stop(self, name: str) -> None:
        """
        Sends ``STOP`` messages to tasks.

        Parameters:
            name: Task name.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.STOP)
        self.socket_router.send_multipart([name.encode(), msg])

    def send_configure(self, name: str, config: dict[str, typing.Any]) -> None:
        """
        Sends ``CONFIGURE`` messages to tasks.

        Parameters:
            name: Task name.
            config: Recieved parameters.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.CONFIGURE(config))
        self.socket_router.send_multipart([name.encode(), msg])

    def init(self, tasks_active: list[str]) -> None:
        """
        Initialize the chain by pausing, disconnecting, and reconnecting
        tasks.

        Parameters:
            tasks_active: Names of tasks to connect.
        """

        # Pausing & disconnecting old tasks.
        if self._tasks_active:
            for name in self._tasks_active:
                self.send_pause(name)
                self.send_disconnect(name)

        # Pausing & disconnecting new tasks.
        for name in tasks_active:
            self.send_pause(name)
            self.send_disconnect(name)

        self._tasks_active = tasks_active

        # Connecting new tasks
        if len(tasks_active) > 1:
            for name_a, name_b in itertools.pairwise(tasks_active):
                self.send_connect(name_b, self.reports[name_a]["address_push"])

    def start(self) -> None:
        """
        Starts the chain.
        """

        for name in self._tasks_active:
            self.send_start(name)

    def pause(self) -> None:
        """
        Pauses the chain.
        """

        for name in self._tasks_active:
            self.send_pause(name)

    def stop(self) -> None:
        """
        Stops the chain.
        """

        for name in self._tasks_active:
            self.send_stop(name)

    def configure(self, config: dict[str, typing.Any]) -> None:
        """
        Configures the chain.
        """

        for name in self._tasks_active:
            self.send_configure(name, config)

    def poll(self) -> None:
        """
        Polls the pool, checking for and processing messages, without blocking.
        """

        try:
            name, msg = self.socket_router.recv_multipart(flags=zmq.NOBLOCK)
            name = name.decode()
            msg = pickle.loads(msg)
        except zmq.Again:
            return

        if type(msg) == Message.REPORT:
            self.handle_report(name, *msg())
        elif type(msg) == Message.PRINT:
            self.handle_print(name, *msg())
        else:
            raise RuntimeError
