"""
Usage:
  pixie16-parameter-scan <settingfile> (<parameter> <module> <channel> <start> <stop> <step>)...
  pixie16-parameter-scan [options]

Loads the settingfile and then scans the pixie16 parameter.

start, stop and step are in ns and will be converted to μs internally.

Live 1D and 2D plots are being displayed and the images and settingfiles saved.

Options:
  --list-parameters   print a list of all possible parameters

"""

import docopt
import sys


def main():
    commands = docopt.docopt(__doc__)
    # print(commands)

    # only import now, since some of the imports take some time
    # this way the command line feels a bit faster
    from pixie16 import scan as pxscan
    from pixie16 import control as pxcontrol

    from pathlib import Path
    import datetime

    if commands["--list-parameters"]:
        print("name                 unit          DPS name")
        print("-------------------------------------------")
        for n, u, dps in pxscan.PARAMETERS:
            uu = f"[{u}]"
            print(f"{n:20} {uu:13} {dps:20}")
        sys.exit()

    today = f"{datetime.datetime.now():%Y-%m-%d}"
    datadir = Path(".")

    # Initialize System, load config file
    pxcontrol.init_and_boot(modules=[2])
    pxcontrol.load_dsp_parameters_from_file(Path(commands["<settingfile>"]))

    # Run info
    dwelltime = 1  # in seconds

    # Write Run Time
    for i, m in enumerate(pxcontrol.modules):
        tmp = pxcontrol.set_run_time(dwelltime, i)
        print(f"Run Time: {tmp}")

    N = len(commands["<channel>"])

    run = 0
    for f in datadir.glob(f"{today}-scan-*.png"):
        parts = f.name.split("-")
        current_run = int(parts[-1][:-4])
        if current_run >= run:
            run = current_run + 1
    print(f"Run: {run}")

    plot_data = datadir / f"{today}-scan-{run:03d}.png"

    if N == 1:
        parameter = pxscan.ScanParameter(
            name=commands["<parameter>"][0],
            module=int(commands["<module>"][0]),
            channel=int(commands["<channel>"][0]),
            start=float(commands["<start>"][0]),
            stop=float(commands["<stop>"][0]),
            step=float(commands["<step>"][0]),
        )

        title = f'1d-Scan using {commands["<settingfile>"]}'
        pxscan.parameter_scan_1d(parameter, title=title, savefile=plot_data)

    elif N == 2:
        parameterA = pxscan.ScanParameter(
            name=commands["<parameter>"][0],
            module=int(commands["<module>"][0]),
            channel=int(commands["<channel>"][0]),
            start=float(commands["<start>"][0]),
            stop=float(commands["<stop>"][0]),
            step=float(commands["<step>"][0]),
        )
        parameterB = pxscan.ScanParameter(
            name=commands["<parameter>"][1],
            module=int(commands["<module>"][1]),
            channel=int(commands["<channel>"][1]),
            start=float(commands["<start>"][1]),
            stop=float(commands["<stop>"][1]),
            step=float(commands["<step>"][1]),
        )

        title = f'2d-Scan using {commands["<settingfile>"]}'

        pxscan.parameter_scan_2d(
            parameterA, parameterB, title=title, savefile=plot_data
        )
    else:
        print("Only 1d and 2d scans are implemented")

    newfile = datadir / f"{today}-scan-{run:03d}-setting.json"
    pxcontrol.save_dsp_parameters_as_json(newfile)
    newfile = datadir / f"{today}-scan-{run:03d}-stats.json"
    pxcontrol.save_stats_to_file(newfile)

    pxcontrol.end_run()
    pxcontrol.exit_system()
