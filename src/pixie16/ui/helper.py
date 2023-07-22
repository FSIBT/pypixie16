"""Some helper functions."""

from contextlib import contextmanager

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor


@contextmanager
def busy_cursor(app):
    """Swap out the cursor for a spinning wheel or similar."""
    app.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
    try:
        yield
    finally:
        app.restoreOverrideCursor()
