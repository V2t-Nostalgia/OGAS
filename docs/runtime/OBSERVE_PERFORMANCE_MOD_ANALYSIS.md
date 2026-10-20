# OGAS third Observe: performance and Mod evidence

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


Status: implementation, offline validation and live Stellaris sampling complete;
the controlled three-phase in-game overhead comparison remains pending.

This is a read-only research surface. It does not load a shared object, inject a
command, alter Stellaris state, or register an Execution Broker action.

## What is implemented

`services/stellaris_native_runtime/research/observe_dashboard/` provides:

- automatic Stellaris PID discovery, process CPU/RSS/uptime and per-thread CPU;
- a conservative `perf` controller with start, pause, resume and safe stop;
- finite, configurable `cpu-clock:u` sampling windows with DWARF callchains;
- exact sample-based Self and Inclusive CPU aggregation by thread;
- retained raw `perf.data`, bounded aggregate windows and SQLite history;
- hierarchical, zoomable Flame Graphs and differential Flame Graphs;
- GameDate and wall-clock progress derived from archived-save evidence;
- existing Observe record/drop/backlog/coverage status without reading raw logs;
- launcher Mod order, descriptor and external-content fingerprints;
- save-declared Mod evidence kept separate from launcher configuration;
- bounded external building/technology/ship/event definition indexes;
- vanilla-catalog command/nested/payload and structural-layout differences; and
- correlation-only evidence that building, ship, research and event content
  continued through already known native command families; and
- an explicit three-phase overhead measurement and comparison tool.

The Web implementation reuses the project's standard-library
`ThreadingHTTPServer` and plain JavaScript/CSS. No front-end framework or second
application platform is introduced.

## Evidence boundaries

The dashboard uses the following labels deliberately:

| Source | What it proves | What it does not prove |
| --- | --- | --- |
| launcher `dlc_load.json` | configured order at scan time | that a running process loaded it |
| archived save `meta` | Mod list declared by that saved session | every definition instantiated in memory |
| external Mod files | definitions and content available on disk | that the engine accepted or used them |
| command catalog difference | type/layout observed with this complete Mod set | which individual Mod caused it |
| `perf` sample | a stack was on CPU at a sample instant | an actual function call count |
| save GameDate delta | real time between observed saved dates | per-tick duration between saves |

`actual_loaded_definitions.available` therefore remains false until a separate,
passive and validated engine-definition enumerator exists. Unknown commands
remain evidence only and never enter the production Action Registry.

## Server diagnostics on 2026-10-16

The target Ubuntu VM was inspected read-only:

```text
Ubuntu 24.04.2 LTS
kernel 7.0.0-38-generic
perf version 7.0.14
kernel.perf_event_paranoid = 4
kernel.kptr_restrict = 1
Stellaris ELF Build ID = c6969e60fd81d738948222a94c0b5a0841abbffc
```

The initial isolated `perf record` self-test was rejected by the kernel at
`perf_event_paranoid=4`. After explicit operator authorization on 2026-10-16,
the runtime-only sysctl value was changed to `2`; no persistent sysctl file was
created and `kptr_restrict` remained `1`. A three-second `cpu-clock:u` test at
49 Hz then captured 75 samples (zero lost samples, 695,220-byte `perf.data`) and
successfully unwound a five-frame DWARF user-space stack. The dashboard's own
`doctor --self-test` subsequently reported `available=true`,
`software_sampling=true`, and `call_stacks=true` with perf 7.0.14.

This temporary setting survives until reboot or another sysctl change. The
`doctor` command remains diagnostic only and never changes system policy. If
the host returns to paranoid level 4, process/thread CPU, memory, GameDate and
capture health remain available while hotspots and Flame Graphs are explicitly
marked unavailable.

## Start the dashboard

From the repository root on the Ubuntu host:

```bash
python3 -m services.stellaris_native_runtime.research.observe_dashboard doctor

python3 -m services.stellaris_native_runtime.research.observe_dashboard serve \
  --capture-root "$HOME/iag-captures/<third-observe-session>" \
  --baseline-catalog "$HOME/iag-captures/<vanilla-baseline>/catalog.json" \
  --output "$HOME/iag-observability/<third-observe-session>" \
  --host 127.0.0.1 \
  --port 8765
```

The profiler starts stopped. Use the Web controls or pass
`--auto-start-profiler` only after perf permission and the intended PID have
been reviewed. Defaults are deliberately sparse:

```text
software event       cpu-clock:u
frequency            19 Hz
window               5 seconds
window interval      60 seconds
call graph           dwarf,8192
observer niceness    +10
Web refresh          3 seconds
```

These defaults were reduced from the initial 49 Hz / 10-second proposal after
a live paused-Stellaris calibration on the target Xeon VM. The initial window
exceeded the 30-second symbol-expansion limit. A 19 Hz / 5-second window
produced a 459,284-byte raw sample and completed DWARF symbol expansion in
18.58 seconds (2.02 seconds user CPU, 0.41 seconds system CPU, 188,380 KiB peak
RSS), while retaining resolved engine stacks such as
`CInGameIdler::UpdateInternal -> CGameIdler::Idle -> CApplication::Run`.

Use an SSH tunnel rather than exposing the research server publicly:

```bash
ssh -L 8765:127.0.0.1:8765 USER@RESEARCH_HOST
```

Then open `http://127.0.0.1:8765/` locally.

## Storage and rotation

The output is split by purpose:

```text
session.json                 immutable session policy
status.json                  latest atomic summary
mod_inventory.json           latest Mod evidence
history.sqlite3              bounded status/window metadata
raw/*.perf.data              original perf samples
aggregates/*.json.gz         stack/hotspot aggregates
```

Defaults retain at most 8 GiB or 2,000 raw windows, 50,000 aggregate windows,
and 250,000 status rows. Removing an old raw/aggregate file updates its retained
flag but keeps the compact window metadata. The existing Observe capture keeps
its own independent segment/save rotation and remains authoritative for command
evidence.

## Web API

The browser consumes only bounded endpoints:

```text
GET  /api/status
GET  /api/windows
GET  /api/windows/<id>
GET  /api/windows/<id>/hotspots?thread=all&sort=self
GET  /api/windows/<id>/flame?thread=all
GET  /api/compare?baseline=<id>&comparison=<id>&thread=all
GET  /api/history
GET  /api/hotspot-history
GET  /api/mods
GET  /api/correlation
POST /api/profiler/start|pause|resume|stop
POST /api/mods/refresh
```

The page displays freshness separately for the dashboard and Observe capture.
When sampling stops, the last window remains inspectable but is not labelled
live.

## Reproducible overhead measurement

Do not compare phases across unrelated saves or game speeds. On a disposable
copy of one save, use equal phase durations and nearby GameDates:

```bash
# Existing Observe only; dashboard and profiler stopped.
python3 -m services.stellaris_native_runtime.research.observe_dashboard.overhead_benchmark \
  measure --label observe --game-pid "$PID" --duration 300 \
  --capture-root "$CAPTURE" --output "$OUT/overhead-observe.json"

# Dashboard running, profiler running, but do not poll the page.
python3 -m services.stellaris_native_runtime.research.observe_dashboard.overhead_benchmark \
  measure --label observe_perf --game-pid "$PID" --duration 300 \
  --capture-root "$CAPTURE" --output "$OUT/overhead-perf.json"

# Same profiler settings, with normal 3-second Web polling.
python3 -m services.stellaris_native_runtime.research.observe_dashboard.overhead_benchmark \
  measure --label observe_perf_web --game-pid "$PID" --duration 300 \
  --capture-root "$CAPTURE" --dashboard-url http://127.0.0.1:8765 \
  --output "$OUT/overhead-web.json"

python3 -m services.stellaris_native_runtime.research.observe_dashboard.overhead_benchmark \
  compare "$OUT/overhead-observe.json" "$OUT/overhead-perf.json" \
  "$OUT/overhead-web.json" --output "$OUT/overhead-comparison.json"
```

Each phase records process/system CPU, RSS, thread count, capture deltas,
request latency and saved GameDate progress. The comparison reports measured
deltas, not causal claims.

## Live validation status

The third Observe run confirmed user-space DWARF unwinding against the exact
4.4.6 ELF, retained raw and aggregate windows over many hours, and exposed
resolved main-loop, AI-worker, scripted-trigger and asynchronous save stacks.
Command, payload and state capture continued with zero reported loss during
these checks. The first concrete Mod/state correlations are documented in
[`MOD_NATIVE_HOOK_COMPATIBILITY_4_4_6.md`](MOD_NATIVE_HOOK_COMPATIBILITY_4_4_6.md).

Still pending:

- the controlled three in-game overhead phases above;
- exact high-frequency call counting in a disposable run;
- causal single-Mod comparisons where attribution matters; and
- whether optional wait/lock tracing is worth its additional cost.

Lock/wait analysis is intentionally reported as unknown. It is not inferred
from on-CPU samples, and no high-frequency timing Hook has been added.
