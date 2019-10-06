from . import read
from . import analyze

from ._version import get_versions

__full_version__ = get_versions()
__version__ = __full_version__["version"]
del get_versions

__all__ = ["read", "analyze", "plot"]
