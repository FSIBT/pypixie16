"""pixie16-coincidence  helps setting up coincidence modes

Usage:
  pixie16-coincidence [<setting_filename>]

"""

from docopt import docopt


def main():
    commands = docopt(__doc__)

    from pathlib import Path
    import sys

    from pixie16.ui import CoincidenceApp, QApplication

    filename = commands["<setting_filename>"]
    filename = Path(filename) if filename else None
    if filename and not filename.exists():
        print(f"[Error] Cannot find file {filename}")
        sys.exit(1)

    app = QApplication([])
    ex = CoincidenceApp(app)
    if filename:
        ex.open_file(filename)
    sys.exit(app.exec_())
