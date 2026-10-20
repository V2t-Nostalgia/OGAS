# Stellaris command discovery probe

This directory contains a **research-only, read-only** runtime probe. It is not
an execution backend and must never be registered with the Execution Broker.

For the exact Stellaris 4.4.6 Linux build recorded in `command_probe.cpp`, the
probe observes two already-mapped points in the native command pipeline:

```text
CSession::Post(CCommand*)
    -> network path, when applicable: CNetworkServer::DispatchOrder(CCommand*)
    -> CSession::ProcessSynchronousCommands() virtual Execute dispatch
```

It writes newline-delimited JSON to
`/tmp/iag-stellaris-command-probe.jsonl` (override with
`IAG_COMMAND_PROBE_LOG`). Every event includes the concrete RTTI class, common
`CCommand` header, module-relative caller, thread ID, and a first-seen stack for
each command vtable. `execute_sync` records the common dispatch immediately
before the original virtual `Execute` call. The game-thread hooks only copy a
fixed-size event into a nonblocking pipe; symbol resolution, demangling, and
file I/O happen on a background writer thread.
The exact-build `CTurnTickCommand` vtable is filtered before enqueueing because
tick traffic carries no action semantics and otherwise dominates the capture.
For long-running sessions the background writer rotates each stream at 128 MiB
or 15 minutes. Closed segments receive a `.ready` suffix; the hot path never
compresses them. Recording stops instead of consuming the filesystem's final
5 GiB, and a later successful event reports the resulting
`writer_dropped_before` count. These defaults can be adjusted with
`IAG_COMMAND_PROBE_ROTATE_BYTES`, `IAG_COMMAND_PROBE_ROTATE_SECONDS`,
`IAG_PAYLOAD_PROBE_ROTATE_BYTES`, `IAG_PAYLOAD_PROBE_ROTATE_SECONDS`, and
`IAG_PROBE_MIN_FREE_BYTES`.

Schema `iag.stellaris.command_probe.v3` additionally copies bounded layouts for
exact-build types recovered statically. Besides fleet commands and nested
`CFleetOrder` objects, the allowlist covers one-shot market commands, the
scalar prefix of event-option selection, selected war/diplomacy wrappers, and
the nested `CDeclareWarAction`. It also covers the statically recovered
`CSetSituationApproachCommand` and `CExecuteEventAfterCommand` prefixes. The
record exposes captured and full object
sizes separately, `known_command_hex`, `known_nested_hex`, nested RTTI and
bounded related fleet IDs. First-seen command and nested vtables carry an
eight-method module-relative structural fingerprint. Unknown RTTI continues to
expose only the common `CCommand` header. A nested diplomatic action may expose
only its statically confirmed common 0x50-byte base prefix and is explicitly
marked incomplete. The probe never guesses a derived object size or follows an
unclassified payload pointer.

`payload_probe.cpp` is a companion observer for polymorphic payloads hidden by
generic command wrappers. It records nested `CFleetOrder` objects written by
`CWriter::Write(int, CPersistent const*)` and `CBuildableBase` objects written
by `CItemFactory<CBuildableBase>::Write`. Its separate JSONL stream is
`/tmp/iag-stellaris-payload-probe.jsonl`. This distinguishes, for example,
attack orders from movement orders and ship construction from building queues
without adding any execution capability.

`event_state_probe.cpp` is a third exact-build, passive stream. It records event
execution and open-event lifetime, event script/title/description/option keys,
situation creation/destruction/stage/approach/delayed-event changes, and event
chain begin/end. Its stream is
`/tmp/iag-stellaris-state-probe.jsonl` (override with
`IAG_STATE_PROBE_LOG`). The hook never evaluates dynamic event descriptions:
that path can depend on scope and RNG. Use `resolve_event_content.py` after the
capture to resolve the stable localization keys from base-game and DLC files.

The intended discovery loop is:

1. inject the probe while Stellaris is stopped in a debugger;
2. verify the probe status and a known command pair;
3. enable `human_ai` in the game console;
4. correlate JSONL command events with observed AI activity;
5. recover layouts and serializers statically from each confirmed RTTI type.

The probe deliberately has no socket, request parser, command constructor, or
write API. Unknown commands remain discovery evidence and cannot become a
production action until their semantics and execution chain are independently
verified.

The separate [`ui_bridge/`](ui_bridge/) probe records the live-verified native
conversation panel, Application-scoped message lists, and bidirectional
`IAGUI1` process bridge. It is presentation/IPC research and is not an
execution backend.

The proposed single-process, per-country observer takeover boundary is
documented in
[`docs/runtime/OBSERVER_AI_COUNTRY_TAKEOVER_4_4_6.md`](../../../docs/runtime/OBSERVER_AI_COUNTRY_TAKEOVER_4_4_6.md).
It uses `CCountryAI::PostAICommandsToSession()` as the country-specific gate;
it does not globally replace player, system, or unmanaged-AI commands.

`observer_takeover_probe.cpp` is the exact-build, one-shot implementation used
to validate that boundary. It starts in read-only observation mode and exposes
a user-owned (`0600`) local Unix socket. It will not suppress a target
country's batch until a reviewed `move_fleet` action has prepared successfully
and every queued command exposes a module-owned native deleting destructor.
After one replacement it becomes verification-only and cannot replace another
batch without an explicit new arm request.

Build and inspect it with:

```bash
cmake -S services/stellaris_native_runtime/research \
  -B /tmp/iag-observer-takeover-build -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build /tmp/iag-observer-takeover-build \
  --target iag_stellaris_observer_takeover_probe -j4

python3 observer_takeover_client.py status
python3 observer_takeover_client.py arm-move \
  <generation-bearing-country-id> <fleet-id> <destination-system-id>
python3 observer_takeover_client.py status
```

The live evidence stream is
`/tmp/iag-stellaris-observer-takeover.jsonl`. The 2026-09-28 experiment
replaced country `1`'s three-command batch with `move_fleet(7, 114)`, confirmed
the native movement-order postcondition, observed subsequent non-empty batches
from unmanaged countries, and left Stellaris running. Full evidence and the
remaining production boundary are in the document linked above.

This remains a disposable-save research probe. Do not hot-unload it, register
it as an Execution Broker backend, or interpret its one-shot success as broad
command-coverage validation.

Analyze a completed or live capture with:

```bash
python3 analyze_capture.py \
  --commands /tmp/iag-stellaris-command-probe.jsonl \
  --payloads /tmp/iag-stellaris-payload-probe.jsonl \
  --states /tmp/iag-stellaris-state-probe.jsonl \
  --require-zero-drops
```

Decode the guarded fleet layouts into comparison-friendly semantic evidence
with:

```bash
python3 decode_fleet_movement.py \
  /tmp/iag-stellaris-command-probe.jsonl \
  --phase session_post
```

The decoder distinguishes replace, append and prepend queue modes and retains
unknown booleans under neutral `flag_*` names. Its output is evidence for
analysis and fixture creation, not a production action request format.

Decode the 16 mapped nested diplomatic action layouts with:

```bash
python3 diplomatic_action_decoder.py \
  /path/to/segments/commands/*.ready.gz
```

The decoder accepts both the earlier capture, where most actions contain only
the common `0x50`-byte `CDiplomaticAction` prefix, and new probe segments with
the complete derived object. It always reports actor and recipient as split
generation-bearing references. Derived fields are emitted only when the full
layout was captured, and `complete=false` keeps old evidence from being
mistaken for a complete semantic target.

The analyzer treats `CCountryAI::PostAICommandsToSession()` in a first-seen
stack as an AI-origin fingerprint. Generic command payloads are considered
final only when their serialization occurs on the inferred game thread after
the matching `CSession::Post`. Objects serialized only by AI worker threads
are reported separately as candidates, never as executed commands.

Do not unload the shared object from a live process. The inline trampolines are
process-lifetime instrumentation.

## Long-running passive capture

`long_run_capture.py` supervises the three read-only streams without attaching to
or controlling Stellaris. It compresses only `.ready` segments, maintains a
command/payload/state catalog, validates and archives stable `.sav`
files, and records the active probe PID plus command sequence high-water marks
with each save. Run it before probe injection and keep its output outside the
Stellaris save directory:

```bash
python3 long_run_capture.py \
  --game-pid "$(pgrep -n stellaris)" \
  --save-root "$HOME/.local/share/Paradox Interactive/Stellaris/save games" \
  --output "$HOME/iag-captures/human-ai-$(date -u +%Y%m%dT%H%M%SZ)"
```

The manager lowers its own CPU priority, can be restarted against the same
output directory, and never sends a game command. Its `health.json`,
`coverage.json`, `catalog.json`, `segment_index.jsonl`, and `save_index.jsonl`
are intended for later automated analysis. `coverage.json` explicitly lists
missing event/situation/chain lifecycle targets and a no-new-discovery plateau;
it supports a human decision to end a run early but never stops the game. The
save association is a recorded stream
high-water mark, not a claim that filesystem save completion and command
submission are one atomic operation. See
[`LONG_RUNNING_AI_COMMAND_CAPTURE_4_4_6.md`](../../../docs/runtime/LONG_RUNNING_AI_COMMAND_CAPTURE_4_4_6.md)
for the operating and recovery procedure.

The third-Observe performance and Mod companion is implemented in
[`observe_dashboard/`](observe_dashboard/). It reads the manager's compact
`health.json`, `catalog.json`, `coverage.json`, and save index; the browser never
opens the growing raw JSONL streams. It adds controlled Linux `perf` windows,
thread-aware hotspots, real sampled-stack Flame Graphs, bounded history, Mod
fingerprints and a reproducible overhead benchmark. It does not load any probe
or inject any command. See
[`OBSERVE_PERFORMANCE_MOD_ANALYSIS.md`](../../../docs/runtime/OBSERVE_PERFORMANCE_MOD_ANALYSIS.md)
for the evidence boundaries and operating procedure.
The market, event-option and war/diplomacy layouts recovered from that capture
are recorded in
[`MARKET_EVENT_WAR_COMMANDS_4_4_6.md`](../../../docs/runtime/MARKET_EVENT_WAR_COMMANDS_4_4_6.md).

## AI megastructure exact-call counter

`ai_megastructure_counter_probe.cpp` is an isolated, exact-build research
probe for the `HandleCivilianFleets -> FindBestPositionForMegaStructure ->
CalcAIWeight -> scripted trigger -> owned fleet list` hotspot. It is not part
of the native runtime, passive Observe bundle, or Execution Broker.

Never add it to a protected long-running session. First build and validate it
against a disposable copy of one save:

```bash
cmake -S services/stellaris_native_runtime/research \
  -B /tmp/iag-ai-counter-build -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build /tmp/iag-ai-counter-build \
  --target iag_stellaris_ai_megastructure_counter_probe -j4

# Explicit arming is mandatory. Start with only the three outer hooks.
IAG_AI_MEGA_COUNTER_ENABLE=1 \
IAG_AI_MEGA_COUNTER_MODE=outer \
IAG_AI_MEGA_COUNTER_LOG=/tmp/iag-ai-counter.jsonl \
  <isolated probe loader>
```

Use `IAG_AI_MEGA_COUNTER_MODE=full` only after the outer-mode overhead phase
passes. Pause aggregation with:

```bash
touch /tmp/iag-stellaris-ai-megastructure-counter.pause
rm /tmp/iag-stellaris-ai-megastructure-counter.pause
```

Analyze one probe instance with:

```bash
python3 analyze_ai_megastructure_counter.py \
  /tmp/iag-ai-counter.jsonl \
  --output /tmp/iag-ai-counter-summary.json
```

Exact entries, sampled CPU hits and repeated opaque input tuples are separate
metrics. A repeated tuple is not proof that a scripted-trigger result is safe
to cache. See
[`AI_MEGASTRUCTURE_HOTSPOT_INVESTIGATION_4_4_6.md`](../../../docs/runtime/AI_MEGASTRUCTURE_HOTSPOT_INVESTIGATION_4_4_6.md).

## Mod/native compatibility audit

Compare a vanilla catalog, Mod-session catalog, content inventory and optional
save without attributing unequal-run differences to a Mod:

```bash
python3 analyze_mod_hook_compatibility.py \
  --baseline-catalog "$HOME/iag-captures/<vanilla>/catalog.json" \
  --modded-catalog "$HOME/iag-captures/<modded>/catalog.json" \
  --mod-inventory "$HOME/iag-observability/<modded>/mod_inventory.json" \
  --save "$HOME/iag-captures/<modded>/saves/<snapshot>.sav" \
  --output /tmp/iag-mod-hook-compatibility.json
```

Older catalogs that did not record `layout_signatures` are explicitly marked
unavailable for layout comparison. A missing field is never reported as a
changed command layout. See
[`MOD_NATIVE_HOOK_COMPATIBILITY_4_4_6.md`](../../../docs/runtime/MOD_NATIVE_HOOK_COMPATIBILITY_4_4_6.md).

## Windows structure matching

The Windows 4.4.6 executable is stripped. Use the Linux symbols as semantic
anchors, then recover and validate a separate Windows ABI/profile:

- `analyze_windows_command.py` locates a command token method, its vtable and
  construction callsites;
- `find_windows_game_idler.py` ranks the Windows game-loop marshal point;
- `find_windows_calc_ftl.py` ranks the fixed-point FTL coordinate helper;
- `windows/` contains the exact-build, one-action live research harness.

Do not copy Linux offsets or object sizes into Windows code. The live-verified
`move_fleet` mapping and PE identity are recorded in
`docs/runtime/NATIVE_FLEET_MOVE_HOOK_4_4_6.md`.

## Offline native producer discovery (4.5.2)

`discover_command_producers.py` reads an exact, symbolized local ELF and its
recovered SDK. It inventories UI/AI producers, retains full selected function
bytes and instruction evidence, and reuses the existing instruction-boundary
check for direct-call xrefs. It does not connect to a game, invoke native code,
load a save, or change any production verification state. Output directories
must be new; missing requested function RVAs and unresolved indirect edges
remain explicit. Install `../tools/sdk_recovery/requirements.txt` for decoding.

The evidence-backed UI/AI chains, explicit-Country candidate/rule interfaces,
save restoration and deterministic-fixture limits are documented in
[`NATIVE_COMMAND_PRODUCER_DISCOVERY_4_5_2.md`](../../../docs/runtime/NATIVE_COMMAND_PRODUCER_DISCOVERY_4_5_2.md).
