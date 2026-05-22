"""
binary_loader.py
Binary file loader that integrates with scope's existing Start/Stop buttons
"""

import time
import os
import struct
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
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

from pixie16.read import read_list_mode_data_as_events


class BinaryReplayThread(QThread):
    progress_update = pyqtSignal(int, int)  # current, total
    mca_histogram_update = pyqtSignal(dict)  # For MCA mode: {channel: histogram}
    event_ready = pyqtSignal(object)  # single event, auto-queued to GUI thread
    replay_finished = pyqtSignal()

    def __init__(self, events, parent_scope, binary_loader):
        super().__init__()
        self.events = events
        self.parent_scope = parent_scope
        self.binary_loader = binary_loader
        self.is_running = False
        self.is_paused = False

        self.mca_histograms = {}
        self.last_mca_update = 0
        self.mca_update_interval = 2.0  # Update MCA display every 2 seconds

        # Pre-allocate MCA histograms for all channels so they're ready
        # if the user switches to MCA mode mid-replay
        if hasattr(parent_scope, "channel_numbers"):
            for ch in parent_scope.channel_numbers:
                self.mca_histograms[ch] = np.zeros(32768, dtype=np.int64)

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

                # Check current_mode dynamically so mode switches mid-replay
                # are respected
                current_mode = self.parent_scope.current_mode
                if current_mode == "mca_mode":
                    self._process_event_for_mca(event)
                elif current_mode == "list_mode":
                    self.event_ready.emit(event)

            current_index = batch_end

            # Emit progress update
            self.progress_update.emit(current_index, len(self.events))

            # Emit MCA histogram update periodically
            if self.parent_scope.current_mode == "mca_mode":
                current_time = time.time()
                if (current_time - self.last_mca_update) >= self.mca_update_interval:
                    display_histograms = {}
                    for ch, hist in self.mca_histograms.items():
                        display_histograms[ch] = np.clip(
                            hist, 0, np.iinfo(np.int32).max
                        ).astype(np.int32)

                    self.mca_histogram_update.emit(display_histograms)
                    self.last_mca_update = current_time

            time.sleep(delay_between_batches)

        # Final MCA update
        if self.parent_scope.current_mode == "mca_mode" and self.mca_histograms:
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

            if energy < 0 or channel not in self.mca_histograms:
                return

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
        if not self.wait(3000):  # 3 second timeout
            print("WARNING: Replay thread did not exit within 3s, terminating")
            self.terminate()
            self.wait(1000)


class BinaryLoadingThread(QThread):
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

            self.progress.emit("Parsing events...")
            events = list(
                read_list_mode_data_as_events([self.filename])
            )
            events.sort(key=lambda x: x.timestamp)
            self.progress.emit(f"Loaded {len(events)} events")
            self.finished.emit(events, self.filename)

        except Exception as e:
            self.failed.emit(f"Loading failed: {str(e)}")


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

        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_binary_file)
        self.clear_button.setEnabled(False)
        file_row.addWidget(self.clear_button)

        file_row.addStretch()
        file_layout.addLayout(file_row)

        # File info
        self.file_label = QLabel("No file loaded")
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

        try:
            # Validate file before loading
            error = self._validate_binary_file(filename)
            if error:
                QMessageBox.critical(self, "Invalid File", error)
                return

            file_size = os.path.getsize(filename)
            size_mb = file_size / (1024 * 1024)

            if size_mb > 500:
                reply = QMessageBox.question(
                    self,
                    "Large File Warning",
                    f"File is {size_mb:.1f} MB. Loading may take a while.\n\nContinue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            # Check for CFD and warn about timestamp accuracy
            self._check_cfd_warning()

            # Start background loading
            self._start_background_loading(filename)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot access file: {e}")

    @staticmethod
    def _validate_binary_file(filename):
        """Validate that a file looks like a Pixie-16 list mode binary.

        Returns an error string on failure, or None if the file is valid.
        """
        file_size = os.path.getsize(filename)
        if file_size == 0:
            return "File is empty."
        if file_size < 16:
            return f"File is too small ({file_size} bytes) to contain a Pixie-16 event header (minimum 16 bytes)."

        # Read the first event header (4 x 32-bit words) and sanity-check
        try:
            with open(filename, "rb") as f:
                raw = f.read(16)
        except OSError as e:
            return f"Cannot read file: {e}"

        w0, w1, w2, w3 = struct.unpack_from("<4I", raw, 0)

        event_length = (w0 >> 17) & 0x3FFF
        header_length = (w0 >> 12) & 0x1F
        channel = w0 & 0xF
        slot = (w0 >> 4) & 0xF
        energy = w3 & 0xFFFF

        # Header length must be 4, 6, 8, 10, 12, or 14 (standard Pixie-16 values)
        valid_header_lengths = {4, 6, 8, 10, 12, 14}
        if header_length not in valid_header_lengths:
            return (
                f"Invalid header length {header_length} in first event.\n"
                f"Expected one of {sorted(valid_header_lengths)}.\n\n"
                f"This file does not appear to be a Pixie-16 list mode binary."
            )

        # Event length must be >= header length
        if event_length < header_length:
            return (
                f"Corrupt first event: event length ({event_length}) "
                f"< header length ({header_length})."
            )

        # Event length should not exceed file size (in 32-bit words)
        if event_length * 4 > file_size:
            return (
                f"First event length ({event_length} words = {event_length * 4} bytes) "
                f"exceeds file size ({file_size} bytes). File may be truncated or corrupt."
            )

        # Channel must be 0-15
        if channel > 15:
            return f"Invalid channel number {channel} in first event (expected 0-15)."

        # Slot must be 2-14 (standard PXI slot range)
        if slot < 2 or slot > 14:
            return (
                f"Suspicious slot number {slot} in first event (expected 2-14).\n"
                f"This file may not be a valid Pixie-16 list mode binary."
            )

        return None  # Validation passed

    def _check_cfd_warning(self):
        try:
            if not self.parent_scope or not hasattr(self.parent_scope, 'spectrum_tab'):
                return
            spectrum_tab = self.parent_scope.spectrum_tab

            if (hasattr(spectrum_tab, 'trace_types') and
                    spectrum_tab.trace_types.get('cfd', False)):
                QMessageBox.warning(
                    self,
                    "CFD Timing Warning",
                    "CFD (Constant Fraction Discriminator) is currently enabled.\n\n"
                    "When loading binary files with CFD enabled, timestamps may be "
                    "inaccurate due to timing differences between the hardware CFD "
                    "and software simulation.\n\n"
                    "For accurate timing analysis of recorded data, consider "
                    "disabling CFD trace display or use live data acquisition instead.",
                )
        except Exception as e:
            print(f"Warning: Could not check CFD status: {e}")

    def _start_background_loading(self, filename):
        print(f"Starting background loading: {filename}")

        # Update UI to loading state
        self.load_button.setEnabled(False)
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
        self.loading_label.setText(message)
        self.status_label.setText(message)

    def _on_loading_finished(self, events, filename):
        # Store loaded data
        self.events = events
        self.current_file = Path(filename)
        self.total_events = len(events)
        self.is_binary_mode = True

        # Update UI
        self.load_button.setEnabled(True)
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
        self.loading_label.setVisible(False)
        self.status_label.setText("Load failed")

        QMessageBox.critical(self, "Loading Failed", error_message)

    def clear_binary_file(self):
        self.current_file = None
        self.events = []
        self.total_events = 0
        self.is_binary_mode = False

        # Stop any running replay
        if self.replay_thread and self.replay_thread.isRunning():
            self.stop_replay()

        # Update UI
        self.file_label.setText("No file loaded")
        self.file_label.setStyleSheet("font-size: 11px; color: gray;")
        self.clear_button.setEnabled(False)
        self.redo_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.status_label.setText("Ready")

        print("Binary file cleared")

    def start_replay(self):
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

            # Connect signals (event_ready auto-queues to GUI thread)
            self.replay_thread.progress_update.connect(self.update_progress)
            self.replay_thread.replay_finished.connect(self.on_replay_finished)
            self.replay_thread.event_ready.connect(
                self.parent_scope.process_list_mode_event
            )

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
            if hasattr(self.parent_scope, "mca_data") and hasattr(self.parent_scope, "cumulative_mca_data"):
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

        # If currently replaying, stop it first (stop() already joins the thread)
        if self.replay_thread and self.replay_thread.isRunning():
            self.stop_replay()

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
            return "Live data"

