import io
import sys
import typing
import pickle
import itertools

import zmq

from . import task
from . import message


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
        names: Names of active tasks.
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

        self.names = []
        self.tasks = {}
        self.reports = {}

        self.context = zmq.Context()
        self.socket_router = self.context.socket(zmq.ROUTER)
        self.address_router = self.socket_router.bind_to_random_port("tcp://127.0.0.1")
        self.address_router = f"tcp://127.0.0.1:{self.address_router}"
        self.poller = zmq.Poller()
        self.poller.register(self.socket_router, zmq.POLLIN)

    def handle_report(self, name: str, report: dict[str, typing.Any]) -> None:
        """
        Handles ``REPORT`` messages from some task.

        Parameters:
            name: Task name.
            report: Recieved report.
        """

        if name not in self.tasks:
            raise ValueError

        self.reports[name] = report

    def handle_print(self, name: str, stdout: io.StringIO, stderr: io.StringIO) -> None:
        """
        Handles ``PRINT`` messages from some task.

        Parameters:
            name: Task name.
            stdout: Recieved stdout.
            stderr: Recieved stderr.
        """

        if name not in self.tasks:
            raise ValueError

        # print(stdout.read(), file=sys.stdout)
        # print(stderr.read(), file=sys.stderr)

    def task_connect(self, name: str, address_pull: str) -> None:
        """
        Sends ``CONNECT`` messages to tasks.

        Parameters:
            name: Task name.
            address_pull: ZMQ pull socket address.
        """

        if name not in self.tasks:
            raise ValueError

        msg = pickle.dumps(message.Message.CONNECT(address_pull))
        self.socket_router.send_multipart([name.encode(), msg])

        self.socket_router.recv_multipart()

    def task_disconnect(self, name: str) -> None:
        """
        Sends ``DISCONNECT`` messages to tasks.

        Parameters:
            name: Task name.
        """

        if name not in self.tasks:
            raise ValueError

        msg = pickle.dumps(message.Message.DISCONNECT)
        self.socket_router.send_multipart([name.encode(), msg])

        self.socket_router.recv_multipart()

    def task_start(self, name: str) -> None:
        """
        Sends ``START`` messages to tasks.

        Parameters:
            name: Task name.
        """

        if name not in self.tasks:
            raise ValueError

        msg = pickle.dumps(message.Message.START)
        self.socket_router.send_multipart([name.encode(), msg])

        self.socket_router.recv_multipart()

    def task_pause(self, name: str) -> None:
        """
        Sends ``PAUSE`` messages to tasks.

        Parameters:
            name: Task name.
        """

        if name not in self.tasks:
            raise ValueError

        msg = pickle.dumps(message.Message.PAUSE)
        self.socket_router.send_multipart([name.encode(), msg])

        self.socket_router.recv_multipart()

    def task_stop(self, name: str) -> None:
        """
        Sends ``STOP`` messages to tasks.

        Parameters:
            name: Task name.
        """

        if name not in self.tasks:
            raise ValueError

        msg = pickle.dumps(message.Message.STOP)
        self.socket_router.send_multipart([name.encode(), msg])

        self.socket_router.recv_multipart()

    def task_configure(self, name: str, config: dict[str, typing.Any]) -> None:
        """
        Sends ``CONFIGURE`` messages to tasks.

        Parameters:
            name: Task name.
            config: Recieved parameters.
        """

        if name not in self.tasks:
            raise ValueError

        msg = pickle.dumps(message.Message.CONFIGURE(config))
        self.socket_router.send_multipart([name.encode(), msg])

    def task_append(self, tsk: task.Task) -> str:
        """
        Pushes task to the pool.

        Parameter:
            tsk: Task to append.

        Returns:
            Name of the task appended.
        """

        if tsk.name in self.tasks:
            raise ValueError

        self.tasks[tsk.name] = tsk

        tsk.start()

        while tsk.name not in self.reports:
            self.poll()

        return tsk.name

    def task_remove(self, name: str) -> task.Task:
        """
        Pops task off the pool.

        Parameter:
            name: Name of task to remove.

        Returns:
            Task removed.
        """

        if name not in self.tasks:
            raise ValueError

        self.task_stop(name)

        tsk = self.tasks.pop(name)

        # tsk.join()
        # tsk.close()
        tsk.kill()

        return tsk

    def init(self, names: list[str]) -> None:
        """
        Initialize the chain by pausing, disconnecting, and reconnecting
        tasks.

        Parameters:
            names: Names of tasks to connect.
        """

        # Pausing & disconnecting old tasks.
        if self.names:
            for name in self.names:
                self.task_pause(name)
                self.task_disconnect(name)

        # Pausing & disconnecting new tasks.
        for name in names:
            self.task_pause(name)
            self.task_disconnect(name)

        self.names = names

        # Connecting new tasks
        if len(names) > 1:
            for name_a, name_b in itertools.pairwise(names):
                self.task_connect(name_b, self.reports[name_a]["address_push"])

    def start(self) -> None:
        """
        Starts the chain.
        """

        for name in self.names:
            self.task_start(name)

    def pause(self) -> None:
        """
        Pauses the chain.
        """

        for name in self.names:
            self.task_pause(name)

    def stop(self) -> None:
        """
        Stops the chain.
        """

        for name in self.names:
            self.task_stop(name)

    def configure(self, config: dict[str, typing.Any]) -> None:
        """
        Configures the chain.
        """

        for name in self.names:
            self.task_configure(name, config)

    def poll(self) -> None:
        """
        Polls the pool, checking for and processing messages, without blocking.
        """

        socks = dict(self.poller.poll(0))
        if not socks.get(self.socket_router) == zmq.POLLIN:
            return

        name, msg = self.socket_router.recv_multipart()
        name = name.decode()
        msg = pickle.loads(msg)

        if type(msg) == message.Message.REPORT:
            self.handle_report(name, *msg())
        elif type(message.Message.PRINT):
            self.handle_print(name, *msg())
