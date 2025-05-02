"""Task and Pipeline class to run data acquisition and data handling.

This file provides two base classes: Task and Pipeline.

They can be used to create a data acquisition pipeline to take data
with the pixie16, convert the binary data to event data and do some
calculation on them.

To use the classes, create custom Task that inherit the base
class. Overwrite the init function if needed and the do_work
function to process the current work load. The cleanup function can be
overwritten to close files and is called once the tasks is finished or
if it gets a keyboard interrupt.

Tasks can then be chained together automatically using the Pipeline
class. This class can also be used to run the pipeline, print a nice
status bar. An example use of 3 different tasks is:

    A = TaskA()
    B = TaskB()
    C = TaskC()
    tasks = [A, B, C]

    pipeline = Pipeline(tasks)

    pipeline.start()  # starts all tasks

    pipeline.wait_with_progress(total=14.0)  # reports progress with a bar

    pipeline.join()  # waits for all tasks to finish
    pipeline.close()  # releases recsources

"""

from collections import deque
from contextlib import redirect_stdout
import copy
import io
import multiprocessing
import queue
import sys
import time
import traceback
from typing import Union

from more_itertools import pairwise
import psutil
from rich.progress import Progress, BarColumn, TimeRemainingColumn, TimeElapsedColumn
from rich import print
import zmq


class Task(multiprocessing.Process):
    """Custom Process that can be stopped and joined into a pipeline.

    ZMQ Push/Pull sockets are used to get data or send data to the next Tasks. We
    provide functions that should be overwritten when customizing
    a Task:

    do_work(value): gets called continously in a while loop without an input queue
    or gets called whenever a value arrives in the input queue.
    If the tasks is done, do_work should set self.done to True.

    cleanup(): Will be called at the end of a tasks, option to close any files, etc.

    If you start a data acquisition in the pixie, make sure that you call
    `init_and_boot` inside the do_work function. Since, for example, the `__init__`
    of a Task will still be executed in the main thread.

    If you need things to be executed in the new process, put them into
    the run() method. As for example is done for the ZMQ initialization.

    Specific tasks are defined in `task.py`.

    Tasks are meant to be created at the beginning of a program and then
    re-used.  You can daisychain them together in different ways for
    each run by reassigning the push/pull connections.

    Each task has a ZMQ socket to receive commands from the main
    pipeline and also a way to send messages back to the main. By
    default we send back CPU and memory usage every 5 seconds and also
    how many items are in the queue.

    Any `print` output that is generated in the do_work function will be
    captured and send as a message to the main pipeline (using the
    `status_queue`) where it will be printed using `rich`.

    """

    # keep a list of all the subclasses
    class_registry = {}

    def __init_subclass__(cls, **kwargs):
        """Called when a subclass is defined."""
        super().__init_subclass__(**kwargs)
        Task.class_registry[cls.__name__] = cls

    def __init__(self, pipeline_address):
        super().__init__()
        # this is the address of the main pipeline
        self.pipeline_address = pipeline_address
        self.start_time = None
        self.stop_time = None
        # messages captured to be send back to the main pipeline
        self.messages = []
        # should we stop?
        self.done = False
        self.name = "Name not set"

        # the current status of the task:
        #   paused   -  not doing any work
        #   ready    -  used in a pipeline, but not started yet, but configured
        #   running  -  used in the current pipeline
        #   finished -  queue empty and previous task is finished
        self.status = "paused"
        # are there any more tasks in the pipeline?
        self.is_final_task = None

        # store all received items from previous task here, so that we can
        # handle them one by one and also call len() on the waiting queue
        self.queue = deque()

        # ZMQ socket to get data from (set in run() method)
        self.pull = None
        self.pull_address = None

        # ZMQ socket to send data to the next task in the pipeline
        self.push = None

        self.last_update = time.time()
        self.work_counter = 0

        # keep track of any internal state
        self.state = {}

    def cleanup(self):
        """Can be overwritten to close any open files, etc"""
        pass

    def send(self, value_dict):
        """Send a status update to the main pipeline.

        Status updates are only send at least 0.5 seconds apart so
        that they don't spam the status queue (unless `force` is given).

        Since sending of the `value_dict` is not garantueed, do not rely on
        this feature and only send information for information purposes.

        Currently, there are two keys in the `value_dict` that have special meaning:
        - runtime: should be the elappsed time during data acquisition
        - message: Any message that should be printed to the screen (we use this, so that the progress bar works well)

        """
        current_time = time.time()
        if value_dict is not None:
            self.socket.send_json(value_dict)
        self.last_update = current_time
        for m in self.messages:
            self.socket.send_json({"type": "message", "message": m})
        self.messages = []

    def do_work(self, value):
        """Needs to be overwritten to do the work.

        The function should return a dictionary where it can store
        multiple values. It must include a 'type' key that has the
        value 'data' and a 'data' key, which should include the data for
        the next task. It may include additional information, say
        'voltage' or 'timestamp'.

        Once a task is done, it should return a `{'type':'finished'} to the
        next task.

        """
        raise NotImplementedError

    def handle_print(self, stringIO: io.StringIO):
        """Handle print statements that got captured"""
        msg = stringIO.getvalue()
        if msg:
            msg = msg.split("\n")
            self.messages += msg
        self.send({"type": "message", "messages": self.messages})

    def handle_command(self, cmd):
        print(f"[{self.name}] Received command: {cmd}")
        cmd_id = cmd.get("cmd_id")

        # Process command here (override in subclass if needed)
        match cmd.get("type"):
            case "connect":
                if (endpoint := cmd.get("endpoint")) is not None:
                    self.pull.connect(endpoint)
                    self.pull_address = endpoint
            case "disconnect":
                if self.pull_address:
                    self.pull.disconnect(self.pull_address)
                self.pull_address = None
            case "set_status":
                value = cmd.get("status")
                if value is not None:
                    self.status = value

                value = cmd.get("final")
                if value is not None:
                    self.is_final_task = value

            case "configure":
                cfg = cmd.get("config")
                if isinstance(cfg, dict):
                    self.state.update(cfg)
                self.configure()
            case "list_config":
                tmp = copy.deepcopy(self.state)
                tmp["type"] = "configuration"
                tmp["name"] = self.name
                self.send(tmp)
            case _:
                self.handle_user_command(cmd)

        # Send ACK back
        self.send({"type": "ack", "cmd_id": cmd_id})

    def configure(self):
        """Can be overriden by a subclass to handle self.state variables received."""
        pass

    def handle_user_command(self, cmd):
        """Place for the individual task to define more commands."""
        pass

    def user_status(self, d: dict):
        """Can be overwritten to add custom elements to the status messages."""
        return d

    def run(self):
        """Runs the new process.

        We handle anythin in here that has to be done once the process
        started, e.g., ZMQ socket creation.

        This also handles communication running data in a continuous
        running while loop.
        """
        # Create ZMQ sockets, and other tasks that need to be done once the
        # process already is running, for example zmq.Context cannot be pickled
        # and therefore not created in the main program
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.DEALER)
        self.socket.setsockopt_string(zmq.IDENTITY, self.__class__.__name__)
        self.socket.connect(self.pipeline_address)

        # The push socket is used to send data to the next task
        self.push = self.context.socket(zmq.PUSH)
        port = self.push.bind_to_random_port("tcp://127.0.0.1")
        self.push_endpoint = f"tcp://127.0.0.1:{port}"

        # report this back to the main thread
        self.send({"type": "endpoint", "value": self.push_endpoint})

        # the pull socket is used to receive data from previous tasks, we only
        # create it here, but don't connect it to an address yet. The main
        # pipeline will do this
        self.pull = self.context.socket(zmq.PULL)

        # We use psutil to get CPU and memory usage
        proc = psutil.Process()
        last_status_time = 0

        try:
            while not self.done:
                # save the time we do the first work unit
                if self.start_time is None:
                    self.start_time = time.time()

                now = time.time()
                # if nothing happens, we call time.sleep later()
                wait = True

                # check for commands
                try:
                    msg = self.socket.recv_json(flags=zmq.NOBLOCK)
                    self.handle_command(msg)
                    wait = False
                except zmq.Again:
                    pass

                # check for new values in the pipeline
                try:
                    value = self.pull.recv_pyobj(flags=zmq.NOBLOCK)
                    self.queue.append(value)
                    wait = False
                except zmq.Again:
                    pass

                if now - last_status_time >= 5.0:
                    mem_info = proc.memory_info()
                    cpu_percent = proc.cpu_percent(interval=None)
                    status = {
                        "type": "status",
                        "memory_rss": mem_info.rss,
                        "memory_vms": mem_info.vms,
                        "cpu_percent": cpu_percent,
                        "queue length": len(self.queue),
                        "timestamp": now,
                        "status": self.status,
                    }
                    status = self.user_status(status)
                    self.send(status)
                    last_status_time = now
                    wait = False

                # do the work and capture any print statements
                out = None
                value = None
                if self.status == "running":
                    if (self.pull_address and self.queue) or (
                        self.pull_address is None
                    ):
                        if self.queue:
                            value = self.queue.popleft()
                        if value == {"type": "finished"}:
                            self.status = "finished"
                            with redirect_stdout(io.StringIO()) as f:
                                self.cleanup()
                                self.handle_print(f)
                            continue

                        with redirect_stdout(io.StringIO()) as f:
                            out = self.do_work(value)
                            self.work_counter += 1
                            self.handle_print(f)
                            wait = False

                    # send result to next stage if available
                    if (not self.is_final_task) and (out is not None):
                        self.push.send_pyobj(out)

                if wait:
                    time.sleep(0.1)

        except Exception as e:
            self.send({"type": "error", "name": self.name})
            print(f"[DEBUG] ----- exception in {self.name} ----")
            print(e)
            print(sys.exc_info())
            traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()

        self.stop_time = time.time()

        self.socket.close()
        self.context.term()


class Pipeline:
    """Manage a linear chain of tasks.

    Chain the input and outputs together, some shortcuts to
    start/stop/join all the Tasks and to test if any Task is still
    running.

    """

    def __init__(self, name: str = "Run", verbose: bool = False):
        self._tasks = {}
        self._endpoints = {}

        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.ROUTER)
        # Bind to a random port on all interfaces (or localhost if you prefer)
        bind_addr_base = "tcp://127.0.0.1"
        port = self.socket.bind_to_random_port(bind_addr_base)
        self.bind_address = f"{bind_addr_base}:{port}"
        print(f"[Pipeline] Bound ROUTER on {self.bind_address}")

        self.poller = zmq.Poller()
        self.poller.register(self.socket, zmq.POLLIN)

        self.task_ack = {}  # Maps identity -> last ack time

        self._cmd_id_counter = 0
        self._pending_acks = {}  # cmd_id -> (task_id, command)

        self.verbose = verbose
        self.status = {}
        self.messages = []
        self.i = 0
        self.start_time = 0
        self.runtime = None
        self.name = name

    def create_task(self, task_name: str):
        if task_name in self._tasks:
            print(f"{task_name} already exists")
        else:
            tmp = Task.class_registry[task_name](self.bind_address)
            self._tasks[task_name] = tmp
            tmp.start()

    def create_pipeline(self, tasks: list[str]):
        for t in tasks:
            self.create_task(t)

        print("Waiting for endpoints to be ready")
        now = time.time()
        while len(self._tasks) != len(self._endpoints):
            self.poll_once()
            time.sleep(0.05)
            if time.time() - now > 20:
                print("error no endpoints received within 20 s")
                break

        # disconnect any old pipeline
        for t in self._tasks:
            self.send_command(t, {"type": "disconnect"})

        # set status for each task
        for t in self._tasks:
            self.send_command(t, {"type": "set_status", "value": "ready"})

        # connect new queues
        if len(tasks) > 1:
            for A, B in pairwise(tasks):
                self.link_tasks(A, B)

    def link_tasks(self, A, B):
        """Link two tasks in a pipeline using a queue."""
        if A not in self._tasks:
            print(f"Error {A} not in tasks")
        if B not in self._tasks:
            print(f"Error {B} not in tasks")

        if A not in self._endpoints:
            print(f"Error {A}'s push endpoint not known")

        self.send_command(B, {"type": "connect", "endpoint": self._endpoints[A]})
        self.send_command(
            A,
            {
                "type": "set_status",
                "status": "ready",
                "final": False,
            },
        )
        self.send_command(
            B,
            {
                "type": "set_status",
                "status": "ready",
                "final": True,
            },
        )

        if self.verbose:
            print(f"[Pipeline] setting up pipeline link: {A} -> {B}", flush=True)

    def start(self):
        """Start all tasks."""
        for t in self._tasks:
            self.send_command(t, {"type": "set_status", "status": "running"})

    def join(self):
        """Join all tasks, i.e. wait until they are all done."""
        for t in self._tasks.values():
            t.join()

    def close(self):
        """Release all resources, needed for pixie16.control."""
        for t in self._tasks.values():
            t.close()
        self.socket.close()
        self.context.term()

    def is_alive(self):
        """Check if any task is still running."""
        for t in self._tasks:
            if t.is_alive():
                return True
        return False

    def execute(self, progress_bar_time: float | int = 0):
        """Runs the whole pipeline.

        Parameters
        ----------
        progress_bar_time
           if > 0 run with a progress bar with this number as the total time it should
           take. Otherwise, run without progressbar.

        """
        self.start()
        if progress_bar_time:
            self.wait_with_progress(total=progress_bar_time)
        else:
            self.wait()
        self.join()
        self.close()

    def update_status(self):
        """Look at the status queue and update the pipeline status.

        We also parse out the runtime of the pixie16 if present.
        """
        try:
            while True:
                value = self.status_queue.get(block=False)
                if "runtime" in value:
                    self.runtime = value.pop("runtime")
                if "message" in value:
                    self.messages.append(value.pop("message"))

                self.status.update(value)
        except queue.Empty:
            pass

    def wait_with_progress(self, total):
        """Create a progress bar while the pipeline is running and show the status updates.

        The run can be interruptted using Ctrl-C.
        """
        try:
            with Progress(
                f"[green]{self.name}",
                BarColumn(
                    style="grey35 on black",
                    complete_style="green on black",
                    finished_style="red on black",
                    pulse_style="white on purple",
                ),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                "{task.description}",
                refresh_per_second=4,
            ) as progress:
                task = progress.add_task("[green] Run", total=total)
                while self.is_alive():
                    time.sleep(0.1)
                    self.update_status()
                    for m in self.messages:
                        progress.console.print(m)
                    self.messages = []
                    text = ",".join(f"{k}: {v}" for k, v in self.status.items())
                    if self.runtime is None:
                        text = "Setting up process pipeline " + text
                        runtime = round(time.time() - self.start_time, 2)
                    else:
                        runtime = self.runtime
                    progress.update(task, completed=runtime, description=text)
                # finish progress bar and print remaining messages
                self.update_status()
                for m in self.messages:
                    print(m)
                progress.update(task, completed=total, description=text)

        except KeyboardInterrupt:
            print("[yellow]INFO[/] got keyboard interrupt... closing")
            self.stop()

    def wait(self):
        """Wait for the pipeline to finish.

        The run can be interruptted using Ctrl-C.
        """
        try:
            while self.is_alive():
                time.sleep(0.1)
                self.update_status()
                for m in self.messages:
                    print(m)
                self.messages = []
        except KeyboardInterrupt:
            print("[yellow]INFO[/]] got keyboard interrupt... closing")
            self.stop()
        # print any remaining messages
        time.sleep(0.1)
        self.update_status()
        for m in self.messages:
            print(m)

    def poll_once(self):
        """
        Poll the ROUTER socket once, process any incoming messages,
        then return immediately.
        """
        socks = dict(self.poller.poll(0))
        if socks.get(self.socket) == zmq.POLLIN:
            identity, msg = self.socket.recv_multipart()
            task_id = identity.decode()
            msg_dict = zmq.utils.jsonapi.loads(msg)
            self.task_ack[task_id] = time.time()  # update last seen time

            match msg_dict.get("type"):
                case "ack":
                    cmd_id = msg_dict.get("cmd_id")
                    if cmd_id in self._pending_acks:
                        print(
                            f"[Pipeline] Received ACK for cmd {cmd_id} from {task_id}"
                        )
                        del self._pending_acks[cmd_id]
                case "status":
                    print(f"[Pipeline] Status from {task_id}: {msg_dict}")
                case "message":
                    print(f"[Pipeline] Message from {task_id}: {msg_dict}")
                case "endpoint":
                    self._endpoints[task_id] = msg_dict.get("value")
                    print(f"[Pipeline] New endpoint from {task_id}: {msg_dict}")
                case _:
                    print(f"[Pipeline] Unknown message from {task_id}: {msg_dict}")

    def send_command(self, task_id, command_dict):
        if task_id not in self._tasks:
            print(f"[Pipeline] Warning: sending to unknown task {task_id}")
        self._cmd_id_counter += 1
        cmd_id = self._cmd_id_counter
        command_dict = dict(command_dict)  # copy to avoid side effects
        command_dict["cmd_id"] = cmd_id
        self._pending_acks[cmd_id] = (task_id, command_dict)
        print(f"[Pipeline] Sending command {cmd_id} to {task_id}: {command_dict}")
        self.socket.send_multipart(
            [task_id.encode(), zmq.utils.jsonapi.dumps(command_dict)]
        )
