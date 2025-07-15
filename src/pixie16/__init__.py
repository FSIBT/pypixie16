import sys

from . import cli
from . import pipeline
from . import read
from . import ui
from . import analyze
from . import control
from . import mock_control
from . import scan
from . import plot

tasks = pipeline.tasks

__all__ = [
    "cli",
    "pipeline",
    "read",
    "ui",
    "analyze",
    "control",
    "mock_control",
    "scan",
    "plot",
    "tasks",
]

# Store original control module for restoration
_original_control = None
_mock_enabled = False


def enable_mock_mode(data_file=None):
    """Enable mock mode by replacing control functions with mock versions

    Args:
        data_file: Optional path to binary data file to use for mock data
    Examples:
        >>> import pixie16 as px
        >>> px.enable_mock_mode()  # Use default test data
        >>> px.enable_mock_mode("my_data.bin")  # Use specific file
    """
    global _original_control, _mock_enabled

    if _mock_enabled:
        print("MOCK: Mock mode already enabled")
        return mock_control

    _original_control = control

    package_name = __name__  # e.g., 'pixie16'
    control_module_name = f"{package_name}.control"

    # Replace in sys.modules
    if control_module_name in sys.modules:
        sys.modules[control_module_name] = mock_control

    # Handle case "from pixie16 import control"
    # by replacing the control attribute in this module
    globals()["control"] = mock_control

    if data_file:
        mock_control.set_mock_data_file(data_file)

    _mock_enabled = True
    print("MOCK: pixie16.control replaced with mock_control")

    return mock_control


def disable_mock_mode():
    global _original_control, _mock_enabled

    if not _mock_enabled:
        print("MOCK: Mock mode not enabled")
        return control

    if _original_control is None:
        print("ERROR: Original control module not stored")
        return control

    package_name = __name__
    control_module_name = f"{package_name}.control"

    # Restore in sys.modules
    if control_module_name in sys.modules:
        sys.modules[control_module_name] = _original_control

    # Restore the control attribute in this module
    globals()["control"] = _original_control

    _mock_enabled = False
    print("MOCK: pixie16.control restored to original")

    return _original_control


def is_mock_enabled():
    return _mock_enabled


def set_mock_data_file(filepath):
    """Set which binary file to use for mock data

    Args:
        filepath: Path to binary data file
    """
    if not _mock_enabled:
        enable_mock_mode(filepath)
    else:
        mock_control.set_mock_data_file(filepath)
