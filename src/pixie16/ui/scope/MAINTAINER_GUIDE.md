# pixie16-scope Maintainer Guide

## What This Software Does

pixie16-scope is a real-time oscilloscope GUI for XIA Pixie-16 digital pulse processors used in nuclear physics experiments. It reads list-mode data from the hardware (individual detector events with digitized waveforms), displays traces, builds energy histograms, and performs coincidence analysis between detector channels.

The scope runs on a Linux workstation physically connected to the Pixie-16 crate via PCI/PCIe. It communicates with the hardware through XIA's proprietary C SDK (`libPixie16Api.so`).

## Modes and Tabs

The scope has two top-level acquisition modes (dropdown at top of window):

**List Mode** (default) — the PIXIE-16 sends individual events with timestamp, channel, energy, and optionally a waveform trace. Four sub-tabs:
- **Histogram** — live energy spectrum (counts vs energy per channel)
- **Raw Traces** — overlaid ADC waveforms from all display channels
- **Single Channel Analysis** — one channel with computed filter overlays (fast trigger, energy filter, CFD)
- **Coincidence Logic** — binary logic visualization between two selected channels

**MCA Mode** — the PIXIE-16 accumulates energy histograms on-chip. No individual events or traces. One tab:
- **MCA Spectrum** — hardware-accumulated histogram (up to 32k bins)

## UI Layout

The window is split with a QSplitter:
- **Left panel** — plot area with the tab bar (Histogram / Raw Traces / Single Channel Analysis / Coincidence Logic)
- **Right panel** — controls. Content changes based on active tab:
  - Histogram or Raw Traces: shows Channel Controls (checkboxes) + Parameter Controls (collapsible, 7 sub-tabs)
  - Single Channel Analysis: swaps to channel selector, trace type checkboxes, L/G spinboxes, persistence controls
  - Coincidence Logic: swaps to channel A/B selectors, timing params, display mode

**Top bar:** Mode dropdown, Start/Stop/Clear buttons, status display (rate, event count)
**Bottom bar:** Info messages (parameter apply results, errors, etc.)

## Hardware Setup

### Physical Setup
- Pixie-16 modules sit in a CompactPCI/PXI crate
- Each module has 16 analog input channels (SMA/LEMO connectors)
- Detectors (LaBr, HPGe, NaI, etc.) connect via preamp → module channel
- The crate connects to the Linux host via a PCI bridge card

### Software Prerequisites
- Linux (tested on Fedora, Debian)
- Python 3.10+
- PyQt6 + system Qt6 libraries
- XIA Pixie-16 SDK installed (provides `libPixie16Api.so`)
- The SDK needs firmware files (DSP, FPGA, communication FPGA) — these come from XIA

### Configuration
The SDK needs to know where firmware files and settings are. This is configured in `config.ini` (located in platform-specific dirs via `platformdirs`):

```ini
[SDK]
library_path = /path/to/xia/sdk/lib

[Output]
data_dir = /path/to/data/output

[Logging]
logdir = /path/to/logs
```

The settings file (`.set` file) contains all per-channel parameters. It's loaded at boot and written back when you save settings from the scope.

### Installing on a New Machine
```bash
# System packages (Fedora)
sudo dnf install python3-pyqt6 mesa-libGL-devel

# System packages (Debian/Ubuntu)
sudo apt install python3-pyqt6 mesa-common-dev libglu1-mesa-dev

# Install pypixie16
pip install -e ".[test]"

# Verify CLI is available
pixie16-scope --help
```

## How to Run an Experiment

### 1. Boot the Hardware
The scope boots the Pixie-16 on launch. It needs the `.set` file path. If booting fails, check:
- Is the crate powered on?
- Is the PCI bridge card driver loaded? (`lspci | grep PLX`)
- Is `config.ini` pointing to the right SDK library and firmware paths?

### 2. Start the Scope
```bash
pixie16-scope
```
Or with specific channels:
```bash
pixie16-scope --channels 0,2,4,6
```

### 3. Start Acquisition
- Click **Start** — this begins a list-mode run on the hardware
- Traces appear on the Raw Traces tab
- Energy histogram builds on the Histogram tab
- The FIFO reader polls every 50ms for new events

### 4. Adjust Parameters
- Open the collapsible **Parameter Controls** panel on the right
- Select the target **Module** and **Channel**
- Go to the relevant tab (Trigger, Energy, Traces, etc.)
- Edit values
- Click **Apply to Channel**
- This stops the run, writes params, reads back from hardware, restarts

### 5. Save Data
- Traces auto-save to cache periodically (via `auto_save_buffer.py`)
- Click **Save** on the persistence panel to save trace buffers manually
- Energy histograms can be saved from the Histogram tab
- Settings can be saved as presets (JSON) via **Save Preset**

### 6. Stop
- Click **Stop** — ends the hardware run, stops data collection
- You can restart with new parameters without closing the app

## Parameter Reference

### What Each Parameter Does Physically

**Trigger Parameters** (affect which events the hardware captures):

| Parameter | What it does | Typical values | Notes |
|---|---|---|---|
| TRIGGER_THRESHOLD | Fast filter output must exceed this to trigger | 100-5000 ADC | **Not raw amplitude** — actual threshold = L × raw_amplitude. Capped by DSP based on filter settings. |
| TRIGGER_RISETIME | Number of ADC samples averaged in fast filter rise | 0.04-0.1 μs (LaBr), 0.5-2.0 μs (HPGe) | Longer = better noise rejection but worse timing. Sets fast_L in FPGA ticks (value ÷ 0.01). |
| TRIGGER_FLATTOP | Flat-top duration of fast trapezoidal filter | 0.0-0.1 μs typical | Sets fast_G in FPGA ticks. |

**Energy Parameters** (affect energy measurement quality):

| Parameter | What it does | Typical values | Notes |
|---|---|---|---|
| ENERGY_RISETIME | Energy filter integration time | 2-6 μs (HPGe), 0.5-1.0 μs (LaBr) | Longer = better resolution but more pileup. |
| ENERGY_FLATTOP | Energy filter flat-top (must cover pulse peak) | 0.5-1.5 μs | Too short = ballistic deficit, too long = pileup. |
| TAU | Preamp exponential decay time constant | Detector-specific | Must match your preamp. Wrong value = poor energy resolution. |
| EMIN | Minimum energy (peak sample position) | 0 typical | |

**Trace Parameters** (affect what waveform data you get):

| Parameter | What it does | Typical values | Notes |
|---|---|---|---|
| TRACE_LENGTH | How many microseconds of waveform to capture | 1.0-10.0 μs | Longer = more data per event, slower throughput. |
| TRACE_DELAY | Pre-trigger delay (how much baseline before the pulse) | 0.2-2.0 μs | **Must be < TRACE_LENGTH**. Shifts the trigger position within the captured window. Visible as time axis shift on Raw Traces. |

**Baseline Parameters** (affect energy accuracy, no visual effect on traces):

| Parameter | What it does | Typical values | Notes |
|---|---|---|---|
| BASELINE_PERCENT | Where in ADC range the baseline sits | 10% | |
| BASELINE_AVERAGE | Samples averaged for baseline (log2) | 3 (= 8 samples) | Higher = smoother but slower adaptation. |
| BLCUT | Baseline cut — reject baseline measurements that deviate too much | 0-1000 ADC | Protects against pileup contaminating baseline. |

**CFD Parameters** (affect timing precision):

| Parameter | What it does | Typical values | Notes |
|---|---|---|---|
| CFDDelay | CFD delay in μs | 0.01-0.63 μs | Max is ~0.63 μs (hardware limit). |
| CFDScale | CFD attenuation fraction | 0-7 | |
| CFDThresh | CFD threshold | 0-65535 ADC | |

**Hardware Parameters** (affect signal conditioning):

| Parameter | What it does | Typical values | Notes |
|---|---|---|---|
| VOFFSET | DC offset voltage applied to input | -1.5 to 1.5 V | Shifts the baseline up/down in the ADC window. Visible on Raw Traces. |
| Gain | Input gain | 2.5 (most detectors) or 0.625 | Higher gain = more dynamic range but easier to saturate. |
| Polarity | Signal polarity | negative (most detectors) | Must match detector output. Flips traces on display. |
| GoodChannel | Enable/disable channel | True/False | Disabled channels don't contribute to data. |
| CaptureTrace | Whether to record ADC waveforms | True/False | Must be True to see traces. Increases data volume. |

### Which Parameters Affect Which Visuals

**Raw Traces tab:**
- TRACE_LENGTH — trace size
- TRACE_DELAY — time axis shift
- VOFFSET — baseline level
- Gain — signal amplitude
- Polarity — trace flip
- TRIGGER_THRESHOLD — fewer/more events arriving
- CaptureTrace — no traces if disabled

**Single Channel Analysis tab:**
- TRIGGER_RISETIME/FLATTOP — fast filter shape
- TRIGGER_THRESHOLD — threshold line on fast filter plot
- ENERGY_RISETIME/FLATTOP — energy filter shape
- TAU — energy filter decay compensation
- CFDDelay/CFDThresh — CFD trace shape

**Histogram tab:**
- ENERGY_RISETIME/FLATTOP/TAU — peak shape and resolution
- BASELINE params — peak position and width
- TRIGGER_THRESHOLD — which events get counted

**No visual effect (hardware DSP only):**
- BLCUT, BASELINE_PERCENT, BASELINE_AVERAGE — affect energy calculation in firmware
- XDT — external deadtime
- QDCLen0-7 — QDC integration gate lengths

## Known Issues and Gotchas

### PIXIE SDK is Not Thread-Safe
The XIA C library (`libPixie16Api.so`) will corrupt memory and segfault if two calls happen concurrently. **All SDK calls must be serialized on the GUI thread.** This is why:
- Parameter reads are synchronous (not in background threads)
- Apply-to-Channel stops the FIFO timer before calling the SDK
- There's a `processEvents()` + sleep before `end_run()` to flush pending callbacks

**Symptom:** `malloc(): unaligned tcache chunk detected` or `tcache_thread_shutdown(): unaligned tcache chunk detected` → segfault. This means two SDK calls overlapped.

### Parameters Require Run Stop
The PIXIE-16 DSP only accepts parameter changes when the run is stopped. This is why Apply-to-Channel does: stop → end_run → sleep → write → read-back → start. If you try to write params during a run, the DSP ignores them.

### TRIGGER_THRESHOLD is Capped by DSP
The hardware caps TRIGGER_THRESHOLD based on the current fast filter settings. For example, with TRIGGER_RISETIME=0.1μs, the max threshold might be ~1311 ADC. You can verify by checking the read-back value in the console log. Setting it lower than the cap works fine.

The threshold is applied to the **fast filter output**, not raw amplitude. Fast filter output ≈ L × (peak - baseline). So a threshold of 1000 with L=10 means raw pulses need amplitude > ~100 to trigger.

### Large Filter Params Can Segfault
If TRIGGER_RISETIME is set too large relative to TRACE_LENGTH, the fast filter computation needs more samples than the trace has. The software guards against this (returns None instead of crashing), but the **SDK itself** (`Pixie16WriteSglChanPar`) can segfault on extreme values. The validation warns about TRIGGER_RISETIME > 0.5μs.

Rule of thumb: `2 × TRIGGER_RISETIME + TRIGGER_FLATTOP < TRACE_LENGTH / 2`

### Mixed Trace Lengths After Parameter Changes
Changing TRACE_LENGTH mid-run creates traces of different sizes in the buffer. This causes `np.array()` to fail with "inhomogeneous shape." The apply flow clears buffers when TRACE_LENGTH changes. The save functions filter to the most common trace length.

### Channel State on Single Channel Analysis
The `hardware_params` dict in `traces_plotter.py` is global (not per-channel). When you apply params to Ch4, the Single Channel Analysis tab uses Ch4's filter settings even when viewing Ch6. The tab now loads per-channel params from the hardware cache when you switch channels, but if the cache is stale (e.g., params were changed externally), the display may be wrong. Click **Read HW** to refresh.

### Coincidence False Positives
The coincidence detection only compares against the most recent event from the other channel. At high event rates, accidental coincidences still occur (this is real physics — random events do overlap within the validation window). The accidental rate is approximately `2 × window × rate_A × rate_B`. With a 1000ns window and 1kHz per channel, expect ~2 accidental coincidences per second.

## Design Decisions and Why

### Why Apply-to-Channel Instead of Auto-Apply
Previously, every spinbox change immediately wrote to hardware. This caused:
1. **GUI freezes** — SDK calls blocked the event loop during active runs
2. **Stale params on other tabs** — switching channels didn't read back, so old values from a different channel would get applied
3. **Accidental overwrites** — editing one tab would send defaults from invisible tabs

The current design: edit freely, then explicitly apply only the visible tab's params. The run stops, params write, read-back confirms, run restarts. The 0.5-1s pause is acceptable for nuclear physics work.

### Why No Threading for SDK Calls
We tried background threads for hardware I/O. The PIXIE SDK's C library corrupted memory when called from multiple threads, causing `tcache_thread_shutdown` crashes. All SDK calls are now synchronous on the GUI thread with `processEvents()` to keep the UI responsive during brief blocking.

### Why Apply Only Sends Active Tab
Sending all 7 tabs' params would overwrite channels' settings with whatever defaults are showing in hidden tabs. If you only changed the trigger threshold, you don't want to accidentally change the CFD settings to their default values on that channel.

### Why Read-Back Only Updates Written Params
After applying, the hardware read-back only updates the spinboxes for params that were actually written. Otherwise, your unsaved edits on other tabs get wiped by the hardware's current values.

### Why Trace Buffers Are Cleared on TRACE_LENGTH/DELAY Changes
Old traces have a different sample count than new traces. Mixing them causes numpy array shape errors in plotting and saving. Clearing on param change ensures clean data.

## Testing

### Running Tests
```bash
# All tests (186 pass, 21 integration tests fail without hardware)
pytest tests/ -v

# Just the unit tests (skip hardware integration)
pytest tests/ -v --ignore=tests/test_pixie_scope_integration.py
```

The 21 failing integration tests in `test_pixie_scope_integration.py` test methods that don't exist on `DynamicPixieHardwareManager` (e.g., `read_parameter` should be `get_parameter`). These are pre-existing — the tests were written for a planned API that was never fully implemented.

### Testing Without Hardware
The scope can run in **dummy mode** (no hardware connected). It won't acquire real data but you can test the UI, parameter controls, and binary file replay.

### Manual Testing Checklist
When making changes, verify:
- [ ] Start/Stop acquisition works
- [ ] Apply to Channel on each tab (Trigger, Energy, Traces, etc.)
- [ ] Channel switching reads back correct params
- [ ] Params from hidden tabs are NOT overwritten on apply
- [ ] TRACE_DELAY shifts the time axis on Raw Traces
- [ ] Single Channel Analysis shows correct filter for selected channel
- [ ] Coincidence Logic shows no false coincidences with independent sources
- [ ] Binary file replay works
- [ ] No segfaults during rapid parameter changes

## File Modification Guide

### To add a new hardware parameter:
1. Add `ParameterSpec` in `parameter_validation.py`
2. Add widget in the appropriate tab in `parameter_controls.py`
3. Add to `_TAB_PARAMS` dict in `parameter_controls.py`
4. Add to `refresh_parameter_cache` list in `hardware_manager.py`
5. If it affects plotting, add to `_PARAM_TO_PLOTTER` in `app.py`
6. If it needs special routing, add to `MODULE_PARAMETERS`, `BIT_PARAMETERS`, or `UI_ONLY_PARAMETERS` in `hardware_manager.py`

### To add a new plot/analysis tab:
1. Create the widget class (see `coincidence_logic_tab.py` as example)
2. Add it as a tab in `traces_plotter.py` `init_ui()`
3. Wire up data flow in `add_trace_data()` or `update_plots()`
4. If it needs right-panel controls, implement `create_controls_widget()` and connect `request_right_panel_swap` signal

### To modify the data pipeline:
1. FIFO reading is in `app.py:read_list_mode_fifo()`
2. Data distribution is in the event loop there (feeds traces_plotter, spectrum_plotter, coincidence_tab)
3. Don't add SDK calls to timer callbacks — they must be serialized

## Complete Feature Inventory

### Main Application Controls
- **Mode** dropdown: "List Mode" or "MCA Mode"
- **Start/Stop** buttons: acquisition control
- **Clear** button: clears accumulated data
- **Clear Cache** button: clears auto-save buffer (500MB max)
- **Save Data / Save Settings** buttons
- **Status bar**: rate (Hz), event count, mode, memory usage

### Raw Traces Tab Controls
- **Max Traces** spinbox (1-100, default 10): how many traces to overlay
- **Threshold** spinbox (0.0-2.0, default 0.001): amplitude filter for display
- **Time Alignment** combo: "Zero" / "Channel" / "None"
- **Ref Channel** combo: reference for channel alignment mode
- **Auto Scale** checkbox
- **Coincidence Mode** checkbox: filters to only coincident events
- **Polarity** button: opens per-channel polarity dialog
- **Clear** button

### Single Channel Analysis Tab Controls (right panel)
- **Channel** combo: select which channel to analyze
- **Polarity** combo: Normal/Inverted for this channel
- **Trace type checkboxes**: Raw, FastTrig, Energy, CFD, LGL
- **L/G spinboxes**: energy filter parameters (FPGA steps, editable inline)
- **Single Channel Persistence**: Enable checkbox, Save button, Clear button
- **Parameter Info label**: shows current hardware param values

### Histogram Tab Controls
- **Min/Max** spinboxes: energy range (default 0-80000)
- **Bins** spinbox (10-100000, default 2000)
- **Log** checkbox: Y-axis log scale
- **Auto** checkbox: auto-scale
- **BG Sub** checkbox: background subtraction
- **Energy** combo: "Pixie-reported" or "Calculated from traces"
- **Clear** button
- **FWHM** button: opens peak analysis window
- **Channel statistics**: per-channel event counts

### FWHM Peak Analysis (floating window)
- **Add ROI** button: places draggable region on spectrum
- **Clear All** button: removes all ROIs
- **Fit** button: runs Gaussian peak fit on each ROI
- **Auto-refit** checkbox: re-fits every 2 seconds
- **Background** combo: linear/quadratic/constant
- **Results table**: Ch, ROI, Mean +/- err, FWHM +/- err, Net Area, Significance, chi-sq
- **Export** button: saves results to CSV

### Coincidence Logic Tab Controls
- **Show Histograms** checkbox: timing histogram overlay
- **Normalize** checkbox: normalize per event
- **Alpha** spinbox (0.1-0.9): histogram transparency
- **Clear Histograms** button
- **Auto Scale** checkbox

**Right panel (when Coincidence tab active):**
- **Channel A/B** combos: select two channels
- **Reference Ch** combo: Channel A or Channel B
- **Display Mode** combo: "Trigger-Aligned" or "Reference Channel"
- **FT BP Delay** (ns): fast trigger backplane delay
- **FT BP Length** (ns): backplane pulse length (default 200)
- **Chan Trig Stretch** (ns): channel trigger width (default 50)
- **External Delay** (ns): delay compensation (default 300)
- **Validation Window** (ns): coincidence window (default 1000)
- **Apply to** combo: Both/Channel A/Channel B
- **Apply to Hardware** button
- **Save Settings** / **Export Timing** buttons

### Binary File Loader
- **Load** button: opens file dialog for .dat files
- **Filename / File Size** labels
- **Playback Rate** spinbox (100-10000 Hz)
- **Progress bar** during replay
- Seamlessly replaces live hardware — same Start/Stop buttons

### Channel Controls (right panel)
- **16 checkboxes** (one per channel) with color indicators
- **Statistics labels** showing per-channel event counts
- **All / None** quick-select buttons

## Complete Parameter Name Mapping

Some UI labels don't match SDK names. This table covers every parameter:

| UI Label | SDK Name | DSP Variable | Type | Unit | Notes |
|---|---|---|---|---|---|
| Threshold | TRIGGER_THRESHOLD | FASTTHRESH | int | ADC | Capped by DSP |
| Rise Time (Trigger) | TRIGGER_RISETIME | FASTLENGTH | float | μs | → FPGA ticks (÷0.01) |
| Flat Top (Trigger) | TRIGGER_FLATTOP | FASTGAP | float | μs | → FPGA ticks (÷0.01) |
| Rise Time (Energy) | ENERGY_RISETIME | SLOWLENGTH | float | μs | → steps (÷0.01) |
| Flat Top (Energy) | ENERGY_FLATTOP | SLOWGAP | float | μs | → steps (÷0.01) |
| Energy Min | EMIN | EMIN | int | index | Peak sample position |
| Energy L | ENERGY_L | — | int | FPGA steps | UI-only, not sent to HW |
| Energy G | ENERGY_G | — | int | FPGA steps | UI-only, not sent to HW |
| Preamp Tau | TAU | PREAMPTAU | float | μs | Stored as ns internally |
| Ext Deadtime | XDT | XWAIT | float | μs | External dead time |
| Baseline % | BASELINE_PERCENT | BASELINEPERCENT | float | % | 0-100 |
| Baseline Avg | BASELINE_AVERAGE | LOG2BWEIGHT | int | log2 | 2^n samples |
| Baseline Cut | BLCUT | BLCUT | int | ADC | Baseline rejection |
| Trace Length | TRACE_LENGTH | TRACELENGTH | float | μs | Samples captured |
| Trace Delay | TRACE_DELAY | TRIGGERDELAY | float | μs | Pre-trigger window |
| CFD Delay | CFDDelay | CFDDELAY | float | μs | Max ~0.63μs |
| CFD Scale | CFDScale | CFDSCALE | float | — | Attenuation fraction |
| CFD Threshold | CFDThresh | CFDTHRESH | int | ADC | CFD trigger level |
| QDC Len 0-7 | QDCLen0-QDCLen7 | QDCLen0-7 | float | μs | 8 integration gates |
| **DC Offset** | **VOFFSET** | **OFFSETDAC** | float | V | **Label ≠ SDK name** |
| Gain | Gain | CHANNEL_CSRA bit | combo | — | 0.625 or 2.5, bit param |
| Polarity | Polarity | CHANNEL_CSRA bit | combo | — | negative/positive, bit param |
| Channel Enabled | GoodChannel | CHANNEL_CSRA bit | bool | — | Bit param |
| Capture Traces | CaptureTrace | CHANNEL_CSRA bit | bool | — | Bit param |

**Bit parameters** (Gain, Polarity, GoodChannel, CaptureTrace) are routed through `change_setting_from_dict()` which reads CHANNEL_CSRA, flips the relevant bit, and writes back. They are NOT sent via `set_channel_parameter()`.

**UI-only parameters** (ENERGY_L, ENERGY_G) are display/debug values computed from ENERGY_RISETIME. They update the plotter's filter visualization but are NOT written to hardware.

## Persistence Mode

Single Channel Analysis tab → enable "Single Channel Persistence":
- Builds a 2D time-amplitude histogram from all traces on the selected channel
- Uses `fast_histogram` library for performance (300×150 bins)
- Displayed as a density heatmap (log scale, blue→red colormap)
- Updates every 25 traces
- Reveals multi-peak structures, noise floor patterns, pulse shape distributions
- **Save** exports traces to .npy, **Clear** resets the histogram

## Auto-Save System

- Timer fires every **30 seconds** during acquisition
- Saves trace buffers, timestamps, energy spectra, MCA data to `.cache/` directory
- Cache limit: **500MB** (configurable), LRU cleanup every 5 minutes
- Formats: `.npy` (arrays), `.npz` (compressed), `.json` (metadata), `.csv` (timing)
- Tracks buffer overflows (deque maxlen exceeded) per channel
- Survives app restart — cache files persist on disk

## Coincidence Logic — What Each Signal Means

The 6-step binary logic chain models the PIXIE-16's internal trigger logic:

| Step | Signal | Color | Fires when |
|---|---|---|---|
| 1 | Local Fast Trigger | Red | Fast filter output exceeds threshold (every event) |
| 2 | Fast Trigger Backplane | Orange | Delayed copy of step 1 (every event) |
| 3 | Channel Trigger | Yellow | **AND gate** — other channel also triggered within window |
| 4 | Channel Validation Trigger | Green | Validation window opened (only on coincidence) |
| 5 | Local Fast for Processing | Blue | Pulse centered in validation window (only on coincidence) |
| 6 | Validated Trigger for Processing | Purple | AND of steps 4 & 5 (only on coincidence) |

Steps 1-2 fire for every event regardless. Steps 3-6 only fire when there's a real coincidence (other channel triggered within the validation window). With no coincidence source, you should see only red/orange signals.

## Hidden/Non-Obvious Features

1. **Remote desktop detection** — auto-detects NoMachine/NX sessions, slows update timers from 100ms to 500ms to reduce network load
2. **Per-channel polarity dialog** — accessible via "Polarity" button on Raw Traces, allows independent inversion per channel (separate from hardware Polarity param)
3. **Offset correction** — `enable_offset_correction` flag in traces_plotter applies computed offsets based on L/G to align traces
4. **Dummy mode** — if SDK import fails, scope runs with simulated data for UI development/testing
5. **Sampling period** — hardcoded to 2.0ns (500MHz module). Would need changing for 250MHz (4ns) or 100MHz (10ns) modules
6. **Persistence image always log scale** — not user-selectable, forced in `get_image_data()`
7. **Energy source toggle** — Histogram tab can compute energy from traces (offline filter) instead of using hardware-reported values
8. **LGL region overlay** — Single Channel Analysis can show the L-G-L energy filter region boundaries as shaded areas
9. **Delta-T export** — Coincidence tab stores up to 50,000 timestamp differences, exportable to CSV for offline analysis

## Areas That Need Further Work

1. **Coincidence logic** — basic nearest-event matching, no pile-up rejection, no multi-hit handling. The validation window (1000ns default) is a simple parameter, not a true hardware coincidence gate.
2. **FWHM calculator** — works but fit convergence can be poor on low-statistics peaks. No automatic peak detection — user must manually place ROIs.
3. **TRIGGER_THRESHOLD capping** — the DSP silently caps the value based on filter settings. The scope shows the capped value but doesn't explain WHY. Could add a tooltip or warning.
4. **MCA mode** — less tested than list mode. The `mca_spectrum_plotter.py` is a simpler version of `spectrum_plotter.py`.
5. **Integration tests** — 21 tests in `test_pixie_scope_integration.py` fail because they test methods that don't exist (`read_parameter` should be `get_parameter`, etc.).
6. **Multi-module support** — module selector exists but is effectively locked to module 0. Multi-module setups are untested.

## Contact and Resources

- **XIA Pixie-16 Manual:** https://xia.com/support/pixie-16/ (requires login)
- **XIA SDK API Reference:** Included with SDK installation
- **pypixie16 docs:** https://pypixie16.readthedocs.io/
- **Repository:** https://bitbucket.org/berkeleylab/pypixie16
- **Primary maintainer:** apersaud@lbl.gov
