from pathlib import Path

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction, QFileDialog, QVBoxLayout, QWidget

import pixie16

from ..widgets import BaseApp
from .main_widget import CoincidencePlot


class CoincidenceApp(BaseApp):
    """An app that display arbitrary fast trigger positions and all coincidence signals that result.

    It also includes the internal delay from the calculation of the coincidences (added to the validation window).
    """

    def __init__(self, app=None):
        super().__init__(name="Pixie16 Coincidence Visualizer", app=app)

        self.settings_filename = None
        self.settings = None
        self.channels = [0, 1, 2]

        FileButton = QAction(QIcon.fromTheme("document-open"), "Open", self)
        FileButton.setShortcut("Ctrl+O")
        FileButton.setStatusTip("Open settings file")
        FileButton.triggered.connect(lambda x: self.open_file())
        self.file_menu.insertAction(self.file_menu.actions()[0], FileButton)

        self.main_widget = QWidget(self)
        self.vbox = QVBoxLayout()

        self.data = CoincidencePlot(main=self)

        self.info_bar.setText(
            "Change values on the right or click on the graph to change the position of the fast trigger location."
        )

        self.vbox.addLayout(self.data)
        self.vbox.addWidget(self.info_bar)

        self.main_widget.setLayout(self.vbox)
        self.main_widget.setFocus()

        self.setCentralWidget(self.main_widget)

        self.show()

    def open_file(self, filename=None) -> None:
        if filename is None or not isinstance(filename, (str, Path)):
            self.settings_filename, _ = QFileDialog.getOpenFileName(
                self, "Open file", str(self.data_path), "Settings files (*.set)"
            )
        else:
            self.settings_filename = filename

        # check if cancel was hit in QFileDialog
        if self.settings_filename == "":
            self.settings_filename = None
            return

        self.settings_filename = Path(self.settings_filename)
        self.settings = pixie16.read.load_settings(self.settings_filename, 0)

        channels = [i for i, x in enumerate(self.settings.MultiplicityMaskL) if x != 0]
        if len(channels) < 1:
            print("[Warning] no coincidence setup detected, not loading settings")
            return

        # get all channels that are involved
        all_channels = []
        for c in channels:
            tmp = self.settings.MultiplicityMaskL[c]
            tmp = f"{tmp:016b}"
            for i, n in enumerate(reversed(tmp)):
                if int(n):
                    all_channels.append(i)
        self.channels = list(set(all_channels))
        self.data.multiplicity = [
            self.settings.MultiplicityMaskL[c] for c in self.channels
        ]

        self.data.channels = self.channels

        self.data.update_channels()

        for i, c in enumerate(self.channels):
            values = {
                "Trigger Delay": self.settings.FtrigoutDelay[c],
                "Trigger Stretch": self.settings.FastTrigBackLen[c],
                "Validation Delay": self.settings.ExternDelayLen[c],
                "Validation Stretch": self.settings.ChanTrigStretch[c],
            }
            self.data.channel_widgets[i].vstack.value = values
