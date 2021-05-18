from contextlib import contextmanager

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCursor


@contextmanager
def busy_cursor(app):
    """Swap out the cursor for a spinning wheel or similar."""
    app.setOverrideCursor(QCursor(Qt.WaitCursor))
    try:
        yield
    finally:
        app.restoreOverrideCursor()
