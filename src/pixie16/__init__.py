import sys

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

if not SDK.load_library():
    print("INFO Mocking pixie16.control since SDK library not found in ini file")
    for name in dir(control):
        obj = getattr(control, name)
        if callable(obj):
            setattr(
                control,
                name,
                mock.Mock(
                    side_effect=lambda *args, **kwargs: print(
                        f"MOCK: pixie16.control: function {name} was called"
                    )
                ),
            )
