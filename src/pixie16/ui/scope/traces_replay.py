"""
Trace Replay System for PIXIE-16 Traces
Stores traces with metadata and provides navigation/replay functionality
"""

import numpy as np
import pickle
import time
from pathlib import Path
from collections import deque
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QSlider,
    QCheckBox,
    QFileDialog,
    QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal


class StoredTrace:
    def __init__(self, trace_data, channel, energy=0, timestamp=None, event=None):
        self.trace_data = np.array(trace_data)
        self.channel = channel
        self.energy = energy
        self.timestamp = timestamp or time.time()
        self.event = event  # Original event object if available

    def to_dict(self):
        return {
            "trace_data": self.trace_data.tolist(),
            "channel": self.channel,
            "energy": self.energy,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            trace_data=np.array(data["trace_data"]),
            channel=data["channel"],
            energy=data.get("energy", 0),
            timestamp=data.get("timestamp", time.time()),
        )


class TraceReplayBuffer:
    def __init__(self, max_size=1000):
        self.traces = deque(maxlen=max_size)
        self.current_index = -1
        self.max_size = max_size
        self.recording = True

    def add_trace(self, stored_trace):
        if self.recording:
            self.traces.append(stored_trace)
            self.current_index = len(self.traces) - 1

    def navigate_to(self, index):
        if 0 <= index < len(self.traces):
            self.current_index = index
            return self.traces[index]
        return None

    def navigate_previous(self):
        if len(self.traces) == 0:
            return None
        self.current_index = max(0, self.current_index - 1)
        return self.traces[self.current_index]

    def navigate_next(self):
        if len(self.traces) == 0:
            return None
        self.current_index = min(len(self.traces) - 1, self.current_index + 1)
        return self.traces[self.current_index]

    def get_current_trace(self):
        if 0 <= self.current_index < len(self.traces):
            return self.traces[self.current_index]
        return None

    def get_info(self):
        """Get (current_position, total_traces, max_size)"""
        return (
            self.current_index + 1 if self.current_index >= 0 else 0,
            len(self.traces),
            self.max_size,
        )

    def clear(self):
        self.traces.clear()
        self.current_index = -1

    def resize(self, new_size):
        if new_size != self.max_size:
            old_traces = list(self.traces)
            self.traces = deque(old_traces[-new_size:], maxlen=new_size)
            self.max_size = new_size

            if self.current_index >= len(self.traces):
                self.current_index = len(self.traces) - 1


class TraceReplayWidget(QWidget):
    # Signals
    trace_selected = pyqtSignal(object)  # StoredTrace
    recording_changed = pyqtSignal(bool)
    replay_mode_changed = pyqtSignal(bool)

    def __init__(self, initial_buffer_size=1000):
        super().__init__()
        self.buffer = TraceReplayBuffer(initial_buffer_size)
        self.replay_mode = False
        self.init_ui()
        self.update_display()

    def init_ui(self):
        layout = QVBoxLayout()

        # Main controls group
        controls_group = QGroupBox("Trace Replay")
        controls_group.setMaximumHeight(100)
        controls_layout = QVBoxLayout()

        # Top row - settings
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("Buffer:"))

        self.buffer_size_spin = QSpinBox()
        self.buffer_size_spin.setRange(10, 5000)
        self.buffer_size_spin.setValue(self.buffer.max_size)
        self.buffer_size_spin.valueChanged.connect(self.on_buffer_size_changed)
        top_layout.addWidget(self.buffer_size_spin)

        self.record_cb = QCheckBox("Rec")
        self.record_cb.setChecked(True)
        self.record_cb.setToolTip("Record traces to buffer")
        self.record_cb.toggled.connect(self.on_recording_changed)
        top_layout.addWidget(self.record_cb)

        self.replay_mode_cb = QCheckBox("Replay")
        self.replay_mode_cb.toggled.connect(self.on_replay_mode_changed)
        top_layout.addWidget(self.replay_mode_cb)

        top_layout.addStretch()
        controls_layout.addLayout(top_layout)

        # Bottom row - navigation
        nav_layout = QHBoxLayout()

        self.first_btn = QPushButton("⏮")
        self.first_btn.setMaximumWidth(30)
        self.first_btn.clicked.connect(self.navigate_first)
        self.first_btn.setEnabled(False)
        nav_layout.addWidget(self.first_btn)

        self.prev_btn = QPushButton("◀")
        self.prev_btn.setMaximumWidth(30)
        self.prev_btn.clicked.connect(self.navigate_previous)
        self.prev_btn.setEnabled(False)
        nav_layout.addWidget(self.prev_btn)

        self.next_btn = QPushButton("▶")
        self.next_btn.setMaximumWidth(30)
        self.next_btn.clicked.connect(self.navigate_next)
        self.next_btn.setEnabled(False)
        nav_layout.addWidget(self.next_btn)

        self.last_btn = QPushButton("⏭")
        self.last_btn.setMaximumWidth(30)
        self.last_btn.clicked.connect(self.navigate_last)
        self.last_btn.setEnabled(False)
        nav_layout.addWidget(self.last_btn)

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setMinimum(0)
        self.position_slider.setMaximum(0)
        self.position_slider.valueChanged.connect(self.on_slider_changed)
        self.position_slider.setEnabled(False)
        nav_layout.addWidget(self.position_slider)

        self.status_label = QLabel("0/0")
        nav_layout.addWidget(self.status_label)

        # Save/Load buttons
        self.save_btn = QPushButton("Save")
        self.save_btn.setMaximumWidth(50)
        self.save_btn.clicked.connect(self.save_traces)
        nav_layout.addWidget(self.save_btn)

        self.load_btn = QPushButton("Load")
        self.load_btn.setMaximumWidth(50)
        self.load_btn.clicked.connect(self.load_traces)
        nav_layout.addWidget(self.load_btn)

        controls_layout.addLayout(nav_layout)
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        self.setLayout(layout)

    def add_trace(self, trace_data, channel, energy=0, event=None):
        stored_trace = StoredTrace(
            trace_data=trace_data.copy()
            if isinstance(trace_data, np.ndarray)
            else np.array(trace_data),
            channel=channel,
            energy=energy,
            timestamp=time.time(),
            event=event,
        )
        self.buffer.add_trace(stored_trace)
        self.update_display()

    def navigate_first(self):
        if len(self.buffer.traces) > 0:
            trace = self.buffer.navigate_to(0)
            if trace:
                self.trace_selected.emit(trace)
                self.update_display()

    def navigate_last(self):
        if len(self.buffer.traces) > 0:
            trace = self.buffer.navigate_to(len(self.buffer.traces) - 1)
            if trace:
                self.trace_selected.emit(trace)
                self.update_display()

    def navigate_previous(self):
        trace = self.buffer.navigate_previous()
        if trace:
            self.trace_selected.emit(trace)
            self.update_display()

    def navigate_next(self):
        trace = self.buffer.navigate_next()
        if trace:
            self.trace_selected.emit(trace)
            self.update_display()

    def on_slider_changed(self, value):
        trace = self.buffer.navigate_to(value)
        if trace:
            self.trace_selected.emit(trace)
            self.update_display()

    def on_buffer_size_changed(self, new_size):
        self.buffer.resize(new_size)
        self.update_display()

    def on_recording_changed(self, enabled):
        self.buffer.recording = enabled
        self.recording_changed.emit(enabled)

    def on_replay_mode_changed(self, enabled):
        self.replay_mode = enabled
        self.replay_mode_changed.emit(enabled)
        self.update_display()

    def update_display(self):
        current_pos, total_traces, max_size = self.buffer.get_info()

        # Update status
        self.status_label.setText(f"{current_pos}/{total_traces}")

        # Update slider
        if total_traces > 0:
            self.position_slider.setMaximum(total_traces - 1)
            if self.buffer.current_index >= 0:
                self.position_slider.setValue(self.buffer.current_index)
        else:
            self.position_slider.setMaximum(0)
            self.position_slider.setValue(0)

        # Update navigation buttons
        nav_enabled = self.replay_mode and total_traces > 0
        self.first_btn.setEnabled(nav_enabled)
        self.prev_btn.setEnabled(nav_enabled)
        self.next_btn.setEnabled(nav_enabled)
        self.last_btn.setEnabled(nav_enabled)
        self.position_slider.setEnabled(nav_enabled)

    def save_traces(self):
        if len(self.buffer.traces) == 0:
            QMessageBox.warning(self, "No Data", "No traces to save")
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Traces",
            f"traces_{int(time.time())}.pkl",
            "Pickle Files (*.pkl);;All Files (*)",
        )

        if filename:
            try:
                # Convert traces to saveable format
                traces_data = [trace.to_dict() for trace in self.buffer.traces]

                save_data = {
                    "traces": traces_data,
                    "current_index": self.buffer.current_index,
                    "timestamp": time.time(),
                    "total_traces": len(self.buffer.traces),
                }

                with open(filename, "wb") as f:
                    pickle.dump(save_data, f)

                QMessageBox.information(
                    self,
                    "Save Complete",
                    f"Saved {len(self.buffer.traces)} traces to {Path(filename).name}",
                )

            except Exception as e:
                QMessageBox.critical(self, "Save Failed", f"Failed to save traces: {e}")

    def load_traces(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Load Traces", "", "Pickle Files (*.pkl);;All Files (*)"
        )

        if filename:
            try:
                with open(filename, "rb") as f:
                    save_data = pickle.load(f)

                # Clear current buffer
                self.buffer.clear()

                # Load traces
                for trace_data in save_data["traces"]:
                    stored_trace = StoredTrace.from_dict(trace_data)
                    self.buffer.traces.append(stored_trace)

                # Restore position
                if len(self.buffer.traces) > 0:
                    self.buffer.current_index = min(
                        save_data.get("current_index", 0), len(self.buffer.traces) - 1
                    )

                self.update_display()

                QMessageBox.information(
                    self,
                    "Load Complete",
                    f"Loaded {len(self.buffer.traces)} traces from {Path(filename).name}",
                )

                # Emit current trace if in replay mode
                if self.replay_mode:
                    current_trace = self.buffer.get_current_trace()
                    if current_trace:
                        self.trace_selected.emit(current_trace)

            except Exception as e:
                QMessageBox.critical(self, "Load Failed", f"Failed to load traces: {e}")

    def clear_traces(self):
        self.buffer.clear()
        self.update_display()

    def get_current_trace(self):
        return self.buffer.get_current_trace()

    def get_buffer_stats(self):
        return self.buffer.get_info()
