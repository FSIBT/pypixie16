""""
Usage:
pixie16-scope

Program to tune parameter in almost real time.
The program can show a "live" MCA spectra and current traces.

TODO:
* add showing history and option to go back to setting from a run in the history
  probably should create a setting class that gets stored with the history data and has a get() and apply() method that talks to the pixie16 directly
* show plots for FT, E, CFD (refactor code from binary browser, both program shoudl to the same)

"""

import cmd
from pathlib import Path

import numpy as np
from matplotlib import pyplot as plt
from rich import print

import pixie16 as px


def validate(value, to_type, name):
    try:
        return to_type(value)
    except ValueError:
        print(f"[red]Error[/]Cannot convert {name} to {to_type}: {value}")
        print("Did not change value!")
        return


class MyCmd(cmd.Cmd):
    intro = (
        "Welcome to the pixie16 scope program\n\n"
        "Type 'help' to see the available commands.\n\n"
    )

    prompt = "Pixie16>"
    CURSOR_KEYS = [
        "".join(chr(c) for c in [27, 91, 65]),  # cursor up
        "".join(chr(c) for c in [27, 91, 66]),  # cursor down
    ]

    def __init__(self) -> None:
        super().__init__()
        self.channel: int = 0
        self.module: int = 0  # should not change during runs
        self.MCA_data = np.zeros(shape=32768)
        self.traces = []
        self.old_data = []
        self.settings_file = None
        self.mca_runtime: float = 2
        self.trace_runtime: float = 2
        self.mca_channel: int = 0
        self.mca_normalize = False
        self.mca_rebin = 1

        self.fig, (self.ax_mca, self.ax_traces) = plt.subplots(nrows=1, ncols=2)

        # create some dummy data
        x = np.linspace(0, 10, 100)
        y = np.sin(x)
        self.ax_traces.plot(x, y)
        plt.show(block=False)

    def postloop(self):
        """Call the matplotlib event loop."""
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()

    def precmd(self, line):
        """Remove cursor up/down keys (readline not working in windows)."""
        for key in MyCmd.CURSOR_KEYS:
            line = line.replace(key, "")
        return line

    def take_traces(self):
        """Take traces and return a 2d numpy array."""
        px.control.enable_trace_settings((self.module, self.mca_channel))
        data = px.control.take_list_mode_data(self.truntime)
        # convert to evenst
        reader = px.read.list_mode.StreamReader()
        parser = px.read.list_mode.ListModeDataReader(reader)
        parser.reader.put(data)
        events = parser.pop_all()
        traces = [e.trace for e in events if e.channel == self.mca_channel]
        return np.asarray(traces)

    def take_MCA_spectrum(self):
        """Take MCA spectrum of the `mca channel`."""
        raw_settings = {
            "channel": (self.module, self.channel),
            "CaptureHistogram": [True],
            "CaptureTrace": [False],
        }
        px.control.change_raw_setting_from_dict(raw_settings)
        data = px.control.take_MCA_spectra(
            (self.module, self.mca_channel), duration=self.runtime
        )
        return data[0]

    def rebin(self, data):
        return data.reshape(-1, self.mca_rebin).sum(axis=1)

    def emptyline(self):
        """Do not repeat the last command (default)."""
        pass

    def exit(self):
        print("Good Bye!")
        return True

    def do_quit(self, arg):
        return self.exit()

    def do_bye(self, arg):
        return self.exit()

    def do_exit(self, arg):
        return self.exit()

    def clear(self):
        """Clear all plots and saved data.

        Move last data into old_data.
        """
        self.old_data.append((self.MCA_data, self.traces, self.channel))
        self.MCA_data = np.zeros((16, 32768))
        self.traces = []
        if self.fig:
            self.ax_mca.clear()
            self.ax_traces.clear()

    def reset(self):
        """Reload last setting file."""
        if self.setting_file is None:
            print(
                f"[red]ERROR[/] Cannot reload setting file, none set (use load <file>)."
            )
            return
        px.control.write_settings_from_file(self.setting_file)
        print(f"[yellow]INFO[/]Loaded file {self.setting_file}.")

    def do_channel(self, args):
        """Change the channel that gets affected by setting changes."""
        value = validate(args, int, "channel number")
        if value is not None:
            self.channel = value
            print(
                f"[yellow]INFO[/] Will change settings on {self.channel} from now on."
            )

    def do_mca_channel(self, args):
        """Change the channel we are looking at (traces and MCA)."""
        value = validate(args, int, "channel number")
        if value is not None:
            self.mca_valuechannel = value
            self.reset()
            print(f"[yellow]INFO[/] Will read data from channel {self.mca_channel}.")

    def do_module(self, args):
        """Change the module that gets affected by setting changes (in slot numbers)."""
        value = validate(args, int, "module number")
        if value is not None:
            px.control.exit_system()
            px.control.init_and_boot(modules=[value])
            print(
                f"[yellow]INFO[/] Will change settings on module {self.module} from now on."
            )

    def do_normalize(self):
        """Toggle normilzation of MCA data."""
        self.normalize = not self.normalize
        if self.normalize:
            print("[yellow]INFO[/] Will now normalize the MCA data.")
        else:
            print("[yellow]INFO[/] Will not normalize the MCA data.")

    # Fast Trigger variables
    def do_FTL(self, args):
        """Set L for the fast trigger filter [in us]."""
        value = validate(args, float, "fast trigger L")
        if value is not None:
            px.control.set_channel_parameter(
                "TRIGGER_RISETIME", value, self.module, self.channel
            )
            self.reset()

    def do_FTG(self, args):
        """Set G for the fast trigger filter [in us]."""
        value = validate(args, float, "fast trigger G")
        if value is not None:
            px.control.set_channel_parameter(
                "TRIGGER_FLATTOP", value, self.module, self.channel
            )
            self.reset()

    def do_FTT(self, args):
        """Set the threshold for the fast trigger filter [in ADC units]."""
        value = validate(args, int, "fast trigger threshold")
        if value is not None:
            px.control.set_channel_parameter(
                "TRIGGER_THRESHOLD", value, self.module, self.channel
            )
            self.reset()

    # Energy variables
    def do_EL(self, args):
        """Set L for the fast trigger filter [in us]."""
        value = validate(args, float, "energy L")
        if value is not None:
            px.control.set_channel_parameter(
                "ENERGY_RISETIME", value, self.module, self.channel
            )
            self.reset()

    def do_EG(self, args):
        """Set G for the fast trigger filter [in us]."""
        value = validate(args, float, "energy G")
        if value is not None:
            px.control.set_channel_parameter(
                "ENERGY_FLATTOP", value, self.module, self.channel
            )
            self.reset()

    def do_EPeak(self, args):
        """Set the threshold for the fast trigger filter [in ADC units]."""
        value = validate(args, int, "energy peaksample")
        if value is not None:
            raw_settings = {
                "channel": (self.module, self.channel),
                "PeakSample": [value],
            }
            px.control.change_raw_setting_from_dict(raw_settings)
            self.reset()

    # CFD variables
    def do_CFD(self, args):
        """Set G for the fast trigger filter [in us]."""
        value = validate(args, int, "CFD threshold")
        if value is not None:
            px.control.set_channel_parameter(
                "CFDThresh", value, self.module, self.channel
            )
            self.reset()

    def do_set_channel_variable(self, args):
        """Set and arbitraty setting on the pixie16."""
        name, value = args.split()
        px.control.set_channel_parameter(name, value, self.module, self.channel)

    def do_runtime(self, args):
        """Set the runtime for each MCA run."""
        runtime = validate(args, float, "MCA run time")
        self.mca_runtime = runtime

    def do_truntime(self, args):
        """Set the runtime for each MCA run."""
        truntime = validate(args, float, "Traces run time")
        self.trace_runtime = truntime

    def do_traces(self, args):
        """Take trace data and display it.

        TODO:
        * option to exchange a bad one that got picked
        * add plots for FT, E, CFD
        * add showing in FPGA cycles instead of 2ns

        The above TOOD's could also be handeled by buttons in
        the QT window through matplotlib's widgets.
        """
        traces = self.take_traces()
        self.traces.extend(traces)

        L = len(traces[0])
        x = np.linspace(0, 2 * L, L)

        # calculate amplitudes
        amplitudes_and_traces = [(t.max() - t[0:50].mean(), t) for t in self.traces]
        amplitudes_and_traces.sort(key=lambda x: x[0])

        # pick 10 equally spaces in amplitudes
        N = np.linspace(0, 1, 10) * (len(self.traces) - 1)
        N = sorted({int(n) for n in N})
        traces = [amplitudes_and_traces[n][1] for n in N]

        self.ax_traces.clear()

        for t in traces:
            self.ax_traces.plot(x, t)

        self.ax_traces.set_xlabel("Time [ns]")
        self.ax_traces.set_ylabel("ADC units")

    def do_mca(self, args):
        """Take MCA data and display it."""
        data = self.take_MCA_spectrum()
        self.MCA_data += data

        tmp = self.rebin(self.MCA_data)

        self.ax_mca.clear()
        if self.normalize:
            tmp = tmp / tmp.sum()

        self.ax_mca.plot(tmp, drawstyle="steps-mid", color="blue")
        self.ax_mca.set_xscale("Channels")
        self.ax_mca.set_yscale("Counts/channel")

    def do_rebin(self, args):
        """Change the MCA rebin factor. This is given in 2^N with a default of 0."""
        value = validate(args, int, "rebin factor")

        if value is not None:
            self.mca_rebin = 2**value
            print(f"[yellow]INFO[/] rebinning MCA by 2**{value}.")

    def do_plots(self, args):
        """Reopen the plotting window in case it got closed."""
        self.fig.show()

    def do_load(self, args):
        """Load a settings file."""

        path = validate(args, Path, "path to load settings file")
        # call load setting file

        if path is None:
            print(f"[red]ERROR[/] cannot load file {path}")
            return

        px.control.write_settings_from_file(path)
        self.setting_file = path


def main():
    px.control.init_and_boot()
    MyCmd().cmdloop()
    px.control.exit_system()


if __name__ == "__main__":
    main()
