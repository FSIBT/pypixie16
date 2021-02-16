import numpy as np

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMainWindow

from ..plot import PlotOnly


class PlotCoincidenceTraces(PlotOnly):
    """Create the plot of fast triggers, delayed triggers, coincidences, validations, etc.

    Devides the axes in several plotting areas: Fast triggers, coincidences, validation.

    Each area is divides by `large_gap` and the plots in each area are divided by `gap`.

    The class provides functions to make plotting easier.

    """

    gap = 0.2
    large_gap = 1.6

    def __init__(self, main: QMainWindow, N, maximum):
        super().__init__(main)
        self.N = N

        self.maximum = maximum

        self.cursor_select = False
        self.fig.canvas.mpl_connect("motion_notify_event", self.onmove)
        # need the following to be able to listen to key events
        self.fig.canvas.mpl_connect(
            "axes_enter_event", lambda x: self.fig.canvas.setFocus()
        )

        self.calc_positions()

    def calc_positions(self):
        height_validation = 3 * (1 + self.gap) * self.N - self.gap
        height_coincidence = (1 + self.gap) * self.N
        height_fast_trigger = 2 * (1 + self.gap) * self.N - self.gap

        self.position_validation = height_validation
        self.position_coincidence = (
            self.position_validation + self.large_gap + height_coincidence
        )
        self.position_fast_trigger = (
            self.position_coincidence + self.large_gap + height_fast_trigger
        )

        self.FT_yrange = [[0, 1]] * self.N  # we set the correct values while plotting
        self.x = np.arange(0, self.maximum, 1)

    def get_y_range(self, y):
        for i, [down, up] in enumerate(self.FT_yrange):
            if down < y < up:
                return i
        return

    def in_y_range(self, y):
        for down, up in self.FT_yrange:
            if down < y < up:
                return True
        return False

    def in_x_range(self, x):
        return 0 < x < self.maximum

    def onmove(self, event):
        y = event.ydata
        if y is None:
            if self.cursor_select:
                QApplication.restoreOverrideCursor()
                self.cursor_select = False
            return

        x = int(event.xdata)

        if self.in_x_range(x) and self.in_y_range(y):
            if not self.cursor_select:
                QApplication.setOverrideCursor(Qt.CrossCursor)
                self.cursor_select = True
        else:
            if self.cursor_select:
                QApplication.restoreOverrideCursor()
                self.cursor_select = False

    def plot_titles(self):
        self.text(-40, self.position_fast_trigger + 1.2, "Fast Triggers and Delays")
        self.text(-40, self.position_coincidence + 1.2, "Coincidence Trigger")
        self.text(-40, self.position_validation + 1.2, "Validation")

    def plot_fast_trigger_and_coinc_window(self, ft, window, i, channel):
        position = self.position_fast_trigger - i * 2 * (1 + self.gap)

        self.FT_yrange[i] = [position, position + 1]

        self.plot(self.x, ft + position, color="black")
        self.text(-30, position, f"Ch {channel}")
        position -= self.gap + 1
        self.plot(self.x, window + position, color="orange")

    def plot_coincidence(self, y, i, channel):
        position = self.position_coincidence - i * (1 + self.gap)

        self.plot(self.x, y + position, color="blue")
        self.text(-30, position, f"Ch {channel}")

    def plot_validation(self, coinc, validation, ft, delayed, i, channel):
        position = self.position_validation - i * 3 * (1 + self.gap)

        self.plot(self.x, coinc + position, color="blue")
        position -= self.gap + 1
        self.plot(self.x, validation + position, color="green")
        validated = np.sum(delayed * validation)
        if validated:
            color = "green"
        else:
            color = "red"
        self.text(-30, position, f"Ch {channel}", backgroundcolor=color)
        position -= self.gap + 1
        self.plot(self.x, ft + position, color="black")
        self.plot(self.x, delayed + position, color="red")
