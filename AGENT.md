# AGENT.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project Overview

**pypixie16** is a Python interface for XIA Pixie-16 digitizer hardware, providing:
- Low-level SDK interface via ctypes
- High-level data acquisition and control
- Real-time data visualization (oscilloscope, MCA)
- Multi-process data processing pipelines
- Binary data file readers with high-performance parsing

**Primary use cases:**
- Nuclear physics experiments (gamma-ray spectroscopy, coincidence measurements)
- Real-time data acquisition from Pixie-16 modules
- Post-acquisition binary data analysis
- Parameter optimization and scanning

## Repository Structure

```
pypixie16/
├── src/pixie16/           # Main package source
│   ├── control.py         # Hardware control interface (C library wrapper)
│   ├── analyze.py         # Data analysis utilities
│   ├── config.py          # Configuration file handling
│   ├── plot.py            # Plotting utilities
│   ├── pipeline/          # ZMQ-based multiprocessing framework
│   │   ├── pipeline.py    # Pipeline orchestrator
│   │   ├── task.py        # Base Task class
│   │   └── tasks/         # Specific task implementations
│   ├── read/              # Data readers
│   │   ├── list_mode/     # High-performance binary reader (optimized)
│   │   ├── settings/      # Settings file readers
│   │   └── mca.py         # MCA spectrum reader
│   ├── ui/                # PyQt6 GUI applications
│   │   ├── scope/         # Oscilloscope interface (pixie16-scope)
│   │   ├── DataAcquisition.py  # DAQ control (pixie16-daq)
│   │   └── binary_browser/     # Binary file browser
│   └── cli/               # Command-line tools
├── tests/                 # Test suite with fixtures
├── docs/                  # Sphinx documentation
└── pyproject.toml         # Project metadata and dependencies
```

## Development Setup

### Prerequisites
- Python 3.10+ (supports 3.10, 3.11, 3.12, 3.13, 3.14)
- Scientific stack: NumPy, Pandas, Matplotlib
- PyQt6 for GUI applications
- XIA Pixie-16 SDK (optional, mocked if unavailable)

### Installation
```bash
# Install in development mode
pip install -e .

# Install with test dependencies
pip install -e ".[test]"

# Install with documentation dependencies
pip install -e ".[docs]"
```

### CLI Applications
After installation, these commands are available:
- `pixie16-scope` - Real-time oscilloscope and list mode viewer
- `pixie16-daq` - Data acquisition control with pipeline management
- `pixie16-binary-browser` - Binary data file visualization
- `pixie16-coincidence` - Coincidence analysis tool
- `pixie16-parameter-scan` - Parameter optimization

## Code Quality and Style

### Formatting and Linting
**ALWAYS run ruff before committing:**
```bash
# Format code
ruff format .

# Lint and auto-fix
ruff check --fix .
```

### Pre-commit Hooks
The project uses pre-commit hooks for automated checks:
```bash
# Install hooks (one-time setup)
pre-commit install

# Run manually
pre-commit run --all-files
```

**Active hooks:**
- Trailing whitespace removal
- TOML/YAML/JSON validation
- Merge conflict detection
- Python debug statement detection
- ruff formatting
- ruff linting

### Code Style Guidelines
- Line length: 88 characters (ruff default)
- Quote style: double quotes
- Docstring format: Google style with Napoleon extension
- Type hints: encouraged but not required
- Follow existing patterns in the codebase

## Git Workflow

### Commit Philosophy
**Prefer many small, logical commits over large, monolithic ones.**

✅ **Good commit practices:**
- Each commit should represent a single logical change
- Commit message clearly describes what changed and why
- Easy to review, understand, and revert if needed
- Enables granular git history and bisecting

❌ **Avoid:**
- Mixing unrelated changes in one commit
- Committing commented-out code or debug prints
- Giant commits with "various fixes" messages

### File Staging
**NEVER use `git add .` or `git add -A`** - Always specify files explicitly:
```bash
# Good - explicit file staging
git add src/pixie16/read/list_mode/list_mode_data_reader.py
git add tests/test_pixie16/test_read/test_event_parsing.py

# Bad - stages everything indiscriminately
git add .
git add -A
```

This prevents accidentally committing:
- Sensitive files (.env, credentials)
- Binary test data
- IDE configuration files
- Temporary debugging files

### Commit Message Format
Use **component prefixes** for clarity and organization:

**Format:** `component: brief description of change`

**Examples:**
```
read: optimize trace extraction using numpy view()
tests: add benchmark for list mode reader
pipeline: fix race condition in ZMQ message handling
pixie-scope: add persistence plot feature
docs: update installation instructions for macOS
CI: add Python 3.14 to test matrix
```

**Common components:**
- `read:` - Data reading modules (list_mode, settings, mca)
- `control:` - Hardware control interface
- `pipeline:` - Data processing pipeline and tasks
- `pixie-scope:` - Oscilloscope GUI
- `pixie-daq:` - DAQ control GUI
- `binary-browser:` - Binary browser GUI
- `tests:` - Test infrastructure
- `docs:` - Documentation
- `CI:` - Continuous integration
- `config:` - Configuration management
- `plot:` - Plotting utilities
- `analyze:` - Analysis functions

### Running Tests
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_pixie16/test_read/test_read.py

# Run with coverage
pytest --cov=pixie16 --cov-report=html

# Run benchmarks
pytest tests/test_pixie16/test_read/test_benchmark.py -v
```

## Key Architecture Patterns

### 1. Pipeline Framework (multiprocessing + ZMQ)
The `pipeline` module implements a task-based data processing system:

**Components:**
- `Pipeline`: Router/orchestrator managing task lifecycle
- `Task`: Base class for processing units (runs in separate process)
- `Message`: Communication protocol between components
- `Status`: State management (INIT, CONNECT, START, STOP, etc.)

**Communication:**
- ZeroMQ for inter-process messaging
- DEALER/ROUTER pattern for command/control
- PUSH/PULL for data flow
- Each task runs in a daemon process with watchdog loop

**Typical pipeline:**
```
LoadFiles → GatherData → ConvertToEvents → SortEvents → SaveData
```

### 2. List Mode Data Reader (High Performance)
Located in `src/pixie16/read/list_mode/`, this module parses binary event data from Pixie-16 hardware.

**Performance optimizations:**
- Direct bitwise operations (no external dependencies)
- Eliminated byteswap operations (native little-endian)
- Optimized Event object construction
- Zero-copy numpy views for trace data
- struct.unpack_from() to avoid memory copies

**Result:** 4.25x speedup (51K → 217K events/sec)

**Key functions:**
- `read_list_mode_data(files)` → pandas DataFrame
- `read_list_mode_data_as_events(files)` → list of Event objects
- `ListModeDataReader.pop()` → parse next event

### 3. Hardware Control (SDK Wrapper)
`control.py` provides Pythonic interface to XIA's C SDK:

**Features:**
- Automatic SDK loading with fallback to mock mode
- Context managers for boot/init
- High-level functions for data acquisition
- Parameter validation and units handling (via pint)

**Mock mode:** Allows development without hardware by simulating SDK functions

### 4. GUI Applications (PyQt6)
All GUIs use PyQt6 with modular design:

**pixie16-scope:**
- Real-time trace visualization
- List mode histogram display
- Coincidence logic analysis
- Binary file replay

**pixie16-daq:**
- Pipeline control interface
- Real-time status monitoring
- Configuration management
- Run control (MCA, list mode, traces)

## Configuration

Uses `config.ini` in platform-specific directories (via `platformdirs`):

**Typical config.ini:**
```ini
[SDK]
library_path = /path/to/xia/sdk/lib

[Output]
data_dir = /path/to/data/output

[Logging]
logdir = /path/to/logs
```

## Important Files for Agents

### When modifying data reading performance:
- `src/pixie16/read/list_mode/list_mode_data_reader.py` - Main reader implementation
- `tests/test_pixie16/test_read/test_read.py` - Integration tests
- `tests/test_pixie16/test_read/test_event_parsing.py` - Unit tests
- `tests/test_pixie16/test_read/test_benchmark.py` - Performance benchmarks

### When modifying pipeline:
- `src/pixie16/pipeline/pipeline.py` - Pipeline orchestrator
- `src/pixie16/pipeline/task.py` - Base Task class
- `src/pixie16/pipeline/tasks/*.py` - Specific task implementations
- `tests/test_pixie16/test_pipeline/` - Pipeline tests

### When modifying GUIs:
- `src/pixie16/ui/scope/app.py` - Main scope application
- `src/pixie16/ui/DataAcquisition.py` - DAQ interface
- `src/pixie16/cli/*.py` - CLI entry points

## Testing Guidelines

- **Always run full test suite** before major changes: `pytest tests/test_pixie16/test_read/ -v`
- **Add tests for new features** following existing patterns
- **Benchmark performance-critical code** using pytest-benchmark
- **Test with real data files** from `tests/files/bin/`

## Changelog Maintenance

**Update `CHANGELOG.md`** when making notable changes:
- Follow [Keep a Changelog](https://keepachangelog.com/) format
- Use Semantic Versioning for releases
- Add changes to `[Unreleased]` section
- Categories: Added, Changed, Fixed, Removed

## Common Optimization Targets

### Performance-critical areas:
1. **List mode reader** (`read/list_mode/`) - Binary parsing hot path
2. **Pipeline message passing** - ZMQ communication overhead
3. **GUI update frequency** - Real-time plot rendering
4. **Memory usage** - Large dataset handling in pipelines

### When optimizing:
- Profile first (cProfile, line_profiler)
- Measure improvement with benchmarks
- Keep code readable and maintainable
- Document performance characteristics in commit messages
- Add regression tests for performance targets

## Dependencies

**Core scientific stack:**
- numpy, pandas, scipy - Numerical computing
- matplotlib - Plotting
- pyqtgraph - Fast real-time plotting for GUIs

**Data processing:**
- msgspec - Fast serialization for Event objects
- pyarrow - Parquet file I/O
- tables (PyTables) - HDF5 support

**GUI and system:**
- PyQt6 - GUI framework
- pyzmq - ZeroMQ messaging
- psutil - System monitoring

**No longer used (removed):**
- bitstruct, cbitstruct - Replaced with direct bitwise operations

## Support and Documentation

- **Documentation:** https://pypixie16.readthedocs.io/
- **Issues:** https://bitbucket.org/berkeleylab/pypixie16/issues
- **License:** BSD License
- **Contact:** apersaud@lbl.gov (primary maintainer)
