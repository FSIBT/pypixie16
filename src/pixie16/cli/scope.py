""""
Usage:
pixie-scope

Program to tune parameter in almost real time.
The program can show a "live" MCA spectra and current traces.
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
    except:
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

    def __init__(self):
        super().__init__()
        self.channel: int = 0
        self.module: int = 0
        self.MCA_data = np.zeros((16, 32768))
        self.traces = []
        self.old_data = []
        self.need_traces: bool = True

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

    def reset(self):
        self.old_data.append((self.MCA_data, self.traces, self.channel))
        self.MCA_data = np.zeros((16, 32768))
        self.traces = []

    def do_channel(self, args):
        """Change the channel we are looking at."""
        value = validate(args, int, "channel number")
        if value is not None:
            self.channel = value
            self.reset()

    def do_FTL(self, args):
        """Set L for the fast trigger filter. [in us]"""
        value = validate(args, float, "fast trigger L")
        if value is not None:
            px.control.set_channel_parameter(
                "TRIGGER_RISETIME", value, self.module, self.channel
            )
            self.reset()

    def do_FTG(self, args):
        """Set G for the fast trigger filter. [in us]"""
        value = validate(args, float, "fast trigger G")
        if value is not None:
            px.control.set_channel_parameter(
                "TRIGGER_FLATTOP", value, self.module, self.channel
            )
            self.reset()

    def do_FTT(self, args):
        """Set the threshold for the fast trigger filter. [in ADC units]"""
        value = validate(args, int, "fast trigger threshold")
        if value is not None:
            px.control.set_channel_parameter(
                "TRIGGER_THRESHOLD", value, self.module, self.channel
            )
            self.reset()

    def do_run(self, args):
        """Runs data acquisition for <runtime> seconds.

        Will take traces, if no traces have been taking using the current settings.
        Otherwise only take MCA data and add to the old data.
        """
        pass
        # ensure capture histogram is on
        # check if we need to take traces, if so do it
        if self.need_traces:
            pass
            #     read traces, pick good ones, add to self.traces
            self.need_traces = False

        # take MCA spectra
        #   read data, add to existing spectra
        # update plots

    def do_plots(self, args):
        """Reopen the plotting window in case it got closed."""
        self.fig.show()

    def do_load(self, args):
        """Load a settings file."""

        path = validate(args, Path, "path to load settings file")
        # call load setting file

    def clear(self):
        pass
        # clear plots


def main():
    px.control.init_and_boot()
    MyCmd().cmdloop()
    px.control.exit_system()


if __name__ == "__main__":
    main()
