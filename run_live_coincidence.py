#!/usr/bin/env python3
"""
CLI command to run the live coincidence visualizer.
Usage: python run_live_coincidence.py
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from pixie16.ui.coincidence.app_live import run_live_coincidence_app

if __name__ == "__main__":
    run_live_coincidence_app()
