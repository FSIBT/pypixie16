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

    This class as four sets of methods: callbacks, handlers, senders, and
    actions. Handlers address incoming messages, senders dispatch outgoing
    messages, and actions provides the user interface. Callbacks facilliate
    subclassing.

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

    def __init__(self, task_kwargs=None):
        self._task_kwargs = task_kwargs or {}
        self._status = Status.WAITING
        self._tasks_active = []
        self._tasks_all = {}
        self._reports = {}
        self._context = zmq.Context()
        self._socket_router = self._context.socket(zmq.ROUTER)
        self._port_router = self._socket_router.bind_to_random_port("tcp://127.0.0.1")
        self._address_router = f"tcp://127.0.0.1:{self._port_router}"

    # Callbacks

    def do_connect(self, _tasks_active: list[str]) -> None:
        """
        ``connect`` callback.

        Parameters:
            _tasks_active: Names of tasks to connect.
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

    def do_print(self, string: str) -> None:
        """
        ``print`` callback.

        Parameters:
            string: Recieved stdout.
        """

        print(string, end="")

    # Special

    def _create_task(self, name: str):
        """
        Creates tasks using class names.

        Parameters:
            name: Task class name.

        Raises:
            ValueError: Task already initialized.
            ValueError: Task not found.
        """

        if name in self._tasks_all:
            raise ValueError(f"ERROR: Task already initialized.")

        if name not in Task.class_registry:
            raise ValueError(f"ERROR: Task not found: '{name}'.")

        task = Task.class_registry[name]()
        task._address_router = self._address_router
        task.start()
        self._tasks_all[name] = task

    # Handlers

    def _handle_report(self, name: str, report: dict[str, typing.Any]) -> None:
        """
        Handles ``Message.REPORT``.

        Parameters:
            name: Task name.
            report: Recieved report.
        """

        assert name in self._tasks_all

        if name in self._reports:
            self._reports[name] |= report
        else:
            self._reports[name] = report

        if "status" in report and report["status"] == Status.PANICKING:
            self._status = Status.PANICKING

        if (
            "status" in report
            and report["status"] == Status.WAITING
            and name == self._tasks_active[-1]
        ):
            self._status = Status.WAITING

    def _handle_print(self, name: str, string: str) -> None:
        """
        Handles ``Message.PRINT``.

        Parameters:
            name: Task name.
            string: Recieved string.
        """

        assert name in self._tasks_all

        self.do_print(string)

    def _handle_error(self, name: str, err: Exception) -> None:
        """
        Handles ``Message.ERROR``.

        Parameters:
            name: Task name.
            err: Recieved error.
        """

        assert name in self._tasks_all

        self._status = Status.PANICKING
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
        self._socket_router.send_multipart([name.encode(), msg])

    def _send_start(self, name: str) -> None:
        """
        Sends ``Message.START``.

        Parameters:
            name: Task name.
        """

        assert name in self._tasks_all

        msg = pickle.dumps(Message.START)
        self._socket_router.send_multipart([name.encode(), msg])

    def _send_quit(self, name: str) -> None:
        """
        Sends ``Message.QUIT``.

        Parameters:
            name: Task name.
        """

        assert name in self._tasks_all

        msg = pickle.dumps(Message.QUIT)
        self._socket_router.send_multipart([name.encode(), msg])

    def _send_configure(self, name: str, config: dict[str, typing.Any]) -> None:
        """
        Sends ``Message.CONFIGURE``.

        Parameters:
            name: Task name.
            config: Parameters to send.
        """

        assert name in self._tasks_all

        msg = pickle.dumps(Message.CONFIGURE(config))
        self._socket_router.send_multipart([name.encode(), msg])

    def _send_stop(self, name: str) -> None:
        """
        Sends ``Message.STOP``.

        Parameters:
            name: Task name.
        """

        assert name in self._tasks_all

        msg = pickle.dumps(Message.STOP)
        self._socket_router.send_multipart([name.encode(), msg])

    # Actions

    def connect(self, _tasks_active: list[str]) -> None:
        """
        Does connecting.

        Parameters:
            _tasks_active: Names of tasks to connect.

        Raises:
            RuntimeError: Not all tasks responding.
        """

        self.do_connect(_tasks_active)

        # Clearing messages and updating status.
        self._status = Status.WAITING
        self._reports = {}

        now = time.time()

        # Pausing & disconnecting old tasks.
        for name in [*self._tasks_all, *_tasks_active]:
            try:
                self._create_task(name)
            except ValueError:
                pass
            self._send_connect(name, None, False, False)

        # Waiting for reinitialization reports.
        self._tasks_active = _tasks_active
        while set(self._reports.keys()) != set(self._tasks_active):
            self.poll()
            if time.time() - now > 30:
                raise RuntimeError(
                    f"ERROR: Not all tasks responding: got {self._reports.keys()}, expected {self._tasks_active}"
                )

        # Connecting new tasks
        prev = None
        for name in _tasks_active:
            self._send_connect(
                name,
                self._reports[prev]["address_push"] if prev else None,
                self._tasks_active[0] == name,
                self._tasks_active[-1] == name,
            )
            prev = name

        self.configure({})

    def start(self) -> None:
        """
        Does starting.
        """

        self.do_start()
        self._status = Status.RUNNING

        for name in self._tasks_active:
            self._send_start(name)

    def stop(self) -> None:
        """
        Does starting.
        """

        self.do_stop()
        self._status = Status.WAITING

        for name in self._tasks_active:
            self._send_stop(name)

    def quit(self) -> None:
        """
        Does quitting.
        """

        self.do_quit()
        self._status = Status.DYING

        for name in self._tasks_all:
            self._send_quit(name)

    def configure(self, config: dict[str, typing.Any]) -> None:
        """
        Does configuring.

        Parameters:
            config: Parameters to send.
        """

        self.do_configure(config)

        for name in self._tasks_active:
            self._send_configure(name, config)

    def poll(self) -> None:
        """
        Does listening.
        """

        self.do_poll()

        try:
            name, msg = self._socket_router.recv_multipart(flags=zmq.NOBLOCK)
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
        else:  # pragma: no cover
            assert False

    # Properties

    @property
    def status(self) -> Status:  # pragma: no cover
        return self._status

    @property
    def tasks_active(self) -> list[str]:  # pragma: no cover
        return self._tasks_active

    @property
    def tasks_active(self) -> list[str]:  # pragma: no cover
        return self._task_kwargs

    @property
    def tasks_all(self) -> dict[str, Task]:  # pragma: no cover
        return self._tasks_all

    @property
    def reports(self) -> dict[str, dict[str, typing.Any]]:  # pragma: no cover
        return self._reports
