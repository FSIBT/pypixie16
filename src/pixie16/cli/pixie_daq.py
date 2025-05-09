"""User interface to acquire data using pixie

Usage:
  pixie16-daq

"""

import sys

from docopt import docopt
from pixie16.ui import DataAcquisition, QApplication
import PyQt6.QtCore  # force the use of pyqt6 for matplotlib


def main():
    commands = docopt(__doc__)

    app = QApplication(sys.argv)
    window = DataAcquisition()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
