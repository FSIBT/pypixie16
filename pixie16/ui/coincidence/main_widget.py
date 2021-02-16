import numpy as np

from PyQt5.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QMainWindow,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..widgets import LabelAndIntNumber, VStack
from .coincidence_plots import PlotCoincidenceTraces


class CoincidencePlot(QHBoxLayout):
    def __init__(self, main: QMainWindow):
        super().__init__()

        self.main = main

        # units in FPGA cycles
        self.maximum = 200
        self.channels = [0, 1, 2]
        self.N = len(self.channels)
        self.channel_widgets = []
        self.multiplicity = [
            0b0000_0000_0000_0000_0111,
            0b0000_0000_0000_0000_0011,
            0b0000_0000_0000_0000_0101,
        ]

        self.cursor_select = False

        self.plot_area = PlotCoincidenceTraces(
            main=self.main, N=self.N, maximum=self.maximum
        )

        self.plot_area.fig.canvas.mpl_connect("button_press_event", self.onclick)
        self.plot_area.fig.canvas.mpl_connect("key_press_event", self.onkey)

        self.scroll = QScrollArea()
        self.vvbox = QWidget()
        self.vbox = QVBoxLayout()
        self.update_channels()
        self.vvbox.setLayout(self.vbox)
        self.scroll.setWidget(self.vvbox)

        self.addWidget(self.plot_area)
        self.addWidget(self.scroll)

        self.draw()

    def update_channels(self):

        while self.vbox.count():
            item = self.vbox.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.vstack.delete()
                widget.vstack.deleteLater()
                widget.deleteLater()

        self.N = len(self.channels)
        self.plot_area.N = self.N
        self.plot_area.calc_positions()

        self.position = [0] * self.N

        self.trigger_delay = [10] * self.N
        self.trigger_stretch = [10] * self.N

        self.coincidence_position = [0] * self.N

        self.internal_delay = 10
        self.validation_delay = [10] * self.N
        self.validation_stretch = [10] * self.N

        self.FT = np.zeros((self.N, self.maximum))
        self.window = np.zeros((self.N, self.maximum))
        self.coincidence = np.ones((self.N, self.maximum))
        self.validation = np.zeros((self.N, self.maximum))
        self.delayed_FT = np.zeros((self.N, self.maximum))

        self.channel_widgets = []
        for c in self.channels:
            inputs = []
            inputs.append(LabelAndIntNumber("Trigger Delay"))
            inputs.append(LabelAndIntNumber("Trigger Stretch"))
            inputs.append(LabelAndIntNumber("Validation Delay"))
            inputs.append(LabelAndIntNumber("Validation Stretch"))
            inputs.append(LabelAndIntNumber("Multiplicity"))

            tmp = VStack(inputs, callback=self.update)
            groupbox = QGroupBox(f"Channel {c}")
            groupbox.vstack = tmp
            groupbox.setLayout(tmp)

            self.channel_widgets.append(groupbox)

        for i in self.channel_widgets:
            self.vbox.addWidget(i)

        self.draw()

    def onclick(self, event):
        y = event.ydata
        if y is None:
            return

        x = int(event.xdata)

        i = self.plot_area.get_y_range(y)
        if i is not None:
            self.position[i] = x

        self.draw()

    def onkey(self, event):
        y = event.ydata
        if y is None:
            return

        x = int(event.xdata)

        i = self.plot_area.get_y_range(y)
        if i is not None:
            if event.key == "left":
                self.position[i] -= 1
            if event.key == "right":
                self.position[i] += 1
            self.position[i] = min(max(self.position[i], 0), self.maximum)

        self.draw()

    def update(self):
        for i, box in enumerate(self.channel_widgets):
            values = box.vstack.value
            self.trigger_delay[i] = values[f"Trigger Delay"]
            self.trigger_stretch[i] = values[f"Trigger Stretch"]
            self.validation_delay[i] = values[f"Validation Delay"]
            self.validation_stretch[i] = values[f"Validation Stretch"]

        self.draw()

    def draw(self):
        self.plot_area.clear()

        self.FT *= 0
        self.window *= 0
        self.coincidence *= 0
        self.delayed_FT *= 0
        self.validation *= 0

        for i in range(self.N):
            self.FT[i, self.position[i]] = 1
            left = min(self.position[i] + self.trigger_delay[i], self.maximum)
            right = min(
                self.position[i] + self.trigger_delay[i] + self.trigger_stretch[i],
                self.maximum,
            )
            self.window[i, left:right] = 1
            # todo use mask
        for i in range(self.N):
            multiplicity = self.multiplicity[i]
            multiplicity = f"{multiplicity:016b}"
            # list of channels
            multiplicity = [i for i, c in enumerate(reversed(multiplicity)) if int(c)]
            for j, c in enumerate(self.channels):
                if c in multiplicity:
                    self.coincidence[i] += self.window[j]
            self.coincidence[i] = self.coincidence[i] >= 2
        self.coincidence_position = [trace.argmax() for trace in self.coincidence]
        for i in range(self.N):
            if self.coincidence_position[i] == 0:
                self.validation[i] *= 0
            else:
                left = min(
                    self.coincidence_position[i] + self.internal_delay, self.maximum
                )
                right = min(
                    self.coincidence_position[i]
                    + self.internal_delay
                    + self.validation_stretch[i],
                    self.maximum,
                )

                self.validation[i, left:right] = 1
            self.delayed_FT[i, self.position[i] + self.validation_delay[i]] = 1

        # print the fast trigger and the delayed and stretch version
        self.plot_area.plot_titles()

        for i, c in enumerate(self.channels):
            self.plot_area.plot_fast_trigger_and_coinc_window(
                self.FT[i], self.window[i], i, c
            )

            # print the coincidence trigger
        for i, c in enumerate(self.channels):
            self.plot_area.plot_coincidence(self.coincidence[i], i, c)

        # print the validation signals
        for i, c in enumerate(self.channels):
            self.plot_area.plot_validation(
                self.coincidence[i],
                self.validation[i],
                self.FT[i],
                self.delayed_FT[i],
                i,
                c,
            )

        self.plot_area.canvas.draw()
