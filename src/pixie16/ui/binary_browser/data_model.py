from PyQt6.QtCore import QAbstractTableModel, Qt
from PyQt6.QtWidgets import QCommonStyle, QStyle

import pixie16


class BinaryDataModel(QAbstractTableModel):
    """Map list mode data to single values that are shown in a row/colum in the UI.

    Data is stored in a list of pypixie.read.Events.

    This class is needed to map entries from the already parsed binary
    data to cells in a QT table.

    This can also be used to highlight or otherwise format the table
    cells as a function of the content.

    """

    def __init__(self, data):
        super().__init__()
        self._data = data
        self.header = pixie16.read.Event.__struct_fields__

        # use some iconds for certain boolean data we also use these
        # to indicate if trace data exist, sine we don't want to
        # show the whole trace in the table
        self.icon_true = QCommonStyle().standardIcon(
            QStyle.StandardPixmap.SP_DialogApplyButton
        )
        self.icon_false = QCommonStyle().standardIcon(
            QStyle.StandardPixmap.SP_DialogCancelButton
        )

    def icon_return(self, value):
        """Return a nice icon for True or False"""
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

        value = getattr(self._data[row], self.header[column])

        if role == Qt.ItemDataRole.DisplayRole:
            if self.header[column] in [
                "trace",
                "CFD_error",
                "pileup",
                "trace_flag",
            ]:
                return None
            return str(value)
        if role == Qt.ItemDataRole.DecorationRole:
            if self.header[index.column()] == "trace":
                return self.icon_return(len(value))
            if self.header[index.column()] in ["CFD_error", "pileup", "trace_flag"]:
                return self.icon_return(not value)

    def rowCount(self, index):
        return len(self._data)

    def columnCount(self, index):
        return len(self.header)

    def headerData(self, section, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self.header[section].title()
