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
        self.tasks_all = {}
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

        if name in self.tasks_all:
            return

        if name not in Task.class_registry:
            raise ValueError(f"PANICKING cannot find task '{name}'")

        task = Task.class_registry[name](**self.task_kwargs)
        self.tasks_all[name] = task
        task.address_router = self.address_router
        task.start()

    def handle_report(self, name: str, report: dict[str, typing.Any]) -> None:
        """
        Handles ``Message.REPORT``.

        Parameters:
            name: Task name.
            report: Recieved report.
        """

        if name not in self.tasks_all:
            print("ERROR: pipeline got a message from a non-active task")

        if name in self.reports:
            self.reports[name] |= report
        else:
            self.reports[name] = report

        if "status" in report and report["status"] == Status.PANICKING:
            self.status = Status.PANICKING

        if "task finished" in report and name == self.tasks_active[-1]:
            self.status = Status.FINISHED

    def handle_print(self, name: str, string: str) -> None:
        """
        Handles ``Message.PRINT``.

        Parameters:
            name: Task name.
            string: Recieved string.
        """

        assert name in self.tasks_all
        print(string, end="")

    def handle_error(self, name: str, err: Exception) -> None:
        """
        Handles ``Message.ERROR``.

        Parameters:
            name: Task name.
            err: Recieved error.
        """

        assert name in self.tasks_all

        self.status = Status.PANICKING
        print(err)

    def update_active_tasks_status(self, msg_type: Message):
        for name in self.tasks_active:
            msg = pickle.dumps(msg_type)
            self.socket_router.send_multipart([name.encode(), msg])

    def send_connect(
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

        if name not in self.tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.CONNECT(address_pull, is_start, is_final))
        self.socket_router.send_multipart([name.encode(), msg])

    # Actions

    def connect(self, tasks_active: list[str]) -> None:
        """
        Does connecting.

        Parameters:
            tasks_active: Names of tasks to connect.

        Raises:
            RuntimeError: Not all tasks responding.
        """

        # Clearing messages and updating status.
        self.status = Status.WAITING
        self.reports = {}

        now = time.time()

        # Pausing & disconnecting old tasks.
        for name in [*self.tasks_all, *tasks_active]:
            self.create_task(name)
            self.send_connect(name, None, False, False)

        # Waiting for reinitialization reports.
        self.tasks_active = tasks_active
        while set(self.reports.keys()) != set(self.tasks_active):
            self.poll()
            if time.time() - now > 30:
                raise RuntimeError(
                    f"ERROR: Not all tasks responding: got {self.reports.keys()}, expected {self.tasks_active}"
                )

        for i in range(10 * len(self.tasks_active)):
            self.poll()
            time.sleep(0.01)

        # Connecting new tasks
        prev = None
        for name in tasks_active:
            self.send_connect(
                name,
                self.reports[prev]["address_push"] if prev else None,
                self.tasks_active[0] == name,
                self.tasks_active[-1] == name,
            )
            prev = name

        self.configure({})

    def start(self) -> None:
        self.status = Status.RUNNING
        self.update_active_tasks_status(Message.START)

    def stop(self) -> None:
        self.status = Status.WAITING
        self.update_active_tasks_status(Message.STOP)

    def quit(self) -> None:
        self.status = Status.DYING
        self.update_active_tasks_status(Message.QUIT)

        for task in self.tasks_all.values():
            task.join()

    def kill(self) -> None:
        self.status = None

        for task in self.tasks_all.values():
            task.kill()

        for task in self.tasks_all.values():
            task.join()

    def configure(self, config: dict[str, typing.Any]) -> None:
        """
        Configures all task by sending the `config` dictionary to all tasks

        Parameters:
            config: Parameters to send.
        """

        self.update_active_tasks_status(Message.CONFIGURE(config))

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
            self.handle_report(name, *msg())
        elif type(msg) == Message.ERROR:
            self.handle_error(name, *msg())
        elif type(msg) == Message.PRINT:
            self.handle_print(name, *msg())
        else:  # pragma: no cover
            assert False
