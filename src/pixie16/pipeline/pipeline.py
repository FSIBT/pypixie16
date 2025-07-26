import sys
import copy
import time
import typing
import pickle
import itertools

import zmq

from .task import Task
from .status import Status
from .message import Message

from rich import print


class Pipeline:
    """
    Represents daisychain of jobs.

    This class as three sets of methods: handlers, senders, and actions.
    Handlers address incoming messages, senders dispatch outgoing messages, and
    actions provides the user interface.

    This class uses the following states:
        * ⏸️ WAITING: Pipeline waiting.
        * ▶️ RUNNING: Pipeline running.
        * ⏏️ DYING: Pipeline dying.
        * 🆘 PANICKING: Pipeline panicking.

    This class send or handles the following messages:
        * ℹ️ CONFIGURE: Update user parameters.
        * 🔁 CONNECT: Update system parameters.
        * ▶️ START: Begin starting.
        * ⏹️ STOP: Begin waiting.
        * ⏏️ QUIT: Begin dying.
        * 📶 DATA: Transmit data.
        * 🆗 REPORT: Transmit info.
        * 🔣 PRINT: Transmit print.
        * 🆘 ERROR: Transmit error.
    """

    # Dunders

    def __init__(self, task_kwargs=None):
        self.status = Status.WAITING
        self.tasks_active = []
        self._tasks_all = {}
        self.reports = {}
        self.task_kwargs = task_kwargs or {}
        self.context = zmq.Context()
        self.socket_router = self.context.socket(zmq.ROUTER)
        port = self.socket_router.bind_to_random_port("tcp://127.0.0.1")
        self.address_router = f"tcp://127.0.0.1:{port}"

    def create_task(self, name: str):
        """
        Creates tasks using class names.

        Parameters:
            name: Task class name.

        Raises:
            ValueError: Task not found, i.e. not in ``Task.class_registry``.
        """

        if name in self._tasks_all:
            raise ValueError(f"PANICKING task already initialized")

        if name not in Task.class_registry:
            raise ValueError(f"PANICKING cannot find pypixie16 task '{name}'")

        task = Task.class_registry[name](**self.task_kwargs)
        self._tasks_all[name] = task
        task._address_router = self.address_router
        task.start()

    # Callbacks

    def do_connect(self, tasks_active: list[str]) -> None:
        """
        ``connect`` callback.

        Parameters:
            tasks_active: Names of tasks to connect.
        """

        pass

    def do_start(self) -> None:
        """
        ``start`` callback.
        """

        pass

    def do_stop(self) -> None:
        """
        ``stop`` callback.
        """

        pass

    def do_quit(self) -> None:
        """
        ``quit`` callback.
        """

        pass

    def do_configure(self, config: dict[str, typing.Any]) -> None:
        """
        ``configure`` callback.

        Parameters:
            config: Parameters to send.
        """

        pass

    def do_poll(self) -> None:
        """
        ``poll`` callback.
        """

        pass

    def do_error(self, err: Exception) -> None:
        """
        ``error`` callback.

        Parameters:
            err: Recieved error.
        """

        print(err)

    def do_print(self) -> None:
        """
        ``print`` callback.

        Parameters:
            string: Recieved stdout.
        """

        print(string, end="")

    # Handlers

    def _handle_report(self, name: str, report: dict[str, typing.Any]) -> None:
        """
        Handles ``Message.REPORT``.

        Parameters:
            name: Task name.
            report: Recieved report.
        """

        if name not in self._tasks_all:
            raise ValueError

        if name in self.reports:
            self.reports[name] |= report
        else:
            self.reports[name] = report

        if "status" in report and report["status"] == Status.PANICKING:
            self.status = Status.PANICKING

        if (
            "status" in report
            and report["status"] == Status.WAITING
            and name == self.tasks_active[-1]
        ):
            self.status = Status.WAITING

    def _handle_print(self, name: str, string: str) -> None:
        """
        Handles ``Message.PRINT``.

        Parameters:
            name: Task name.
            string: Recieved string.
        """

        if name not in self._tasks_all:
            raise ValueError

        self.do_print(string)

    def _handle_error(self, name: str, err: Exception) -> None:
        """
        Handles ``Message.ERROR``.

        Parameters:
            name: Task name.
            err: Recieved error.
        """

        if name not in self._tasks_all:
            raise ValueError

        self.do_error(err)

    # Senders

    def _send_connect(
        self, name: str, address_pull: str, is_start: bool, is_final: bool
    ) -> None:
        """
        Sends ``Message.CONNECT``.

        Parameters:
            name: Task name.
            address_pull: ZMQ pull socket address.
            is_start: First task flag.
            is_final: Last task flag.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.CONNECT(address_pull, is_start, is_final))
        self.socket_router.send_multipart([name.encode(), msg])

    def _send_start(self, name: str) -> None:
        """
        Sends ``Message.START``.

        Parameters:
            name: Task name.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.START)
        self.socket_router.send_multipart([name.encode(), msg])

    def _send_quit(self, name: str) -> None:
        """
        Sends ``Message.QUIT``.

        Parameters:
            name: Task name.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.QUIT)
        self.socket_router.send_multipart([name.encode(), msg])

    def _send_configure(self, name: str, config: dict[str, typing.Any]) -> None:
        """
        Sends ``Message.CONFIGURE``.

        Parameters:
            name: Task name.
            config: Parameters to send.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.CONFIGURE(config))
        self.socket_router.send_multipart([name.encode(), msg])

    def _send_stop(self, name: str) -> None:
        """
        Sends ``Message.STOP``.

        Parameters:
            name: Task name.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.STOP)
        self.socket_router.send_multipart([name.encode(), msg])

    # Actions

    def connect(self, tasks_active: list[str]) -> None:
        """
        Does connecting.

        Parameters:
            tasks_active: Names of tasks to connect.
        """

        self.do_connect(tasks_active)

        # Clearing messages and updating status.
        self.status = Status.WAITING
        self.reports = {}

        now = time.time()

        # Pausing & disconnecting old tasks.
        for name in [*self._tasks_all, *tasks_active]:
            try:
                self.create_task(name)
            except ValueError:
                pass
            self._send_connect(name, None, False, False)

        # Waiting for reinitialization reports.
        self.tasks_active = tasks_active
        while set(self.reports.keys()) != set(self.tasks_active):
            self.poll()
            if time.time() - now > 30:
                print("[red]ERROR[/] could not get a response from all tasks")
                print(f"      got {self.reports.keys()}")
                print(f"      expected {self.tasks_active}")
                sys.exit(1)

        # Connecting new tasks
        prev = None
        for name in tasks_active:
            self._send_connect(
                name,
                self.reports[prev]["address_push"] if prev else None,
                self.tasks_active[0] == name,
                self.tasks_active[-1] == name,
            )
            prev = name

        self.configure({})

    def start(self) -> None:
        """
        Does starting.
        """

        self.do_start()
        self.status = Status.RUNNING

        for name in self.tasks_active:
            self._send_start(name)

    def stop(self) -> None:
        """
        Does starting.
        """

        self.do_stop()
        self.status = Status.WAITING

        for name in self.tasks_active:
            self._send_stop(name)

    def quit(self) -> None:
        """
        Does quitting.
        """

        self.do_quit()
        self.status = Status.DYING

        for name in self._tasks_all:
            self._send_quit(name)

    def configure(self, config: dict[str, typing.Any]) -> None:
        """
        Does configuring.

        Parameters:
            config: Parameters to send.
        """

        self.do_config(config)

        for name in self.tasks_active:
            self._send_configure(name, config)

    def poll(self) -> None:
        """
        Does listening.
        """

        try:
            name, msg = self.socket_router.recv_multipart(flags=zmq.NOBLOCK)
        except zmq.Again:
            return

        name = name.decode()
        msg = pickle.loads(msg)

        if type(msg) == Message.REPORT:
            self._handle_report(name, *msg())
        elif type(msg) == Message.ERROR:
            self._handle_error(name, *msg())
        elif type(msg) == Message.PRINT:
            self._handle_print(name, *msg())
        else:
            assert False
