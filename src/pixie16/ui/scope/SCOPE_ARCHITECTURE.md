# pixie16-scope Architecture

## Overview

The scope is a PyQt6 real-time oscilloscope for XIA Pixie-16 digitizer hardware. It captures data from the PIXIE-16 module and displays it in real-time across multiple analysis views.

**Entry point:** `pixie16-scope` CLI → `src/pixie16/cli/scope.py` → `PixieScopeApp`

## Main Modes

The scope has two top-level acquisition modes, selected via a dropdown at the top of the window:

### List Mode (default)
The PIXIE-16 captures individual detector events — each event has a timestamp, channel number, energy value, and optionally a digitized waveform (trace). The scope reads these events from the hardware FIFO and distributes them to 4 sub-tabs:

```
List Mode
├── Histogram tab        — live energy spectrum (counts vs energy, per channel)
├── Raw Traces tab       — overlaid waveforms from all display channels
├── Single Channel Analysis tab — one channel with computed filter overlays
└── Coincidence Logic tab      — binary logic visualization between 2 channels
```

### MCA Mode
The PIXIE-16 hardware does the histogramming internally — it accumulates energy spectra on-chip and the scope periodically reads the accumulated histogram. No individual events or traces are available. This mode uses `MCASpectrumPlotter` instead of `TracesPlotter`.

```
MCA Mode
└── MCA Spectrum tab     — hardware-accumulated energy histogram (up to 32k bins)
```

## UI Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  [Mode ▼ List Mode]  [Start]  [Stop]  [Clear]   Status: Ready       │
├───────────────────────────────────────────┬─────────────────────────┤
│                                           │  Binary File Loader     │
│   LEFT PANEL (plots)                      │  ┌───────────────────┐  │
│                                           │  │ [Load] file.dat   │  │
│   ┌─────────────────────────────────────┐ │  └───────────────────┘  │
│   │ [Histogram] [Raw Traces] [SCA] [CL] │ │                         │
│   ├─────────────────────────────────────┤ │  Channel Controls       │
│   │                                     │ │  ┌───────────────────┐  │
│   │                                     │ │  │ ☑ Ch0  ☑ Ch1  ...│  │
│   │         Active Tab Content          │ │  │ [All] [None]      │  │
│   │         (plot area)                 │ │  └───────────────────┘  │
│   │                                     │ │                         │
│   │                                     │ │  ▶ Parameter Controls  │
│   │                                     │ │  ┌───────────────────┐  │
│   │                                     │ │  │ Module [0] Ch [4] │  │
│   │                                     │ │  │ [Trigger][Energy] │  │
│   │                                     │ │  │ [Timing][Traces]  │  │
│   │                                     │ │  │ [CFD][QDC][HW]    │  │
│   │                                     │ │  │                   │  │
│   │                                     │ │  │ [Apply to Channel]│  │
│   │                                     │ │  │ [Read HW] [Save]  │  │
│   └─────────────────────────────────────┘ │  └───────────────────┘  │
├───────────────────────────────────────────┴─────────────────────────┤
│  Info bar: Applied 3/3 parameters to M0:Ch4                         │
└─────────────────────────────────────────────────────────────────────┘
```

**Note:** The right panel content changes depending on which tab is active:
- **Histogram / Raw Traces**: shows Channel Controls + Parameter Controls (default)
- **Single Channel Analysis**: swaps to channel selector + trace type checkboxes + L/G spinboxes + persistence controls
- **Coincidence Logic**: swaps to channel A/B selectors + timing parameters + display mode

## Sub-Tab Details

### Histogram Tab (`spectrum_plotter.py`)
Live energy spectrum from list mode events. Each incoming event's energy is binned into a per-channel histogram.

**What you see:** Multiple colored curves (one per enabled channel) showing counts vs energy.

**Controls:** energy range (min/max), bin count, log scale, auto-scale, background subtraction, energy source (hardware-reported vs calculated from traces), FWHM peak fitting button.

**Data source:** `add_energy(channel, energy)` called per event from FIFO reader.

### Raw Traces Tab (part of `traces_plotter.py`)
Overlaid ADC waveforms from all display channels. Shows the most recent N traces per channel.

**What you see:** Color-coded traces (one color per channel) with X=time(ns), Y=amplitude(ADC). Multiple traces from the same channel overlay with the same color.

**Controls:** max traces to display, amplitude threshold filter, time alignment mode (zero/channel/none), reference channel, auto-scale, polarity dialog, clear.

**Data source:** `add_trace_data(channel, trace, energy, timestamp)` called per event.

**Time axis:** Shifted by TRACE_DELAY (trigger at t=0, pre-trigger is negative time). When time alignment is "Channel", traces are offset by timestamp difference relative to a reference channel.

### Single Channel Analysis Tab (part of `traces_plotter.py`)
Detailed view of ONE channel with computed digital signal processing overlays.

**What you see:** The raw trace plus optional overlays:
- **Fast Trigger** — trapezoidal fast filter output (uses TRIGGER_RISETIME, TRIGGER_FLATTOP, TRIGGER_THRESHOLD)
- **Energy Filter** — trapezoidal energy filter output (uses ENERGY_RISETIME, ENERGY_FLATTOP, TAU)
- **CFD** — Constant Fraction Discriminator trace (uses CFDDelay, CFDScale, CFDThresh)
- **LGL region** — shaded L-G-L boundaries on the energy filter
- **Trigger/peak markers** — dots showing where triggers and peak samples were detected
- **Threshold line** — horizontal red dashed line at fast_threshold

**Persistence mode:** When enabled, builds a 2D time-amplitude heatmap from accumulated traces. Shows pulse shape distributions as a density plot.

**Important:** The filter computations use `hardware_params` dict which is loaded per-channel from the hardware cache when you switch channels. If you apply params to Ch4 and switch to Ch6, the filters shown match Ch6's actual hardware settings.

### Coincidence Logic Tab (`coincidence_logic_tab.py`)
Binary waveform visualization modeling the PIXIE-16's internal trigger logic between two channels.

**What you see:** 11 horizontal binary signals (HIGH/LOW) stacked vertically, showing the trigger decision chain:

```
y=11  Local Fast Trig A      ████░░░░░░░░░░░   (red)
y=10  Fast Trig BP A          ░░████░░░░░░░░░   (orange)
y=9   Local Fast Trig B      ░░░░████░░░░░░░   (red)
y=8   Fast Trig BP B          ░░░░░░████░░░░░   (orange)
y=7   ChanTrig A (A AND B)   ░░░░░░░░████░░░   (yellow)     ← coincidence gate
y=6   Chan Valid Trig A       ░░░░░░░░░░████░   (green)      ← only on coincidence
y=5   Local FT Proc A         ░░░░░░░░░░░██░░   (blue)       ← only on coincidence
y=3.5 Valid Trig Proc A       ░░░░░░░░░░░██░░   (purple)     ← only on coincidence
y=3   Chan Valid Trig B       ░░░░░░░░░░████░   (green)      ← only on coincidence
y=2   Local FT Proc B         ░░░░░░░░░░░██░░   (blue)       ← only on coincidence
y=1   Valid Trig Proc B       ░░░░░░░░░░░██░░   (purple)     ← only on coincidence
```

Steps 1-2 (red/orange) fire for every event. Steps 3-6 (yellow/green/blue/purple) only fire when there's a real coincidence between channels A and B.

**Display modes:**
- **Trigger-Aligned:** both channels' triggers at t=0 (useful for seeing relative timing of logic signals)
- **Reference Channel:** selected channel fixed at t=0, other channel offset by actual timestamp difference (shows real time-of-flight)

**Delta-T histogram:** tracks timestamp differences between coincident events, exportable to CSV.

### MCA Spectrum Tab (`mca_spectrum_plotter.py`)
Only visible in MCA Mode. Shows the hardware-accumulated energy histogram (up to 32k bins). Similar controls to the Histogram tab but data comes from `read_histograms()` instead of per-event binning.

## File Structure (17 files, ~13,300 lines)

```
src/pixie16/ui/scope/
├── app.py                    (1847 lines) Main application window
├── traces_plotter.py         (2948 lines) Central tab container + trace logic
├── coincidence_logic_tab.py  (1508 lines) Coincidence binary logic
├── spectrum_plotter.py        (882 lines) List mode energy histogram
├── hardware_manager.py        (819 lines) SDK interface + parameter cache
├── parameter_controls.py      (688 lines) Hardware param UI + Apply button
├── parameter_validation.py    (595 lines) Range checking + constraints
├── fwhm_analyzer.py           (702 lines) Peak detection + FWHM
├── binary_loader.py           (582 lines) Binary file replay
├── mca_spectrum_plotter.py    (563 lines) MCA histogram display
├── data_manager.py            (515 lines) File save paths + settings
├── fwhm_widget.py             (470 lines) ROI + Gaussian fitting UI
├── auto_save_buffer.py        (445 lines) Auto-save cache management
├── traces_replay.py           (373 lines) Trace navigation/replay
├── channel_controls.py        (348 lines) Channel enable/disable
├── persistence_histogram.py    (53 lines) Fast 2D histogram
└── __init__.py                  (1 line)  Exports PixieScopeApp
```

## Component Descriptions

### app.py — Main Application
`PixieScopeApp(QMainWindow)` — owns all components, manages layout, connects signals.

**Layout:** QSplitter with left (plots) and right (controls) panels.

**Key responsibilities:**
- Start/stop acquisition (hardware run control)
- Route parameter changes from UI → hardware → plotter
- FIFO data polling (50ms timer reads list mode events)
- Mode switching (list mode vs MCA mode)
- Coordinates all child widgets

**Important methods:**
- `start_acquisition()` / `stop_acquisition()` — run control
- `apply_all_parameters()` → `_execute_apply_batch()` — parameter apply flow
- `_sync_parameter_to_plotter()` — propagates hardware params to plot state
- `read_parameters_from_hardware()` — reads params on channel switch
- `read_list_mode_fifo()` — FIFO polling callback

### traces_plotter.py — Central Tab Container
`TracesPlotter(QWidget)` — the main plot area with 4 sub-tabs:

1. **Histogram** (`ContinuousSpectrumPlotter`) — live energy spectra
2. **Raw Traces** — overlaid waveforms from all display channels
3. **Single Channel Analysis** — one channel with computed overlays (fast filter, energy filter, CFD)
4. **Coincidence Logic** (`CoincidenceLogicTab`) — binary logic visualization

**Key internal state:**
- `hardware_params` dict — filter settings used for Single Channel Analysis computations
- `trace_data[channel]` — deque per channel (maxlen=1000) of raw ADC traces
- `trace_delay_ns[channel]` — per-channel trace delay for time axis shifting
- `channel_polarity[channel]` — per-channel polarity inversion (True=normal)
- `display_channels` — which channels show on Raw Traces

**Important methods:**
- `add_trace_data(channel, trace, energy, timestamp)` — called per event from FIFO
- `update_plots()` — called by 100ms timer, dispatches to active tab's update
- `compute_hardware_traces(type, trace, channel)` — computes fast_trigger/cfd/energy filter overlays
- `calculate_aligned_time_axis(length, timestamp, channel)` — time axis with trace_delay offset
- `_load_channel_hardware_params(channel)` — loads per-channel params from hardware cache

### hardware_manager.py — SDK Interface
`DynamicPixieHardwareManager` — wraps the PIXIE-16 C SDK.

**Parameter routing in `_apply_parameter_to_hardware()`:**
- `MODULE_PARAMETERS` → `px.control.set_module_parameter()`
- `BIT_PARAMETERS` (Gain, Polarity, GoodChannel, CaptureTrace) → `px.control.change_setting_from_dict()`
- `UI_ONLY_PARAMETERS` (ENERGY_L, ENERGY_G) → skipped (display only)
- Everything else → `px.control.set_channel_parameter()`

**Parameter cache:** `state.current_parameters[module][channel][param_name]` — updated on write and read-back.

**SDK safety:** Thread lock (`parameter_lock`) for cache access. But ALL SDK calls must happen on the GUI thread (C library is not thread-safe).

### parameter_controls.py — Hardware Parameter UI
`ParameterControls(QGroupBox)` — collapsible panel on the right side.

**7 parameter tabs:**
| Tab | Parameters |
|---|---|
| Trigger | TRIGGER_THRESHOLD, TRIGGER_RISETIME, TRIGGER_FLATTOP |
| Energy | ENERGY_RISETIME, ENERGY_FLATTOP, EMIN, ENERGY_L, ENERGY_G |
| Timing | TAU, XDT, BASELINE_PERCENT, BASELINE_AVERAGE, BLCUT |
| Traces | TRACE_LENGTH, TRACE_DELAY |
| CFD | CFDDelay, CFDScale, CFDThresh |
| QDC | QDCLen0–QDCLen7 |
| Hardware | VOFFSET, Gain, Polarity, GoodChannel, CaptureTrace |

**"Apply to Channel" button:** Only sends params from the currently visible tab to the selected module/channel. Does NOT auto-apply on every spinbox change.

**Channel switching:** Emits `request_read_hardware` signal → app reads params from hardware → updates spinboxes for new channel.

### parameter_validation.py — Validation
`PixieParameterValidator` — `ParameterSpec` per param with min/max, data type, unit, DSP variable name. Module-type aware (100MHz/250MHz/500MHz have different ranges).

### coincidence_logic_tab.py — Coincidence Analysis
`CoincidenceLogicTab(QWidget)` — binary waveform visualization.

**6 logic steps per channel:**
1. Local Fast Trigger (red) — fast filter exceeds threshold
2. Fast Trigger Backplane (orange) — delayed trigger pulse
3. Channel Trigger (yellow) — AND gate (requires other channel trigger within window)
4. Channel Validation Trigger (green) — validation window (only fires on coincidence)
5. Local Fast for Processing (blue) — centered in validation window
6. Validated Trigger for Processing (purple) — AND of steps 4 & 5

**Coincidence matching:** Compares only the most recent event from the other channel (not entire buffer). Default validation window: 1000ns.

**Display modes:** trigger-aligned (both at t=0) or reference-channel (offset by delta-T).

### spectrum_plotter.py — Energy Histogram
`ContinuousSpectrumPlotter` — bins incoming energies into histograms per channel. Supports auto-scale, log scale, background subtraction, and FWHM overlay.

### mca_spectrum_plotter.py — MCA Display
`MCASpectrumPlotter` — for MCA acquisition mode (hardware histogramming, up to 32k bins). Different from spectrum_plotter which handles list mode.

### fwhm_analyzer.py + fwhm_widget.py — Peak Analysis
Peak detection using `scipy.signal.find_peaks`, Gaussian fitting with `lmfit`. ROI selection on spectra, FWHM readout.

### binary_loader.py — File Replay
Loads `.bin` list mode files for offline analysis. Integrates with Start/Stop buttons — when a binary file is loaded, Start replays from file instead of live hardware.

### data_manager.py + auto_save_buffer.py — Data Persistence
`DataSettingsManager` handles save directories and file naming. `AutoSaveBuffer` periodically saves trace buffers, spectra, and histograms to cache. Handles mixed-length traces (from TRACE_LENGTH changes mid-run).

### traces_replay.py — Trace Navigation
Circular buffer of captured traces with prev/next/jump navigation for reviewing specific waveforms.

### channel_controls.py — Channel Display
Checkboxes to enable/disable channel visibility on plots. Display channel selection.

### persistence_histogram.py — 2D Histogram
`PersistenceHistogram` — accumulates traces into a 2D histogram for persistence-mode display (heatmap of overlaid traces). Uses `fast_histogram` for performance.

## Data Flow

### Live Acquisition
```
Hardware FIFO → data_timer (50ms) → read_list_mode_fifo()
  → for each event:
      ├─ traces_plotter.add_trace_data(ch, trace, energy, ts)
      │   ├─ stores in trace_data[ch] deque
      │   ├─ feeds persistence_histogram
      │   └─ feeds replay buffer
      ├─ spectrum_plotter.add_energy(ch, energy)
      └─ coincidence_tab.add_event_with_trace(event)
  → update_timer (100ms) → update_plots()
      ├─ Raw Traces: plot latest N traces per channel
      ├─ Single Channel Analysis: compute filter overlays
      └─ Histogram: update spectrum display
```

### Parameter Apply
```
User edits spinbox on Trigger tab → clicks "Apply to Channel"
  → parameter_controls.apply_to_channel()
  → emits parameter_changed per param (only active tab)
  → app.apply_all_parameters() collects + debounces
  → app._execute_apply_batch():
      1. stop_acquisition()
      2. kill FIFO timer, processEvents()
      3. end_run() + sleep
      4. update_parameter() per param → SDK write
      5. refresh_parameters() → SDK read-back
      6. update UI spinboxes (only written params)
      7. _sync_parameter_to_plotter() → update hardware_params
      8. clear trace buffers if TRACE_LENGTH/DELAY changed
      9. start_acquisition()
```

## SDK Name → Plotter Key Mapping

| SDK Parameter | Plotter Key | Conversion |
|---|---|---|
| TRIGGER_THRESHOLD | fast_threshold | direct |
| TRIGGER_RISETIME | fast_L | μs ÷ 0.01 → FPGA ticks |
| TRIGGER_FLATTOP | fast_G | μs ÷ 0.01 → FPGA ticks |
| ENERGY_RISETIME | energy_L | μs ÷ 0.01 → steps |
| ENERGY_FLATTOP | energy_G | μs ÷ 0.01 → steps |
| TAU | decay_ns | μs × 1000 → ns |
| EMIN | energy_P | direct |
| CFDDelay | CFD_delay | direct |
| CFDThresh | CFD_threshold | direct |
| TRACE_DELAY | trace_delay_ns[ch] | μs × 1000 → ns |
| Polarity | channel_polarity[ch] | "positive"→True |

## Known Constraints

- **PIXIE SDK not thread-safe** — all SDK calls must be on GUI thread, serialized
- **TRIGGER_THRESHOLD capped by DSP** — max depends on fast filter settings
- **Filter params must fit in trace** — 2×L+G must be < FPGA trace length or computation fails
- **Parameter write requires run stopped** — end_run() before write, start_run() after
- **Mixed trace lengths** — changing TRACE_LENGTH mid-run creates inhomogeneous buffers (handled by filtering on save)
