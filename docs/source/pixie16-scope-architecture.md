# PIXIE-16 Scope Architecture

## System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                     PixieScopeApp (QMainWindow)                      │
│  ┌──────────────┐ ┌──────────────┐ ┌─────────────┐ ┌─────────────┐  │
│  │  Parameter   │ │   Channel    │ │    Data     │ │  AutoSave   │  │
│  │  Controls    │ │   Controls   │ │   Manager   │ │   Buffer    │  │
│  └──────────────┘ └──────────────┘ └─────────────┘ └─────────────┘  │
│  ┌──────────────┐ ┌──────────────┐ ┌─────────────┐ ┌─────────────┐  │
│  │ MCA Spectrum │ │   Traces     │ │ Coincidence │ │    FWHM     │  │
│  │ Plotter      │ │   Plotter    │ │ Logic Tab   │ │   Widget    │  │
│  └──────────────┘ └──────────────┘ └─────────────┘ └─────────────┘  │
│  ┌──────────────┐ ┌──────────────┐ ┌─────────────┐                  │
│  │  Spectrum    │ │  Persistence │ │   Trace     │                  │
│  │  Plotter     │ │  Histogram   │ │   Replay    │                  │
│  └──────────────┘ └──────────────┘ └─────────────┘                  │
└──────────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │ Hardware Manager  │
                    │ + Validator       │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │   PIXIE-16        │
                    │   Hardware        │
                    └───────────────────┘
```

## Data Flow

1. **Hardware → Application**
   ```
   PIXIE-16 Hardware → DynamicPixieHardwareManager → LiveDataReader → UI Components
   ```

2. **Parameter Updates**
   ```
   UI Widget → ParameterValidator → ParameterChangeManager → HardwareManager → PIXIE-16
   ```

3. **Traces Mode Pipeline**
   ```
   Raw ADC Traces → Trace Type Selection → Filter Computation → Plot Display
                          ↓                       ↓
                   fast_trigger/CFD     Energy Filter (L-G-L trapezoidal)
                                                  ↓
                                        Threesums Calibration
   ```

4. **Coincidence Logic Pipeline**
   ```
   Binary Waveforms → 6-stage Logic Histogram → Visualization
   (local_fast_trigger → fast_trigger_bp → chan_trig → ...)
   ```

## Core Subsystems

### Hardware Management (`hardware_manager.py`)

**DynamicPixieHardwareManager** — abstraction over PIXIE-16 hardware.

- Parameter caching with `threading.Lock` to avoid I/O bottlenecks
- Mode-specific configuration templates (histogram/list/traces)
- `read_from_dictionary()` — load settings from dict/JSON with DSP variable mapping (e.g. `FastThresh` → `TRIGGER_THRESHOLD`, `ChanCSRa` polarity bit extraction)
- `load_default_settings()` — load packaged `default.json` via `importlib_resources`
- Dummy mode for hardware-free development

### Parameter Validation (`parameter_validation.py`)

**PixieParameterValidator** — module-aware (100/250/500 MHz) validation with range checking and unit normalization.

**ParameterChangeManager** — debounced (300ms) batch updates with change callbacks.

### Trace Types & Energy Filter (`traces_plotter.py`)

Trace types are toggleable per-channel: `raw`, `fast_trigger`, `energy_filter`, `CFD`. Each has a color mapping and hardware computation path.

**Energy filter** computes trapezoidal filter traces using `compute_energy_filter(traces_fpga, R, L, G, ...)` from hardware parameters. LGL vertical lines visualize the trapezoidal filter tap regions (L-G-L) directly on the plot. Trigger point detection and peak sample marking are overlaid.

### Coincidence Logic (`coincidence_logic_tab.py`)

**BinaryHistogramData** — manages 2000-bin histograms for 6 logic pipeline stages. Thread-safe with mutex locking.

**CoincidenceLogicTab** — visualizes the full trigger/validation pipeline with color-coded traces and real-time histogram accumulation.

### FWHM Analysis (`fwhm_analyzer.py`, `fwhm_widget.py`)

**FWHMAnalyzer** — peak detection with Gaussian fitting (lmfit with scipy/numpy fallback). Background subtraction, multi-peak decomposition, overlapping peak filtering. Results include statistical significance (sigma), detection limits (Currie's approximation), and energy-domain calibration.

**FWHMAnalysisWidget** — interactive ROI selection (8 cycling colors), results table (peak, FWHM channels/keV, resolution %, SNR, quality), auto-update timer, export via DataSaver.

### Persistence Histogram (`persistence_histogram.py`)

2D histogram accumulator (time × amplitude) using `fast_histogram`. Dynamically expands ranges, log-scale output for pyqtgraph display. Visualizes hundreds of overlaid traces.

### Trace Replay (`traces_replay.py`)

**TraceReplayBuffer** — circular deque (default 1000) with index navigation.

**TraceReplayWidget** — record/replay toggle, navigation slider, pickle save/load with JSON metadata. Emits `trace_selected` signal.

### Auto-Save Buffer (`auto_save_buffer.py`)

**AutoSaveBufferService** — background QObject that auto-saves traces/MCA/energy data to timestamped NPZ+JSON files. Detects buffer overflow and warns about data loss.

**BufferCacheManager** — LRU cache with configurable limits (50MB–5GB), auto-cleanup of old files.

## Threading Model

- **Main thread**: UI updates, signal/slot dispatch
- **Hardware thread**: acquisition, parameter writes
- **Worker threads**: data processing, auto-save
- Synchronization: `threading.Lock` for parameters, Qt signals for cross-thread communication

## Configuration

Module types (100/250/500 MHz) determine timing resolution and parameter ranges. Parameters are defined as `ParameterSpec` with name, type, range, unit, and DSP variable mapping.

Settings can be loaded from:
- Hardware (live read with caching)
- JSON dictionary (`read_from_dictionary`)
- Packaged defaults (`load_default_settings`)

## Extension Points

### Adding New Parameters
1. Add spec in `parameter_validation.py`
2. Add UI widget in `parameter_controls.py`
3. Add hardware mapping in `hardware_manager.py`

### Adding Acquisition Modes
1. Define mode template in `hardware_manager.py`
2. Create plotter widget
3. Wire into `PixieScopeApp` mode selection

### Adding Trace Types
1. Add entry to trace types dictionary in `traces_plotter.py`
2. Implement computation in `compute_hardware_traces()`
3. Add color mapping