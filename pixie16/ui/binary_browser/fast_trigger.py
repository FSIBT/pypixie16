import numpy as np
from matplotlib import cm
from PyQt5.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)


from ..plot import Plot
from ..widgets import LabelAndIntNumber, VStack
from ...analyze import (
    convert_trace_to_FPGA,
    calculate_fast_filter,
    get_fast_trigger_index,
)


class FastTrigger(QWidget):
    """Create all kind of traces that are calculated on the FPGA."""

    def __init__(self, main):
        super().__init__()
        self.main = main

        self.buttons = QHBoxLayout()
        self.buttons_widgets = []
        self.plot_names = [
            "traces",
            "fast trigger",
            "CFD",
            "energy",
            "energy linearity",
        ]
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
        self.energy_linearity_plot = Plot(main=main)

        self.N = 10
        self.raw_data = np.zeros(self.N)[:, np.newaxis]
        self.data_FPGA = np.zeros(self.N)[:, np.newaxis]
        self.fast_trigger = np.zeros(self.N)[:, np.newaxis]
        # get N colors for plotting
        self.colors = cm.get_cmap("jet")(np.linspace(0, 1, self.N))
        self.triggers = np.zeros(self.N)
        self.baseline_index = 1
        self.energy_values = np.zeros(self.N)

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
                LabelAndIntNumber("Range", name="R"),
                LabelAndIntNumber("G (energy steps)", name="G"),
                LabelAndIntNumber("L (energy steps)", name="L"),
                LabelAndIntNumber(
                    "Peaksample (energy steps)", value=10, name="peaksample"
                ),
                LabelAndIntNumber("decay (ns)", value=28, name="decay"),
            ],
            callback=self.update_energies,
        )

        self.energy_linearity = VStack(
            [LabelAndIntNumber("Integration Length", name="L")],
            callback=self.update_energy_linearity,
        )

        self.grid.addLayout(self.buttons, 0, 0, 1, 2)

        self.grid.addWidget(self.trace_plot, 1, 0)
        self.grid.addWidget(self.fast_plot, 2, 0)
        self.grid.addWidget(self.cfd_plot, 3, 0)
        self.grid.addWidget(self.energy_plot, 4, 0)
        self.grid.addWidget(self.energy_linearity_plot, 5, 0)

        self.grid.addWidget(self.channels, 1, 1)
        self.grid.addLayout(self.ft, 2, 1)
        self.grid.addLayout(self.cfd, 3, 1)
        self.grid.addLayout(self.energy, 4, 1)
        self.grid.addLayout(self.energy_linearity, 5, 1)

        # todo: add channel select and index select at bottom
        # add L, G, threshold  for CFD and FAST trigger and energy

        # add other tab to show histogram across all events of peaks or CFD

        self.setLayout(self.grid)

    def show_hide(self, name, widget):
        for i, plot_name in enumerate(self.plot_names):
            if name == plot_name:
                for c in [0, 1]:
                    tmp = self.grid.itemAtPosition(1 + i, c).widget()
                    if tmp is None:
                        print(f' no items at {i+1} {c} for {name}"')
                        continue
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
        if not len(events):
            print(f"[Info]: no events for channel {channel} that have traces")
            return
        events.sort(key=lambda x: x.energy)

        # pick N events equally spaced in energy sorted event list
        N = np.linspace(0, 1, self.N) * (len(events) - 1)
        N = sorted({int(n) for n in N})

        self.trace_plot.axes.clear()
        self.raw_data = np.array([events[n].trace for n in N])
        self.data_FPGA = convert_trace_to_FPGA(self.raw_data)
        for i, ft in enumerate(self.data_FPGA):
            self.trace_plot.axes.plot(ft, color=self.colors[i], drawstyle="steps-mid")
        self.trace_plot.axes.set_title("traces")
        self.trace_plot.axes.set_xlabel("FPGA cycles")
        self.trace_plot.canvas.draw()

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
        if self.data_FPGA.max() == 0:
            return

        length = len(self.data_FPGA[0])

        self.fast_triggers = calculate_fast_filter(self.raw_data, L=L, G=G)

        self.triggers = get_fast_trigger_index(self.fast_triggers, T)

        # plots traces
        for i, trace in enumerate(self.fast_triggers):
            self.fast_plot.axes.plot(trace, color=self.colors[i], drawstyle="steps-mid")

        # plot triggers
        for i, positions in enumerate(self.triggers):
            for p in positions:
                self.fast_plot.axes.axvline(p, color=self.colors[i])

        # plot threshold
        self.fast_plot.axes.axhline(T, color="black")

        # calc noise level
        try:
            first_trigger_offset = int(min(t[0] for t in self.triggers) - 10)
        except (ValueError, IndexError):
            print(
                "[Warning]: No trigger found, using the first 20% of the trace to estimate baseline",
                flush=True,
            )
            first_trigger_offset = int(length * 0.2)
        self.baseline_index = first_trigger_offset

        if first_trigger_offset > 0:
            average_noise = [r[:first_trigger_offset].std() for r in self.fast_triggers]
            average_noise = np.asarray(average_noise).mean()

            max_noise = [r[:first_trigger_offset].max() for r in self.fast_triggers]
            max_noise = np.asarray(max_noise).max()

            self.fast_plot.axes.set_title(
                f"Fast Trigger: noise level $\\sigma$={average_noise:.1f} "
                f"max={max_noise:.1f} before x={first_trigger_offset}"
            )
        else:
            self.fast_plot.axes.set_title("Fast Trigger: cannot calculate noise level")
            self.baseline_index = 1

        self.fast_plot.axes.set_xlabel("FPGA cycles")
        self.fast_plot.canvas.draw()

        self.update_energies()

    def update_energies(self):
        """Calcuate energy distribution as described in Mauricio's thesis.

        The energy calculation here is based on 20 ns time steps so
        currently only SlowFilterRange=1 works.

        See page 33 of Mauricio's thesis for details.

        Note: the pixie16 multiplies all energies by a factor of 4

        """
        R = self.energy.value["R"]
        L = self.energy.value["L"]
        G = self.energy.value["G"]
        P = self.energy.value["peaksample"]
        q = self.energy.value["decay"]
        q = np.exp(-2 / q)

        self.energy_values *= 0

        self.energy_plot.axes.clear()

        self.slow_filter_range = 2 ** R
        # check how long the trace is, if it is too short, we try to
        # fix it by adding data points at `baseline` value to the
        # trace on the left and right
        length = len(self.data_FPGA[0]) // self.slow_filter_range
        pad_data = False

        if length - 2 * L - G + 1 <= 0:
            print(
                "[Warning]: L, G for energy filter are too large for the supplied trace length and slowfilter range. Padding data",
                flush=True,
            )
            pad_data = True
            pad_length = 2 * (L + G)
            length += 2 * pad_length
        elif length - 2 * L - G + 1 <= 20:
            print(
                "[Warning]: L, G for energy filter are large for the supplied trace length and slowfilter range. Padding data",
                flush=True,
            )
            pad_data = True
            pad_length = L + G
            length += 2 * pad_length

        result = np.zeros(length - 2 * L - G + 1)

        qL = q ** (5 * L * self.slow_filter_range)
        c2 = 1 - q
        c3 = (1 - q) / (1 - qL)
        c1 = c3 * qL

        # self.data is already in FPGA cycles
        baseline = [t[: self.baseline_index].mean() for t in self.data_FPGA]
        # convert to energy cycles
        baseline_pad = np.asarray(baseline).mean() * self.slow_filter_range
        baseline = baseline_pad * (L + G) * 4 * c2

        for i, trace in enumerate(self.data_FPGA):
            # need to convert to avoid overflows in the sums
            trace = trace.astype(np.int64)

            # for the energy calculation groups of 10 ns * 2**slowfilterrange
            # the traces are already in 10ns groups, so we now handle the slowfilterrange
            N = (trace.shape[0] // self.slow_filter_range) * self.slow_filter_range
            trace = trace[:N].reshape(
                trace.shape[0] // self.slow_filter_range, self.slow_filter_range
            )
            trace = trace.sum(axis=1)

            if pad_data:
                pad = np.ones(pad_length) * int(baseline_pad)
                trace = np.concatenate([pad, trace, pad])

            if len(self.triggers[i]):
                # calculate trigger position in new time units
                trigger_pos = (
                    int(self.triggers[i][0]) // self.slow_filter_range - 2 * L - G + P
                )
                if pad_data:
                    trigger_pos += pad_length

            for k in range(2 * L + G - 1, length):
                S1 = trace[k - 2 * L - G + 1 : k - L - G + 1].sum()
                S2 = trace[k - L - G + 1 : k - L + 1].sum()
                S3 = trace[k - L + 1 : k + 1].sum()

                result[k - 2 * L - G + 1] = (
                    4 * (-c1 * S1 + c2 * S2 + c3 * S3) - baseline
                )
                if len(self.triggers[i]):
                    if k - 2 * L - G + 1 == trigger_pos:
                        print(
                            f"[INFO] found peaksample position {i}: ",
                            S1,
                            S2,
                            S3,
                            baseline,
                        )
                        self.energy_values[i] = result[k - 2 * L - G + 1]

            self.energy_plot.axes.plot(
                result, color=self.colors[i], drawstyle="steps-mid"
            )
            if len(self.triggers[i]):
                if 0 < trigger_pos < len(result):
                    self.energy_plot.axes.plot(
                        trigger_pos, result[trigger_pos], "o", color=self.colors[i]
                    )
            self.energy_plot.axes.set_xlabel(f"{self.slow_filter_range*10} ns cycles")
            self.energy_plot.axes.set_ylabel("Energy")
            self.energy_plot.axes.set_title(f"Energy baseline {baseline:.1f}")
        self.energy_plot.canvas.draw()

        self.update_energy_linearity()

    def update_energy_linearity(self):
        L = self.energy_linearity.value["L"]

        baseline = [t[: self.baseline_index].mean() for t in self.data_FPGA]
        baseline = np.asarray(baseline).mean()

        energy = np.zeros(self.N)
        for i, trace in enumerate(self.data_FPGA):
            try:
                trigger_pos = int(self.triggers[i][0])
            except IndexError:
                trigger_pos = 0
            if trigger_pos:
                if trigger_pos + L < len(trace):
                    energy[i] = (
                        trace[trigger_pos : trigger_pos + L].sum() - baseline * L
                    )
        self.energy_linearity_plot.axes.clear()
        X = energy
        Y = self.energy_values
        fit = np.poly1d(np.polyfit(X, Y, 1))
        F = fit(X)
        mask = X > 0
        if mask.sum() == 0:
            self.energy_linearity_plot.canvas.draw()
            return
        X = X[mask]
        Y = Y[mask]
        F = F[mask]
        C = np.array(self.colors)[mask]
        r2 = ((F - Y.mean()) ** 2).sum() / ((Y - Y.mean()) ** 2).sum()
        if r2 < 0.96:
            self.energy_linearity_plot.axes.plot(X, F, color="black")
            self.energy_linearity_plot.axes.scatter(X, Y, c=C)
            self.energy_linearity_plot.axes.set_xlabel("Integrated trace")
            self.energy_linearity_plot.axes.set_ylabel("Calculated energy")
            self.energy_linearity_plot.axes.set_title(f"Fit r2={r2:.6f}")
        else:
            self.energy_linearity_plot.axes.scatter(X, (Y - F) / F, c=C)
            self.energy_linearity_plot.axes.set_xlabel("Integrated energy")
            self.energy_linearity_plot.axes.set_ylabel("Error to linear fit [%]")
            self.energy_linearity_plot.axes.set_title(f"Fit Error  r2={r2:.6f}")

        self.energy_linearity_plot.canvas.draw()

    def pick_channel(self, i):
        channel = self.main.channels[i]

        self.update_traces(channel)
        self.update_fasttrigger()  # also updated energies
