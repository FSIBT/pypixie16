"""
MCA Spectrum Plotter for PIXIE-16
Displays multi-channel analyzer histograms in real-time
"""

import numpy as np
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
)
from PyQt6.QtCore import QTimer
import pyqtgraph as pg


class MCASpectrumPlotter(QWidget):
    def __init__(self, channels=None, title="PIXIE-16 MCA Spectra"):
        super().__init__()

        self.channels = channels or [4, 9]  # Default channels from working config
        self.mca_data = {ch: np.zeros(4096, dtype=np.int32) for ch in self.channels}

        # Display settings
        self.energy_min = 0
        self.energy_max = 4095
        self.log_scale = False
        self.auto_scale = True

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
        # print("Adding test data to verify plotting...")
        # for i, channel in enumerate(self.channels):
        #     test_data = np.zeros(4096, dtype=np.int32)
        #     # Create a clear peak at different positions for each channel
        #     peak_pos = 500 + i * 500  # Channel 4 at bin 500, Channel 9 at bin 1000
        #     for j in range(50):  # Create a 50-bin wide peak
        #         if peak_pos + j < 4096:
        #             test_data[peak_pos + j] = 100 - j  # Descending peak

        #     self.mca_data[channel] = test_data
        #     print(
        #         f"Added test peak for channel {channel} at bin {peak_pos}, sum={np.sum(test_data)}"
        #     )

        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_plots)
        # self.update_timer.start(500)  # Update every 500ms

        # # Force an immediate plot update to show test data
        # QTimer.singleShot(100, self.update_plots)

    def init_ui(self):
        layout = QVBoxLayout()

        # Controls
        controls = self.create_controls()
        layout.addWidget(controls)

        # Plot area
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel("left", "Counts")
        self.plot_widget.setLabel("bottom", "Channel/Energy")
        self.plot_widget.setTitle("MCA Spectra")
        self.plot_widget.showGrid(True, True, alpha=0.3)
        self.plot_widget.addLegend()

        layout.addWidget(self.plot_widget)

        # Statistics display
        self.stats_label = QLabel("Statistics: No data")
        layout.addWidget(self.stats_label)

        self.setLayout(layout)

        # Initialize plot curves
        self.curves = {}
        for i, channel in enumerate(self.channels):
            color = self.colors[i % len(self.colors)]
            self.curves[channel] = self.plot_widget.plot(
                pen=pg.mkPen(color=color, width=2), name=f"Ch {channel}"
            )

    def create_controls(self):
        group = QGroupBox("Display Controls")
        layout = QHBoxLayout()

        # Energy range
        layout.addWidget(QLabel("Energy Min:"))
        self.energy_min_spin = QSpinBox()
        self.energy_min_spin.setRange(0, 4090)
        self.energy_min_spin.setValue(0)
        self.energy_min_spin.valueChanged.connect(self.update_energy_range)
        layout.addWidget(self.energy_min_spin)

        layout.addWidget(QLabel("Max:"))
        self.energy_max_spin = QSpinBox()
        self.energy_max_spin.setRange(5, 4095)
        self.energy_max_spin.setValue(4095)
        self.energy_max_spin.valueChanged.connect(self.update_energy_range)
        layout.addWidget(self.energy_max_spin)

        # Display options
        self.log_scale_cb = QCheckBox("Log Scale")
        self.log_scale_cb.toggled.connect(self.toggle_log_scale)
        layout.addWidget(self.log_scale_cb)

        self.auto_scale_cb = QCheckBox("Auto Scale")
        self.auto_scale_cb.setChecked(True)
        self.auto_scale_cb.toggled.connect(self.toggle_auto_scale)
        layout.addWidget(self.auto_scale_cb)

        # Clear button
        self.clear_btn = QPushButton("Clear Spectra")
        self.clear_btn.clicked.connect(self.clear_data)
        layout.addWidget(self.clear_btn)

        # ROI controls
        layout.addWidget(QLabel("ROI:"))
        self.roi_start = QSpinBox()
        self.roi_start.setRange(0, 4090)
        self.roi_start.setValue(100)
        layout.addWidget(self.roi_start)

        layout.addWidget(QLabel("to"))
        self.roi_end = QSpinBox()
        self.roi_end.setRange(5, 4095)
        self.roi_end.setValue(200)
        layout.addWidget(self.roi_end)

        layout.addStretch()

        group.setLayout(layout)
        return group

    def start_live_updates(self):
        """Start the plot update timer"""
        if not self.update_timer.isActive():
            self.update_timer.start(500)
            print("MCA Plotter: Started live updates")

    def stop_live_updates(self):
        """Stop the plot update timer"""
        if self.update_timer.isActive():
            self.update_timer.stop()
            print("MCA Plotter: Stopped live updates")

    def update_mca_histogram(self, channel, histogram_data):
        """Update MCA histogram data for a specific channel"""
        print(f"MCA Plotter: Received data for channel {channel}")
        print(
            f"MCA Plotter: Data type={type(histogram_data)}, shape={histogram_data.shape if hasattr(histogram_data, 'shape') else 'no shape'}"
        )
        print(
            f"MCA Plotter: Data sum={np.sum(histogram_data) if hasattr(histogram_data, '__len__') else 'no sum'}"
        )

        if channel in self.mca_data:
            old_sum = np.sum(self.mca_data[channel])
            self.mca_data[channel] = histogram_data.copy()
            new_sum = np.sum(self.mca_data[channel])
            print(f"MCA Plotter: Channel {channel} updated: {old_sum} -> {new_sum}")
        else:
            print(
                f"MCA Plotter: Channel {channel} not in mca_data keys: {list(self.mca_data.keys())}"
            )

    def update_energy_range(self):
        """Update energy display range"""
        self.energy_min = self.energy_min_spin.value()
        self.energy_max = self.energy_max_spin.value()

        if self.energy_min >= self.energy_max:
            self.energy_max = self.energy_min + 10
            self.energy_max_spin.setValue(self.energy_max)

    def toggle_log_scale(self, enabled):
        """Toggle logarithmic scale"""
        self.log_scale = enabled
        if enabled:
            self.plot_widget.setLogMode(False, True)
        else:
            self.plot_widget.setLogMode(False, False)

    def toggle_auto_scale(self, enabled):
        """Toggle auto scaling"""
        self.auto_scale = enabled
        if not enabled:
            self.plot_widget.setXRange(self.energy_min, self.energy_max)

    def clear_data(self):
        """Clear all MCA data"""
        for channel in self.channels:
            self.mca_data[channel] = np.zeros(4096, dtype=np.int32)
        self.update_plots()

    def update_plots(self):
        """Update the plot display"""
        try:
            total_counts = 0
            channel_stats = {}

            print(
                f"Plot Update: Processing {len(self.channels)} channels: {self.channels}"
            )

            for channel in self.channels:
                if channel in self.mca_data and channel in self.curves:
                    data = self.mca_data[channel]
                    data_sum = np.sum(data)
                    data_max = np.max(data)

                    print(
                        f"Plot Update: Channel {channel} - sum={data_sum}, max={data_max}"
                    )

                    # Create x-axis (bin numbers or energy if calibrated)
                    x_data = np.arange(len(data))

                    # Apply energy range filter for display
                    mask = (x_data >= self.energy_min) & (x_data <= self.energy_max)
                    x_plot = x_data[mask]
                    y_plot = data[mask]

                    # Handle log scale
                    if self.log_scale:
                        y_plot = np.where(y_plot > 0, y_plot, 0.1)  # Avoid log(0)
                    # Update curve
                    if len(x_plot) > 0:
                        print(
                            f"Plot Update: Setting data for channel {channel}: x_len={len(x_plot)}, y_max={np.max(y_plot)}"
                        )
                        self.curves[channel].setData(x_plot, y_plot)
                    else:
                        print(f"Plot Update: No data to plot for channel {channel}")

                    # Statistics
                    total_ch_counts = np.sum(data)
                    total_counts += total_ch_counts

                    # ROI analysis
                    roi_start = self.roi_start.value()
                    roi_end = self.roi_end.value()
                    roi_counts = np.sum(data[roi_start : roi_end + 1])

                    channel_stats[channel] = {
                        "total": total_ch_counts,
                        "roi": roi_counts,
                        "peak_bin": np.argmax(data),
                        "peak_counts": np.max(data),
                    }

            # Update statistics display
            stats_text = f"Total Counts: {total_counts:,} | "
            for ch, stats in channel_stats.items():
                stats_text += f"Ch{ch}: {stats['total']:,} ({stats['roi']} ROI) | "

            self.stats_label.setText(stats_text.rstrip(" | "))

            # Auto scale if enabled
            if self.auto_scale and total_counts > 0:
                self.plot_widget.autoRange()

        except Exception as e:
            print(f"Error updating MCA plots: {e}")

    def get_spectrum_data(self):
        """Get current spectrum data for saving"""
        return self.mca_data.copy()

    def set_channels(self, channels):
        """Update the list of channels to display"""
        # Remove old curves
        for channel in self.channels:
            if channel in self.curves:
                self.plot_widget.removeItem(self.curves[channel])

        # Update channels
        self.channels = channels
        self.mca_data = {
            ch: self.mca_data.get(ch, np.zeros(4096, dtype=np.int32))
            for ch in self.channels
        }

        # Create new curves
        self.curves = {}
        for i, channel in enumerate(self.channels):
            color = self.colors[i % len(self.colors)]
            self.curves[channel] = self.plot_widget.plot(
                pen=pg.mkPen(color=color, width=2), name=f"Ch {channel}"
            )

    def export_data(self, filename):
        """Export MCA data to file"""
        try:
            np.savez(
                filename, **{f"ch_{ch}": data for ch, data in self.mca_data.items()}
            )
            print(f"MCA data exported to {filename}")
        except Exception as e:
            print(f"Error exporting MCA data: {e}")
