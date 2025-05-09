"""User interface to acquire data using pixie

Usage:
  pixie16-daq

"""

from docopt import docopt

# force the use of pyqt6 for matplotlib
import PyQt6.QtCore

commands = docopt(__doc__)
import sys
from pixie16.ui import DataAcquisition, QApplication


def main():
    app = QApplication(sys.argv)
    window = DataAcquisition()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
