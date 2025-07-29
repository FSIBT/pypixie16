"""
binary_loader.py
Binary file loader that integrates with scope's existing Start/Stop buttons
"""

import time
import threading
import os
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
    mca_histogram_update = pyqtSignal(dict)  # For MCA mode: {channel: histogram}
    replay_finished = pyqtSignal()

    def __init__(self, events, parent_scope, binary_loader):
        super().__init__()
        self.events = events
        self.parent_scope = parent_scope
        self.binary_loader = binary_loader
        self.is_running = False
        self.is_paused = False

        self.mca_histograms = {}
        self.is_mca_mode = False
        self.last_mca_update = 0
        self.mca_update_interval = 2.0  # Update MCA display every 2 seconds

        # Initialize MCA histograms if in MCA mode
        if (
            hasattr(parent_scope, "current_mode")
            and parent_scope.current_mode == "mca_mode"
        ):
            self.is_mca_mode = True
            for ch in parent_scope.channel_numbers:
                self.mca_histograms[ch] = np.zeros(32768, dtype=np.int64)
            print("MCA mode detected - will accumulate histograms during replay")

    def run(self):
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

                if self.is_mca_mode:
                    self._process_event_for_mca(event)

                # Feed event to the appropriate scope processor
                try:
                    if self.parent_scope.current_mode == "list_mode":
                        self.parent_scope.process_list_mode_event(event)
                    elif self.parent_scope.current_mode == "traces_mode":
                        trace_data = getattr(event, "trace", np.random.random(100))
                        if hasattr(
                            self.parent_scope.spectrum_tab, "add_event_with_trace"
                        ):
                            self.parent_scope.spectrum_tab.add_event_with_trace(
                                event, trace_data
                            )
                        else:
                            self.parent_scope.process_traces_event(event)
                except Exception as e:
                    print(f"Error processing event {i}: {e}")

            current_index = batch_end

            # Emit progress update
            self.progress_update.emit(current_index, len(self.events))

            # Emit MCA histogram update
            if self.is_mca_mode:
                current_time = time.time()
                if (current_time - self.last_mca_update) >= self.mca_update_interval:
                    # Convert to int32
                    display_histograms = {}
                    for ch, hist in self.mca_histograms.items():
                        display_histograms[ch] = np.clip(
                            hist, 0, np.iinfo(np.int32).max
                        ).astype(np.int32)

                    self.mca_histogram_update.emit(display_histograms)
                    self.last_mca_update = current_time

            time.sleep(delay_between_batches)

        # Final MCA update
        if self.is_mca_mode and self.mca_histograms:
            display_histograms = {}
            for ch, hist in self.mca_histograms.items():
                display_histograms[ch] = np.clip(
                    hist, 0, np.iinfo(np.int32).max
                ).astype(np.int32)
            self.mca_histogram_update.emit(display_histograms)

        # Replay finished
        self.replay_finished.emit()
        self.is_running = False

    def _process_event_for_mca(self, event):
        try:
            channel = getattr(event, "channel", 0)
            energy = getattr(event, "energy", 0)

            if channel in self.mca_histograms:
                # Convert energy to bin number (assuming 16-bit energy range)
                bin_number = int((energy / 65536.0) * 32768)
                bin_number = max(0, min(bin_number, 32767))

                # Accumulate in histogram
                self.mca_histograms[channel][bin_number] += 1
        except Exception as e:
            print(f"Error processing MCA event: {e}")

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def stop(self):
        self.is_running = False
        self.wait()


class BinaryLoadingThread(QThread):
    """Separate thread for loading binary files without blocking UI"""

    progress = pyqtSignal(str)
    finished = pyqtSignal(list, str)  # events, filename
    failed = pyqtSignal(str)

    def __init__(self, filename):
        super().__init__()
        self.filename = filename

    def run(self):
        """Load binary file in background"""
        try:
            file_size = os.path.getsize(self.filename)
            size_mb = file_size / (1024 * 1024)
            self.progress.emit(f"Reading {size_mb:.1f} MB file...")

            if pixie16:
                self.progress.emit("Parsing events...")
                events = list(
                    pixie16.read.read_list_mode_data_as_events([self.filename])
                )
                events.sort(key=lambda x: x.timestamp)
                self.progress.emit(f"Loaded {len(events)} events")
                self.finished.emit(events, self.filename)
            else:
                self.progress.emit("pixie16 not available, generating dummy data...")
                events = self._generate_dummy_events()
                self.finished.emit(events, self.filename)

        except Exception as e:
            self.failed.emit(f"Loading failed: {str(e)}")

    def _generate_dummy_events(self):
        """Generate dummy events when pixie16 not available"""
        events = []
        base_timestamp = int(time.time() * 1e8)
        for i in range(5000):
            event = type(
                "Event",
                (),
                {
                    "channel": np.random.randint(0, 16),
                    "timestamp": base_timestamp
                    + i * 100000
                    + np.random.randint(-10000, 10000),
                    "energy": np.random.randint(100, 4000),
                    "trace": np.random.randint(0, 4096, np.random.randint(100, 1000))
                    if np.random.random() > 0.3
                    else [],
                },
            )()
            events.append(event)
        return events


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
        self.loading_thread = None
        self.is_binary_mode = False

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

        self.load_button = QPushButton("Load")
        self.load_button.clicked.connect(self.load_binary_file)
        file_row.addWidget(self.load_button)

        # Cancel button for loading
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_loading)
        self.cancel_button.setEnabled(False)
        file_row.addWidget(self.cancel_button)

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

        # Loading progress label
        self.loading_label = QLabel("")
        self.loading_label.setStyleSheet("font-size: 10px; color: blue;")
        self.loading_label.setVisible(False)
        file_layout.addWidget(self.loading_label)

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
        # Don't allow loading if already loading
        if self.loading_thread and self.loading_thread.isRunning():
            return

        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load Binary File",
            "",
            "Binary files (*.bin);;All files (*)",
        )

        if not filename:
            return

        # Check file size and warn for large files
        try:
            file_size = os.path.getsize(filename)
            size_mb = file_size / (1024 * 1024)

            if size_mb > 500:  # Warn for files > 500MB
                reply = QMessageBox.question(
                    self,
                    "Large File Warning",
                    f"File is {size_mb:.1f} MB. Loading may take a while.\n\nContinue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            # Start background loading
            self._start_background_loading(filename)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot access file: {e}")

    def _start_background_loading(self, filename):
        """Start loading in background thread"""
        print(f"Starting background loading: {filename}")

        # Update UI to loading state
        self.load_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.loading_label.setVisible(True)
        self.loading_label.setText("Loading...")
        self.status_label.setText("Loading binary file...")

        # Create and start loading thread
        self.loading_thread = BinaryLoadingThread(filename)
        self.loading_thread.progress.connect(self._on_loading_progress)
        self.loading_thread.finished.connect(self._on_loading_finished)
        self.loading_thread.failed.connect(self._on_loading_failed)
        self.loading_thread.start()

    def _on_loading_progress(self, message):
        """Handle loading progress"""
        self.loading_label.setText(message)
        self.status_label.setText(message)

    def _on_loading_finished(self, events, filename):
        """Handle successful loading"""
        print(f"Loading completed: {len(events)} events")

        # Store loaded data
        self.events = events
        self.current_file = Path(filename)
        self.total_events = len(events)
        self.is_binary_mode = True

        # Update UI
        self.load_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.loading_label.setVisible(False)
        self.clear_button.setEnabled(True)
        self.redo_button.setEnabled(True)

        self.file_label.setText(f"📁 {self.current_file.name}")
        self.file_label.setStyleSheet("font-size: 11px; color: blue;")
        self.status_label.setText(f"Loaded {self.total_events:,} events")

        # Emit signal
        self.file_loaded.emit(filename, self.total_events)
        print("Binary file ready for replay")

    def _on_loading_failed(self, error_message):
        """Handle loading failure"""
        print(f"Loading failed: {error_message}")

        # Reset UI
        self.load_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.loading_label.setVisible(False)
        self.status_label.setText("Load failed")

        QMessageBox.critical(self, "Loading Failed", error_message)

    def cancel_loading(self):
        """Cancel background loading"""
        if self.loading_thread and self.loading_thread.isRunning():
            print("Cancelling loading...")
            self.loading_thread.terminate()
            self.loading_thread.wait(1000)

            # Reset UI
            self.load_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.loading_label.setVisible(False)
            self.status_label.setText("Loading cancelled")

    def clear_binary_file(self):
        # Cancel loading if in progress
        if self.loading_thread and self.loading_thread.isRunning():
            self.cancel_loading()

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
        self.redo_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.status_label.setText("Ready")

        print("Binary file cleared - back to live/dummy mode")

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

            # Connect MCA-specific signal
            self.replay_thread.mca_histogram_update.connect(self._update_mca_display)

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

    def _update_mca_display(self, histograms):
        try:
            # Update display
            if hasattr(self.parent_scope, "spectrum_tab") and hasattr(
                self.parent_scope.spectrum_tab, "update_mca_histogram"
            ):
                for channel, histogram in histograms.items():
                    self.parent_scope.spectrum_tab.update_mca_histogram(
                        channel, histogram
                    )

            # Update internal MCA data storage
            if hasattr(self.parent_scope, "mca_data"):
                for channel, histogram in histograms.items():
                    if channel in self.parent_scope.mca_data:
                        self.parent_scope.mca_data[channel] = histogram
                        self.parent_scope.cumulative_mca_data[channel] = (
                            histogram.astype(np.int64)
                        )

            print(f"Updated MCA display: {len(histograms)} channels")

        except Exception as e:
            print(f"Error updating MCA display: {e}")

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
