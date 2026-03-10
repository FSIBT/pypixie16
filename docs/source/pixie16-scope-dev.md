# PIXIE-16 Scope Developer Guide

## Module Map

```
pixie16.ui.scope/
├── app.py                    # Main window, mode switching, signal wiring
├── hardware_manager.py       # Hardware abstraction, parameter cache, settings I/O
├── parameter_validation.py   # Module-aware validation, debounced change manager
├── parameter_controls.py     # Scrollable parameter panels with LGL controls
├── channel_controls.py       # Channel enable/disable, batch selection
├── mca_spectrum_plotter.py   # MCA histogram display
├── traces_plotter.py         # Trace visualization, trace types, energy filter, LGL lines
├── spectrum_plotter.py       # Continuous spectrum accumulation
├── coincidence_logic_tab.py  # Binary waveform histograms, trigger pipeline visualization
├── fwhm_analyzer.py          # Peak detection, Gaussian fitting, FWHM calculation
├── fwhm_widget.py            # ROI selection UI, FWHM results table, auto-analysis
├── persistence_histogram.py  # 2D trace persistence (time × amplitude)
├── traces_replay.py          # Circular trace buffer with save/load and navigation
├── auto_save_buffer.py       # Background auto-save service with LRU cache management
├── data_manager.py           # Data export (CSV, JSON, NPZ)
└── binary_loader.py          # Binary file loading and replay
```

## Key Classes

### `DynamicPixieHardwareManager`
- `initialize_system()` — hardware init
- `start_mode(mode)` — start acquisition (histogram/list/traces)
- `update_parameter(name, value, module, channel)` — live parameter write
- `stop_acquisition()` — stop current run
- `read_from_dictionary(settings_dict)` — load from JSON/dict with DSP name mapping (`FastThresh` → `TRIGGER_THRESHOLD`, `ChanCSRa` → polarity bit extraction)
- `load_default_settings()` — load packaged `default.json`
- Parameter reads are cached with `threading.Lock` to reduce hardware I/O

### `TracesPlotter`
Trace types dictionary controls which computed traces are displayed per channel:
- `raw` — raw ADC samples
- `fast_trigger` — fast trigger filter output
- `energy_filter` — trapezoidal energy filter computed from `(R, L, G)` hardware params
- `CFD` — constant fraction discriminator

`compute_hardware_traces()` handles per-type scaling and time alignment. When energy filter is enabled, LGL vertical lines mark the trapezoidal filter tap regions on the plot. Trigger points and peak samples are overlaid.

### `CoincidenceLogicTab`
Accumulates binary waveform histograms across 6 logic pipeline stages (`local_fast_trigger`, `fast_trigger_bp`, `chan_trig`, etc.). `BinaryHistogramData` manages the 2000-bin histograms with mutex locking. Display modes: `trigger_aligned`, channel A/B reference.

### `FWHMAnalyzer`
Peak detection → background estimation → Gaussian fit (lmfit, falls back to scipy/numpy). `FWHMResult` carries 30+ fields: peak center, sigma, FWHM (channels and keV), net/gross area, SNR, statistical significance, detection limits (Currie's approximation).

### `FWHMAnalysisWidget`
Interactive ROI selection with `LinearRegionItem` overlays (8 cycling colors). Results displayed in a table with columns: channel, ROI, peak, FWHM (ch/keV), resolution %, counts, SNR, quality. Configurable peak height ratio and background window. Export via `DataSaver`.

### `PersistenceHistogram`
2D accumulator using `fast_histogram`. Dynamically expands x/y ranges. Log-scale output for pyqtgraph `ImageItem` display.

### `TraceReplayBuffer` / `TraceReplayWidget`
Circular deque (default 1000 traces). `StoredTrace` wraps data + metadata (channel, energy, timestamp). Widget provides record/replay toggle, slider navigation, pickle save/load with JSON metadata sidecar.

### `AutoSaveBufferService`
Background QObject saving traces/MCA/energy data to timestamped NPZ+JSON files. Per-source-type save logic. Detects buffer overflow and emits warnings. `BufferCacheManager` does LRU cleanup (configurable 50MB–5GB).

### `ParameterControls`
Collapsible accordion sections with `QScrollArea` (max 400px height). Energy tab includes LGL spinboxes (`Energy L`, `Energy G`) for live trapezoidal filter tuning. "All Channels" toggle for batch parameter application. All changes go through `ParameterChangeManager` for debounced hardware sync.

## Acquisition Modes

### MCA
`MCASpectrumPlotter` — real-time histogram accumulation, 32k+ bins, log/linear scaling, multi-channel overlay.

### List Mode
Integrated in `app.py` with `LiveDataReader` — event-by-event recording, energy spectrum generation, coincidence analysis.

### Traces
`TracesPlotter` — raw ADC capture with selectable trace types (raw/fast_trigger/energy_filter/CFD), energy filter visualization with LGL lines, trigger validation overlay. Supports persistence histogram and trace replay.

## Settings Persistence

Settings can be loaded from three sources:
1. **Live hardware** — cached reads via `hardware_manager`
2. **JSON dictionary** — `read_from_dictionary()` maps DSP variable names to internal parameter names
3. **Packaged defaults** — `load_default_settings()` via `importlib_resources`

## Dummy Mode

Run without hardware for development. Synthetic data generation, all UI functional. No special setup required — detected automatically when hardware is absent.

## Testing

```bash
python tests/test_pixiescope.py all          # all tests
python tests/test_pixiescope.py validation   # parameter validation
python tests/test_pixiescope.py hardware     # hardware interaction
python tests/test_pixiescope.py integration  # full integration
python tests/test_pixiescope.py coverage     # with coverage
```