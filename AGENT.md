# AGENT.md

## Environment
- **Package Manager:** The project primarily uses `uv` for fast dependency management and environment isolation. All `pip` commands should be prefixed with `uv pip` (e.g. `uv pip install`), and python commands should be executed within the user-provided `uv` environment (e.g., using `uv run`).


This file provides guidance to AI coding agents when working with code in this repository.

## Commands

### Development Commands
- **Install in development mode**: `uv pip install -e .`
- **Install with test dependencies**: `uv pip install -e ".[test]"`
- **Install with documentation dependencies**: `uv pip install -e ".[docs]"`
- **Install with fast binary parsing**: `uv pip install -e ".[fast]"`
- **Run tests**: `uv run pytest`
- **Run tests with coverage**: `uv run pytest --cov`
- **Format code**: Always run `ruff format` before committing.
- **Lint code**: Always run `ruff check --fix` before committing.
- **Pre-commit hooks**: `pre-commit install` and `pre-commit run --all-files`

### Build and Documentation
- **Build package**: `uv build`
- **Build documentation**: Navigate to `docs/` and run `make html`

### CLI Applications
The package provides several command-line tools after installation:
- `pixie16-parameter-scan`: Parameter scanning utility
- `pixie16-binary-browser`: Binary data browser GUI
- `pixie16-coincidence`: Coincidence analysis tool
- `pixie16-scope`: Oscilloscope-like interface
- `pixie16-daq`: Data acquisition control

## Code Architecture

### Core Modules Structure
```
src/pixie16/
├── __init__.py              # Main package initialization with SDK loading
├── control.py               # Hardware control interface to Pixie16 modules
├── analyze.py               # Data analysis functions and decorators
├── config.py                # Configuration file handling (config.ini)
├── plot.py                  # Plotting utilities
├── scan.py                  # Parameter scanning functionality
├── variables.py             # Variable definitions and management
├── C_library_sdk.py         # C library interface via ctypes
├── cli/                     # Command-line interfaces
├── pipeline/                # Data processing pipeline framework
├── read/                    # Data reading modules
├── ui/                      # GUI applications (PyQt6-based)
└── data/                    # Default configuration and test data
```

### Key Architectural Patterns

**SDK Integration**: The package provides a Python interface to XIA's Pixie16 C libraries via ctypes. If the SDK is not available, control functions are automatically mocked to allow development without hardware.

**Pipeline Architecture**: The `pipeline` module implements a ZeroMQ-backed multiprocessing task-based data processing system:
- `Pipeline`: Main orchestrator class (router)
- `Task`: Base class for processing tasks (dealer/push/pull). Handlers run in independent daemon processes with watchdog loops.
- `Message`: Communication between pipeline components
- `Status`: Pipeline state management
- `tasks/`: Predefined processing tasks (GatherData, ConvertToEvents, etc.)

**Configuration Management**: Uses a hierarchical config.ini file system with platform-specific directories (handled by `platformdirs`). The config stores:
- SDK library paths
- Output directories
- Hardware parameters
- Analysis settings

**Data Reading**: Specialized modules for different data formats:
- `list_mode/`: List mode data parsing (includes Cython optimizations)
- `settings/`: Configuration file readers/writers
- `mca.py`: Multi-channel analyzer data

**GUI Framework**: PyQt6-based applications with modular design:
- `binary_browser/`: Binary data visualization
- `coincidence/`: Coincidence analysis interface
- `DataAcquisition.py`: Main DAQ control interface. Acts as the UI frontend to the ZMQ pipeline.

## Configuration Requirements

The package requires a `config.ini` file in the platform-specific config directory. If missing, the package will provide instructions for creating it. The config should specify:
- Path to XIA SDK libraries
- Output data directories
- Hardware-specific parameters

## Development Notes

- **Version Management:** Uses `setuptools_scm` for version management from git tags
- **Code Style:** Enforced by `ruff` with specific configuration in `pyproject.toml`. Always use ruff for formatting and linting.
- **Pre-commit hooks:** Ensure code quality before commits
- **Tests:** Test files located in `tests/` with sample data in `tests/files/`
- **Documentation:** Built with Sphinx and hosted on Read The Docs
- **Python Version:** Supports Python 3.10+ with scientific computing dependencies (NumPy, Pandas, Matplotlib)
- **Changelog:** Always update `CHANGELOG.md` following the Keep a Changelog standard (Semantic Versioning) when making structural or feature changes.

## Git Workflow Guidelines

### File Staging Rules
- **NEVER use `git add .` or `git add -A`** - Always specify files explicitly by name
- **Good**: `git add src/pixie16/plot.py tests/test_plot.py`
- **Bad**: `git add .` or `git add -A`
- This ensures intentional staging and avoids accidentally committing unrelated files

### Commit Message Format
- **Always use component prefixes** for categorization and clarity
- **Format**: `component: brief description of change`
- **Examples**:
  - `plot: add logarithmic scale support for histograms`
  - `CI: update Python version matrix to include 3.13`
  - `pixie-scope: fix real-time update frequency`
  - `pipeline: optimize ZMQ message handling`
  - `tests: add unit tests for control parameter validation`
  - `docs: update installation instructions for macOS`

### Common Component Prefixes
- `plot:` - Plotting utilities and visualization
- `control:` - Hardware control interface
- `pipeline:` - Data processing pipeline
- `tests:` - Test files and testing infrastructure
- `CI:` - Continuous integration and build system
- `docs:` - Documentation changes
- `pixie-scope:` - Oscilloscope GUI application
- `pixie-daq:` - Data acquisition GUI application
- `binary-browser:` - Binary data browser GUI
- `coincidence:` - Coincidence analysis tools
- `config:` - Configuration management
- `analyze:` - Data analysis functions
- `read:` - Data reading modules
