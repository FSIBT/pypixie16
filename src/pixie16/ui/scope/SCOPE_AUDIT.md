# pixie16-scope Code Audit

Full code review of the scope application, performed 2026-05-21 against
branch `bugfix/pixiescope-issues-v2`.

## Open Items — Verified Real Issues

These are genuine issues confirmed by code reading. They are not crash-critical
for typical lab use but should be addressed over time.

### Medium Priority

**Polarity not applied to persistence histogram** (`traces_plotter.py:1256-1273`)
The persistence histogram receives raw traces before polarity correction. Channels
with inverted polarity show un-inverted traces in the persistence 2D view. The main
trace display is correct; only the background heatmap is affected.

**Parameter cache not refreshed during acquisition** (`hardware_manager.py:72,129`)
`parameter_cache` is populated at init and updated on writes, but if parameters are
changed by an external tool while the scope is running, the cache goes stale.
Workaround: click Read HW to refresh. Could add periodic cache refresh.

**500MHz module timing constraints placeholder** (`parameter_validation.py:52-58`)
The 500MHz module type copies 100MHz constraints with a "Same as 100MHz for now"
comment. If 500MHz modules are used in the lab, these ranges need updating
(2ns clock vs 10ns).

**`compute_hardware_traces()` returns None without logging** (`traces_plotter.py:2308-2425`)
Multiple failure paths (filter too long, empty trace, etc.) return None silently.
Adding a print/log at each return path would help users understand why a filter
overlay disappeared.

### Low Priority

**Auto-save trace length filtering** (`auto_save_buffer.py:266-277`)
When `TRACE_LENGTH` changes mid-run, traces of different lengths exist in the
buffer. The save function keeps only the most common length. This is documented
behavior and the right default, but a warning in the saved file's metadata about
dropped traces would be helpful.

**Coincidence timestamp buffers small** (`coincidence_logic_tab.py:191,199`)
`ch_a_timestamps` and `ch_b_timestamps` are `deque(maxlen=500)`. At high replay
rates with uneven channel activity, the faster channel can push out timestamps
before coincidence pairing finds them. Increasing to 5000 would cost negligible
memory.

## Known Limitations (By Design)

These are documented in MAINTAINER_GUIDE.md and are hardware/SDK constraints,
not software bugs.

- **SDK not thread-safe** — all calls serialized on GUI thread (verified, guards intact)
- **Parameters require run stopped** — stop/write/restart flow (verified, working)
- **TRIGGER_THRESHOLD capped by DSP** — read-back logging in place (verified)
- **Large filter params can segfault in SDK** — software guards return None (verified)
- **Mixed trace lengths** — buffers cleared on change, save filters by length (verified)
- **hardware_params global not per-channel** — mitigated by per-channel load on switch (verified)
- **Coincidence false positives** — by design, only checks most recent event (verified)
