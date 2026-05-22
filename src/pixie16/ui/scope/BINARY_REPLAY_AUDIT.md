# Binary Replay Code Audit

Code review of `binary_loader.py` and its integration with the scope application.
Performed 2026-05-21 against branch `bugfix/pixiescope-issues-v2`.

---

## Critical Issues

### 1. Replay completion does not reset app state

**Files:** `app.py:549-577`, `binary_loader.py:561-568`

When binary replay finishes naturally (all events processed), `on_replay_finished()`
emits `replay_stopped` but **nothing in app.py listens to that signal**. Consequences:

- `is_acquiring` stays `True` — Start button remains disabled
- `stop_live_updates()` is never called — update timers (100 ms traces, 500 ms
  coincidence) keep firing on stale data indefinitely
- Stop button stays enabled but clicking it tries to stop an already-finished thread

Manual stop via the Stop button works correctly because `stop_acquisition()` in
app.py explicitly handles binary replay. Only the natural-completion path is broken.

**Fix:** Connect `binary_loader.replay_stopped` (or `replay_finished`) to a handler
in app.py that calls `stop_live_updates()`, resets `is_acquiring = False`, and
re-enables the Start button. Alternatively, connect `replay_finished` directly to
`stop_acquisition`.

### 2. Replay thread calls GUI methods from background thread

**File:** `binary_loader.py:85-86`

`BinaryReplayThread.run()` calls `self.parent_scope.process_list_mode_event(event)`
directly. This method (app.py:751) touches `spectrum_tab.add_event()` and
`spectrum_tab.add_event_with_trace()`, which modify Qt widget state (deques, plot
data, coincidence buffers). Qt requires all widget access to happen on the main
(GUI) thread.

In practice this often works because Python's GIL serialises dict/deque mutations,
and PyQt's signal mechanism auto-queues cross-thread calls. But it is technically
unsafe and can cause assertion failures or segfaults under load or during mode
switches.

**Fix:** Emit a signal from the replay thread carrying the event, and connect it
(auto-queued) to `process_list_mode_event` on the main thread. This is a small
refactor: add a `pyqtSignal(object)` to `BinaryReplayThread`, emit it per event,
connect it in `start_replay()`.

---

## High-Priority Issues

### 3. MCA mode flag is static — mode switches during replay are ignored

**File:** `binary_loader.py:48-55`

`BinaryReplayThread.__init__` snapshots `parent_scope.current_mode` into
`self.is_mca_mode` and never updates it. If the user switches between List Mode
and MCA Mode during a replay:

- List -> MCA: replay keeps feeding `process_list_mode_event`, MCA histograms
  are never accumulated. Display shows nothing.
- MCA -> List: replay keeps accumulating MCA histograms, but `process_list_mode_event`
  is skipped because `current_mode` is now `"list_mode"` (line 85 check passes but
  MCA accumulation continues on stale flag).

**Fix:** Instead of a static flag, check `parent_scope.current_mode` dynamically in
the run loop (it's a simple string read, safe enough). Or: block mode switching while
replay is running (simpler, arguably better UX for handoff).

### 4. Silent data loss during large replays — no user notification

**Files:** `traces_plotter.py:158` (trace buffer maxlen=1000),
`spectrum_plotter.py:69` (energy buffer maxlen=50000)

With 100k events across 16 channels (~6,250 events/channel), the trace buffer
overflows after 1,000 events per channel. The overflow counter increments silently
(traces_plotter.py:1251) with a suppressed debug print every 100 overflows.

The user sees a full-looking display but has no indication that only the most recent
1,000 traces are retained. For histogram mode this matters less (the histogram
accumulates correctly), but for trace-level analysis it means early events are lost.

**Fix (low-effort):** Show a one-time warning in the status bar when overflow first
occurs, e.g. "Trace buffer full — oldest traces are being discarded." No code
change to buffer size needed; the circular buffer behavior is correct, the user
just needs to know about it.

---

## Medium-Priority Issues

### 5. `redo_replay()` has a fixed 100 ms sleep that may be insufficient

**File:** `binary_loader.py:589-590`

After calling `stop_replay()`, the code sleeps 0.1 s then immediately starts a new
replay. `stop_replay()` calls `self.replay_thread.stop()` which sets
`is_running = False` and calls `self.wait()` (blocking join). So the `time.sleep`
is actually redundant — `stop()` already waits. But if `stop()` is changed in the
future to be non-blocking, the fixed sleep could be too short on slow systems,
risking two concurrent replay threads.

**Fix:** Remove the `time.sleep(0.1)` — `stop()` already joins. If non-blocking
stop is ever needed, use `replay_thread.finished` signal instead of sleeping.

### 6. MCA energy-to-bin conversion: default energy of -1 maps to bin 0

**File:** `binary_loader.py:131`

The Event class defaults `energy = -1` (list_mode_data_reader.py:180). If an event
reaches `_process_event_for_mca` with this default, `int((-1 / 65536.0) * 32768)`
= 0, so it silently accumulates in bin 0.

Not a concern for well-formed binary data (energy is always 0-65535 from the
header), but could produce a spurious spike at bin 0 if the parser emits
partially-constructed events on corrupt data.

**Fix:** Skip events with `energy < 0` in `_process_event_for_mca`.

### 7. Coincidence timestamp buffers are small (maxlen=500)

**File:** `coincidence_logic_tab.py:191,199`

`ch_a_timestamps` and `ch_b_timestamps` are `deque(maxlen=500)`. At 1000 Hz replay
rate, each channel fills in ~1 second if events are evenly distributed. If one
channel has a much higher rate than the other (common in nuclear physics — some
detectors are noisier), the slow channel's partner timestamps can be lost before a
coincidence pair is found.

This is a pre-existing limitation, not introduced by the replay feature. During live
acquisition the same buffers are used, but the low event rate masks the problem.
Replay at high rates exposes it.

**Fix:** Increase to `maxlen=5000` or make configurable. The memory cost is trivial
(5000 int64 timestamps = 40 KB per channel).

### 8. Trace length not validated against TRACE_LENGTH parameter

**Files:** `traces_plotter.py:1218-1223`, `list_mode_data_reader.py:426`

Traces from the binary reader are `numpy.uint16` arrays whose length is determined
by the event header's Trace Length field. The scope never checks that this matches
the current `TRACE_LENGTH` hardware parameter. If the binary was recorded with a
different trace length than what the scope currently expects, the time axis and
filter calculations will silently produce wrong results (filters assume a fixed
trace length that divides evenly by 5 for FPGA conversion).

**Fix:** On file load, read the first event's trace length and compare it to the
current `TRACE_LENGTH` parameter. Warn the user if they differ.

---

## Low-Priority / Cosmetic Issues

### 9. `_check_cfd_warning` references `self.parent` instead of `self.parent_scope`

**File:** `binary_loader.py:382`

```python
if hasattr(self.parent, 'traces_plotter'):
```

Should be `self.parent_scope`. `self.parent` is the Qt widget parent (likely None
or the GroupBox), which never has a `traces_plotter` attribute. The check silently
fails, so the CFD warning is never shown. Harmless but useless code.

**Fix:** Change `self.parent` to `self.parent_scope`.

### 10. `replay_rate_hz` accessed from replay thread without synchronization

**File:** `binary_loader.py:67,572`

The replay thread reads `self.binary_loader.replay_rate_hz` each batch cycle. The
GUI thread writes it when the spinbox changes. Python's GIL makes simple int
read/write atomic, so this is safe in CPython. But it's technically a data race
under the C spec.

**Fix:** Not worth fixing — the worst case is reading a stale rate for one 100 ms
batch cycle. Document the intentional unsynchronized access with a comment.

### 11. `_update_mca_display` does not check for `cumulative_mca_data`

**File:** `binary_loader.py:532`

The code checks `hasattr(self.parent_scope, "mca_data")` but then accesses
`self.parent_scope.cumulative_mca_data` without checking it exists. If `mca_data`
exists but `cumulative_mca_data` does not (e.g., partially initialized app state),
an `AttributeError` is raised. The outer `try/except` catches it, but silently
losing the update is confusing.

**Fix:** Add `hasattr` check for `cumulative_mca_data`, or access both in the
same conditional.

---

## Summary Table

| # | Severity | Issue | File(s) |
|---|----------|-------|---------|
| 1 | CRITICAL | Replay completion doesn't reset app state / stop timers | app.py, binary_loader.py |
| 2 | CRITICAL | Replay thread calls GUI methods from background thread | binary_loader.py |
| 3 | HIGH | MCA mode flag static during replay | binary_loader.py |
| 4 | HIGH | Silent data loss during large replays | traces_plotter.py, spectrum_plotter.py |
| 5 | MEDIUM | Redundant sleep in redo_replay | binary_loader.py |
| 6 | MEDIUM | Energy -1 default maps to bin 0 | binary_loader.py |
| 7 | MEDIUM | Coincidence timestamp buffers too small for replay rates | coincidence_logic_tab.py |
| 8 | MEDIUM | Trace length not validated against hardware parameter | traces_plotter.py |
| 9 | LOW | CFD warning checks wrong parent reference | binary_loader.py |
| 10 | LOW | replay_rate_hz unsynchronized (safe in CPython) | binary_loader.py |
| 11 | LOW | Missing hasattr check for cumulative_mca_data | binary_loader.py |
