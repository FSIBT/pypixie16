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

    pipeline.start()

    pipeline.wait_with_progress(total=14.0)

    pipeline.join()

"""

import multiprocessing
import queue
import sys
import time
import traceback

from more_itertools import pairwise
import tqdm


class Task(multiprocessing.Process):
    """Custom Process that can be stopped and joined into a pipeline.

    Queues are used to get data or send data to the next Tasks. We
    provide functions that should be overwritten when customizing
    a Task:

    do_calc(value): gets called continously in a while loop without an input queue
    or gets called whenever a value arrives in the input queue.
    If the tasks is done, do_calc should set self.done to True.
    cleanup(): option to close any files, etc.
    """

    def __init__(self, event=None):
        super().__init__()
        self.stop_event = event or multiprocessing.Event()
        self.input_queue = None
        self.output_queue = None
        self.status_queue = None
        self.start_time = None
        self.stop_time = None
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

        """
        current_time = time.time()
        if self.status_queue and (current_time - self.last_update > 0.5):
            self.status_queue.put(value_dict)
            self.last_update = current_time

    def do_work(self, value):
        """Needs to be overwritten to do the work.

        value will be the current element in the queue.
        """
        pass

    def stop(self):
        self.stop_event.set()

    def join(self, *args, **kwargs):
        self.stop()
        super().join(*args, **kwargs)

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
                # do the work
                out = self.do_work(value)

                # send result to next stage if available
                if self.output_queue and out is not None:
                    self.output_queue.put(out)
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"[DEBUG] ----- exception in {self.name} ----")
            print(e)
            print(sys.exc_info())
            traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()
            self.stop_event.set()
        finally:
            self.cleanup()

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

    def __init__(self, tasks, verbose=False):
        self._tasks = tasks
        self.verbose = verbose
        self.status = {}
        self.i = 0
        self.start_time = 0
        self.runtime = 0
        self.queues = {}

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
        q = multiprocessing.Queue()
        A.output_queue = q
        B.input_queue = q
        self.queues[A.name] = q
        if self.verbose:
            print(
                f"[Pipeline] setting up pipeline link: {A.name} -> {B.name}", flush=True
            )

    def start(self):
        self.start_time = time.time()
        for t in self._tasks:
            t.start()

    def join(self):
        for t in self._tasks:
            t.join()

    def stop(self):
        self.stop_event.set()

    def is_alive(self):
        for t in self._tasks:
            if t.is_alive():
                return True
        return False

    def update_status(self):
        try:
            while True:
                value = self.status_queue.get(block=False)
                self.status.update(value)
        except queue.Empty:
            pass
        if "runtime" in self.status:
            self.runtime = self.status["runtime"]
        else:
            self.runtime = round(time.time() - self.start_time, 2)

    def wait_with_progress(self, total):
        try:
            with tqdm.tqdm(total=total) as pbar:
                while self.is_alive():
                    time.sleep(0.1)
                    self.update_status()
                    # no need to also show runtime in postfix
                    postfix = self.status.copy()
                    postfix.pop("runtime", None)
                    pbar.set_postfix(postfix)
                    if self.runtime < total:
                        pbar.n = self.runtime
                    else:
                        pbar.n = total
                    pbar.update(0)
        except KeyboardInterrupt:
            print("[INFO] got keyboard interrupt... closing")
            self.stop()
