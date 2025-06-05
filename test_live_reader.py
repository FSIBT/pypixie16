#!/usr/bin/env python3
"""
Test script for live data reading simulation.
This simulates live data by reading the binary file in chunks.
"""

import sys
from pathlib import Path
import time
import numpy as np

# Add pypixie16 to path
pypixie_dir = Path(__file__).parent.parent
sys.path.insert(0, str(pypixie_dir / "src"))

from pixie16.read.list_mode.list_mode_data_reader import (
    StreamReader,
    ListModeDataReader,
    Event,
    EmptyError,
)


class LiveDataSimulator:
    """Simulate live data by reading binary file in chunks."""

    def __init__(self, binary_file, chunk_size=1000):
        self.binary_file = Path(binary_file)
        self.chunk_size = chunk_size  # Number of 32-bit words per chunk
        self.file_data = None
        self.position = 0
        self.load_file()

    def load_file(self):
        """Load the entire binary file as uint32 array."""
        self.file_data = np.fromfile(self.binary_file, dtype=np.uint32)
        print(f"Loaded {len(self.file_data)} 32-bit words from {self.binary_file.name}")

    def get_next_chunk(self):
        """Get the next chunk of data, simulating live streaming."""
        if self.position >= len(self.file_data):
            return None

        end_pos = min(self.position + self.chunk_size, len(self.file_data))
        chunk = self.file_data[self.position : end_pos]
        self.position = end_pos

        return chunk

    def simulate_live_reading(self, duration_seconds=10):
        """Simulate live data reading for specified duration."""

        # Create stream reader
        stream_reader = StreamReader(initial_buffer_size=10000)
        data_reader = ListModeDataReader(stream_reader)

        events_processed = 0
        channels_seen = set()
        traces_count = 0

        print(f"Starting live simulation for {duration_seconds} seconds...")
        start_time = time.time()

        while time.time() - start_time < duration_seconds:
            # Get new chunk (simulating data from hardware)
            chunk = self.get_next_chunk()
            if chunk is None:
                print("Reached end of file")
                break

            # Add chunk to stream buffer
            stream_reader.put(chunk)

            # Process any complete events in the buffer
            events_this_iteration = 0
            try:
                while True:
                    event = data_reader.pop()
                    events_processed += 1
                    events_this_iteration += 1
                    channels_seen.add(event.channel)

                    if len(event.trace) > 0:
                        traces_count += 1

                    # Print info for first few events
                    if events_processed <= 5:
                        print(
                            f"Event {events_processed}: Ch{event.channel}, "
                            f"Energy={event.energy}, Trace_len={len(event.trace)}"
                        )

            except EmptyError:
                # No more complete events in buffer yet
                pass

            if events_this_iteration > 0:
                print(
                    f"Processed {events_this_iteration} events, "
                    f"buffer size: {len(stream_reader)}"
                )

            # Simulate real-time delay
            time.sleep(0.1)

        print(f"\n=== Live Simulation Results ===")
        print(f"Total events processed: {events_processed}")
        print(f"Channels seen: {sorted(channels_seen)}")
        print(f"Events with traces: {traces_count}")
        print(f"Buffer final size: {len(stream_reader)}")

        return events_processed, channels_seen, traces_count


if __name__ == "__main__":
    binary_file = (
        sys.argv[1] if len(sys.argv) > 1 else input("Enter binary file path: ")
    )

    simulator = LiveDataSimulator(binary_file)
    simulator.simulate_live_reading(duration_seconds=5)
