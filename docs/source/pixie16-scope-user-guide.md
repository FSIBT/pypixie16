# Pixiescope User Guide

## Overview

Pixiescope (`pixie16-scope`) is a real-time oscilloscope and spectrum analyzer for PIXIE-16 digital pulse processors. It provides live waveform capture, energy spectrum accumulation, coincidence timing analysis, and hardware parameter tuning — all from a single GUI.

## Quick Start

```bash
# With hardware connected
pixie16-scope

# Development mode (no hardware required)
pixie16-scope --dummy

# Specify slot and channels
pixie16-scope --slot 2 --channels 0,1,4,9
```

## Main Window Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Mode: [MCA ▾] [List Mode ▾] [Traces ▾]   [Start] [Stop]  │
├───────────────────────────────────┬─────────────────────────┤
│                                   │   Parameter Controls    │
│                                   │   ┌─────────────────┐   │
│         Plot Area                 │   │ Trigger Tab     │   │
│   (Spectrum / Traces /            │   │ Energy Tab      │   │
│    Coincidence Logic)             │   │ Timing Tab      │   │
│                                   │   │ Traces Tab      │   │
│                                   │   │ CFD Tab         │   │
│                                   │   └─────────────────┘   │
│                                   │   Channel Controls      │
│                                   │   [Ch0 ☑] [Ch1 ☐] ...  │
├───────────────────────────────────┴─────────────────────────┤
│  Status: Ch4: 1234 events | 12:34:56                        │
└─────────────────────────────────────────────────────────────┘
```

## Acquisition Modes

### MCA (Multi-Channel Analyzer)

The simplest mode. The PIXIE-16 FPGA accumulates energy histograms internally — Pixiescope periodically reads and displays them.

- **32,768 bins** per channel (0–32k ADC units)
- **Log/linear** Y-axis toggle
- **Multi-channel overlay** — enable multiple channels to compare spectra
- **Update rate**: ~2s (remote desktop) or ~5s (local)

Use MCA mode when you want a quick energy spectrum without event-by-event processing.

### List Mode

Event-by-event data acquisition. Each event carries channel, energy, timestamp, and (optionally) a waveform trace.

- Energy spectra are accumulated in software from individual events
- Events feed into the **Coincidence Logic** tab and **FWHM Analysis**
- Use this mode when you need timing information or coincidence analysis

### Traces Mode

Live waveform capture with computed filter overlays. This is the most feature-rich mode.

- **Raw ADC traces** displayed in real time
- **Computed overlays**: fast trigger filter, energy filter, CFD
- **LGL (Lead-Gap-Lead) regions** mark the trapezoidal energy filter windows
- **Persistence histogram** accumulates trace density over time
- **Trace replay** buffer stores the last 1000 traces for review

## Trace Types

In Traces mode, four trace types can be toggled independently per channel:

### Raw Trace (blue)
The digitized ADC waveform — what the detector actually produced. At 500 MHz, each sample is 2 ns apart.

### Fast Trigger Filter (orange)
The FPGA's fast filter output, used for triggering. Computed from the raw trace using the fast filter rise time (L) and flat top (G) parameters. When this exceeds the threshold, the module triggers.

### Energy Filter (green)
The trapezoidal energy filter output. This is the filter that measures pulse height (energy). It uses the slow filter parameters: Energy Rise Time (L), Energy Flat Top (G), and Filter Range (R).

The filter operates on decimated data: each energy filter step spans `2^R * 5` raw ADC samples.

### CFD — Constant Fraction Discriminator (red)
A bipolar timing signal derived from the fast trigger. The zero-crossing of the CFD provides sub-sample timing resolution. Parameters B (delay) and D (scale factor) control the CFD shape.

The CFD output is shorter than the raw trace by `B + D` samples, offset accordingly on the time axis.

## LGL Regions

When the energy filter trace type is enabled, vertical lines mark the **L-G-L trapezoidal filter windows** on the raw trace:

```
    L (baseline)     G (gap)      L (signal)
  ◄──────────────►◄──────────►◄──────────────►
  |   S1 sum      |  S2 sum   |   S3 sum      |
  |   (blue)      |  (green)  |   (red)       |
```

- **S1** (first L region): baseline sum — averaged signal before the pulse
- **S2** (G region): gap — transition zone, not used in energy calculation
- **S3** (second L region): signal sum — averaged signal at pulse peak
- **Energy = S3 - S1** (signal minus baseline)

The LGL window position is computed from the nearest fast trigger to the trace center, using the exact formula from the FPGA firmware:

```
k = (trigger_fpga_index + fpga_delay) // filter_range + peaking_time - 1
```

Toggle LGL display on/off with the **"Show LGL Regions"** checkbox in the right-side controls panel.

## Coincidence Logic Tab

Accessed via the tab selector when in List Mode or Traces mode. Visualizes the PIXIE-16 trigger validation pipeline as binary (HIGH/LOW) waveforms.

### Channel Selection

- **Channel A**: reference channel (e.g., your detector of interest)
- **Channel B**: coincidence partner (e.g., a gate detector or pulser)

Changing either channel clears accumulated data and resets the plot.

### Six Logic Stages

The plot shows six binary signals stacked vertically, representing the trigger validation pipeline:

| Y Position | Signal | Color | Description |
|-----------|--------|-------|-------------|
| 11 (A), 9 (B) | Local Fast Trigger | Red | Channel fires when fast filter exceeds threshold |
| 10 (A), 8 (B) | Fast Trigger Backplane | Orange | Trigger broadcast to other channels via backplane |
| 7 (A only) | Channel Trigger | Yellow | AND of local trigger with partner channel's backplane trigger |
| 6 (A), 3 (B) | Channel Validation Trigger | Green | Validation window — defines the acceptance time gate |
| 5 (A), 2 (B) | Local Fast for Processing | Blue | Fast trigger qualified for event processing |
| 3.5 (A), 1 (B) | Validated Trigger for Processing | Purple | Final validated trigger — events that pass all gates |

### Display Modes

- **Trigger-Aligned**: Both channels align their trigger points to t=0. Use this to see the raw trigger timing of each channel independently.
- **Reference Channel (Ch A Fixed)**: Channel A stays at t=0. Channel B's time axis shifts by the timestamp difference between the B event and the nearest A event. Use this to see the actual timing offset between channels.
- **Coincidence-Centered**: Coincident events (events where both channels triggered within a time window) are centered at t=0. Non-coincident events are offset by 500 ns for visual separation.

### Histograms

Toggle **"Show Histograms"** to accumulate the binary signal positions over many events. Gray filled regions behind the binary traces show where each signal tends to fire. This builds up a timing distribution — useful for checking timing stability and coincidence windows.

### Hardware Timing Parameters

The timing parameters panel lets you adjust and apply coincidence timing to hardware:

- **FT Backplane Delay** (ns): delay before broadcasting trigger to backplane
- **FT Backplane Length** (ns): duration of backplane trigger pulse
- **Channel Trigger Stretch** (ns): extends the validation window
- **External Delay Length** (ns): delay for external trigger input
- **Validation Window** (ns): acceptance gate width

Click **"Apply to Hardware"** to write these parameters to the selected channel(s). The **Current Settings** display updates to show the values actually set on hardware.

## Persistence Histogram

In Traces mode, toggle **"Persistence"** to accumulate a 2D density map of trace shapes over time. Instead of showing just the latest trace, persistence overlays hundreds of traces as a heatmap:

- **White → Blue → Green → Yellow → Red** colormap (dense regions are red)
- The latest trace is drawn on top in blue for reference
- Useful for seeing jitter, noise distributions, and pulse shape variation
- Update interval: every 25 traces (to avoid GPU overload)

**NoMachine note**: Persistence uses an opaque colormap (no transparency) and reduced resolution (300x150 bins) to avoid crashing remote desktop sessions.

## FWHM Analysis

Available in List Mode. Analyze energy peaks with Gaussian fitting:

1. Select a **Region of Interest (ROI)** by clicking and dragging on the spectrum
2. The analyzer automatically detects peaks within the ROI
3. Results include:
   - Peak center (channel and keV if calibrated)
   - FWHM in channels and keV
   - Energy resolution (%)
   - Net counts and signal-to-noise ratio
   - Statistical significance (sigma)
4. Multiple ROIs can be active simultaneously (8 colors cycle)
5. Export results to CSV/JSON

## Parameter Controls

The right-side panel provides collapsible tabs for tuning hardware parameters in real time:

### Trigger Tab
- **Threshold**: fast filter trigger threshold (ADC units)
- **Rise Time**: fast filter rise time L (microseconds)
- **Flat Top**: fast filter flat top G (microseconds)

### Energy Tab
- **Rise Time**: energy filter L (microseconds)
- **Flat Top**: energy filter G (microseconds)
- **Energy L / Energy G**: direct FPGA tap values for LGL visualization

### Timing Tab
- **Preamp Tau**: preamplifier decay time constant
- **Baseline %**: baseline averaging percentage

### Traces Tab
- **Trace Length**: waveform capture length (microseconds)
- **Trace Delay**: pre-trigger delay (microseconds)

### CFD Tab
- **CFD Threshold**: CFD discriminator level
- **CFD B**: delay parameter
- **CFD D**: scale factor

Parameters are debounced (300 ms default) — rapid adjustments are batched into a single hardware write. Use the **"All Channels"** toggle to apply changes to every channel simultaneously.

## Settings Management

### Loading Settings
Settings can be loaded from three sources:
- **Live hardware**: reads current parameter values from the PIXIE-16 module
- **Dictionary/JSON**: load a saved configuration file via `read_from_dictionary()`
- **Package defaults**: built-in default parameter set

### Saving Settings
Use the Data Manager panel to export current settings and acquired data in CSV, JSON, or NPZ format.

## Trace Replay

The trace replay buffer stores the last 1000 captured traces. Use the replay controls to:

- **Pause** acquisition and browse stored traces
- **Navigate** with the slider or arrow buttons
- **Save** the buffer to disk (pickle format with JSON metadata)
- **Load** a previously saved buffer for offline review

## Remote Desktop (NoMachine)

Pixiescope detects NoMachine sessions automatically (via `NXSESSIONID` or `NX_CLIENT` environment variables) and applies performance optimizations:

- **Slower update timers**: MCA reads every 5s instead of 2s, FIFO reads every 200ms instead of 50ms
- **Reduced memory thresholds**: 800MB warning / 600MB critical (vs 1500/1200 local)
- **Persistence rendering**: opaque colormap, reduced resolution, less frequent updates
- **No alpha transparency**: all rendered elements use solid colors to avoid GPU compositing overhead

These optimizations prevent the X11/NX rendering pipeline from being overwhelmed by rapid plot updates.

## Dummy Mode

Run Pixiescope without hardware for development, training, or UI testing:

```bash
pixie16-scope --dummy
```

Dummy mode generates synthetic data (random traces, simulated spectra) so all UI components remain functional. No special configuration needed.

## Keyboard and Controls Reference

| Action | Control |
|--------|---------|
| Start acquisition | Start button or menu |
| Stop acquisition | Stop button or menu |
| Switch mode | Mode dropdown (MCA / List / Traces) |
| Toggle trace types | Checkboxes in right panel |
| Toggle LGL regions | "Show LGL Regions" checkbox |
| Toggle persistence | "Persistence" checkbox |
| Clear data | Clear button |
| Save traces | Save button in replay controls |
| Auto-scale plot | Right-click plot → Auto Range |
| Zoom | Scroll wheel on plot |
| Pan | Click and drag on plot |

## Troubleshooting

### No traces appearing
- Check that acquisition is started (Start button)
- Verify the correct channel is enabled in Channel Controls
- Check that the trigger threshold is set appropriately — too high means no triggers

### Energy filter looks wrong
- Verify Energy Rise Time and Flat Top are reasonable (try 1.0 and 0.3 microseconds)
- Check that Filter Range (R) matches what's set on the hardware
- LGL regions should bracket the pulse peak — if they don't, the trigger position may be off

### Coincidence plot shows no data
- Ensure both Channel A and Channel B are connected to active detectors
- Check that the channels are set correctly in the Channel Selection dropdowns
- Channels with no signal above threshold will show nothing (by design)

### NoMachine session crashes
- This is typically caused by GPU-intensive rendering (alpha transparency, large images)
- Pixiescope auto-detects NoMachine and applies mitigations
- If crashes persist, try disabling persistence mode
- Reduce the number of simultaneously displayed channels

### Apply to Hardware shows errors
- `"Not a valid channel parameter name"` — the parameter may be a module-level parameter (e.g., `FastTrigBackplaneEna`). This is handled automatically in recent versions.
- Check the terminal output for specific error messages
