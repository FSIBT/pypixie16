"""
MCA Spectrum Plotter for PIXIE-16
Displays multi-channel analyzer histograms in real-time
FEATURES:
- Rebins data to ~2000 bins for better display performance
- Log y-axis scaling
- Step plots for proper histogram visualization
- Handles data[channel_row, :] format from PIXIE
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

        self.channels = channels or [4, 9]  # Channel numbers (not row indices)

        # Data storage - keyed by channel number
        self.mca_data = {ch: np.array([]) for ch in self.channels}
        self.bin_counts = {ch: 0 for ch in self.channels}
        self.max_bins_seen = 0

        # Rebinning settings
        self.target_bins = 2048  # Target number of bins for display
        self.rebin_factor = 1  # Will be calculated based on input data

        # Display settings
        self.energy_min = 0
        self.energy_max = 2047  # In rebinned coordinates
        self.log_scale = True  # Default to log scale for MCA data
        self.auto_scale = True

        self.info_bar = None

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

    def rebin_data(self, data, target_bins=None):
        """Rebin histogram data to target number of bins"""
        if target_bins is None:
            target_bins = self.target_bins

        original_bins = len(data)
        if original_bins <= target_bins:
            # No rebinning needed
            return data, np.arange(len(data)), 1

        # Calculate rebin factor
        rebin_factor = original_bins // target_bins
        if original_bins % target_bins != 0:
            rebin_factor += 1

        # Trim data to make it evenly divisible
        trimmed_length = (original_bins // rebin_factor) * rebin_factor
        trimmed_data = data[:trimmed_length]

        # Reshape and sum
        reshaped = trimmed_data.reshape(-1, rebin_factor)
        rebinned_data = np.sum(reshaped, axis=1)

        # Create new x-axis in terms of original bin numbers (bin centers)
        rebinned_x = np.arange(len(rebinned_data)) * rebin_factor + rebin_factor // 2

        print(
            f"Rebinning: {original_bins} -> {len(rebinned_data)} bins (factor: {rebin_factor})"
        )

        return rebinned_data, rebinned_x, rebin_factor

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(5)  # Reduce spacing
        layout.setContentsMargins(5, 5, 5, 5)  # Reduce margins

        # Controls - compact version
        controls = self.create_controls()
        layout.addWidget(controls)

        # Plot area
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel("left", "Counts (Log Scale)")
        self.plot_widget.setLabel("bottom", "Energy/Channel (Rebinned)")
        self.plot_widget.setTitle("MCA Spectra")
        self.plot_widget.showGrid(True, True, alpha=0.3)
        self.plot_widget.addLegend()

        self.plot_widget.setBackground("w")

        # Set log scale by default
        self.plot_widget.setLogMode(False, True)

        layout.addWidget(self.plot_widget)

        # Statistics display - compact version
        self.stats_label = QLabel("Statistics: Waiting for data...")
        self.stats_label.setMaximumHeight(30)  # Limit height
        self.stats_label.setStyleSheet("QLabel { font-size: 11px; padding: 2px; }")
        layout.addWidget(self.stats_label)

        self.setLayout(layout)

        # Initialize plot curves
        self.curves = {}
        for i, channel in enumerate(self.channels):
            color = self.colors[i % len(self.colors)]
            # Use stepMode for proper histogram display
            self.curves[channel] = self.plot_widget.plot(
                pen=pg.mkPen(color=color, width=2),
                name=f"Ch {channel}",
                stepMode=True,  # This gives us step plots like plt.step
            )

    def create_controls(self):
        """Create compact control panel"""
        group = QGroupBox("Display Controls")
        group.setMaximumHeight(100)  # Limit height for compactness

        # Use two rows for better space utilization
        main_layout = QVBoxLayout()
        main_layout.setSpacing(3)

        # First row - Binning and range controls
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(5)

        # Target bins - compact
        row1_layout.addWidget(QLabel("Bins:"))
        self.target_bins_spin = QSpinBox()
        self.target_bins_spin.setRange(500, 8192)
        self.target_bins_spin.setValue(self.target_bins)
        self.target_bins_spin.valueChanged.connect(self.update_target_bins)
        self.target_bins_spin.setMaximumWidth(80)
        row1_layout.addWidget(self.target_bins_spin)

        # Energy range - compact
        row1_layout.addWidget(QLabel("Min:"))
        self.energy_min_spin = QSpinBox()
        self.energy_min_spin.setRange(0, 8191)
        self.energy_min_spin.setValue(0)
        self.energy_min_spin.valueChanged.connect(self.update_energy_range)
        self.energy_min_spin.setMaximumWidth(80)
        row1_layout.addWidget(self.energy_min_spin)

        row1_layout.addWidget(QLabel("Max:"))
        self.energy_max_spin = QSpinBox()
        self.energy_max_spin.setRange(1, 8192)
        self.energy_max_spin.setValue(2047)
        self.energy_max_spin.valueChanged.connect(self.update_energy_range)
        self.energy_max_spin.setMaximumWidth(80)
        row1_layout.addWidget(self.energy_max_spin)

        # Auto-detect button - compact
        self.auto_detect_btn = QPushButton("Auto")
        self.auto_detect_btn.setToolTip("Auto-detect data range")
        self.auto_detect_btn.clicked.connect(self.auto_detect_data_range)
        self.auto_detect_btn.setMaximumWidth(50)
        row1_layout.addWidget(self.auto_detect_btn)

        # Bin info display - compact
        self.bin_info_label = QLabel("Bins: Unknown")
        self.bin_info_label.setStyleSheet("QLabel { font-size: 10px; }")
        row1_layout.addWidget(self.bin_info_label)

        row1_layout.addStretch()

        # Second row - Display options and actions
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(5)

        # Display options - compact checkboxes
        self.log_scale_cb = QCheckBox("Log")
        self.log_scale_cb.setChecked(True)
        self.log_scale_cb.toggled.connect(self.toggle_log_scale)
        row2_layout.addWidget(self.log_scale_cb)

        self.auto_scale_cb = QCheckBox("Auto Scale")
        self.auto_scale_cb.setChecked(True)
        self.auto_scale_cb.toggled.connect(self.toggle_auto_scale)
        row2_layout.addWidget(self.auto_scale_cb)

        # Clear button - compact
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_data)
        self.clear_btn.setMaximumWidth(60)
        row2_layout.addWidget(self.clear_btn)

        row2_layout.addStretch()

        # Add rows to main layout
        main_layout.addLayout(row1_layout)
        main_layout.addLayout(row2_layout)

        group.setLayout(main_layout)
        return group

    def auto_detect_data_range(self):
        """Auto-detect where the actual data is and set display range"""
        print("Auto-detecting data range...")

        # Find where data actually exists across all channels
        min_data_bin = float("inf")
        max_data_bin = 0
        total_counts = 0

        for channel in self.channels:
            if channel in self.mca_data and len(self.mca_data[channel]) > 0:
                raw_data = self.mca_data[channel]

                # Find non-zero data range in original coordinates
                non_zero_bins = np.where(raw_data > 0)[0]
                if len(non_zero_bins) > 0:
                    # Convert to rebinned coordinates
                    rebin_factor = (
                        len(raw_data) // self.target_bins
                        if len(raw_data) > self.target_bins
                        else 1
                    )

                    min_raw = non_zero_bins[0]
                    max_raw = non_zero_bins[-1]

                    min_rebinned = min_raw // rebin_factor
                    max_rebinned = max_raw // rebin_factor

                    min_data_bin = min(min_data_bin, min_rebinned)
                    max_data_bin = max(max_data_bin, max_rebinned)

                    total_counts += np.sum(raw_data)

                    print(
                        f"Channel {channel}: raw range {min_raw}-{max_raw}, rebinned {min_rebinned}-{max_rebinned}"
                    )

        if min_data_bin != float("inf") and total_counts > 0:
            # Add some padding around the data
            padding = max(50, (max_data_bin - min_data_bin) // 10)

            new_min = max(0, min_data_bin - padding)
            new_max = min(self.target_bins - 1, max_data_bin + padding)

            print(f"Auto-detected range: {new_min} to {new_max} (rebinned coordinates)")
            print(f"Total counts found: {total_counts}")

            # Update the controls
            self.energy_min_spin.setValue(new_min)
            self.energy_max_spin.setValue(new_max)

            # Update info bar if available
            if self.info_bar:
                self.info_bar.setText(
                    f"Auto-detected data range: {new_min}-{new_max} (rebinned), {total_counts:,} counts"
                )
        else:
            print("No data found for auto-detection")
            if self.info_bar:
                self.info_bar.setText("No data found - cannot auto-detect range")

    def update_target_bins(self):
        """Update target bin count for rebinning"""
        self.target_bins = self.target_bins_spin.value()
        # Update energy range controls
        self.energy_max_spin.setMaximum(self.target_bins)
        self.energy_min_spin.setMaximum(self.target_bins - 1)
        if self.energy_max > self.target_bins:
            self.energy_max = self.target_bins - 1
            self.energy_max_spin.setValue(self.energy_max)

    def update_dynamic_ranges(self, num_bins):
        """Update UI ranges based on actual number of bins received"""
        if num_bins > self.max_bins_seen:
            self.max_bins_seen = num_bins
            rebinned_size = min(num_bins, self.target_bins)

            print(f"MCA Plotter: Raw bins: {num_bins}, Rebinned: {rebinned_size}")

            self.bin_info_label.setText(f"Raw: {num_bins}, Display: {rebinned_size}")

    def start_live_updates(self):
        if not self.update_timer.isActive():
            self.update_timer.start(500)
            print("MCA Plotter: Started live updates")

    def stop_live_updates(self):
        if self.update_timer.isActive():
            self.update_timer.stop()
            print("MCA Plotter: Stopped live updates")

    def update_mca_histogram(self, channel, histogram_data):
        if not isinstance(histogram_data, np.ndarray):
            histogram_data = np.array(histogram_data)

        num_bins = len(histogram_data)
        data_sum = np.sum(histogram_data)
        data_max = np.max(histogram_data) if num_bins > 0 else 0

        print(f"MCA Plotter: Received data for channel {channel}")
        print(f"MCA Plotter: Raw bins={num_bins}, sum={data_sum}, max={data_max}")

        if channel in self.mca_data:
            # Store the raw data
            self.mca_data[channel] = histogram_data.copy()
            self.bin_counts[channel] = num_bins

            # Update UI ranges if needed
            self.update_dynamic_ranges(num_bins)

            print(f"MCA Plotter: Channel {channel} updated with {num_bins} bins")
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
            self.plot_widget.setLabel("left", "Counts (Log Scale)")
        else:
            self.plot_widget.setLogMode(False, False)
            self.plot_widget.setLabel("left", "Counts (Linear Scale)")

    def toggle_auto_scale(self, enabled):
        """Toggle auto scaling"""
        self.auto_scale = enabled
        if not enabled:
            self.plot_widget.setXRange(self.energy_min, self.energy_max)

    def clear_data(self):
        """Clear all MCA data"""
        for channel in self.channels:
            self.mca_data[channel] = np.array([])
            self.bin_counts[channel] = 0
        self.update_plots()

    def update_plots(self):
        """Update the plot display with rebinned data and step plots - FIXED stepMode"""
        try:
            total_counts = 0
            channel_stats = {}

            print(
                f"Plot Update: Processing {len(self.channels)} channels: {self.channels}"
            )

            for channel in self.channels:
                if channel in self.mca_data and channel in self.curves:
                    raw_data = self.mca_data[channel]

                    if len(raw_data) == 0:
                        print(f"Plot Update: Channel {channel} - no data")
                        continue

                    # Rebin the data
                    rebinned_data, rebinned_x, rebin_factor = self.rebin_data(raw_data)

                    data_sum = np.sum(rebinned_data)
                    data_max = np.max(rebinned_data)

                    print(
                        f"Plot Update: Channel {channel} - rebinned bins={len(rebinned_data)}, sum={data_sum}, max={data_max}"
                    )

                    # Apply display range filter
                    mask = (rebinned_x >= self.energy_min) & (
                        rebinned_x <= self.energy_max
                    )
                    x_plot = rebinned_x[mask]
                    y_plot = rebinned_data[mask]

                    # Handle log scale - avoid log(0)
                    if self.log_scale:
                        y_plot = np.where(y_plot > 0, y_plot, 0.1)

                    # FIXED: For stepMode=True, x must have len(y)+1 elements
                    # Create bin edges instead of bin centers
                    if len(x_plot) > 0:
                        # Create x_edges array with one more element
                        if len(x_plot) == len(y_plot):
                            # Add one more bin edge at the end
                            bin_width = rebin_factor if len(x_plot) > 1 else 1
                            x_edges = np.append(x_plot, x_plot[-1] + bin_width)
                        else:
                            x_edges = x_plot

                        print(
                            f"Plot Update: Setting data for channel {channel}: x_len={len(x_edges)}, y_len={len(y_plot)}, y_max={np.max(y_plot) if len(y_plot) > 0 else 0}"
                        )

                        # Now x_edges has len(y_plot) + 1 elements as required
                        self.curves[channel].setData(x_edges, y_plot)
                    else:
                        print(f"Plot Update: No data in range for channel {channel}")

                    # Statistics (using original raw data for accuracy)
                    total_ch_counts = np.sum(raw_data)
                    total_counts += total_ch_counts

                    channel_stats[channel] = {
                        "total": total_ch_counts,
                        "peak_bin": np.argmax(raw_data),
                        "peak_counts": np.max(raw_data),
                        "raw_bins": len(raw_data),
                        "display_bins": len(rebinned_data),
                        "rebin_factor": rebin_factor,
                    }

            # Update statistics display - compact version
            if len(channel_stats) > 0:
                # Show only essential info for space efficiency
                stats_text = f"Total: {total_counts:,} | "

                # Show first few channels to avoid overcrowding
                display_channels = list(channel_stats.keys())[:6]  # Limit to 6 channels

                for ch in display_channels:
                    stats = channel_stats[ch]
                    stats_text += f"Ch{ch}: {stats['total']:,} | "

                if len(channel_stats) > 6:
                    stats_text += f"...+{len(channel_stats) - 6} more"
                else:
                    stats_text = stats_text.rstrip(" | ")

                self.stats_label.setText(stats_text)
            else:
                self.stats_label.setText("Statistics: Waiting for data...")

            # Auto scale if enabled
            if self.auto_scale and total_counts > 0:
                self.plot_widget.autoRange()

        except Exception as e:
            print(f"Error updating MCA plots: {e}")
            import traceback

            traceback.print_exc()

    def get_spectrum_data(self):
        """Get current spectrum data for saving (returns raw, not rebinned data)"""
        return self.mca_data.copy()

    def set_channels(self, channels):
        """Update the list of channels to display"""
        # Remove old curves
        for channel in self.channels:
            if channel in self.curves:
                self.plot_widget.removeItem(self.curves[channel])

        # Update channels
        self.channels = channels
        # Preserve existing data, create empty arrays for new channels
        new_mca_data = {}
        for ch in self.channels:
            new_mca_data[ch] = self.mca_data.get(ch, np.array([]))
        self.mca_data = new_mca_data

        # Create new curves with step mode
        self.curves = {}
        for i, channel in enumerate(self.channels):
            color = self.colors[i % len(self.colors)]
            self.curves[channel] = self.plot_widget.plot(
                pen=pg.mkPen(color=color, width=2),
                name=f"Ch {channel}",
                stepMode=True,  # Step plots for histogram data
            )

    def set_display_channels(self, channels):
        """Set which channels to display (compatibility method)"""
        self.set_channels(channels)

    def export_data(self, filename):
        """Export MCA data to file (saves raw data, not rebinned)"""
        try:
            np.savez(
                filename, **{f"ch_{ch}": data for ch, data in self.mca_data.items()}
            )
            print(f"MCA data exported to {filename}")
        except Exception as e:
            print(f"Error exporting MCA data: {e}")

    def set_info_bar(self, info_bar):
        """Set reference to parent info bar for status updates"""
        self.info_bar = info_bar
