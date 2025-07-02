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

    Pipelines use the following status to transition between initialization,
    running, pausing, and stoping:

    * ⏸️ READY: Active tasks waiting.
    * ▶️ RUNNING: Active tasks running.
    * 🆒 DONE: All tasks stoped
    * ✅ FINISHED: Active tasks finished.
    * 🆘 ERROR: Any tasks has an error.

    * PIPELINE-TO-TASK:
        * 🔁 CONNECT: Connect to given ZMQ push queue.
        * 🔀 DISCONNECT: Disconnect from the ZMQ push queue.
        * ▶️ START: Change status to ``RUNNING``.
        * ⏹️ STOP: Change status to ``DONE``.
        * ℹ️ CONFIGURE: Update parameters.
        * ✅ FINISHED: Change status to ``FINISHED``.
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
        self.status = Status.READY
        self.tasks_active = []
        self._tasks_all = {}
        self.reports = {}
        self.context = zmq.Context()
        self.socket_router = self.context.socket(zmq.ROUTER)
        self.address_router = self.socket_router.bind_to_random_port("tcp://127.0.0.1")
        self.address_router = f"tcp://127.0.0.1:{self.address_router}"

    def create_task(self, name: str):
        """
        Creates tasks using class names.

        This method initializes tasks from ``Task.class_registry`, and adds them
        to the pipeline pool, and starts them.

        Parameters:
            name: Task class name.

        Raises:
            ValueError: Task already initialized, i.e. in ``_tasks_all``.
            ValueError: Task not found, i.e. not in ``Task.class_registry``.
        """

        if name in self._tasks_all:
            raise ValueError(f"ERROR task already initialized")

        if name not in Task.class_registry:
            raise ValueError(f"ERROR cannot find pypixie16 task '{name}'")

        task = Task.class_registry[name]()
        self._tasks_all[name] = task
        task.address_router = self.address_router
        task.start()

    def handle_error(self, err: Exception) -> None:
        """
        Handles errors.

        The pipeline runtime calls this method if any task has the ``ERROR``
        status.

        Parameters:
            err: The excpetion raised.
        """

        self.status = Status.ERROR

    def handle_finished(self) -> None:
        """
        Handles complete pipelines.

        The pipeline runtime calls this method if all active tasks have the
        ``FINISHED`` status.
        """

        self.status = Status.FINISHED

    def handle_report(self, name: str, report: dict[str, typing.Any]) -> None:
        """
        Handles ``REPORT`` messages from some task.

        This method overwrites the last report with the given report. So, the
        pipeline only stores the last report recieved from each task.

        Parameters:
            name: Task name.
            report: Recieved report.

        Raises:
            ValueError: Task no found, i.e. not in ``_tasks_all``.
        """

        if name not in self._tasks_all:
            raise ValueError

        if name in self.reports:
            self.reports[name] |= report
        else:
            self.reports[name] = report

    def handle_print(self, name: str, stdout: str, stderr: str) -> None:
        """
        Handles ``PRINT`` messages from some task.

        This method prints non-empty writes to stdout and stderr. So, when
        tasks write to standard streams, it gets printed by the pipeline.

        Parameters:
            name: Task name.
            stdout: Recieved stdout.
            stderr: Recieved stderr.

        Raises:
            ValueError: Task no found, i.e. not in ``_tasks_all``.
        """

        if name not in self._tasks_all:
            raise ValueError

        if stdout:
            print(stdout, end="")
        if stderr:
            print(stderr, end="")

    def send_connect(
        self, name: str, address_pull: str, is_start: bool, is_final: bool
    ) -> None:
        """
        Sends ``CONNECT`` messages to tasks.

        This method connects each task in the pipeline by sending the address
        of the previous task's output and flags. The tasks handle this using
        ``handle_connect``. This method blocks while waiting for a reponse,
        namely a report.

        Parameters:
            name: Task name.
            address_pull: ZMQ pull socket address.
            is_start: First task flag.
            is_final: Last task flag.

        Raises:
            ValueError: Task no found, i.e. not in ``_tasks_all``.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.CONNECT(address_pull, is_start, is_final))
        self.socket_router.send_multipart([name.encode(), msg])

    def send_disconnect(self, name: str) -> None:
        """
        Sends ``DISCONNECT`` messages to tasks.

        This method disconnect each task in the pipeline by telling them to
        zero the address of previous task's output and the flags. The tasks
        handle this using ``handle_disconnect``. This method blocks while
        waiting for a reponse, namely a report.

        Parameters:
            name: Task name.

        Raises:
            ValueError: Task no found, i.e. not in ``_tasks_all``.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.DISCONNECT)
        self.socket_router.send_multipart([name.encode(), msg])

    def send_start(self, name: str) -> None:
        """
        Sends ``START`` messages to tasks.

        This method starts each task in the pipeline, starting data processing
        or collection. The tasks handle this using ``handle_start``. This
        method blocks while waiting for a reponse, namely a report.

        Parameters:
            name: Task name.

        Raises:
            ValueError: Task no found, i.e. not in ``_tasks_all``.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.START)
        self.socket_router.send_multipart([name.encode(), msg])

        while self.poll(is_block=True) != name:
            pass

    def send_stop(self, name: str) -> None:
        """
        Sends ``STOP`` messages to tasks.

        This method stops each task in the pipeline, pausing data processing
        or collection. The tasks handle this using ``handle_stop``. This
        method blocks while waiting for a reponse, namely a report.

        Parameters:
            name: Task name.

        Raises:
            ValueError: Task no found, i.e. not in ``_tasks_all``.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.STOP)
        self.socket_router.send_multipart([name.encode(), msg])

        while self.poll(is_block=True) != name:
            pass

    def send_configure(self, name: str, config: dict[str, typing.Any]) -> None:
        """
        Sends ``CONFIGURE`` messages to tasks.

        This method configures or reconfigures each task in the pipeline. The
        tasks handle this using ``do_configure`` and ``handle_configure``. This
        method blocks while waiting for a reponse, namely a report.

        Parameters:
            name: Task name.
            config: Parameters to send.

        Raises:
            ValueError: Task no found, i.e. not in ``_tasks_all``.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.CONFIGURE(config))
        self.socket_router.send_multipart([name.encode(), msg])

        while self.poll(is_block=True) != name:
            pass

    def send_finished(self, name: str) -> None:
        """
        Sends ``FINISHED`` messages to tasks.

        This method shortcuts regular execution by sending the ``FINISED``
        message to a task from the pipeline rather than the previous task. The
        tasks handle this using ``handle_finished``. This method blocks while
        waiting for a reponse, namely a report.

        Parameters:
            name: Task name.

        Raises:
            ValueError: Task no found, i.e. not in ``_tasks_all``.
        """

        if name not in self._tasks_all:
            raise ValueError

        msg = pickle.dumps(Message.FINISHED)
        self.socket_router.send_multipart([name.encode(), msg])

        while self.poll(is_block=True) != name:
            pass

    def init(self, tasks_active: list[str]) -> None:
        """
        Initialize active tasks.

        This method sets the pipeline status to ``READY``, creates, pauses, or
        disconnects tasks as needed, reconstitutes the active tasks by
        connecting/reconnecting them.

        Parameters:
            tasks_active: Names of tasks to connect.
        """

        # Clearing messages and updating status.
        self.status = Status.READY
        self.reports = {}

        # Pausing & disconnecting old tasks.
        for name in [*self._tasks_all, *tasks_active]:
            try:
                self.create_task(name)
            except ValueError:
                pass
            self.send_disconnect(name)

        # Waiting for reinitialization reports.
        self.tasks_active = tasks_active
        while set(self.reports.keys()) != set(self.tasks_active):
            self.poll()

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

        # Waiting for connection reports.
        names = set()
        while names != set(self.tasks_active):
            names.add(self.poll(is_block=True))

    def start(self) -> None:
        """
        Starts the active tasks.

        This method sets the pipleine status to ``RUNNING`` and starts all the
        active tasks.
        """

        # Clearing messages and updating status.
        self.status = Status.RUNNING

        for name in self.tasks_active:
            self.send_start(name)

    def stop(self) -> None:
        """
        Stops the active tasks.

        This method sets the pipleine status to ``DONE`` and starts all the
        active tasks.
        """

        # Clearing messages and updating status.
        self.status = Status.DONE

        for name in self._tasks_all:
            self.send_stop(name)

    def configure(self, config: dict[str, typing.Any]) -> None:
        """
        Configures the active tasks.

        This method configures or reconfigures the active tasks by sending the
        given configuration.

        Parameters:
            config: Parameters to send.
        """

        for name in self.tasks_active:
            self.send_configure(name, config)

    def poll(self, is_block: bool = False) -> None:
        """
        Polls listens for and handles messages from the tasks.

        This method listens for messages from the tasks and handles them using
        the "handle" methods and updates the pipeline's status by calling other
        "do" methods.

        Parameters:
            is_block: Block/no block flag.
        """

        try:
            if is_block:
                name, msg = self.socket_router.recv_multipart()
            else:
                name, msg = self.socket_router.recv_multipart(flags=zmq.NOBLOCK)
        except zmq.Again:
            return

        name = name.decode()
        msg = pickle.loads(msg)

        if type(msg) == Message.REPORT:
            self.handle_report(name, *msg())
        elif type(msg) == Message.PRINT:
            self.handle_print(name, *msg())
        else:
            raise RuntimeError

        if (
            name in self.reports
            and "status" in self.reports[name]
            and self.reports[name]["status"] == Status.ERROR
        ):
            self.handle_error(self.reports[name]["error"])

        if (
            self.status != Status.READY
            and self.tasks_active
            and self.tasks_active[-1] in self.reports
            and "status" in self.reports[self.tasks_active[-1]]
            and self.reports[self.tasks_active[-1]]["status"] == Status.FINISHED
        ):
            self.handle_finished()

        return name
