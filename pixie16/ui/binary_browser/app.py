from collections import Counter, defaultdict
from pathlib import Path

from fast_histogram import histogram1d
import numpy as np
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QAction,
    QFileDialog,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import pixie16

from ..widgets import BaseApp
from ..helper import busy_cursor
from ..plot import Plot
from .channel_select import ChannelSelect
from .fast_trigger import FastTrigger
from .data_model import BinaryDataModel


class BinaryApp(BaseApp):
    """The main window"""

    def __init__(self, app=None):
        super().__init__(name="Pixie16 Binary File Browser", app=app)

        self.filename = None
        self.channels = []
        self.selected_channels = []
        self.data = []
        self.model = None

        FileButton = QAction(QIcon.fromTheme("document-open"), "Open", self)
        FileButton.setShortcut("Ctrl+O")
        FileButton.setStatusTip("Open binary file")
        FileButton.triggered.connect(lambda x: self.open_file())
        self.file_menu.insertAction(self.file_menu.actions()[0], FileButton)

        self.main_widget = QWidget(self)
        self.main_window = QVBoxLayout()

        self.tabs = QTabWidget()

        self.main_window.addWidget(self.tabs)
        self.main_window.addWidget(self.info_bar)

        self.main_widget.setLayout(self.main_window)
        self.main_widget.setFocus()
        self.setCentralWidget(self.main_widget)

        self.datatab = QWidget()
        self.datatab_layout = QVBoxLayout()

        self.channel_select = ChannelSelect(main=self)

        self.dataview = QTableView()
        self.dataview.setSortingEnabled(True)
        self.dataview.setSelectionBehavior(QTableView.SelectRows)

        self.datatab_layout.addLayout(self.channel_select)
        self.datatab_layout.addWidget(self.dataview)
        self.datatab.setLayout(self.datatab_layout)

        self.traces = Plot(main=self)
        self.mca = Plot(main=self)
        self.fasttrigger = FastTrigger(main=self)

        self.tabs.addTab(self.datatab, "Binary data")
        self.tabs.addTab(self.traces, "Traces")
        self.tabs.addTab(self.mca, "MCA")
        self.tabs.addTab(self.fasttrigger, "Fast Trigger/CFD")

        self.tabs.currentChanged.connect(self.tab_change)

        self.show()

    def open_file(self, filename=None) -> None:
        if filename is None or not isinstance(filename, (str, Path)):
            self.filename, _ = QFileDialog.getOpenFileName(
                self, "Open file", str(self.data_path), "Binary files (*.bin)"
            )
        else:
            self.filename = filename

        # check if cancel was hit in QFileDialog
        if self.filename == "":
            self.filename = None
            return

        self.filename = Path(self.filename)
        with busy_cursor(self.app):
            self.data = list(pixie16.read.read_list_mode_data_as_events(self.filename))
            self.parse_data()
            self.set_data_model()
            self.update_gui()

        # count events per channel
        tmp = Counter([x.channel for x in self.data])
        summary = "  ".join(f"{k}:{v}" for k, v in sorted(tmp.items()))
        gamma_sum = 0
        for ch, cnt in sorted(tmp.items()):
            if ch < 9:
                gamma_sum += cnt
        gamma_sum_str = "".join(f"Gamma events: {gamma_sum}")

        if self.filename:
            self.info_bar.setText(
                f"{self.filename.name}    {summary}    {gamma_sum_str}"
            )

    def parse_data(self):
        self.channels = sorted({x.channel for x in self.data})
        self.data = sorted(self.data, key=lambda x: x.timestamp)

    def set_data_model(self):
        self.model = BinaryDataModel(self.data)
        self.dataview.setModel(self.model)

    def update_gui(self):
        self.fasttrigger.add_channels()

        self.channel_select.clear_channels()
        self.channel_select.add_channels()

    def tab_change(self, i):
        if not self.data:
            return
        if not self.model:
            return

        indexes = self.dataview.selectionModel().selectedRows()
        if i == 1:  # plot traces
            self.traces.fig.clear()
            self.traces.canvas.draw()
            # get list of channels in selections
            selected_channels = [
                self.data[index.row()].channel
                for index in sorted(indexes)
                if not self.dataview.isRowHidden(index.row())
            ]
            # make unique
            selected_channels = list(set(selected_channels))

            if not selected_channels:
                return

            self.traces.fig.clear()
            self.traces.axes = self.traces.fig.subplots(
                nrows=len(selected_channels), sharex=True
            )
            if not isinstance(self.traces.axes, np.ndarray):
                self.traces.axes = np.array([self.traces.axes])
            for index in sorted(indexes):
                row = index.row()
                if self.dataview.isRowHidden(row):
                    continue
                channel = self.data[row].channel
                trigger_pos = selected_channels.index(channel)
                self.traces.axes[trigger_pos].plot(self.data[row].trace)
            for i, channel in enumerate(selected_channels):
                self.traces.axes[i].set_title(f"channel {channel}")
            self.traces.fig.tight_layout()
            self.traces.canvas.draw()
        if i == 2:  # MCA spectra
            if self.mca.update:
                self.mca.fig.clear()
                self.mca.axes = self.mca.fig.subplots(
                    nrows=len(self.channels), sharex=True
                )
                # create list of energies for each channel
                energies = defaultdict(list)
                bins = 512
                rebin_factor = 32 * 1024 / 512
                for d in self.data:
                    energies[d.channel].append(d.energy / rebin_factor)
                X = np.linspace(0, bins - 1, bins)
                for i, [c, ax] in enumerate(zip(self.channels, self.mca.axes)):
                    tmp = histogram1d(energies[c], bins=bins, range=[0, bins - 1])
                    ax.plot(X, tmp)
                    ax.set_ylabel("Counts/bin")
                    ax.set_title(f"Channel {c}")
                ax.set_xlabel("Energy [a.u.]")
                self.mca.fig.tight_layout()
                self.mca.canvas.draw()
                self.mca.update = False

    def click_channel(self, channel, button):
        if channel == "all" and button.isChecked():
            self.selected_channels = self.channels
        elif channel == "all" and not button.isChecked():
            self.selected_channels = []
        else:
            if button.isChecked() and channel not in self.selected_channels:
                self.selected_channels.append(channel)
            elif not button.isChecked() and channel in self.selected_channels:
                self.selected_channels.remove(channel)

        self.channel_select.update_button_status()
        self.update_channel_selection()

    def update_channel_selection(self):
        for i, d in enumerate(self.data):
            if d.channel in self.selected_channels:
                self.dataview.showRow(i)
            else:
                self.dataview.hideRow(i)
