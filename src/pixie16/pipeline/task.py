"""Base Task class for pipeline data processing components.

This module defines the Task base class that all pipeline processing
components inherit from. Tasks run as independent processes and communicate
via ZeroMQ messages, enabling distributed and parallel data processing.

Key Features
------------
- Multiprocessing with ZeroMQ communication
- Automatic task registration system
- State machine with error handling
- Memory and performance monitoring
- Extensible callback system

Task Lifecycle
--------------
1. Registration (automatic via __init_subclass__)
2. Instantiation by Pipeline
3. Process startup and ZeroMQ connection
4. Message handling loop
5. Graceful shutdown
"""

import io
import abc
import sys
import time
import typing
import pickle
import traceback
import contextlib
import collections
import multiprocessing

import zmq
import psutil

from .error import Error
from .status import Status
from .message import Message


SECONDS_WAIT = 0.1


class Task(multiprocessing.Process):
    """Base class for pipeline processing tasks.

    Task represents a single processing unit in the data analysis pipeline.
    Each task runs as an independent process and communicates via ZeroMQ
    messages. Tasks implement specific data processing algorithms and can
    be chained together to create complex workflows.

    Architecture
    ------------
    Tasks follow a message-driven architecture with four method categories:
    - **Handlers**: Process incoming messages from other tasks/pipeline
    - **Senders**: Dispatch outgoing messages and data
    - **Actions**: User interface methods for external control
    - **Callbacks**: Extension points for subclass customization

    Task States
    -----------
    - ⏸️ WAITING: Task idle, ready to process
    - ▶️ RUNNING: Task actively processing data
    - 🏁 FINISHED: Task completed successfully
    - ⏏️ DYING: Task shutting down
    - 🆘 PANICKING: Task in error state

    Message Protocol
    ----------------
    - ℹ️ CONFIGURE: Update user parameters
    - 🔁 CONNECT: Update system parameters
    - ▶️ START: Begin processing
    - ⏹️ STOP: Pause processing
    - ⏏️ QUIT: Shutdown task
    - 📶 DATA: Inter-task data flow
    - 🆗 REPORT: Status/monitoring info
    - 🔣 PRINT: Debug output
    - 🆘 ERROR: Error conditions

    Examples
    --------
    >>> class MyTask(Task):
    ...     def callback_process(self, data):
    ...         return process_data(data)
    >>> task = MyTask()
    >>> task.start()
    """

    # Dunders

    class_registry = {}

    def __init_subclass__(cls, **kwargs):
        """Register Task subclasses in global registry.

        Automatically registers each Task subclass by name, enabling
        dynamic task creation by the Pipeline class.

        Parameters
        ----------
        **kwargs
            Additional subclass initialization parameters.

        Notes
        -----
        Task registration is automatic - no manual registration required.
        """

        super().__init_subclass__(**kwargs)
        Task.class_registry[cls.__name__] = cls

    def __init__(self, **kwargs):
        """Initialize a new Task instance.

        Sets up the task's multiprocessing environment, ZeroMQ messaging,
        and internal state management structures.

        Parameters
        ----------
        **kwargs
            Task-specific configuration parameters passed from Pipeline.

        Notes
        -----
        Typically called automatically by Pipeline.create_task() rather
        than directly by user code.
        """

        super().__init__()

        self.kwargs = kwargs
        self.name = self.__class__.__name__
        self.config = {}
        self.status = None
        self._queue = collections.deque()
        self._context = None
        self._socket_push = None
        self._socket_pull = None
        self._socket_dealer = None
        self._address_push = None
        self._address_pull = None
        self._address_dealer = None

        # get's set in pipeline before starting the task
        self.address_router = None

        self._heart_beat_timestamp = 0
        self._ps_data = None
        self._pending_report = {}
        self._last_report_flush_time = 0

    def do_init(self) -> None:
        """
        ``init`` callback.
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

    def do_connect(self, address_pull: str, is_start: bool, is_final: bool) -> None:
        """
        ``connect`` callback.

        Parameters:
            address_pull: ZMQ pll address.
            is_start: First task flag.
            is_final: Last task flag.
        """

        pass

    def do_configure(self, config: dict) -> None:
        """
        ``configure`` callback.

        Parameters:
            config: Configuration for configuring.
        """

        pass

    def do_wait(self) -> None:
        """
        ``wait`` callback.
        """

        pass

    def do_work(self, datum: typing.Any) -> None:
        """
        ``work`` callback.

        Parameters:
            datum: Data for working.
        """

        pass

    # Handlers

    def _handle_start(self) -> None:
        """
        Handles ``Message.START``.
        """

        self.begin()

    def _handle_stop(self) -> None:
        """
        Handles ``Message.STOP``.
        """

        while self._queue:
            self.poll()
            self.work()

        self.stop()

    def _handle_quit(self) -> None:
        """
        Handles ``Message.QUIT``.
        """

        self.status = Status.DYING

    def _handle_connect(
        self, address_pull: str, is_start: bool, is_final: bool
    ) -> None:
        """
        Handles ``Message.CONNECT``.

        Parameters:
            address_pull: ZMQ pll address.
            is_start: First task flag.
            is_final: Last task flag.
        """

        self.connect(address_pull, is_start, is_final)

    def _handle_configure(self, config: dict) -> None:
        """
        Handles ``Message.CONFIGURE``.

        Parameters:
            config: Configuration recieved.
        """

        self.configure(config)

    def _handle_data(self, data: typing.Any) -> None:
        """
        Handles ``Message.DATA``.

        Parameters:
            data: Data recieved.
        """

        self._queue.append(data)
        self.report({"queue": len(self._queue)})

    def _handle_finished(self):
        # finish work
        while self._queue:
            self.poll()
            self.work()

        # handle left over and open files, etc.
        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.do_stop()
                self.print(out.getvalue())
        except Exception as err:
            self.panic(Error(traceback.format_exc()))

        self.status = Status.FINISHED
        self.send_finished()
        self.report({"status": self.status})

    # Senders

    def _send_stop(self) -> None:
        """
        Sends ``Message.STOP``.
        """

        if not self._is_final:
            msg = Message.STOP
            self._socket_push.send_pyobj(msg)

    def send_finished(self) -> None:
        """
        Sends ``Message.FINISHED``.
        """
        self.status = Status.FINISHED

        if not self._is_final:
            msg = Message.FINISHED
            self._socket_push.send_pyobj(msg)
        else:
            self.send_report({"task finished": True})

        self.flush_report()

    def send_data(self, data: typing.Any) -> None:
        """
        Sends ``Message.DATA``.

        Parameters:
            data: Data to send.
        """

        if data and not self._is_final:
            msg = Message.DATA(data)
            self._socket_push.send_pyobj(msg)

    def flush_report(self) -> None:
        """Flushes any pending reports to the pipeline."""
        if self._pending_report and self._socket_dealer:
            msg = pickle.dumps(
                Message.REPORT(self._pending_report), protocol=pickle.HIGHEST_PROTOCOL
            )
            self._socket_dealer.send(msg)
            self._pending_report = {}
            self._last_report_flush_time = time.time()

    def send_report(self, report: dict, force: bool = False) -> None:
        """
        Sends ``Message.REPORT``.

        Parameters:
            report: Report to send.
            force: Force immediate dispatch bypassing rate limiter.
        """
        if not report:
            return

        self._pending_report.update(report)

        # Critical lifecycle keys must be dispatched immediately
        critical_keys = {
            "status",
            "task finished",
            "address_push",
            "address_pull",
            "is_start",
            "is_final",
            "meta-start-time",
            "meta-end-time",
        }

        if force or any(k in report for k in critical_keys):
            self.flush_report()
            return

        now = time.time()
        if now - self._last_report_flush_time >= 0.5:
            self.flush_report()

    def _send_print(self, string: str) -> None:
        """
        Sends ``Message.PRINT``.

        Parameters:
            string: String to send.
        """

        if string:
            msg = pickle.dumps(Message.PRINT(string), protocol=pickle.HIGHEST_PROTOCOL)
            self._socket_dealer.send(msg)

    def _send_error(self, error: Error) -> None:
        """
        Sends ``Message.ERROR``.

        Parameters:
            error: Error to send.
        """

        if error:
            msg = pickle.dumps(Message.ERROR(error), protocol=pickle.HIGHEST_PROTOCOL)
            self._socket_dealer.send(msg)

    # Actions

    def init(self):
        if self.address_router is None:
            print(f"ERROR  no router address given in {self.name}!")

        self.status = Status.WAITING
        self._context = zmq.Context()
        self._socket_dealer = self._context.socket(zmq.DEALER)
        self._socket_push = self._context.socket(zmq.PUSH)
        self._socket_pull = self._context.socket(zmq.PULL)
        self._socket_dealer.setsockopt(zmq.IDENTITY, self.name.encode())
        self._socket_dealer.connect(self.address_router)
        self._address_push = self._socket_push.bind_to_random_port("tcp://127.0.0.1")
        self._address_push = f"tcp://127.0.0.1:{self._address_push}"

        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.do_init()
                self.print(out.getvalue())
        except Exception as err:
            self.panic(Error(traceback.format_exc()))

        self.report({"status": self.status, "address_push": self._address_push})

    def begin(self):
        """
        Starts the task.
        """

        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.do_start()
                self.print(out.getvalue())
        except Exception as err:
            self.panic(Error(traceback.format_exc()))

        self.status = Status.RUNNING
        self.report({"status": self.status})

    def stop(self):
        """
        Stops the task.
        """

        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.do_stop()
                self.print(out.getvalue())
        except Exception as err:
            self.panic(Error(traceback.format_exc()))

        self.status = Status.WAITING
        self.report({"status": self.status})
        self._send_stop()

    def quit(self):
        """
        Quits the task.
        """

        if self.status != Status.WAITING:
            self.stop()

        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.do_quit()
                self.print(out.getvalue())
        except Exception as err:
            self.panic(Error(traceback.format_exc()))

        self.status = Status.DYING
        self.report({"status": self.status})

        # Flush any remaining metadata/metrics before pulling the plug
        self.flush_report()

        if self._socket_pull:
            self._socket_pull.setsockopt(zmq.LINGER, 0)
            self._socket_pull.close()
        if self._socket_push:
            self._socket_push.setsockopt(zmq.LINGER, 0)
            self._socket_push.close()
        if self._socket_dealer:
            self._socket_dealer.setsockopt(zmq.LINGER, 0)
            self._socket_dealer.close()
        if self._context:
            self._context.term()

    def connect(self, address_pull: str, is_start: bool, is_final: bool):
        """
        Connects the task.

        Parameters:
            address_pull: ZMQ pll address.
            is_start: First task flag.
            is_final: Last task flag.
        """

        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.do_connect(address_pull, is_start, is_final)
                self.print(out.getvalue())
        except Exception as err:
            self.panic(Error(traceback.format_exc()))

        if address_pull:
            self._socket_pull.connect(address_pull)
        elif self._address_pull:
            self._socket_pull.disconnect(self._address_pull)

        self._address_pull = address_pull
        self._is_start = is_start
        self._is_final = is_final
        self.send_report(
            {
                "address_pull": self._address_pull,
                "address_push": self._address_push,
                "is_start": self._is_start,
                "is_final": self._is_final,
            }
        )

    def configure(self, config: dict):
        """
        Configures the task.

        Parameters:
            config: Configuration for configuring.
        """

        if not config:
            return

        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.do_configure(config)
                self.print(out.getvalue())
        except Exception as err:
            self.panic(Error(traceback.format_exc()))

        self.config |= config

    def panic(self, error: Error):
        """
        Panics for the task.

        Parameters:
            error: Error for panicking.
        """

        self.status = Status.PANICKING
        self._send_error(error)
        self.report({"status": self.status})

    def wait(self):
        """
        Waits for the task.
        """

        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.do_wait()
                self.print(out.getvalue())
        except Exception as err:
            self.panic(Error(traceback.format_exc()))

        time.sleep(SECONDS_WAIT)

    def work(self) -> None:
        """
        Works for the task.
        """

        val = self._queue.popleft() if self._queue else None

        if val or self._is_start:
            if val is Message.FINISHED:
                self.send_finished()
                return

            try:
                # with contextlib.redirect_stdout(io.StringIO()) as out:
                #     ret = self.do_work(val)
                #     self._send_data(ret)
                # self.print(out.getvalue())
                ret = self.do_work(val)
                if ret is not None:
                    self.send_data(ret)
            except Exception as err:
                self.panic(Error(traceback.format_exc()))

    def report(self, report: dict) -> None:
        """
        Reports for the task.

        Parameters:
            report: Report to report.
        """

        self.send_report(report)

    def print(self, string: str) -> None:
        """
        Prints for the task.

        Parameters:
            string: String to print.
        """

        self._send_print(string)

    def send(self, report: typing.Any) -> None:
        """
        Reports for the task.

        Parameters:
            data: Data to send.
        """

        self.send_data(report)

    def poll(self):
        """
        Listens to sockets for the task.
        """

        # from pipeline
        try:
            msg = self._socket_dealer.recv(flags=zmq.NOBLOCK)
            msg = pickle.loads(msg)

            if type(msg) == Message.CONNECT:
                self._handle_connect(*msg())
            elif type(msg) == Message.CONFIGURE:
                self._handle_configure(*msg())
            elif msg == Message.START:
                self._handle_start()
            elif msg == Message.STOP:
                self._handle_stop()
            elif msg == Message.QUIT:
                self._handle_quit()
            else:  # pragma: no cover
                print(f"Error to unhandled message 1 {msg}")
                assert False
        except zmq.Again:
            pass

        # from previous task
        try:
            msg = self._socket_pull.recv_pyobj(flags=zmq.NOBLOCK)

            if type(msg) == Message.DATA:
                self._handle_data(*msg())
            elif msg == Message.STOP:
                self._handle_stop()
            elif msg == Message.FINISHED:
                self._handle_finished()
            else:  # pragma: no cover
                print(f"Error to unhandled message 2 {msg}")
                assert False
        except zmq.Again:
            pass

    def send_heart_beat(self):
        "send a heart beat every second"
        now = time.time()
        if now - self._heart_beat_timestamp > 0.5:  # TODO: slow down later
            if self._ps_data is None:
                self._ps_data = psutil.Process(self.pid)

            self.send_report(
                {
                    "name": self.name,
                    "status": self.status,
                    "cpu": self._ps_data.cpu_percent(),
                    "memory": self._ps_data.memory_info().rss,
                    "queue": len(self._queue),
                    "activity": now,
                }
            )

            self._heart_beat_timestamp = now

    def run(self):
        """
        Represents the task.
        """

        self.init()

        while True:
            self.poll()

            self.send_heart_beat()

            if self.status == Status.RUNNING:
                self.work()
            elif self.status == Status.WAITING:
                self.wait()
            elif self.status == Status.FINISHED:
                self.wait()
            elif self.status == Status.PANICKING:
                self.wait()
            elif self.status == Status.DYING:
                break
            else:
                print(f"Error unhandled run status {self.status}")

                assert False
