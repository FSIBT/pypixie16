"""
Real-time spectrum plotter for PIXIE-16 data.
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
    QSplitter,
    QWidget,
)
from .channel_controls import ChannelDisplayControls

import logging

logger = logging.getLogger(__name__)


class ContinuousSpectrumPlotter(QGroupBox):
    def __init__(
        self,
        app,
        instrument_name: str,
        display_name: str = "PIXIE Energy Spectra",
        channels: list[int] = [4, 5, 9],
        channel_names: list[str] = None,
        energy_range: tuple = (0, 3000),
        bins: int = 1000,
        bkg_color: str = "w",
        update_hooks: list = None,
    ):
        super().__init__(display_name)

        self.app = app
        self.instrument = instrument_name
        self.channels = channels
        self.channel_names = channel_names or [f"Ch{ch}" for ch in channels]
        self.energy_range = energy_range
        self.bins = bins
        self.update_hooks = update_hooks or []
        self.display_channels = self.channels.copy()
        self.channel_controls = None

        self.energy_data = defaultdict(lambda: deque(maxlen=50000))
        self.last_update = time.time()
        self.update_rate = 0.5  # seconds

        channel_colors = [
            (3, 7, 252),  # Blue
            (252, 3, 3),  # Red
            (0, 128, 0),  # Green
            (128, 128, 128),  # Gray
            (255, 192, 203),  # Pink
            (255, 20, 147),  # Deep Pink
            (75, 0, 130),  # Indigo
            (255, 105, 180),  # Hot Pink
            (0, 255, 127),  # Spring Green
            (246, 190, 0),  # Yellow
            (255, 0, 255),  # Magenta
            (0, 255, 255),  # Cyan
            (128, 0, 128),  # Purple
            (255, 165, 0),  # Orange
            (128, 128, 0),  # Olive
            (0, 0, 128),  # Navy
        ]

        self.setup_ui(bkg_color, channel_colors)
        self.setup_continuous_reading()

    def setup_ui(self, bkg_color, channel_colors):
        main_layout = QVBoxLayout()

        self.display = pg.PlotWidget()
        self.display.setBackground(bkg_color)
        self.display.setLabel("left", "Counts")
        self.display.setLabel("bottom", "Energy", "keV")
        self.display.setTitle("PIXIE-16 Energy Spectra")
        self.display.showGrid(x=True, y=True)
        self.display.setMenuEnabled(enableMenu=True)

        self.plot_items = {}
        for i, channel in enumerate(self.channels):
            color = channel_colors[i % len(channel_colors)]
            pen = pg.mkPen(color=color, width=2)
            curve = pg.PlotCurveItem(pen=pen, name=self.channel_names[i])
            self.plot_items[channel] = curve
            self.display.addItem(curve)

        main_layout.addWidget(self.display)

        self.create_control_widgets()
        control_group = self.create_control_group()
        main_layout.addWidget(control_group)

        self.setLayout(main_layout)

    def create_control_widgets(self):
        self.energy_min_label = QLabel("Energy Min (keV):")
        self.energy_min_spin = QDoubleSpinBox()
        self.energy_min_spin.setRange(0, 10000)
        self.energy_min_spin.setValue(self.energy_range[0])
        self.energy_min_spin.valueChanged.connect(self.update_energy_range)

        self.energy_max_label = QLabel("Energy Max (keV):")
        self.energy_max_spin = QDoubleSpinBox()
        self.energy_max_spin.setRange(0, 10000)
        self.energy_max_spin.setValue(self.energy_range[1])
        self.energy_max_spin.valueChanged.connect(self.update_energy_range)

        self.bins_label = QLabel("Bins:")
        self.bins_spin = QSpinBox()
        self.bins_spin.setRange(10, 10000)
        self.bins_spin.setValue(self.bins)
        self.bins_spin.valueChanged.connect(self.update_bins)

        self.log_scale_cb = QCheckBox("Log Scale")
        self.log_scale_cb.toggled.connect(self.toggle_log_scale)

        self.auto_scale_cb = QCheckBox("Auto Scale")
        self.auto_scale_cb.setChecked(True)
        self.auto_scale_cb.toggled.connect(self.toggle_auto_scale)

        self.stats_labels = {}
        for ch in self.channels:
            label = QLabel(f"Ch{ch}: 0 events")
            self.stats_labels[ch] = label

    def save_data(self):
        try:
            from PyQt6.QtWidgets import QFileDialog
            import json

            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Spectrum Data",
                f"pixie_spectra_{int(time.time())}.json",
                "JSON Files (*.json);;All Files (*)",
            )

            if file_path:
                data_to_save = {}
                for channel in self.channels:
                    if (
                        hasattr(self.spectrum_tab, "energy_data")
                        and channel in self.spectrum_tab.energy_data
                    ):
                        data_to_save[f"channel_{channel}"] = list(
                            self.spectrum_tab.energy_data[channel]
                        )

                data_to_save["metadata"] = {
                    "timestamp": time.time(),
                    "channels": self.channels,
                    "dummy_mode": self.dummy_mode,
                    "total_events": sum(
                        len(data)
                        for data in data_to_save.values()
                        if isinstance(data, list)
                    ),
                }

                with open(file_path, "w") as f:
                    json.dump(data_to_save, f, indent=2)

                self.info_bar.setText(f"Data saved to {file_path}")

        except Exception as e:
            print(f"Failed to save data: {str(e)}")

    def create_control_group(self):
        group = QGroupBox("Plot Controls")
        layout = QGridLayout()
        row = 0
        layout.addWidget(self.energy_min_label, row, 0)
        layout.addWidget(self.energy_min_spin, row, 1)
        layout.addWidget(self.energy_max_label, row, 2)
        layout.addWidget(self.energy_max_spin, row, 3)

        row += 1
        layout.addWidget(self.bins_label, row, 0)
        layout.addWidget(self.bins_spin, row, 1)
        layout.addWidget(self.log_scale_cb, row, 2)
        layout.addWidget(self.auto_scale_cb, row, 3)

        row += 1
        stats_layout = QHBoxLayout()
        for ch, label in self.stats_labels.items():
            stats_layout.addWidget(label)
        layout.addLayout(stats_layout, row, 0, 1, 4)

        group.setLayout(layout)
        return group

    def setup_continuous_reading(self):
        for channel in self.display_channels:
            param_name = f"CH{channel}_ENERGY_DATA"

            if self.app:
                self.app.add_auto_update_instrument_parameter(
                    self.instrument, param_name
                )

                self.app.add_hook(
                    self.instrument,
                    param_name,
                    "post_read_hooks",
                    self.create_energy_hook(channel),
                )

        self.update_timer = QtCore.QTimer()
        self.update_timer.timeout.connect(self.update_display)
        self.update_timer.start(int(self.update_rate * 1000))

    def create_energy_hook(self, channel):
        def energy_hook(energy_data_string):
            return self.process_energy_data(channel, energy_data_string)

        return energy_hook

    def process_energy_data(self, channel, energy_data_string):
        if energy_data_string is None:
            return energy_data_string

        try:
            if isinstance(energy_data_string, str):
                energy_list = json.loads(energy_data_string)
            else:
                energy_list = energy_data_string

            for hook in self.update_hooks:
                try:
                    energy_list = hook(self, channel, energy_list)
                except Exception as e:
                    logger.warning(f"Update hook failed: {e}")

            if isinstance(energy_list, list):
                for energy in energy_list:
                    self.energy_data[channel].append(energy)

        except Exception as e:
            logger.warning(f"Failed to process energy data for channel {channel}: {e}")

        return energy_data_string

    def update_display(self):
        current_time = time.time()
        if current_time - self.last_update < self.update_rate:
            return

        self.last_update = current_time

        for channel in self.channels:
            if channel not in self.energy_data or len(self.energy_data[channel]) == 0:
                if channel in self.stats_labels:
                    self.stats_labels[channel].setText(f"Ch{channel}: 0 events")
                self.plot_items[channel].setData([], [])
                continue

            energies = list(self.energy_data[channel])

            if channel in self.stats_labels:
                self.stats_labels[channel].setText(
                    f"Ch{channel}: {len(energies)} events"
                )

            if channel in self.display_channels:
                counts, bin_edges = np.histogram(
                    energies, bins=self.bins, range=self.energy_range
                )

                bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
                if self.log_scale_cb.isChecked():
                    counts = np.maximum(counts, 1)
                    self.plot_items[channel].setData(bin_centers, np.log10(counts))
                else:
                    self.plot_items[channel].setData(bin_centers, counts)
            else:
                self.plot_items[channel].setData([], [])

        if self.auto_scale_cb.isChecked():
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
        print(f"Spectrum plotter: setting display channels to {channels}")
        self.display_channels = channels

        for channel in self.channels:
            if channel in self.display_channels:
                print(f"Showing channel {channel}")
            else:
                print(f"Hiding channel {channel}")
                self.plot_items[channel].setData([], [])
