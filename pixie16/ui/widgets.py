from pathlib import Path
import sys
from typing import List

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QIntValidator
from PyQt5.QtWidgets import (
    QAction,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

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


class VStack(QVBoxLayout):
    """Stack of LabelAndIntNumber.

    Helper class to make it easier to create a VBoxLayout of
    LabelAndIntNumber Widgets and to connect a callback.

    """

    def __init__(self, widgets: List[LabelAndIntNumber], callback=None):
        super().__init__()
        self.widgets = widgets

        for w in widgets:
            self.addWidget(w)
            if callback:
                w.number.editingFinished.connect(callback)

    @property
    def value(self):
        return {w.name: w.value for w in self.widgets}

    @value.setter
    def value(self, value_dict):
        for k, v in value_dict.items():
            for w in self.widgets:
                if w.name == k:
                    w.value = v
                    break

    def delete(self):
        for w in self.widgets:
            w.deleteLater()


class BaseApp(QMainWindow):
    """Base class for pypixie16 QT apps.

    Sets up the main window, the title, a menubar and an info_bar.
    """

    def __init__(self, name="", app=None):
        super().__init__()
        self.app = app
        self.name = name
        self.data_path = Path.home()

        if sys.platform == "win32":
            QIcon.setThemeSearchPaths([r"c:\Program Files\Git\usr\share\icons"])

        QIcon.setThemeName("Adwaita")

        # set up the window
        self.setWindowTitle(self.name)

        # file menu
        self.menu = self.menuBar()
        self.file_menu = self.menu.addMenu("File")
        self.help_menu = self.menu.addMenu("Help")

        quitButton = QAction(QIcon.fromTheme("application-exit"), "Exit", self)
        quitButton.setShortcut("Ctrl+Q")
        quitButton.setStatusTip("Quit")
        quitButton.triggered.connect(self.close)
        self.file_menu.addAction(quitButton)

        aboutButton = QAction(QIcon.fromTheme("help-about"), "About", self)
        aboutButton.setStatusTip("About")
        aboutButton.triggered.connect(self.about)
        self.help_menu.addAction(aboutButton)

        self.info_bar = QLabel()
        self.info_bar.setTextInteractionFlags(Qt.TextSelectableByMouse)

    def about(self):
        """Print some help that is useful for debugging"""
        pyversion = ".".join([str(i) for i in sys.version_info])
        QMessageBox.about(
            self,
            "About",
            f"{self.name}\n\n"
            + f"python-version: {pyversion}\n"
            + f"pixie16-version: {pixie16.__version__}",
        )
