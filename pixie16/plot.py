import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from PyQt5.QtWidgets import (
    QMainWindow,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class MyNavigationToolbar(NavigationToolbar):
    """Only display the buttons we need"""

    toolitems = [
        t
        for t in NavigationToolbar.toolitems
        if t[0] in ("Home", "Back", "Forward", "Pan", "Zoom", "Save")
    ]


class Plot(QWidget):
    """A Widget with a matplotlib figure and and (optional) navigation toolbar.

    We already create a figure and single axis to plot on.

    """

    def __init__(self, main: QMainWindow, with_navbar: bool = True) -> None:
        super().__init__()
        self.main = main
        self.update = True  # do we need to update when switching tabs?

        self.fig = plt.figure()
        self.axes = self.fig.subplots()
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.vbox = QVBoxLayout()

        if with_navbar:
            self.nav = MyNavigationToolbar(self.canvas, self, coordinates=False)
            self.nav.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.vbox.addWidget(self.nav)

        self.vbox.addWidget(self.canvas)

        self.setLayout(self.vbox)


class PlotOnly(Plot):
    """A matplotlib area with a single axes and without borders and navbar.

    Also added shortcuts to clear the plot, add text, and plot data using steps.
    """

    def __init__(self, main: QMainWindow):
        super().__init__(main, with_navbar=False)

        self.axes.axis("off")

    def clear(self):
        self.axes.clear()
        self.axes.axis("off")

    def plot(self, x, y, **kwargs):
        kwargs["drawstyle"] = "steps-mid"
        self.axes.plot(x, y, **kwargs)

    def text(self, x, y, text, **kwargs):
        self.axes.text(x, y, text, **kwargs)
