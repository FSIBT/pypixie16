"""
Real-time spectrum plotter for PIXIE-16 list mode (binary) data.
"""

import json
import pyqtgraph as pg
import numpy as np
from collections import deque, defaultdict
import time

from PyQt6 import QtCore
from PyQt6.QtWidgets import (
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QDoubleSpinBox,
    QPushButton,
    QCheckBox,
    QSpinBox,
    QWidget,
    QSplitter,
    QTabWidget,
)

# Import FWHM analysis components
try:
    from .fwhm_widget import FWHMAnalysisWidget
    FWHM_AVAILABLE = True
except ImportError as e:
    print(f"FWHM analysis not available: {e}")
    FWHM_AVAILABLE = False

import logging

logger = logging.getLogger(__name__)


class ContinuousSpectrumPlotter(QWidget):
    def __init__(
        self,
        app=None,
        instrument_name="pixie16",
        display_name="PIXIE Energy Spectra",
        channels=None,
        channel_names=None,
        energy_range=(0, 4096),
        bins=1000,
        bkg_color="w",
        update_hooks=None,
    ):
        super().__init__()

        self.app = app
        self.instrument = instrument_name
        self.channels = channels or list(range(16))
        self.channel_names = channel_names or [f"Ch{ch}" for ch in self.channels]
        self.energy_range = energy_range
        self.bins = bins
        self.update_hooks = update_hooks or []
        self.display_channels = self.channels.copy()

        # Energy data storage - use deque for efficient append/pop operations
        self.energy_data = defaultdict(lambda: deque(maxlen=50000))
        self.last_update = time.time()
        self.update_rate = 0.5  # seconds

        # Update timer
        self.update_timer = QtCore.QTimer()
        self.update_timer.timeout.connect(self.update_display)

        # Channel colors
        self.channel_colors = [
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

        self.setWindowTitle(display_name)
        self.setup_ui(bkg_color)

    def setup_ui(self, bkg_color):
        main_layout = QVBoxLayout()

        # Controls
        control_group = self.create_control_group()
        main_layout.addWidget(control_group)

        # Create horizontal splitter for plot and FWHM analysis
        splitter = QSplitter(QtCore.Qt.Orientation.Horizontal)
        
        # Left side: Plot area
        plot_widget = QWidget()
        plot_layout = QVBoxLayout(plot_widget)
        
        self.display = pg.PlotWidget()
        self.display.setBackground(bkg_color)
        self.display.setLabel("left", "Counts")
        self.display.setLabel("bottom", "Energy", "a.u.")
        self.display.setTitle("PIXIE-16 List Mode Energy Spectra")
        self.display.showGrid(x=True, y=True)
        self.display.setMenuEnabled(enableMenu=True)
        self.display.addLegend()

        # Store reference to plot widget for FWHM integration
        self.plot_widget = self.display

        # Create plot items for each channel
        self.plot_items = {}
        for i, channel in enumerate(self.channels):
            color = self.channel_colors[i % len(self.channel_colors)]
            pen = pg.mkPen(color=color, width=2)
            curve = pg.PlotCurveItem(pen=pen, name=self.channel_names[i])
            self.plot_items[channel] = curve
            self.display.addItem(curve)

        plot_layout.addWidget(self.display)

        # Statistics display
        self.stats_widget = self.create_stats_widget()
        plot_layout.addWidget(self.stats_widget)
        
        splitter.addWidget(plot_widget)

        # Right side: FWHM Analysis (if available)
        if FWHM_AVAILABLE:
            self.fwhm_widget = FWHMAnalysisWidget(spectrum_plotter=self)
            self.fwhm_widget.connect_to_plotter(self)
            splitter.addWidget(self.fwhm_widget)
            
            # Set initial splitter sizes (70% plot, 30% FWHM)
            splitter.setSizes([700, 300])
        else:
            self.fwhm_widget = None
            
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)

    def create_control_widgets(self):
        self.energy_min_label = QLabel("Energy Min (a.u.):")
        self.energy_min_spin = QDoubleSpinBox()
        self.energy_min_spin.setRange(0, 10000)
        self.energy_min_spin.setValue(self.energy_range[0])
        self.energy_min_spin.valueChanged.connect(self.update_energy_range)

        self.energy_max_label = QLabel("Energy Max (a.u.):")
        self.energy_max_spin = QDoubleSpinBox()
        self.energy_max_spin.setRange(0, 100000)
        self.energy_max_spin.setValue(self.energy_range[1])
        self.energy_max_spin.valueChanged.connect(self.update_energy_range)

        self.bins_label = QLabel("Bins:")
        self.bins_spin = QSpinBox()
        self.bins_spin.setRange(10, 100000)
        self.bins_spin.setValue(self.bins)
        self.bins_spin.valueChanged.connect(self.update_bins)

        self.log_scale_cb = QCheckBox("Log Scale")
        self.log_scale_cb.toggled.connect(self.toggle_log_scale)

        self.auto_scale_cb = QCheckBox("Auto Scale")
        self.auto_scale_cb.setChecked(True)
        self.auto_scale_cb.toggled.connect(self.toggle_auto_scale)

        self.clear_btn = QPushButton("Clear Spectra")
        self.clear_btn.clicked.connect(self.clear_data)

    def create_control_group(self):
        self.create_control_widgets()

        group = QGroupBox("Plot Controls")
        group.setMaximumHeight(80)  # Make more compact
        layout = QHBoxLayout()  # Use horizontal layout
        layout.setSpacing(5)

        # Energy range controls
        layout.addWidget(QLabel("Min:"))
        self.energy_min_spin.setMaximumWidth(80)
        layout.addWidget(self.energy_min_spin)

        layout.addWidget(QLabel("Max:"))
        self.energy_max_spin.setMaximumWidth(80)
        layout.addWidget(self.energy_max_spin)

        # Bins control
        layout.addWidget(QLabel("Bins:"))
        self.bins_spin.setMaximumWidth(70)
        layout.addWidget(self.bins_spin)

        # Checkboxes with shorter text
        self.log_scale_cb.setText("Log")
        layout.addWidget(self.log_scale_cb)

        self.auto_scale_cb.setText("Auto")
        layout.addWidget(self.auto_scale_cb)

        # Clear button
        self.clear_btn.setText("Clear")
        self.clear_btn.setMaximumWidth(60)
        layout.addWidget(self.clear_btn)

        layout.addStretch()
        group.setLayout(layout)
        return group

    def create_stats_widget(self):
        self.stats_labels = {}

        stats_group = QGroupBox("Channel Statistics")
        stats_group.setMaximumHeight(60)  # More compact
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(3)

        # Only show first 8 channels to save space, or use scrollable area
        display_channels = (
            self.channels[:8] if len(self.channels) > 8 else self.channels
        )

        for ch in display_channels:
            label = QLabel(f"Ch{ch}: 0")
            label.setStyleSheet("QLabel { font-size: 10px; }")  # Smaller font
            self.stats_labels[ch] = label
            stats_layout.addWidget(label)

        if len(self.channels) > 8:
            more_label = QLabel(f"...+{len(self.channels) - 8} more")
            more_label.setStyleSheet("QLabel { font-size: 10px; color: gray; }")
            stats_layout.addWidget(more_label)

        stats_layout.addStretch()
        stats_group.setLayout(stats_layout)
        return stats_group

    def start_live_updates(self):
        if not self.update_timer.isActive():
            self.update_timer.start(int(self.update_rate * 1000))
            print("List Mode Plotter: Started live updates")

    def stop_live_updates(self):
        if self.update_timer.isActive():
            self.update_timer.stop()
            print("List Mode Plotter: Stopped live updates")

    def add_energy_event(self, channel, energy):
        if channel in self.channels:
            self.energy_data[channel].append(energy)

    def add_energy_events(self, channel, energies):
        if channel in self.channels:
            if isinstance(energies, list | np.ndarray):
                self.energy_data[channel].extend(energies)
            else:
                self.energy_data[channel].append(energies)

    def update_display(self):
        current_time = time.time()
        if current_time - self.last_update < self.update_rate:
            return

        self.last_update = current_time
        total_events = 0

        # Process ALL channels but only display selected ones
        for channel in self.channels:
            event_count = (
                len(self.energy_data[channel]) if channel in self.energy_data else 0
            )
            total_events += event_count

            # Update statistics for ALL channels (even hidden ones)
            if channel in self.stats_labels:
                self.stats_labels[channel].setText(f"Ch{channel}: {event_count} events")

            # Only display data for selected channels
            if channel not in self.display_channels:
                # Channel not selected for display - hide it
                self.plot_items[channel].setData([], [])
                continue

            # Channel is selected for display
            if event_count == 0:
                # No data for this channel
                self.plot_items[channel].setData([], [])
                continue

            # Display the channel data
            try:
                energies = list(self.energy_data[channel])

                # Create histogram
                counts, bin_edges = np.histogram(
                    energies, bins=self.bins, range=self.energy_range
                )

                # Calculate bin centers
                bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

                # Apply log scale if enabled
                if self.log_scale_cb.isChecked():
                    plot_counts = np.where(counts > 0, counts, 0.1)
                    plot_counts = np.log10(plot_counts)
                else:
                    plot_counts = counts

                self.plot_items[channel].setData(bin_centers, plot_counts)

            except Exception as e:
                print(f"Error updating channel {channel}: {e}")
                self.plot_items[channel].setData([], [])

        # Auto scale if enabled
        if self.auto_scale_cb.isChecked() and total_events > 0:
            self.display.autoRange()

    def update_energy_range(self):
        self.energy_range = (self.energy_min_spin.value(), self.energy_max_spin.value())
        if not self.auto_scale_cb.isChecked():
            self.display.setXRange(*self.energy_range)

    def update_bins(self):
        self.bins = self.bins_spin.value()

    def toggle_log_scale(self, checked):
        if checked:
            self.display.setLabel("left", "Log10(Counts)")
        else:
            self.display.setLabel("left", "Counts")

    def toggle_auto_scale(self, checked):
        if not checked:
            self.display.setXRange(*self.energy_range)

    def set_display_channels(self, channels):
        print(f"List Mode Plotter: set_display_channels called with {channels}")
        self.display_channels = channels if channels else []

        # hide unselected channels
        for channel in self.channels:
            if channel not in self.display_channels:
                self.plot_items[channel].setData([], [])
                print(f"List Mode: Hiding channel {channel}")
            else:
                print(f"List Mode: Will show channel {channel}")

        self.update_display()

    def clear_data(self):
        for channel in self.channels:
            self.energy_data[channel].clear()

        # Clear plots immediately
        for channel in self.channels:
            self.plot_items[channel].setData([], [])
            if channel in self.stats_labels:
                self.stats_labels[channel].setText(f"Ch{channel}: 0 events")

    def get_spectrum_data(self):
        data = {}
        for channel in self.channels:
            if len(self.energy_data[channel]) > 0:
                data[channel] = list(self.energy_data[channel])
        return data
        
    def get_histogram_data(self):
        histogram_data = {}
        for channel in self.channels:
            if len(self.energy_data[channel]) > 0:
                energies = list(self.energy_data[channel])
                # Create histogram matching current display parameters
                hist, bin_edges = np.histogram(energies, bins=self.bins, range=self.energy_range)
                histogram_data[channel] = hist
        return histogram_data

    def set_channels(self, channels):
        # Remove old plot items
        for channel in self.channels:
            if channel in self.plot_items:
                self.display.removeItem(self.plot_items[channel])

        # Update channels
        self.channels = channels
        self.display_channels = channels.copy()

        # Preserve existing data, create empty deques for new channels
        new_energy_data = {}
        for ch in self.channels:
            new_energy_data[ch] = self.energy_data.get(ch, deque(maxlen=50000))
        self.energy_data = new_energy_data

        # Create new plot items
        self.plot_items = {}
        for i, channel in enumerate(self.channels):
            color = self.channel_colors[i % len(self.channel_colors)]
            pen = pg.mkPen(color=color, width=2)
            curve = pg.PlotCurveItem(pen=pen, name=f"Ch {channel}")
            self.plot_items[channel] = curve
            self.display.addItem(curve)

        # Update statistics labels
        self.update_stats_labels()

    def update_stats_labels(self):
        """Update the statistics labels for current channels"""
        # Clear old layout
        layout = self.stats_widget.layout()
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Create new labels
        self.stats_labels = {}
        for ch in self.channels:
            label = QLabel(f"Ch{ch}: 0 events")
            self.stats_labels[ch] = label
            layout.addWidget(label)

        layout.addStretch()

    # def get_channel_statistics(self):
    #     """Get statistics for all channels"""
    #     stats = {}
    #     for channel in self.channels:
    #         event_count = len(self.energy_data[channel])
    #         if event_count > 0:
    #             energies = list(self.energy_data[channel])
    #             stats[channel] = {
    #                 "count": event_count,
    #                 "mean": np.mean(energies),
    #                 "std": np.std(energies),
    #                 "min": np.min(energies),
    #                 "max": np.max(energies),
    #             }
    #         else:
    #             stats[channel] = {
    #                 "count": 0,
    #                 "mean": 0,
    #                 "std": 0,
    #                 "min": 0,
    #                 "max": 0,
    #             }
    #     return stats
