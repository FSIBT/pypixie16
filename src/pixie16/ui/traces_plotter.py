"""
Traces Plotter for PIXIE-16 with Real-Time Axis
Displays real-time ADC traces from PIXIE-16 channels
FEATURES:
- Multi-channel trace overlay
- Configurable trace history depth
- Amplitude-based trace selection
- Real-time axis in nanoseconds (based on PIXIE-16 timing)
- Color-coded channels
- Trace statistics and analysis
"""

import numpy as np
from collections import deque, defaultdict
import time

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QPushButton,
    QComboBox,
    QSlider,
)
from PyQt6.QtCore import QTimer, Qt
import pyqtgraph as pg


class TracesPlotter(QWidget):
    def __init__(self, channels=None, title="PIXIE-16 Traces"):
        super().__init__()

        self.channels = channels or list(range(16))  # Channel numbers
        self.display_channels = self.channels.copy()

        # Data storage - keyed by channel number
        self.trace_data = {
            ch: deque(maxlen=100) for ch in self.channels
        }  # Store last 100 traces per channel
        self.last_traces = {
            ch: None for ch in self.channels
        }  # Current displayed trace per channel

        # Display settings
        self.max_traces_display = 10  # Number of traces to show simultaneously
        self.trace_length_ns = 1000  # Default trace length in nanoseconds
        self.time_per_sample = 2.0  # ns per sample (default for PIXIE-16)
        self.amplitude_threshold = 0.1  # Minimum amplitude to display trace
        self.auto_scale = True
        self.show_statistics = True

        # REAL-TIME AXIS SETTINGS
        self.use_realtime_axis = True  # ON by default as per your request
        self.trace_delay_ns = {}  # Per-channel TRACE_DELAY from default.json
        self.sampling_period_ns = 2.0  # Will be loaded from config
        self.alpha_channel = 9  # Alpha detector channel

        # Channel colors
        self.colors = [
            "#1f77b4",
            "#ff7f0e",
            "#2ca02c",
            "#d62728",
            "#9467bd",
            "#8c564b",
            "#e377c2",
            "#7f7f7f",
            "#bcbd22",
            "#17becf",
            "#aec7e8",
            "#ffbb78",
            "#98df8a",
            "#ff9896",
            "#c5b0d5",
            "#c49c94",
        ]

        self.setWindowTitle(title)
        self.init_ui()

        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_plots)

    def init_ui(self):
        layout = QVBoxLayout()

        # Controls
        controls = self.create_controls()
        layout.addWidget(controls)

        # Plot area
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel("left", "Amplitude (V)")

        # Set initial axis label based on real-time axis setting
        if self.use_realtime_axis:
            self.plot_widget.setLabel("bottom", "Time (ns) - Real-Time Axis")
            self.plot_widget.setTitle("PIXIE-16 Traces - Real-Time Axis")
        else:
            self.plot_widget.setLabel("bottom", "Sample Index")
            self.plot_widget.setTitle("PIXIE-16 Traces - Sample Index")

        self.plot_widget.showGrid(True, True, alpha=0.3)
        self.plot_widget.addLegend()
        self.plot_widget.setBackground("w")

        layout.addWidget(self.plot_widget)

        # Statistics display
        self.stats_label = QLabel("Statistics: Waiting for traces...")
        layout.addWidget(self.stats_label)

        self.setLayout(layout)

        # Initialize plot curves
        self.curves = {}
        for i, channel in enumerate(self.channels):
            color = self.colors[i % len(self.colors)]
            self.curves[channel] = self.plot_widget.plot(
                pen=pg.mkPen(color=color, width=1.5), name=f"Ch {channel}"
            )

    def create_controls(self):
        group = QGroupBox("Trace Controls")
        group.setMaximumHeight(120)
        layout = QVBoxLayout()
        layout.setSpacing(3)

        # First row - Original controls
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(5)

        row1_layout.addWidget(QLabel("Max:"))
        self.max_traces_spin = QSpinBox()
        self.max_traces_spin.setRange(1, 50)
        self.max_traces_spin.setValue(self.max_traces_display)
        self.max_traces_spin.valueChanged.connect(self.update_max_traces)
        self.max_traces_spin.setMaximumWidth(60)
        row1_layout.addWidget(self.max_traces_spin)

        row1_layout.addWidget(QLabel("Thr:"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 2.0)
        self.threshold_spin.setValue(self.amplitude_threshold)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.valueChanged.connect(self.update_threshold)
        self.threshold_spin.setMaximumWidth(80)
        row1_layout.addWidget(self.threshold_spin)

        row1_layout.addWidget(QLabel("ns/smp:"))
        self.time_per_sample_spin = QDoubleSpinBox()
        self.time_per_sample_spin.setRange(0.1, 10.0)
        self.time_per_sample_spin.setValue(self.time_per_sample)
        self.time_per_sample_spin.setSingleStep(0.1)
        self.time_per_sample_spin.valueChanged.connect(self.update_time_scale)
        self.time_per_sample_spin.setMaximumWidth(80)
        row1_layout.addWidget(self.time_per_sample_spin)

        # Checkboxes
        self.auto_scale_cb = QCheckBox("Auto")
        self.auto_scale_cb.setChecked(True)
        self.auto_scale_cb.toggled.connect(self.toggle_auto_scale)
        row1_layout.addWidget(self.auto_scale_cb)

        self.show_stats_cb = QCheckBox("Stats")
        self.show_stats_cb.setChecked(True)
        self.show_stats_cb.toggled.connect(self.toggle_statistics)
        row1_layout.addWidget(self.show_stats_cb)

        # Clear button
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_data)
        self.clear_btn.setMaximumWidth(60)
        row1_layout.addWidget(self.clear_btn)

        row1_layout.addStretch()

        # 2nd row - Real-time axis controls
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(5)

        # Show timing info
        row2_layout.addWidget(QLabel("Timing:"))
        self.timing_info_label = QLabel(f"{self.sampling_period_ns:.1f}ns/smp")
        self.timing_info_label.setStyleSheet("font-size: 10px; color: gray;")
        row2_layout.addWidget(self.timing_info_label)

        row2_layout.addStretch()

        # Add both rows to layout
        layout.addLayout(row1_layout)
        layout.addLayout(row2_layout)

        group.setLayout(layout)
        return group

    def update_alpha_channel(self, channel):
        """Update alpha channel for timing reference"""
        self.alpha_channel = channel
        print(f" Alpha channel set to: {channel}")

    def calculate_real_time_axis(self, trace_length, channel):
        """
        Calculate real-time axis for a trace based on PIXIE-16 timing
        From your notes: time_ns = (sample * sampling_period) - trace_delay
        """
        if not self.use_realtime_axis:
            # Standard sample index
            return np.arange(trace_length)

        # Get channel-specific trace delay
        trace_delay = self.trace_delay_ns.get(channel, 200)  # Fallback to 200ns

        # Each sample represents sampling_period_ns of time
        sample_times = np.arange(trace_length) * self.sampling_period_ns

        # Subtract trace delay (time before trigger)
        # This gives time relative to trigger (negative = before trigger)
        real_times = sample_times - trace_delay

        print(f" Ch{channel} Real-Time Axis:")
        print(f"   Trace length: {trace_length} samples")
        print(f"   Sampling period: {self.sampling_period_ns} ns/sample")
        print(f"   Trace delay: {trace_delay} ns")
        print(f"   Time range: {real_times[0]:.1f} to {real_times[-1]:.1f} ns")
        print(
            f"   Trigger at sample {trace_delay / self.sampling_period_ns:.0f} (time=0)"
        )

        return real_times

    def add_trace(self, channel, trace_data):
        """Add a new trace for the specified channel (unchanged from working version)"""
        try:
            if channel not in self.channels:
                return

            # Convert to numpy array if needed
            if not isinstance(trace_data, np.ndarray):
                trace_data = np.array(trace_data)

            # Validate trace data
            if len(trace_data) == 0:
                return

            # Check if trace meets amplitude threshold
            if len(trace_data) > 10:  # Need enough samples to measure amplitude
                amplitude = np.max(trace_data) - np.min(trace_data)
                if amplitude >= self.amplitude_threshold:
                    self.trace_data[channel].append(trace_data)
                    print(
                        f"Added trace to channel {channel}: length={len(trace_data)}, amplitude={amplitude:.3f}"
                    )
            else:
                # For short traces, add anyway
                self.trace_data[channel].append(trace_data)

        except Exception as e:
            print(f"Error adding trace to channel {channel}: {e}")

    def update_max_traces(self):
        """Update maximum number of traces to display"""
        self.max_traces_display = self.max_traces_spin.value()

    def update_threshold(self):
        """Update amplitude threshold"""
        self.amplitude_threshold = self.threshold_spin.value()

    def update_time_scale(self):
        """Update time scale (ns per sample)"""
        self.time_per_sample = self.time_per_sample_spin.value()
        # Note: For real-time axis, sampling_period_ns comes from config, not this control

    def toggle_auto_scale(self, enabled):
        """Toggle auto scaling"""
        self.auto_scale = enabled

    def toggle_statistics(self, enabled):
        """Toggle statistics display"""
        self.show_statistics = enabled

    def start_live_updates(self):
        """Start live updating"""
        if not self.update_timer.isActive():
            self.update_timer.start(100)  # Update every 100ms
            print("Traces Plotter: Started live updates")

    def stop_live_updates(self):
        """Stop live updating"""
        if self.update_timer.isActive():
            self.update_timer.stop()
            print("Traces Plotter: Stopped live updates")

    def clear_data(self):
        """Clear all trace data"""
        for channel in self.channels:
            self.trace_data[channel].clear()
            self.last_traces[channel] = None
        self.update_plots()

    def update_plots(self):
        """Updated to use real-time axis when enabled"""
        try:
            total_traces = 0
            channel_stats = {}

            # Process ALL channels but only display selected ones
            for channel in self.channels:
                has_data = (
                    channel in self.trace_data and len(self.trace_data[channel]) > 0
                )

                if has_data:
                    traces = list(self.trace_data[channel])
                    total_traces += len(traces)

                    # Calculate statistics for ALL channels (even hidden ones)
                    if traces:
                        recent_trace = traces[-1]
                        amplitude = np.max(recent_trace) - np.min(recent_trace)
                        baseline = (
                            np.mean(recent_trace[:10]) if len(recent_trace) > 10 else 0
                        )

                        channel_stats[channel] = {
                            "count": len(traces),
                            "amplitude": amplitude,
                            "baseline": baseline,
                            "max_value": np.max(recent_trace),
                            "min_value": np.min(recent_trace),
                        }

                # Only display data for selected channels
                if channel not in self.display_channels:
                    # Channel not selected for display - hide it
                    self.curves[channel].setData([], [])
                    continue

                # Channel is selected for display
                if not has_data:
                    # No data for this channel
                    self.curves[channel].setData([], [])
                    continue

                # Display the channel data
                traces = list(self.trace_data[channel])
                display_traces = traces[-self.max_traces_display :]

                if display_traces:
                    # Create overlay of multiple traces
                    trace_length = len(display_traces[0])
                    time_axis = self.calculate_real_time_axis(trace_length, channel)

                    # Plot all traces with some transparency
                    combined_y = []
                    combined_x = []

                    for i, trace in enumerate(display_traces):
                        if len(trace) == trace_length:  # Ensure consistent length
                            # Offset traces slightly for visibility
                            offset = i * 0.01  # Small vertical offset
                            y_data = trace + offset

                            combined_x.extend(time_axis)
                            combined_x.append(np.nan)  # Separator for multiple traces
                            combined_y.extend(y_data)
                            combined_y.append(np.nan)

                    if combined_x and combined_y:
                        self.curves[channel].setData(combined_x, combined_y)
                        self.last_traces[channel] = display_traces[
                            -1
                        ]  # Keep most recent

            # Update statistics display - show stats for displayed channels
            if self.show_statistics:
                if self.display_channels:
                    axis_mode = "Real-Time" if self.use_realtime_axis else "Sample"
                    stats_text = f"Total Traces: {total_traces} ({axis_mode}) | "
                    for ch in self.display_channels:
                        if ch in channel_stats:
                            stats = channel_stats[ch]
                            delay_info = (
                                f"({self.trace_delay_ns.get(ch, 0):.0f}ns)"
                                if self.use_realtime_axis
                                else ""
                            )
                            stats_text += f"Ch{ch}{delay_info}: {stats['count']} traces, Amp: {stats['amplitude']:.3f}V | "
                    self.stats_label.setText(stats_text.rstrip(" | "))
                else:
                    self.stats_label.setText("No channels selected for display")
            else:
                self.stats_label.setText("Statistics hidden")

            # Auto scale if enabled
            if self.auto_scale and total_traces > 0:
                self.plot_widget.autoRange()

        except Exception as e:
            print(f"Error updating traces plots: {e}")
            import traceback

            traceback.print_exc()

    def set_timing_settings(self, settings):
        """Receive timing settings from scope"""
        self.trace_delay_ns = settings.get("trace_delay_ns", {})
        self.sampling_period_ns = settings.get("sampling_period_ns", 2.0)
        self.alpha_channel = settings.get("alpha_channel", 9)

        # Update timing info label
        if hasattr(self, "timing_info_label"):
            self.timing_info_label.setText(f"{self.sampling_period_ns:.1f}ns/smp")

    # All other methods remain unchanged from the working version
    def set_channels(self, channels):
        """Update the list of channels to display"""
        # Remove old curves
        for channel in self.channels:
            if channel in self.curves:
                self.plot_widget.removeItem(self.curves[channel])

        # Update channels
        self.channels = channels

        # Preserve existing data, create empty deques for new channels
        new_trace_data = {}
        for ch in self.channels:
            new_trace_data[ch] = self.trace_data.get(ch, deque(maxlen=100))
        self.trace_data = new_trace_data

        # Create new curves
        self.curves = {}
        for i, channel in enumerate(self.channels):
            color = self.colors[i % len(self.colors)]
            self.curves[channel] = self.plot_widget.plot(
                pen=pg.mkPen(color=color, width=1.5), name=f"Ch {channel}"
            )

    def set_display_channels(self, channels):
        print(f"Traces Plotter: set_display_channels called with {channels}")
        self.display_channels = channels if channels else []

        # Immediately hide non-selected channels
        for channel in self.channels:
            if channel not in self.display_channels:
                self.curves[channel].setData([], [])
                print(f"Traces: Hiding channel {channel}")
            else:
                print(f"Traces: Will show channel {channel}")

        # Force immediate update
        self.update_plots()

    def get_trace_data(self):
        """Get current trace data for saving"""
        return {ch: list(traces) for ch, traces in self.trace_data.items()}

    def export_data(self, filename):
        """Export trace data to file (includes real-time axis info)"""
        try:
            trace_data = self.get_trace_data()

            # Add metadata including real-time axis info
            metadata = {
                "channels": self.channels,
                "max_traces_display": self.max_traces_display,
                "time_per_sample_ns": self.time_per_sample,
                "amplitude_threshold": self.amplitude_threshold,
                "total_traces": sum(len(traces) for traces in trace_data.values()),
                "timestamp": time.time(),
                # Real-time axis metadata
                "use_realtime_axis": self.use_realtime_axis,
                "sampling_period_ns": self.sampling_period_ns,
                "trace_delay_ns": self.trace_delay_ns,
                "alpha_channel": self.alpha_channel,
            }

            if filename.endswith(".npz"):
                # Save as NumPy compressed format
                save_dict = {}
                save_dict["metadata"] = metadata

                for ch, traces in trace_data.items():
                    if traces:
                        # Convert list of traces to 2D array
                        max_length = max(len(trace) for trace in traces)
                        trace_array = np.full((len(traces), max_length), np.nan)

                        for i, trace in enumerate(traces):
                            trace_array[i, : len(trace)] = trace

                        save_dict[f"ch_{ch}_traces"] = trace_array

                np.savez_compressed(filename, **save_dict)

            else:
                # Save as JSON (less efficient but more readable)
                import json

                # Convert numpy arrays to lists for JSON serialization
                json_data = {"metadata": metadata}
                for ch, traces in trace_data.items():
                    json_data[f"ch_{ch}"] = [
                        trace.tolist() if isinstance(trace, np.ndarray) else trace
                        for trace in traces
                    ]

                with open(filename, "w") as f:
                    json.dump(json_data, f, indent=2)

            print(
                f"Trace data exported to {filename} (Real-time axis: {self.use_realtime_axis})"
            )

        except Exception as e:
            print(f"Error exporting trace data: {e}")

    def import_data(self, filename):
        """Import trace data from file"""
        try:
            if filename.endswith(".npz"):
                data = np.load(filename, allow_pickle=True)

                # Load metadata if available
                if "metadata" in data:
                    metadata = data["metadata"].item()
                    self.time_per_sample = metadata.get(
                        "time_per_sample_ns", self.time_per_sample
                    )
                    self.amplitude_threshold = metadata.get(
                        "amplitude_threshold", self.amplitude_threshold
                    )
                    # Load real-time axis settings if available
                    self.use_realtime_axis = metadata.get("use_realtime_axis", True)
                    self.sampling_period_ns = metadata.get("sampling_period_ns", 2.0)
                    if "trace_delay_ns" in metadata:
                        self.trace_delay_ns = metadata["trace_delay_ns"]

                # Load trace data
                for key in data.keys():
                    if key.startswith("ch_") and key.endswith("_traces"):
                        ch_str = key.split("_")[1]
                        try:
                            ch = int(ch_str)
                            if ch in self.channels:
                                trace_array = data[key]
                                # Convert back to list of traces
                                traces = []
                                for trace_row in trace_array:
                                    # Remove NaN padding
                                    valid_data = trace_row[~np.isnan(trace_row)]
                                    if len(valid_data) > 0:
                                        traces.append(valid_data)

                                self.trace_data[ch] = deque(traces, maxlen=100)
                        except ValueError:
                            continue

            else:
                # Load JSON format
                import json

                with open(filename) as f:
                    data = json.load(f)

                # Load metadata
                if "metadata" in data:
                    metadata = data["metadata"]
                    self.time_per_sample = metadata.get(
                        "time_per_sample_ns", self.time_per_sample
                    )
                    self.amplitude_threshold = metadata.get(
                        "amplitude_threshold", self.amplitude_threshold
                    )

                # Load trace data
                for key, traces in data.items():
                    if key.startswith("ch_"):
                        ch_str = key.split("_")[1]
                        try:
                            ch = int(ch_str)
                            if ch in self.channels:
                                self.trace_data[ch] = deque(
                                    [np.array(trace) for trace in traces], maxlen=100
                                )
                        except ValueError:
                            continue

            print(f"Trace data imported from {filename}")
            self.update_plots()

        except Exception as e:
            print(f"Error importing trace data: {e}")
