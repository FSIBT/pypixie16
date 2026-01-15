import unittest.mock as mock

from . import cli
from . import pipeline
from . import read
from . import ui
from . import analyze
from . import control
from . import scan
from . import plot
from . import C_library_sdk as SDK
from ._version import __version__, __version_tuple__

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
    "__version__",
    "__version_tuple__",
]

if not SDK.load_library():
    print("INFO Mocking pixie16.control since SDK library not found in ini file")
    # Functions that don't use SDK and should NOT be mocked
    non_sdk_functions = {
        "_set_bits",
        "_expand_values",
        "_expand_list",
        "_create_coincidence_masks",
        "_handle_coincidences",
    }

    for name in dir(control):
        obj = getattr(control, name)
        if callable(obj) and name not in non_sdk_functions:
            setattr(
                control,
                name,
                mock.Mock(
                    side_effect=lambda *args, **kwargs: print(
                        f"MOCK: pixie16.control: function {name} was called"
                    )
                ),
            )
