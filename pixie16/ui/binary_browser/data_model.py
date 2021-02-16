from PyQt5.QtCore import QAbstractTableModel, Qt
from PyQt5.QtWidgets import QCommonStyle, QStyle

import pixie16


class BinaryDataModel(QAbstractTableModel):
    """Maps to a list of pixie16.read.Event data.

    E.g. data from a list mode run of the pixie16.

    """

    def __init__(self, data):
        super().__init__()
        self._data = data
        self.header = pixie16.read.Event._fields
        self.icon_true = QCommonStyle().standardIcon(QStyle.SP_DialogApplyButton)
        self.icon_false = QCommonStyle().standardIcon(QStyle.SP_DialogCancelButton)

    def icon_return(self, value):
        if value:
            return self.icon_true
        return self.icon_false

    def data(self, index, role):
        """Return the data.

        For some True/False data, we display an icon instead. To do
        this, we return no data in DisplayRole, but an icon for
        DecorationRole.

        """
        column = index.column()
        row = index.row()

        if role == Qt.DisplayRole:
            if self.header[column] in [
                "trace",
                "CFD_error",
                "pileup",
                "trace_flag",
            ]:
                return None
            return str(self._data[row][column])
        if role == Qt.DecorationRole:
            if self.header[index.column()] == "trace":
                return self.icon_return(len(self._data[row][column]))
            if self.header[index.column()] in ["CFD_error", "pileup", "trace_flag"]:
                return self.icon_return(not self._data[row][column])

    def rowCount(self, index):
        return len(self._data)

    def columnCount(self, index):
        return len(self.header)

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return self.header[section].title()
