"""
binary_loader.py
Binary file loader that integrates with scope's existing Start/Stop buttons
"""

import time
import threading
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

try:
    import pixie16
except ImportError:
    pixie16 = None


class BinaryReplayThread(QThread):
    progress_update = pyqtSignal(int, int)  # current, total
    replay_finished = pyqtSignal()

    def __init__(self, events, parent_scope, binary_loader):
        super().__init__()
        self.events = events
        self.parent_scope = parent_scope
        self.binary_loader = binary_loader  # Reference to get current rate
        self.is_running = False
        self.is_paused = False

    def run(self):
        """Main replay loop with dynamic rate adjustment"""
        self.is_running = True
        current_index = 0

        while self.is_running and current_index < len(self.events):
            if self.is_paused:
                time.sleep(0.1)
                continue

            # Get current rate dynamically
            current_rate = self.binary_loader.replay_rate_hz
            events_per_batch = max(1, current_rate // 10)  # 10 batches per second
            delay_between_batches = 0.1  # 100ms

            # Process a batch of events
            batch_end = min(current_index + events_per_batch, len(self.events))

            for i in range(current_index, batch_end):
                if not self.is_running:
                    break

                event = self.events[i]

                # Feed event to the appropriate scope processor
                try:
                    if self.parent_scope.current_mode == "list_mode":
                        self.parent_scope.process_list_mode_event(event)
                    elif self.parent_scope.current_mode == "traces_mode":
                        trace_data = getattr(event, "trace", np.random.random(100))

                        # Check if spectrum_tab has coincidence-aware method
                        if hasattr(
                            self.parent_scope.spectrum_tab, "add_event_with_trace"
                        ):
                            self.parent_scope.spectrum_tab.add_event_with_trace(
                                event, trace_data
                            )
                        else:
                            # Fallback to old method
                            self.parent_scope.process_traces_event(event)

                except Exception as e:
                    print(f"Error processing event {i}: {e}")

            current_index = batch_end

            # Emit progress update
            self.progress_update.emit(current_index, len(self.events))

            # Sleep between batches
            time.sleep(delay_between_batches)

        # Replay finished
        self.replay_finished.emit()
        self.is_running = False

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def stop(self):
        self.is_running = False
        self.wait()


class BinaryFileLoader(QWidget):
    # Signals for integration with scope
    file_loaded = pyqtSignal(str, int)  # filename, num_events
    replay_started = pyqtSignal()
    replay_stopped = pyqtSignal()

    def __init__(self, parent_scope=None):
        super().__init__()

        self.parent_scope = parent_scope

        # File and replay state
        self.current_file = None
        self.events = []
        self.total_events = 0
        self.replay_thread = None
        self.is_binary_mode = False  # Track if we're using binary data

        # Replay settings
        self.replay_rate_hz = 1000

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Binary file controls
        file_group = QGroupBox("Binary File Loader")
        file_layout = QVBoxLayout()

        # File loading row
        file_row = QHBoxLayout()

        self.load_button = QPushButton("Load Binary File")
        self.load_button.clicked.connect(self.load_binary_file)
        file_row.addWidget(self.load_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_binary_file)
        self.clear_button.setEnabled(False)
        file_row.addWidget(self.clear_button)

        file_row.addStretch()
        file_layout.addLayout(file_row)

        # File info
        self.file_label = QLabel("No file loaded - using live/dummy data")
        self.file_label.setStyleSheet("font-size: 11px; color: gray;")
        file_layout.addWidget(self.file_label)

        # Replay rate control with redo button
        rate_row = QHBoxLayout()
        rate_row.addWidget(QLabel("Replay Rate:"))
        self.rate_spin = QSpinBox()
        self.rate_spin.setRange(1, 100000)
        self.rate_spin.setValue(self.replay_rate_hz)
        self.rate_spin.valueChanged.connect(self.update_replay_rate)
        self.rate_spin.setMaximumWidth(80)
        self.rate_spin.setSuffix(" Hz")
        rate_row.addWidget(self.rate_spin)

        # Add redo button
        self.redo_button = QPushButton("Redo")
        self.redo_button.clicked.connect(self.redo_replay)
        self.redo_button.setEnabled(False)
        self.redo_button.setMaximumWidth(60)
        self.redo_button.setToolTip("Replay the same file again")
        rate_row.addWidget(self.redo_button)

        rate_row.addStretch()
        file_layout.addLayout(rate_row)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        file_layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-size: 10px;")
        file_layout.addWidget(self.status_label)

        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        self.setLayout(layout)

    def load_binary_file(self):  # Replay functionality
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load Binary File",
            "",
            "Binary files (*.bin);;All files (*)",
        )

        if not filename:
            return

        try:
            self.status_label.setText("Loading file...")

            # Load events using pixie16 library
            if pixie16:
                print(f"Loading binary file: {filename}")
                # fmt: off
                self.events = list(
                    pixie16.read.read_list_mode_data_as_events([filename])
                )
                # fmt: on
                self.events.sort(key=lambda x: x.timestamp)
                print(f"✓ Binary file loaded: {len(self.events)} events")
            else:
                print("Warning: pixie16 module not available, generating dummy data")
                self.events = self._generate_dummy_events()
                print(f"✓ Generated dummy events: {len(self.events)} events")

            self.current_file = Path(filename)
            self.total_events = len(self.events)
            self.is_binary_mode = True

            # Update UI
            self.file_label.setText(f"📁 {self.current_file.name}")
            self.file_label.setStyleSheet("font-size: 11px; color: blue;")
            self.clear_button.setEnabled(True)
            self.redo_button.setEnabled(True)  # Enable redo button
            self.status_label.setText(f"Loaded {self.total_events:,} events")

            # Emit signal
            self.file_loaded.emit(filename, self.total_events)

            print(f"Binary file ready: {filename}")
            print("Use scope's Start button to begin replay")

        except Exception as e:
            error_msg = f"Error loading file: {e}"
            print(error_msg)
            QMessageBox.critical(self, "Load Error", error_msg)
            self.status_label.setText("Load failed")

    def clear_binary_file(self):
        """Clear loaded binary file and return to live/dummy mode"""
        self.current_file = None
        self.events = []
        self.total_events = 0
        self.is_binary_mode = False

        # Stop any running replay
        if self.replay_thread and self.replay_thread.isRunning():
            self.stop_replay()

        # Update UI
        self.file_label.setText("No file loaded - using live/dummy data")
        self.file_label.setStyleSheet("font-size: 11px; color: gray;")
        self.clear_button.setEnabled(False)
        self.redo_button.setEnabled(False)  # Disable redo button
        self.progress_bar.setVisible(False)
        self.status_label.setText("Ready")

        print("Binary file cleared - back to live/dummy mode")

    def _generate_dummy_events(self):
        events = []
        base_timestamp = int(time.time() * 1e8)

        for i in range(5000):
            # fmt: off
            event = type("Event", (), {
                "channel": np.random.randint(0, 16),
                "timestamp": (
                    base_timestamp + i * 100000 + np.random.randint(-10000, 10000)
                ),
                "energy": np.random.randint(100, 4000),
                "trace": (
                    np.random.randint(0, 4096, np.random.randint(100, 1000))
                    if np.random.random() > 0.3
                    else []
                ),
            })()
            # fmt: on
            events.append(event)

        return events

    def start_replay(self):
        """Start replaying binary file (called by scope's Start button)"""
        if not self.is_binary_mode or not self.events:
            return False  # Not in binary mode

        if self.replay_thread and self.replay_thread.isRunning():
            return False  # Already running

        try:
            print(
                f"Starting binary replay: {self.total_events} events at {self.replay_rate_hz} Hz"
            )

            # Create and start replay thread
            # fmt: off
            self.replay_thread = BinaryReplayThread(
                self.events, self.parent_scope, self
            )
            # fmt: on

            # Connect signals
            self.replay_thread.progress_update.connect(self.update_progress)
            self.replay_thread.replay_finished.connect(self.on_replay_finished)

            # Start thread
            self.replay_thread.start()

            # Update UI
            self.progress_bar.setVisible(True)
            self.progress_bar.setMaximum(self.total_events)
            self.progress_bar.setValue(0)
            self.status_label.setText(f"Replaying at {self.replay_rate_hz} Hz")

            self.replay_started.emit()
            return True

        except Exception as e:
            print(f"Error starting binary replay: {e}")
            return False

    def stop_replay(self):
        if self.replay_thread and self.replay_thread.isRunning():
            print("Stopping binary replay...")
            self.replay_thread.stop()

            # Update UI
            self.progress_bar.setVisible(False)
            self.status_label.setText("Replay stopped")

            self.replay_stopped.emit()
            return True
        return False

    def update_progress(self, current, total):
        self.progress_bar.setValue(current)

        # Update status
        percent = (current / total) * 100 if total > 0 else 0
        self.status_label.setText(f"Replaying: {current:,}/{total:,} ({percent:.1f}%)")

    def on_replay_finished(self):
        print("Binary replay completed")
        self.progress_bar.setVisible(False)
        self.status_label.setText("Replay completed")

        # Could auto-restart or stop here
        # For now, just stop
        self.replay_stopped.emit()

    def update_replay_rate(self):
        old_rate = self.replay_rate_hz
        self.replay_rate_hz = self.rate_spin.value()

        print(f"Replay rate changed: {old_rate} → {self.replay_rate_hz} Hz")

        # Update status if currently replaying
        if self.replay_thread and self.replay_thread.isRunning():
            self.status_label.setText(f"Replaying at {self.replay_rate_hz} Hz")

    def redo_replay(self):
        if not self.is_binary_mode or not self.events:
            return

        print(f"Redoing replay of {self.current_file.name}")

        # If currently replaying, stop it first
        if self.replay_thread and self.replay_thread.isRunning():
            self.stop_replay()
            # Wait a bit for thread to stop
            time.sleep(0.1)

        # Clear any existing data in the scope
        if hasattr(self.parent_scope, "clear_data"):
            self.parent_scope.clear_data()

        # Start replay again
        if hasattr(self.parent_scope, "start_acquisition"):
            self.parent_scope.start_acquisition()
        else:
            self.start_replay()

    def is_using_binary_data(self):
        return self.is_binary_mode and len(self.events) > 0

    def get_data_source_info(self):
        if self.is_binary_mode:
            return f"Binary: {self.current_file.name} ({self.total_events:,} events)"
        else:
            return "Live/Dummy data"

    def set_parent_scope(self, scope):
        self.parent_scope = scope
