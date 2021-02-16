"""UI elements for the binary file browser"""

from PyQt5.QtCore import QAbstractTableModel, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QIcon, QIntValidator
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QComboBox,
    QCommonStyle,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStyle,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from fast_histogram import histogram1d
import matplotlib.pyplot as plt
from matplotlib import cm
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import numpy as np

import pixie16
