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

    Pipelines use the following states to transition between chain
    initialization, running, pausing, and stoping:
    * ▶️ RUNNING: Chain running.
    * ⏸️ PAUSED: Chain waiting.
    * 🆒 DONE: Chain done.
    * ✅ READY: Chain initialized.
    * 🆘 ERROR: Chain detected an error.

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

    def __init__(self):
        """
        Initializes ``Pipeline``.
        """

        self._status = Status.READY
        self._tasks_active = []
        self._tasks_all = {}
        self.reports = {}
        self.context = zmq.Context()
        self.socket_router = self.context.socket(zmq.ROUTER)
        self.address_router = self.socket_router.bind_to_random_port("tcp://127.0.0.1")
        self.address_router = f"tcp://127.0.0.1:{self.address_router}"

    def create_task(self, name: str):
        if name not in Task.class_registry:
            print(f"ERROR cannot find pypixie16 task '{name}'")
            sys.exit(1)

        task = Task.class_registry[name]()
        self._tasks_all[name] = task
        task.address_router = self.address_router
        task.start()

        self.poll(is_noblock=False)

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

    def handle_error(self, err: Exception) -> None:
        """
        Handles errors condition.
        """

        self._status = Status.ERROR
        raise err

    def handle_finished(self) -> None:
        """
        Handles finished condition.
        """

        self._status = Status.FINISHED

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

        self._status = Status.READY

        # Pausing & disconnecting old tasks.
        if self.tasks_active:
            for name in self.tasks_active:
                self.send_pause(name)
                self.send_disconnect(name)
                self.send_configure(name, {"is_final": False, "is_start": False})

        # Pausing & disconnecting new tasks.
        for name in tasks_active:
            self.create_task(name)
            self.send_pause(name)
            self.send_disconnect(name)
            self.send_configure(name, {"is_final": False, "is_start": False})

        self.tasks_active = tasks_active

        # Connecting new tasks
        if len(tasks_active) > 1:
            for name_a, name_b in itertools.pairwise(tasks_active):
                self.send_connect(name_b, self.reports[name_a]["address_push"])
                self.poll(is_noblock=False)

        if tasks_active:
            self.send_configure(
                self._tasks_active[0], {"is_final": False, "is_start": True}
            )
            self.send_configure(
                self._tasks_active[-1], {"is_final": True, "is_start": False}
            )

            self.poll(is_noblock=False)
            self.poll(is_noblock=False)

    def start(self) -> None:
        """
        Starts the chain.
        """

        self._status = Status.RUNNING

        for name in self._tasks_active:
            self.send_start(name)

    def pause(self) -> None:
        """
        Pauses the chain.
        """

        self._status = Status.PAUSED

        for name in self._tasks_active:
            self.send_pause(name)

    def stop(self) -> None:
        """
        Stops the chain.
        """

        self._status = Status.DONE

        for name in self._tasks_active:
            self.send_stop(name)

    def configure(self, config: dict[str, typing.Any]) -> None:
        """
        Configures the chain.
        """

        for name in self.tasks_active:
            self.send_configure(name, config)

    def poll(self, is_noblock: bool = True) -> None:
        """
        Polls the pool, checking for and processing messages, without blocking.

        Parameter:
            is_noblock: Block/no block flag.
        """

        try:
            if is_noblock:
                name, msg = self.socket_router.recv_multipart(flags=zmq.NOBLOCK)
            else:
                name, msg = self.socket_router.recv_multipart()

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

        for name in self._tasks_active:
            if self.reports[name]["status"] == Status.ERROR:
                self.handle_error(self.reports[name]["error"])

        if self._status != Status.READY:
            if (
                not self._tasks_active
                or self.reports[self._tasks_active[-1]]["status"] == Status.FINISHED
            ):
                self.handle_finished()
