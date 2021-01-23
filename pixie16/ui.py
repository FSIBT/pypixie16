"""UI elements for the binary file browser"""

from collections import Counter, defaultdict
from pathlib import Path
import sys
from typing import List

from PyQt5.QtCore import QAbstractTableModel, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QIcon, QIntValidator
from PyQt5.QtWidgets import (
    QApplication,
    QGridLayout,
    QComboBox,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QFileDialog,
    QHBoxLayout,
    QTableView,
    QSizePolicy,
    QVBoxLayout,
    QLabel,
    QWidget,
    QPushButton,
    QTabWidget,
    QAction,
    QStyle,
    QCommonStyle,
)

from fast_histogram import histogram1d
import matplotlib.pyplot as plt
from matplotlib import cm
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import numpy as np

import pixie16


class LabelAndIntNumber(QWidget):
    """A generic Int input widget in combination with a QLabel."""

    def __init__(self, label: str, value: int = 1, name=None) -> None:
        super().__init__()
        if name is None:
            self.name = label
        else:
            self.name = name

        self.box = QHBoxLayout()

        self.label = QLabel(label)
        self.number = QLineEdit()
        self.validator = QIntValidator(1, 500_000)
        self.number.setValidator(self.validator)

        self.box.addWidget(self.label)
        self.box.addWidget(self.number)

        self.setLayout(self.box)

        self.value = value

    @property
    def value(self) -> int:
        return int(self.number.text())

    @value.setter
    def value(self, value):
        self.number.setText(str(int(value)))


class BinaryDataModel(QAbstractTableModel):
    """Maps to a list of pixie16.read.Event data.

    E.g. data from a list mode run of the pixie16.

    """

    def __init__(self, data):
        super().__init__()
        self._data = data
        self.header = pixie16.read.Event._fields
        self.icon_true = QCommonStyle().standardIcon(QStyle.SP_DialogApplyButton)
        self.icon_false = QCommonStyle().standardIcon(QStyle.SP_DialogCancelButton)

    def icon_return(self, value):
        if value:
            return self.icon_true
        return self.icon_false

    def data(self, index, role):
        """Return the data.

        For some True/False data, we display an icon instead. To do
        this, we return no data in DisplayRole, but an icon for
        DecorationRole.

        """
        column = index.column()
        row = index.row()

        if role == Qt.DisplayRole:
            if self.header[column] in [
                "trace",
                "CFD_error",
                "pileup",
                "trace_flag",
            ]:
                return None
            return str(self._data[row][column])
        if role == Qt.DecorationRole:
            if self.header[index.column()] == "trace":
                return self.icon_return(len(self._data[row][column]))
            if self.header[index.column()] in ["CFD_error", "pileup", "trace_flag"]:
                return self.icon_return(not self._data[row][column])

    def rowCount(self, index):
        return len(self._data)

    def columnCount(self, index):
        return len(self.header)

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return self.header[section].title()


class ChannelSelect(QHBoxLayout):
    """Horizontal list of buttons that can be changed during runtime."""

    def __init__(self, main):
        super().__init__()
        self.channels = []
        self.main = main

    def clear_channels(self):
        while self.count():
            item = self.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def add_channels(self):
        self.addWidget(QLabel("Show/Hide:"))
        for channel in self.main.channels:
            tmp = QPushButton(f"Ch {channel}")
            tmp.setCheckable(True)
            tmp.toggle()
            tmp.clicked.connect(
                lambda state, channel=channel, widget=tmp: self.main.click_channel(
                    channel, widget
                )
            )

            self.channels.append(tmp)
            self.addWidget(tmp)
            # by default show all channels
            if channel not in self.main.selected_channels:
                self.main.selected_channels.append(channel)

        tmp = QPushButton("All")
        tmp.setCheckable(True)
        tmp.toggle()
        tmp.clicked.connect(
            lambda state, channel, widget=tmp: self.main.click_channel("all", widget)
        )

        self.channels.append(tmp)
        self.addWidget(tmp)

    def update_button_status(self):
        for w, channel in zip(self.channels, self.main.channels):
            if not w.isChecked() and channel in self.main.selected_channels:
                w.toggle()
            if w.isChecked() and channel not in self.main.selected_channels:
                w.toggle()


class MyNavigationToolbar(NavigationToolbar):
    """Only display the buttons we need"""

    toolitems = [
        t
        for t in NavigationToolbar.toolitems
        if t[0] in ("Home", "Back", "Forward", "Pan", "Zoom", "Save")
    ]


class Plot(QWidget):
    """A Widget with a matplotlib figure and the navigation toolbar already included.

    We already create a figure and single axis to plot on.

    """

    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self.update = True  # do we need to update when switching tabs?

        self.fig = plt.figure()
        self.axes = self.fig.subplots()
        self.plot = FigureCanvas(self.fig)
        self.plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.nav = MyNavigationToolbar(self.plot, self, coordinates=False)
        self.nav.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.vbox = QVBoxLayout()
        self.vbox.addWidget(self.nav)
        self.vbox.addWidget(self.plot)

        self.setLayout(self.vbox)


class VStack(QWidget):
    """Stack of LabelAndIntNumber.

    Helper class to make it easier to create a VBoxLayout of
    LabelAndIntNumber Widgets and to connect a callback.

    """

    def __init__(self, widgets: List[LabelAndIntNumber], callback=None):
        super().__init__()
        self.widgets = widgets

        self.box = QVBoxLayout()

        for w in widgets:
            self.box.addWidget(w)
            if callback:
                w.number.editingFinished.connect(callback)
        self.setLayout(self.box)

    @property
    def value(self):
        return {w.name: w.value for w in self.widgets}


class FastTrigger(QWidget):
    """Create all kind of traces that are calculated on the FPGA."""

    def __init__(self, main):
        super().__init__()
        self.main = main

        self.buttons = QHBoxLayout()
        self.buttons_widgets = []
        self.plot_names = ["traces", "fast trigger", "CFD", "energy"]
        self.buttons.addWidget(QLabel("Show/Hide:"))
        for i in self.plot_names:
            tmp = QPushButton(i)
            tmp.setCheckable(True)
            tmp.toggle()
            tmp.clicked.connect(
                lambda state, name=i, widget=tmp: self.show_hide(name, widget)
            )
            self.buttons_widgets.append(tmp)
            self.buttons.addWidget(tmp)

        self.grid = QGridLayout()

        self.trace_plot = Plot(main=main)
        self.fast_plot = Plot(main=main)
        self.cfd_plot = Plot(main=main)
        self.energy_plot = Plot(main=main)

        self.data = []
        self.N = 10
        n = np.linspace(0, 1, self.N)
        cmap = cm.get_cmap("jet")
        self.colors = [cmap(i) for i in n]
        self.triggers = np.zeros(self.N)
        self.baseline_index = 1

        self.channel_label = QLabel("Channel")
        self.channels = QComboBox()
        self.channels.currentIndexChanged.connect(self.pick_channel)

        self.ft = VStack(
            [
                LabelAndIntNumber("G"),
                LabelAndIntNumber("L"),
                LabelAndIntNumber("Threshold", value=100),
            ],
            callback=self.update_fasttrigger,
        )

        self.cfd = VStack([LabelAndIntNumber("Threshold", value=100)])

        self.energy = VStack(
            [
                LabelAndIntNumber("G (20 ns steps)", name="G"),
                LabelAndIntNumber("L (20 ns steps)", name="L"),
                LabelAndIntNumber(
                    "Peaksample (10 ns steps)", value=10, name="peaksample"
                ),
                LabelAndIntNumber("decay (ns)", value=28, name="decay"),
            ],
            callback=self.update_energies,
        )

        self.grid.addLayout(self.buttons, 0, 0, 1, 2)

        self.grid.addWidget(self.trace_plot, 1, 0)
        self.grid.addWidget(self.fast_plot, 2, 0)
        self.grid.addWidget(self.cfd_plot, 3, 0)
        self.grid.addWidget(self.energy_plot, 4, 0)

        self.grid.addWidget(self.channels, 1, 1)
        self.grid.addWidget(self.ft, 2, 1)
        self.grid.addWidget(self.cfd, 3, 1)
        self.grid.addWidget(self.energy, 4, 1)

        # todo: add channel select and index select at bottom
        # add L, G, threshold  for CFD and FAST trigger and energy

        # add other tab to show histogram across all events of peaks or CFD

        self.setLayout(self.grid)

    def show_hide(self, name, widget):
        for i, plot_name in enumerate(self.plot_names):
            if name == plot_name:
                for c in [0, 1]:
                    tmp = self.grid.itemAtPosition(1 + i, c).widget()
                    tmp.setHidden(not tmp.isHidden())

    def add_channels(self):
        for c in self.main.channels:
            self.channels.addItem(str(c))

    def update_traces(self, channel):
        """Show the traces in FPGA cycles.

        We pick 10 traces for 10 different energies in the channels,
        plot them and store them, so they can be used for the other
        plots.

        """

        events = [
            d for d in self.main.data if d.channel == channel and len(d.trace) > 0
        ]
        events.sort(key=lambda x: x.energy)
        if not len(events):
            print(f"[Info]: no events for channel {channel} that have traces")
            return
        N = np.linspace(0, 1, self.N) * (len(events) - 1)
        N = sorted({int(n) for n in N})
        self.trace_plot.axes.clear()
        self.data = []
        for i, n in enumerate(N):
            trace = events[n].trace
            L = trace.shape[0]
            trace = trace.reshape(L // 5, 5)
            trace = trace.sum(axis=1)
            self.data.append(trace)
            self.trace_plot.axes.plot(
                trace, color=self.colors[i], drawstyle="steps-mid"
            )
        self.trace_plot.axes.set_title("traces")
        self.trace_plot.axes.set_xlabel("FPGA cycles")
        self.trace_plot.plot.draw()

    def update_fasttrigger(self):
        """Calculate and show the Fast Trigger signal and the threshold.

        We also try to give a good estimmate for the trigger
        threshold, but this is only based on the 10 traces.  For this
        we calcualte the standard derivation and maximum value from
        all traces up to 20 ns before the first calculated trigger.

        Those values will also be used to estimate the baseline for the energy calculation.
        The triggers are also stored, so that they can be re-used for CFD and energy calculation.

        """

        L = self.ft.value["L"]
        G = self.ft.value["G"]
        T = self.ft.value["Threshold"]

        self.triggers *= 0

        self.fast_plot.axes.clear()
        if not self.data:
            return

        length = len(self.data[0])
        result = np.zeros(length - 2 * L - G + 1)

        fast_triggers = []

        for i, trace in enumerate(self.data):
            trace = trace.astype(np.int64)

            for k in range(2 * L + G - 1, length):
                result[k - 2 * L - G + 1] = (
                    trace[k - L + 1 : k + 1].sum()
                    - trace[k - 2 * L - G + 1 : k - L - G + 1].sum()
                )

            fast_triggers.append(result.copy())
            self.fast_plot.axes.plot(
                result, color=self.colors[i], drawstyle="steps-mid"
            )
            for pos, (left, right) in enumerate(zip(result[:-1], result[1:])):
                if left < T and right >= T:
                    self.fast_plot.axes.axvline(pos, color=self.colors[i])
                    if self.triggers[i] == 0:
                        self.triggers[i] = pos
        self.fast_plot.axes.axhline(T, color="black")

        # calc noise level
        first_trigger_offset = int(self.triggers[self.triggers > 0].min() - 10)
        self.baseline_index = first_trigger_offset

        if first_trigger_offset > 0:
            average_noise = [r[:first_trigger_offset].std() for r in fast_triggers]
            average_noise = np.asarray(average_noise).mean()

            max_noise = [r[:first_trigger_offset].max() for r in fast_triggers]
            max_noise = np.asarray(max_noise).max()

            self.fast_plot.axes.set_title(
                f"Fast Trigger: noise level $\\sigma$={average_noise:.1f} "
                f"max={max_noise:.1f} before x={first_trigger_offset}"
            )
        else:
            self.fast_plot.axes.set_title("Fast Trigger: cannot calculate noise level")
            self.baseline_index = 1

        self.fast_plot.axes.set_xlabel("FPGA cycles")
        self.fast_plot.plot.draw()

        self.update_energies()

    def update_energies(self):
        """Calcuate energy distribution as described in Mauricio's thesis.

        The energy calculation here is based on 20 ns time steps so
        currently only SlowFilterRange=1 works.

        """
        L = self.energy.value["L"]
        G = self.energy.value["G"]
        P = self.energy.value["peaksample"]
        q = self.energy.value["decay"]
        q = np.exp(-2 / q)

        self.energy_plot.axes.clear()

        length = len(self.data[0]) // 2
        result = np.zeros(length - 2 * L - G + 1)

        c2 = 1 - q
        c3 = (1 - q) / (1 - q ** (10 * L))
        c1 = c3 * q ** (10 * L)

        baseline = [t[: self.baseline_index].mean() for t in self.data]
        baseline = np.asarray(baseline).mean()

        for i, trace in enumerate(self.data):
            trace = trace.astype(np.int64)

            # for the energy calculation groups of 20 ns (or larger are used)
            trace = trace.reshape(trace.shape[0] // 2, 2)
            trace = trace.sum(axis=1)
            for k in range(2 * L + G - 1, length):
                result[k - 2 * L - G + 1] = (
                    -c1 * trace[k - L + 1 : k + 1].sum()
                    + c2 * trace[k - L - G + 1 : k - G + 1].sum()
                    + c3 * trace[k - 2 * L - G + 1 : k - L - G + 1].sum()
                ) - c2 * baseline * 2 * (L + G)
            self.energy_plot.axes.plot(
                result, color=self.colors[i], drawstyle="steps-mid"
            )
            if self.triggers[i]:
                pos = int(self.triggers[i] + P) // 2
                self.energy_plot.axes.plot(
                    pos, result[pos], "o", color=self.colors[i],
                )
            self.energy_plot.axes.set_xlabel("20 ns cycles")
            self.energy_plot.axes.set_ylabel("Energy")
            self.energy_plot.axes.set_title(f"Energy baseline {baseline:.1f}")
        self.energy_plot.plot.draw()

    def pick_channel(self, i):
        channel = self.main.channels[i]

        self.update_traces(channel)
        self.update_fasttrigger()  # also updated energies


class App(QMainWindow):
    """The main window"""

    def __init__(self, app=None):
        super().__init__()
        self.app = app
        self.filename = None
        self.channels = []
        self.selected_channels = []
        self.data = []

        # set up the window
        self.setWindowTitle("Pixie16 Binary File Browser")

        # file menu
        self.menu = self.menuBar()
        self.file_menu = self.menu.addMenu("File")
        self.help_menu = self.menu.addMenu("Help")

        if sys.platform == "win32":
            QIcon.setThemeSearchPaths([r"c:\Program Files\Git\usr\share\icons"])
        QIcon.setThemeName("Adwaita")

        FileButton = QAction(QIcon.fromTheme("document-open"), "Open", self)
        FileButton.setShortcut("Ctrl+O")
        FileButton.setStatusTip("Open binary file")
        FileButton.triggered.connect(lambda x: self.open_file())
        self.file_menu.addAction(FileButton)

        quitButton = QAction(QIcon.fromTheme("application-exit"), "Exit", self)
        quitButton.setShortcut("Ctrl+Q")
        quitButton.setStatusTip("Quit")
        quitButton.triggered.connect(self.close)
        self.file_menu.addAction(quitButton)

        aboutButton = QAction(QIcon.fromTheme("help-about"), "About", self)
        aboutButton.setStatusTip("About")
        aboutButton.triggered.connect(self.about)
        self.help_menu.addAction(aboutButton)

        self.main_widget = QWidget(self)
        self.main_window = QVBoxLayout()

        self.info_bar = QLabel()
        self.info_bar.setTextInteractionFlags(Qt.TextSelectableByMouse)

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
                self, "Open file", "e:\\ROOTS", "Binary files (*.bin)"
            )
        else:
            self.filename = filename

        # check if cancel was hit in QFileDialog
        if self.filename == "":
            self.filename = None
            return

        self.filename = Path(self.filename)
        self.data = list(
            pixie16.read.read_list_mode_data(self.filename, keep_trace=True)
        )
        self.parse_data()

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
        self.channels = sorted(set(x.channel for x in self.data))

        self.data = sorted(self.data, key=lambda x: x.timestamp)
        self.model = BinaryDataModel(self.data)
        self.dataview.setModel(self.model)

        self.fasttrigger.add_channels()

        self.channel_select.clear_channels()
        self.channel_select.add_channels()

    def tab_change(self, i):
        if not self.data:
            return

        indexes = self.dataview.selectionModel().selectedRows()
        if i == 1:  # plot traces
            self.traces.fig.clear()
            self.traces.plot.draw()
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
                pos = selected_channels.index(channel)
                self.traces.axes[pos].plot(self.data[row].trace)
            for i, channel in enumerate(selected_channels):
                self.traces.axes[i].set_title(f"channel {channel}")
            self.traces.fig.tight_layout()
            self.traces.plot.draw()
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
                self.mca.plot.draw()
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

    def about(self):
        """Print some help that is useful for debugging"""
        pyversion = ".".join([str(i) for i in sys.version_info])
        QMessageBox.about(
            self,
            "About",
            "Pixie16 binary Browser\n\n"
            + f"python-version: {pyversion}\n"
            + f"pixie16-version: {pixie16.__version__}",
        )
