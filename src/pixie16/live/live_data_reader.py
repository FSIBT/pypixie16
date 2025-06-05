"""
Live data reader for real-time Pixie16 data processing.
Fixed version for permanent integration.
"""

import time
import threading
from collections import defaultdict, deque
from typing import Optional, Any
from collections.abc import Callable
import numpy as np

from ..read.list_mode.list_mode_data_reader import (
    StreamReader,
    ListModeDataReader,
    Event,
    EmptyError,
    LeftoverBytesError,
)


class LiveEventBuffer:
    """Thread-safe buffer for live events with channel-based organization."""

    def __init__(self, max_events_per_channel=10000):
        self.max_events = max_events_per_channel
        self.events_by_channel = defaultdict(lambda: deque(maxlen=self.max_events))
        self.lock = threading.Lock()
        self.total_events = 0

    def add_event(self, event: Event):
        """Add an event to the appropriate channel buffer."""
        with self.lock:
            self.events_by_channel[event.channel].append(event)
            self.total_events += 1

    def get_recent_events(self, channel: int, count: int = 100) -> list[Event]:
        """Get the most recent events for a specific channel."""
        with self.lock:
            channel_events = self.events_by_channel[channel]
            return list(channel_events)[-count:]

    def get_all_recent_events(self, count: int = 100) -> dict[int, list[Event]]:
        """Get recent events for all channels."""
        with self.lock:
            result = {}
            for channel, events in self.events_by_channel.items():
                result[channel] = list(events)[-count:]
            return result

    def get_statistics(self) -> dict[str, Any]:
        """Get buffer statistics."""
        with self.lock:
            stats = {
                "total_events": self.total_events,
                "channels": list(self.events_by_channel.keys()),
                "events_per_channel": {
                    ch: len(events) for ch, events in self.events_by_channel.items()
                },
            }
            return stats


class LiveDataReader:
    """Real-time data reader for Pixie16 list mode data."""

    def __init__(self, initial_buffer_size=1_000_000):
        # Core components
        self.stream_reader = StreamReader(initial_buffer_size)
        self.data_reader = ListModeDataReader(self.stream_reader)
        self.event_buffer = LiveEventBuffer()

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

        # Callbacks for real-time notifications
        self.event_callbacks = []

    def add_event_callback(self, callback: Callable[[Event], None]):
        """Add a callback that gets called for each new event."""
        self.event_callbacks.append(callback)

    def start_processing(self):
        """Start the live data processing thread."""
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
        """Stop the live data processing thread."""
        if not self.is_running:
            return

        self.is_running = False
        self.stop_event.set()

        if self.processing_thread:
            self.processing_thread.join(timeout=2.0)

        print("Live data processing stopped")

    def add_data(self, data: np.ndarray):
        """Add new binary data to the processing stream."""
        if data.dtype != np.uint32:
            data = data.view(np.uint32)

        self.stream_reader.put(data)
        self.stats["bytes_processed"] += len(data) * 4

    def _processing_loop(self):
        """Main processing loop that runs in a separate thread."""
        last_stats_update = time.time()
        events_since_last_update = 0

        while not self.stop_event.wait(0.001):
            try:
                while True:
                    try:
                        event = self.data_reader.pop()
                        self.event_buffer.add_event(event)
                        events_since_last_update += 1

                        # Call event callbacks
                        for callback in self.event_callbacks:
                            try:
                                callback(event)
                            except Exception as e:
                                print(f"Error in event callback: {e}")

                    except EmptyError:
                        break
                    except LeftoverBytesError:
                        break

                # Update statistics periodically
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

    def get_live_events(
        self, channel: int | None = None, count: int = 100
    ) -> dict[int, list[Event]]:
        """Get recent events for live visualization."""
        if channel is not None:
            return {channel: self.event_buffer.get_recent_events(channel, count)}
        else:
            return self.event_buffer.get_all_recent_events(count)

    def get_statistics(self) -> dict[str, Any]:
        """Get comprehensive statistics about the live processing."""
        stats = self.stats.copy()
        stats.update(self.event_buffer.get_statistics())

        if stats["start_time"]:
            stats["uptime"] = time.time() - stats["start_time"]

        stats["buffer_size"] = len(self.stream_reader)
        stats["is_running"] = self.is_running

        return stats


class LiveDataSourceInterface:
    """Interface for connecting to actual Pixie16 hardware or file simulation."""

    def __init__(self, live_reader: LiveDataReader):
        self.live_reader = live_reader
        self.is_active = False
        self.simulation_thread = None

    def start_acquisition(self):
        """Start data acquisition from hardware."""
        self.is_active = True
        self.live_reader.start_processing()

    def stop_acquisition(self):
        """Stop data acquisition."""
        self.is_active = False
        self.live_reader.stop_processing()

        if self.simulation_thread and self.simulation_thread.is_alive():
            self.simulation_thread.join(timeout=1.0)

    def simulate_from_file(
        self, binary_file: str, chunk_size: int = 1000, delay_ms: float = 10
    ):
        """Simulate live data by reading from a binary file."""

        def simulation_thread():
            try:
                file_data = np.fromfile(binary_file, dtype=np.uint32)
                position = 0

                print(f"Starting file simulation: {len(file_data)} words")

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
