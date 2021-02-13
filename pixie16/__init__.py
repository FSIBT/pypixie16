import sys

from . import read
from . import plot
from . import ui
from . import analyze

from ._version import version as __version__


if sys.maxsize > 2 ** 31 - 1:
    # 64 bit systems
    __all__ = ["read", "analyze", "plot", "ui"]
if sys.maxsize == 2 ** 31 - 1:
    # 32 bit systems can also use the controls
    from . import scan
    from . import control
    from . import pipeline
    from . import tasks

    __all__ = ["read", "analyze", "plot", "ui", "scan", "control", "pipeline", "tasks"]
