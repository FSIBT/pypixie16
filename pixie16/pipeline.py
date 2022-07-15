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

from contextlib import redirect_stdout
import io
import multiprocessing
import queue
import sys
import time
import traceback
from typing import List, Union

from more_itertools import pairwise
from rich.progress import Progress, BarColumn, TimeRemainingColumn, TimeElapsedColumn
from rich import print


class Task(multiprocessing.Process):
    """Custom Process that can be stopped and joined into a pipeline.

    Queues are used to get data or send data to the next Tasks. We
    provide functions that should be overwritten when customizing
    a Task:

    do_work(value): gets called continously in a while loop without an input queue
    or gets called whenever a value arrives in the input queue.
    If the tasks is done, do_work should set self.done to True.

    cleanup(): Will be called at the end of a tasks, option to close any files, etc.

    If you start a data acquisition in the pixie, make sure that you call
    `init_and_boot` inside the do_work function. Since the, for example, the `__init__`
    of a Task will still be executed in the main thread.

    For example of Tasks, see `task.py`

    Since Tasks are meant to be daisychained together, each has an `input_queue` and
    an `output_queue`. Furthermore, there can be a `status_queue` that is used to talk
    to the main thread and print information to the screen.

    Any `print` output that is generated in the do_work function will be captured and
    send as a message to the main pipeline (using the `status_queue`) thread where it
    will be printed using rich.

    """

    def __init__(self, event=None):
        super().__init__()
        self.stop_event = event or multiprocessing.Event()
        self.input_queue = None
        self.output_queue = None
        self.status_queue = None
        self.start_time = None
        self.stop_time = None
        self.messages = []  # messages to be send to the main pipeline
        self.name = "general task"
        self.done = False
        self.last_update = time.time()

    def cleanup(self):
        """Can be overwritten to close any open files, etc"""
        pass

    def send_status(self, value_dict):
        """Send a status update to the main pipeline.

        Status updates are only send at least 0.5 seconds apart so
        that they don't spam the status queue.

        Since sending of the `value_dict` is not garantueed, do not rely on
        this feature and only send information for information purposes.

        Currently, there are two keys in the `value_dict` that have special meaning:
        - runtime: should be the elappsed time during data acquisition
        - message: Any message that should be printed to the screen (we use this, so
                   that the progress bar works well)

        """
        current_time = time.time()
        if self.status_queue and (current_time - self.last_update > 0.5):
            self.status_queue.put(value_dict)
            self.last_update = current_time
            for m in self.messages:
                self.status_queue.put({"message": m})
            self.messages = []

    def do_work(self, value):
        """Needs to be overwritten to do the work.

        value will be the current element in the queue.
        """
        raise NotImplementedError

    def stop(self):
        """Set signal that will stop all workers."""
        self.stop_event.set()

    def join(self, *args, **kwargs):
        """Stop all workers and wait until they are done."""
        self.stop()
        super().join(*args, **kwargs)

    def handle_print(self, stringIO: io.StringIO):
        """Handle print statements that got captured"""
        msg = stringIO.getvalue()
        if msg:
            msg = msg.split("\n")
            self.messages += msg
        self.send_status({})

    def run(self):
        try:
            while not self.stop_event.is_set() and not self.done:
                # get next value from queue or if no queue set it to None
                if self.input_queue is None:
                    value = None
                else:
                    try:
                        value = self.input_queue.get(timeout=0.2)
                        if value is None:
                            self.done = True
                            continue
                    except queue.Empty:
                        continue
                # save the time we do the first work unit
                if self.start_time is None:
                    self.start_time = time.time()
                # do the work and capture any print statements
                with redirect_stdout(io.StringIO()) as f:
                    out = self.do_work(value)
                    self.handle_print(f)

                # send result to next stage if available
                if self.output_queue and out is not None:
                    self.output_queue.put(out)
        except KeyboardInterrupt:
            self.stop_event.set()
        except Exception as e:
            print(f"[DEBUG] ----- exception in {self.name} ----")
            print(e)
            print(sys.exc_info())
            traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()
            self.stop_event.set()
        finally:
            with redirect_stdout(io.StringIO()) as f:
                self.cleanup()
                self.handle_print(f)

        # if we are done, indicate that the queue should end
        if self.output_queue:
            self.output_queue.put(None)
        self.stop_time = time.time()

        # print(f"Finished Tasks {self.name}")


class Pipeline:
    """Manage a linear chain of tasks.

    Chain the input and outputs together, some shortcuts to
    start/stop/join all the Tasks and to test if any Task is still
    running.

    """

    def __init__(self, tasks: List[Task], name: str = "Run", verbose: bool = False):
        self._tasks = tasks
        self.verbose = verbose
        self.status = {}
        self.messages = []
        self.i = 0
        self.start_time = 0
        self.runtime = None
        self.queues = {}
        self.name = name

        # we'll use a single event for all tasks
        self.stop_event = multiprocessing.Event()
        # set up a Queue that can report back status to the main task
        self.status_queue = multiprocessing.Queue()

        for t in self._tasks:
            t.stop_event = self.stop_event
            t.status_queue = self.status_queue

        if len(tasks) > 1:
            for A, B in pairwise(tasks):
                self.link_tasks(A, B)

    def link_tasks(self, A, B):
        """Link two tasks in a pipeline using a queue."""
        q = multiprocessing.Queue()
        A.output_queue = q
        B.input_queue = q
        self.queues[A.name] = q
        if self.verbose:
            print(
                f"[Pipeline] setting up pipeline link: {A.name} -> {B.name}", flush=True
            )

    def start(self):
        """Start all tasks."""
        self.start_time = time.time()
        for t in self._tasks:
            t.start()

    def join(self):
        """Join all tasks, i.e. wait until they are all done."""
        for t in self._tasks:
            t.join()

    def close(self):
        """Release all resources, needed for pixie16.control."""
        for t in self._tasks:
            t.close()
        for q in self.queues.values():
            q.close()

    def stop(self):
        """Stop all workers in the pipeline."""
        self.stop_event.set()

    def is_alive(self):
        """Check if any task is still running."""
        for t in self._tasks:
            if t.is_alive():
                return True
        return False

    def execute(self, progress_bar_time: Union[float, int] = 0):
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
                # finish progress bar
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
        except KeyboardInterrupt:
            print("[yellow]INFO[/]] got keyboard interrupt... closing")
            self.stop()
