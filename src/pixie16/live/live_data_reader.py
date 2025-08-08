"""
:ive data reader for real-time Pixie16 data processing.
"""

import time
import threading
from collections.abc import Callable
import numpy as np

from ..read.list_mode.list_mode_data_reader import (
    StreamReader,
    ListModeDataReader,
    Event,
    EmptyError,
    LeftoverBytesError,
)


class LiveDataReader:
    def __init__(self, initial_buffer_size=1_000_000):
        # Core components
        self.stream_reader = StreamReader(initial_buffer_size)
        self.data_reader = ListModeDataReader(self.stream_reader)

        # Threading and control
        self.processing_thread = None
        self.is_running = False
        self.stop_event = threading.Event()

        # Statistics and monitoring
        self.stats = {
            "events_processed": 0,
            "bytes_processed": 0,
            "processing_rate": 0.0,
            "start_time": None,
            "last_update": time.time(),
        }

        # Event callbacks (used by scope.py)
        self.event_callbacks = []

    def add_event_callback(self, callback: Callable[[Event], None]):
        self.event_callbacks.append(callback)

    def start_processing(self):
        if self.is_running:
            return

        self.is_running = True
        self.stop_event.clear()
        self.stats["start_time"] = time.time()

        self.processing_thread = threading.Thread(
            target=self._processing_loop, daemon=True
        )
        self.processing_thread.start()
        print("Live data processing started")

    def stop_processing(self):
        if not self.is_running:
            return

        self.is_running = False
        self.stop_event.set()

        if self.processing_thread:
            self.processing_thread.join(timeout=2.0)

        print("Live data processing stopped")

    def add_data(self, data: np.ndarray):
        if data.dtype != np.uint32:
            data = data.view(np.uint32)

        self.stream_reader.put(data)
        self.stats["bytes_processed"] += len(data) * 4

    def get_statistics(self) -> dict[str, any]:
        stats = self.stats.copy()

        if stats["start_time"]:
            stats["uptime"] = time.time() - stats["start_time"]

        stats["buffer_size"] = len(self.stream_reader)
        stats["is_running"] = self.is_running

        return stats

    def _processing_loop(self):
        last_stats_update = time.time()
        events_since_last_update = 0

        while not self.stop_event.wait(0.001):
            try:
                while True:
                    try:
                        event = self.data_reader.pop()
                        events_since_last_update += 1

                        for callback in self.event_callbacks:
                            try:
                                callback(event)
                            except Exception as e:
                                print(f"Error in event callback: {e}")

                    except EmptyError:
                        break
                    except LeftoverBytesError:
                        break

                current_time = time.time()
                if current_time - last_stats_update >= 1.0:
                    time_elapsed = current_time - last_stats_update
                    self.stats["processing_rate"] = (
                        events_since_last_update / time_elapsed
                    )
                    self.stats["events_processed"] += events_since_last_update
                    self.stats["last_update"] = current_time

                    events_since_last_update = 0
                    last_stats_update = current_time

            except Exception as e:
                print(f"Error in processing loop: {e}")
                break


class LiveDataSourceInterface:
    def __init__(self, live_reader: LiveDataReader):
        self.live_reader = live_reader
        self.is_active = False
        self.simulation_thread = None

    def start_acquisition(self):
        self.is_active = True
        self.live_reader.start_processing()

    def stop_acquisition(self):
        self.is_active = False
        self.live_reader.stop_processing()

        if self.simulation_thread and self.simulation_thread.is_alive():
            self.simulation_thread.join(timeout=1.0)

    def simulate_from_file(
        self, binary_file: str, chunk_size: int = 1000, delay_ms: float = 10
    ):
        def simulation_thread():
            try:
                file_data = np.fromfile(binary_file, dtype=np.uint32)
                position = 0

                while self.is_active and position < len(file_data):
                    end_pos = min(position + chunk_size, len(file_data))
                    chunk = file_data[position:end_pos]

                    self.live_reader.add_data(chunk)
                    position = end_pos

                    time.sleep(delay_ms / 1000.0)

                print("File simulation completed")
            except Exception as e:
                print(f"Simulation error: {e}")

        self.start_acquisition()
        self.simulation_thread = threading.Thread(target=simulation_thread, daemon=True)
        self.simulation_thread.start()
        return self.simulation_thread
