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
    machines. They have the following statues:

    * ⏸️ READY: Task waiting.
    * ▶️ RUNNING: Task processing data.
    * 🆒 DONE: Task done.
    * ✅ FINISHED: Task finished and waiting.
    * 🆘 ERROR: Task waiting with error.

    Tasks uses ZMQ Push/Pull sockets to get and send messages between other
    tasks and the pipeline. Tasks send and recieve the following kinds of
    messages between themselves and the pipeline.

    * PIPELINE-TO-TASK:
        * 🔁 CONNECT: Connect to given ZMQ push queue.
        * 🔀 DISCONNECT: Disconnect from the ZMQ push queue.
        * ▶️ START: Change status to ``RUNNING``.
        * ⏹️ STOP: Change status to ``FINISHED``.
        * ℹ️ CONFIGURE: Update parameters.
        * ✅ FINISHED: Change status to ``FINISHED``.
    * TASK-TO-PIPELINE:
        * 🆗 REPORT: Transmit status to pipeline.
        * 🔣 PRINT: Print to stdout/stderr.
    * TASK-TO-TASK:
        * 📶 DATA: Transmit data to next task.
        * ✅ FINISHED: Change status to ``FINISHED``.

    Since ``Task`` extends ``abc.ABC``, it has methods that must be
    overwritten, i.e. the "do" methods:

    * ``do_work``: Tasks call this function continuously in RUNNING status when
    there the queue has data. This method runs in a parallel subthread.
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
        is_start: First task flag.
        is_final: Last task flag.
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

        Notes:
            This method runs in the main process.
        """

        super().__init_subclass__(**kwargs)
        Task.class_registry[cls.__name__] = cls

    def __init__(self):
        """
        Initializes ``Task``.

        Notes:
            This method runs in the main process.
        """

        super().__init__()

        # Regular fields.
        self.name: str = self.__class__.__name__
        self.error: Exception = None
        self._kill: bool = False
        self.queue: collections.deque = collections.deque()
        self.status: Status = Status.READY
        self.config: dict = {}
        self.is_start: bool = False
        self.is_final: bool = False

        # ZMQ fields.
        self.context: zmq.Context = None
        self.socket_pull: zmq.Socket = None
        self.socket_push: zmq.Socket = None
        self.socket_dealer: zmq.Socket = None
        self.address_pull: str = None
        self.address_push: str = None
        self.address_router: str = None

    def do_report(self) -> dict:
        """
        Reports to the pipeline.

        Ths task runtime calls this method when handling report generation.

        Returns:
            Dictionary to send a report to the pipeline.

        Notes:
            The task runtime captures prints to stdout/stderr and sends them to
            the pipeline's ``handle_print`` method.

            The task runtime captures errors, updates it status to ``ERROR``
            and stores the latest error in the ``error`` field.

            This method runs in subprocesses, and it can be overwritten.
        """

        return {}

    def do_configure(self, config: dict) -> None:
        """
        Configures/reconfigures tasks.

        Ths task runtime calls this method when handling configuration.

        Parameters:
            config: New configuration.

        Notes:
            The task runtime captures prints to stdout/stderr and sends them to
            the pipeline's ``handle_print`` method.

            The task runtime captures errors, updates it status to ``ERROR``
            and stores the latest error in the ``error`` field.

            This method runs in subprocesses, and it can be overwritten.
        """

        pass

    def do_startup(self) -> None:
        """
        Initializes task runtimes.

        The task runtime calls this method after starting but before recieving
        the ``START`` message.

        Notes:
            The task runtime captures prints to stdout/stderr and sends them to
            the pipeline's ``handle_print`` method.

            The task runtime captures errors, updates it status to ``ERROR``
            and stores the latest error in the ``error`` field.

            This method runs in subprocesses, and it can be overwritten.
        """

        pass

    def do_cleanup(self) -> None:
        """
        Deinitializes task runtimes.

        The task runtime calls this method after recieving the ``STOP`` message
        before closing.

        Notes:
            The task runtime captures prints to stdout/stderr and sends them to
            the pipeline's ``handle_print`` method.

            The task runtime captures errors, updates it status to ``ERROR``
            and stores the latest error in the ``error`` field.

            This method runs in subprocesses, and it can be overwritten.
        """

        pass

    @abc.abstractmethod
    def do_work(self, value: typing.Any) -> typing.Any:  # pragma: no cover
        """
        Does stuff.

        The task runtime calls this method when in the ``RUNNING`` status and
        the task is first in the pipeline or has data in its input queue.

        When finished, call the ``send_finished``. To pause, call the
        ``send_pause`` method. To stop, call the ``send_stop`` method. To
        handle and error, raise it. Finally, return the data to send it to the
        next task in the pipeline; if this method returns ``None`` it will not
        send to the next task.

        Parameters:
            value: Data recieved from the previous task in the pipeline.

        Return:
            Data to send to the next task in the pipeline.


        Notes:
            The task runtime captures prints to stdout/stderr and sends them to
            the pipeline's ``handle_print`` method.

            The task runtime captures errors, updates it status to ``ERROR``
            and stores the latest error in the ``error`` field.

            This method runs in subprocesses, and it must be overwritten.
        """

        raise NotImplementedError

    def handle_connect(self, address_pull: str, is_start: bool, is_final: bool) -> None:
        """
        Handles ``CONNECT`` messages from the pipeline.

        This method connects the ZMQ pull sockect and setes the start/final
        flags. So, after calling this message, the task will communicate with
        other tasks.

        Parameters:
            address_pull: ZMQ pull socket address.
            is_start: First task flag.
            is_final: Last task flag.
        """

        if address_pull:
            self.socket_pull.connect(address_pull)
        self.address_pull = address_pull
        self.is_start = is_start
        self.is_final = is_final
        self.send_report(
            {
                "name": self.name,
                "address_pull": self.address_pull,
                "is_start": self.is_start,
                "is_final": self.is_final,
            }
        )
        self.handle_configure({})

    def handle_disconnect(self) -> None:
        """
        Handles ``DISCONNECT`` messages from the pipeline.

        This method disconnects the ZMQ pull sockect and resets the start/final
        flags to ``False``. So, after calling this message, the task will not
        communicate with other tasks.

        Notes:
            This method runs in subprocesses.
        """

        if self.address_pull:
            self.socket_pull.disconnect(self.address_pull)
        self.address_pull = None
        self.is_start = False
        self.is_final = False
        self.send_report(
            {
                "name": self.name,
                "address_pull": self.address_pull,
                "is_start": self.is_start,
                "is_final": self.is_final,
            }
        )

    def handle_start(self) -> None:
        """
        Handles ``START`` messages from the pipeline.

        This method changes task's status to ``RUNNING``. So, the task will
        still poll and handle message before calling ``do_work`` after getting
        the ``START`` message.

        Notes:
            This method runs in subprocesses.
        """

        self.status = Status.RUNNING

    def handle_stop(self) -> None:
        """
        Handles ``STOP`` messages from the pipeline.

        This method causes the tasks to quit and call ``do_cleanup``. So, the
        tasks will close after getting the ``STOP`` message.

        Notes:
            This method runs in subprocesses.
        """

        self._kill = True

    def handle_configure(self, config: dict) -> None:
        """
        Handles ``CONFIGURE`` messages from the pipeline.

        This method calls ``do_configure`` to enable user configuration and
        on-the-fly reconfiguration of tasks. So, to minimize memory usage,
        incoming configurations update, not replace, the current configuration.

        Parameters:
            config: Recieved parameters.

        Notes:
            Instead of overriding this function, use ``do_configure`` to
            prevent issues.

            This method runs in subprocesses.
        """

        try:
            with contextlib.redirect_stdout(io.StringIO()) as f:
                with contextlib.redirect_stderr(io.StringIO()) as g:
                    self.do_configure(config)
                    self.send_print(f.getvalue(), g.getvalue())
        except Exception as err:
            self.status = Status.ERROR
            self.error = err

        self.config |= config

    def handle_data(self, data: typing.Any) -> None:
        """
        Handles ``DATA`` message from the pervious task.

        This method appends incoming data to the end of the queue. So, tasks
        store their incoming data in their runtime.

        Parameters:
            data: Recieved data.

        Notes:
            This method runs in subprocesses.
        """

        self.queue.append(data)

    def handle_finished(self) -> None:
        """
        Handles ``FINISHED`` messages from the previous task.

        This method calls ``do_work`` until this tasks finishes, and it calls
        ``send_finished`` to cascade the ``FINISHED`` message through the
        pipeline. So, as ``FINISHED`` messages cascade through the pipeline,
        tasks call this method.

        Notes:
            This method runs in subprocesses.
        """

        self.send_report()

        while self.queue:
            self.poll()

            try:
                val = self.queue.popleft() if self.queue else None
                with contextlib.redirect_stdout(io.StringIO()) as f:
                    with contextlib.redirect_stderr(io.StringIO()) as g:
                        ret = self.do_work(val)
                        self.send_print(f.getvalue(), g.getvalue())
                self.send_data(ret)
            except Exception as err:
                self.status = Status.ERROR
                self.error = err

        self.send_finished()

    def send_report(self, report: dict | None = None) -> None:
        """
        Sends ``REPORT`` messages to the pipeline.

        This method transfers the dictionary returned from ``do_report``
        updated with default information to the pipeline. The pipeline handles
        this using ``handle_report``.

        Notes:
            Instead of overriding this function, use ``do_report`` to
            prevent issues.

            This method runs in subprocesses.
        """
        if report is None:
            try:
                with contextlib.redirect_stdout(io.StringIO()) as f:
                    with contextlib.redirect_stderr(io.StringIO()) as g:
                        report = self.do_report()
                        self.send_print(f.getvalue(), g.getvalue())
            except Exception as err:
                self.status = Status.ERROR
                self.error = err

            ps_data = psutil.Process(self.pid)

            tmp = {
                "name": self.name,
                "error": self.error,
                "status": self.status,
                "cpu": ps_data.cpu_percent(),
                "memory": ps_data.memory_percent(),
                "queue": len(self.queue),
            }
            if report is None:
                report = tmp
            else:
                report |= tmp

        msg = pickle.dumps(Message.REPORT(report), protocol=pickle.HIGHEST_PROTOCOL)
        self.socket_dealer.send(msg)

    def send_print(self, stdout: str, stderr: str) -> None:
        """
        Sends ``PRINT`` messages to the pipeline.

        This method transfers captured stdout and stderr data if anything was
        written to the streams to the pipeline. The pipeline handles this using
        ``handle_print``.

        Parameters:
            stdout: Captured stdout to send.
            stderr: Captured stderr to send.

        Notes:
            This method runs in subprocesses.
        """

        if stdout or stderr:
            msg = pickle.dumps(
                Message.PRINT(stdout, stderr), protocol=pickle.HIGHEST_PROTOCOL
            )
            self.socket_dealer.send(msg)

    def send_data(self, data: typing.Any) -> None:
        """
        Sends ``DATA`` messages to the next task.

        This transfering data through the pipeline if its not the final task.
        The next task in the pipeline handles this using ``handle_data``.

        Parameters:
            data: Sent data.

        Notes:
            This method runs in subprocesses.
        """

        msg = Message.DATA(data)
        if not self.is_final and data:
            self.socket_push.send_pyobj(msg)

    def send_finished(self) -> None:
        """
        Sends ``FINISHED`` messages to the next task.

        This method changes this task's status to ``FINISHED`` and it cascades
        the ``FINISHED`` message through the pipeline if its not the final
        task in the pipeline. The next task in the pipeline handles this using
        ``handle_finished``.

        Notes:
            This method runs in subprocesses.
        """

        self.status = Status.FINISHED
        self.send_report()

        msg = Message.FINISHED
        if not self.is_final:
            self.socket_push.send_pyobj(msg)

    def poll(self, is_block: bool = False) -> None:
        """
        Polls the sockets for messages from other the pipeline and other tasks.

        This method handles messages by calling the "handle" methods. The
        ``is_block`` flag determines if/if not this method block to wait for
        some message from the pipeline. If this tasks recieves a message from
        the pipeline or the previous task, it sends a report to the pipeline.

        Parameters:
            is_block: Block/no block flag.

        Notes:
            This method runs in subprocesses.
        """

        # Processing messages from pipeline.
        try:
            if is_block:
                msg = self.socket_dealer.recv()
            else:
                msg = self.socket_dealer.recv(flags=zmq.NOBLOCK)

            msg = pickle.loads(msg)

            if type(msg) == Message.CONNECT:
                self.handle_connect(*msg())
            elif msg == Message.DISCONNECT:
                self.handle_disconnect()
            elif msg == Message.START:
                self.handle_start()
            elif msg == Message.STOP:
                self.handle_stop()
            elif msg == Message.FINISHED:
                self.handle_finished()
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

            self.send_report()
        except zmq.Again:
            pass

    def run(self):
        """
        Runs the process.

        This method initializes ZMQ sockets, listens for and handles
        interprocess communication using the ``poll` method and the "handle"
        methods, implements the state machine, and calls the user-implemented
        "do" methods.

        Notes:
            This method is subprocesses' runtime.
        """

        self.status = Status.READY

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
            with contextlib.redirect_stdout(io.StringIO()) as f:
                with contextlib.redirect_stderr(io.StringIO()) as g:
                    self.do_startup()
                    self.send_print(f.getvalue(), g.getvalue())
        except Exception as err:
            self.status = Status.ERROR
            self.error = err

        self.send_report(
            {
                "name": self.name,
                "status": self.status,
                "error": self.error,
                "address_push": self.address_push,
                "address_router": self.address_router,
            }
        )

        while not self._kill:
            self.poll()

            try:
                if self.status == Status.RUNNING:
                    if self.queue or self.is_start:
                        val = self.queue.popleft() if self.queue else None
                        with contextlib.redirect_stdout(io.StringIO()) as f:
                            with contextlib.redirect_stderr(io.StringIO()) as g:
                                ret = self.do_work(val)
                                self.send_print(f.getvalue(), g.getvalue())
                        self.send_data(ret)
                    else:
                        continue
                elif self.status == Status.READY:
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
            with contextlib.redirect_stdout(io.StringIO()) as f:
                with contextlib.redirect_stderr(io.StringIO()) as g:
                    self.do_cleanup()
                    self.send_print(f.getvalue(), g.getvalue())
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
