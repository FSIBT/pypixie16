import time

from .. import task


DEFAULT_SORT_SIZE: int = 10_000
DEFAULT_SORT_NUMBER_TO_SORT: int = 8_000
DEFAULT_SORT_START_TIME: int = 0
DEFAULT_SORT_ALL_START_TIME: list[int] = None


class SortEvents(task.Task):
    """Task to sort events by timestamp.

    This task, takes as input list of events that have already been
    converted from the binary format to namedtuples. It then populates
    an additionl column `chunk time` in the namedtuple which will
    roughly be the unix time stamp of the event. For a run that wasn't
    paused, the `chunk timestamp` will just be the normal time stamp
    plus the unix timestamp from the beginning of the run.

    The task will add incoming events to an internal list and once a
    certain number, M, of events has been reached, it will sort the
    events and send the first N off. Normally N<M, so that some events
    are held back since they might need to be sorted together with new
    events that will come in next.

    In case the event input stream comes from a run that has been
    paused and restarted, the timestamps in the event stream might
    have reset to start counting again at zero. However, we want the
    chunk time to be roughly the real time, so we have to add special
    code to handle this.

    For this to work, we detect whenever the timestamps go back to
    zero (our proxy for this is to test if the current event's timestamp
    is more than 20s before the last event, which should only happen
    if the counter did reset).

    We supply several options through the init variable
    `all_start_times` to handle the chunk time:

    1. `all_start_times` is None
       In this case, we just use the system time.time() for this event
       and calculate the following events `chunk time` by adding the
       delta t calculated from the pixie timestamp.
       This mode should be used during data acquisition.
       If one starts/stops the data acquisition, one should also write
       down all the start time, so that one can rerun the binary convertion
       later by using the next mode.
    2. `all_start_times` is a list of unix time stamps
       In this case, we use a value from the list whenever we notice a
       reset in the timestamps and otherwise handle delta t's as above.
       This mode can be used when binary data as to be converted again and
       the original time stamps should be recreated.
    3. `all_start_times` is a float > 0
       This mode can be used to estimate times when binary data needs to be
       converted again, but start times for b) are not available.
       In this case, we just ignore the negative dt at the point of
       the reset and keep adding positive dt to the `chunk time` and also
       add the value of `all_start_times` at the time of the reset. The value
       should be an estimate of how long it took between stopping and re-starting
       the data acquisition.

    """

    def do_init(self):
        """
        Initializes the task.

        Notes:
            This methods extends ``Task.do_work``.
        """

        self.data = []

        self.count = 0
        self.first_event_timestamp = None
        self.last_event_timestamp = 0
        self.report_times = [0]  # Initialize with start_time
        self.report_time_queue = None
        self.number_of_resets = 0

        self.config = {
            "sort_size": DEFAULT_SORT_SIZE,
            "sort_number_to_sort": DEFAULT_SORT_NUMBER_TO_SORT,
            "sort_start_time": DEFAULT_SORT_START_TIME,
            "sort_all_start_time": DEFAULT_SORT_ALL_START_TIME,
        }

    def do_configure(self, config_dict: dict):
        """
        Configures the task.

        Notes:
            This methods extends ``Task.do_work``.
        """

        self.N_to_sort = config_dict.get(
            "sort_number_to_sort", self.config["sort_number_to_sort"]
        )
        self.sort_size = config_dict.get("sort_size", self.config["sort_size"])
        self.start_time = config_dict.get(
            "sort_start_time", self.config["sort_start_time"]
        )
        self.all_start_times = config_dict.get(
            "sort_all_start_time", self.config["sort_all_start_time"]
        )

        if "sort_start_time" in config_dict:
            self.report_times = [self.start_time]

    def do_work(self, events_lst):
        """
        Works for the task.

        This method does sorting, time reset recognition, and handling.

        Whenever we reach `self.sort_size` events, sort them by time and
        pass the first `self.N_to_sort` events to the next `Task`. We keep
        the a few events behind, since they might need to be sorted with
        the next incoming batch.

        Notes:
            This methods extends ``Task.do_work``.
        """

        new_events_lst = []
        if self.first_event_timestamp is None and events_lst:
            self.first_event_timestamp = events_lst[0].timestamp * 1e-9
        for event in events_lst:
            ts = event.timestamp * 1e-9  # in s
            if ts + 20 < self.last_event_timestamp:
                # detected a reset of the FPGA counter on the pixie16
                self.number_of_resets += 1
                if self.all_start_times is None:
                    self.start_time = time.time()
                elif isinstance(self.all_start_times, list | tuple):
                    if self.number_of_resets >= len(self.all_start_times):
                        print(
                            "[red]ERROR[/] SortEventTask: detected more list mode starts than given timestamps. Estimating time offset"
                        )
                        self.start_time += (
                            self.last_event_timestamp - self.first_event_timestamp
                        ) + 35  # estimate of time of break
                    else:
                        self.start_time = self.all_start_times[self.number_of_resets]
                elif isinstance(self.all_start_times, int | float):
                    self.start_time += (
                        self.last_event_timestamp - self.first_event_timestamp
                    ) + self.all_start_times
                    self.report_times.append(self.start_time)
                else:
                    print(
                        "[red]ERROR[/] unknown type for all_start_times in SortEvents... cannot continue!!! "
                    )
                self.first_event_timestamp = ts
            event.chunk_timestamp = self.start_time + ts - self.first_event_timestamp
            new_events_lst.append(event)
            self.last_event_timestamp = ts

        # Sort events according to UNIX timestamp
        out = []
        self.data.extend(new_events_lst)
        while len(self.data) > self.sort_size:
            self.data.sort(key=lambda x: x.chunk_timestamp)
            out = self.data[: self.N_to_sort]
            self.data = self.data[self.N_to_sort :]
            if not self.is_final:
                self.send(out)
                self.count += 1

    def do_quit(self):
        """
        Quits the task.

        Notes:
            This methods extends ``Task.do_quit``.
        """

        self.data.sort(key=lambda x: x.chunk_timestamp)
        if not self.is_final:
            self.send(self.data)
        if self.report_time_queue:
            self.report_time_queue.put(self.report_times)
        self.data = []
