# Event, situation and event-chain discovery (Stellaris 4.4.6 Linux)

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


Status: statically recovered and compile-verified; live hook validation pending.

This document defines the third passive stream used by the long-running
`human_ai` observer experiment. It complements command and polymorphic-payload
capture. It is research instrumentation, not an Execution Broker backend and
does not expose an executable semantic action.

## Exact-build boundary

The probe accepts only Linux ELF Build ID:

```text
c6969e60fd81d738948222a94c0b5a0841abbffc
```

Every inline hook also checks the exact instruction bytes it replaces. A build
ID or prefix mismatch fails closed before any patch is installed. Linux
addresses below are module-relative semantic anchors; they are not Windows
addresses and must not be copied into a different build.

## Captured lifecycle

The state stream records:

```text
CEvent::Execute
  event script key
  event definition ID
  first title key
  first description key
  option localization keys
  selected option index and execution mode
  root scope type/object/hash

CGameState::AddOpenPlayerEvent
COpenPlayerEvent::Uninitialize
  open-event ID, country and event definition

CGameState::CreateNewSituation / DestroySituation
CSituation::UpdateStage
CSituation::SetCurrentApproach
CSituation::AddDelayedEvent
  situation ID, country, type key, progress, stage, approach and delayed event

CCountryEventManager::BeginEventChain / EndEventChain
  country, chain definition ID/key and initial scope
```

The writer schema is `iag.stellaris.event_state_probe.v1`; the default file is
`/tmp/iag-stellaris-state-probe.jsonl`.

## Hook map

| Function | Linux 4.4.6 offset | Captured role |
|---|---:|---|
| `CGameState::AddOpenPlayerEvent` | `0x18124c0` | player-visible event opened |
| `COpenPlayerEvent::Uninitialize` | `0x21cead0` | player-visible event removed |
| `CGameState::CreateNewSituation` | `0x1811f00` | situation creation |
| `CGameState::DestroySituation` | `0x1811f20` | situation destruction |
| `CSituation::UpdateStage` | `0x1c17750` | stage/progress transition |
| `CSituation::SetCurrentApproach` | `0x1c19f00` | approach transition |
| `CSituation::AddDelayedEvent` | `0x1c1c650` | situation-owned delayed event |
| `CCountryEventManager::BeginEventChain` | `0x20a2d80` | chain start |
| `CCountryEventManager::EndEventChain` | `0x20a2e60` | chain end |
| `CEvent::Execute` | `0x21d3560` | common event execution |

Supporting read-only functions:

| Function/data | Offset | Use |
|---|---:|---|
| event manager singleton | `0x54e4648` | event numeric ID to script key |
| `CEventManager::GetLogID(int)` | `0x21eff10` | owned event script-key string |
| `CEvent::GetFirstDescKey()` | `0x21d61b0` | owned description key |
| event option first-key getter | `0x21f4110` | owned option localization key |
| `CString` destructor | `0x16584b0` | release returned owned strings |
| `CString` data/size | `0x3e4be60` / `0x3e4c870` | bounded key copy |

## Recovered layouts

All offsets are for the exact Linux build.

### Event definition

```text
+0x008  database/event definition ID
+0x110  title CString
+0x5e0  option container
          +0x08 data pointer
          +0x14 count
          entry stride 0x10
```

The open-player-event object exposes its event handle at `+0x08`, scope at
`+0x10`, open-event ID at `+0x180`, and country ID at `+0x184`.

`CEventScope` is `0x170` bytes. Its root `CScopeObjectReference` starts at the
scope address, is `0x28` bytes, and exposes scope type at `+0x08` and object ID
at `+0x10`. The probe records a bounded hash of the complete scope as evidence;
it does not interpret every nested scope entry.

### Situation

```text
+0x008  generation-bearing situation ID
+0x204  country reference
+0x208  situation type pointer
+0x210  current approach pointer
+0x218  raw fixed-point progress
+0x570  stage index
```

A database situation type stores its numeric ID at `+0x08` and key CString at
`+0x10`. The selected approach key is read from the statically recovered
approach CString at `+0x08`.

### Event chain

An event-chain definition stores database ID at `+0x08` and key CString at
`+0x10`. `CCountryEventManager` is embedded at country `+0x26c8`; the probe uses
that relationship to record the owning country ID at country `+0x20`.

## Event text boundary

The hook records stable localization keys, not a fully rendered UI string.
Dynamic event text can depend on scope, scripted localization and RNG. Calling
the dynamic render path from an observation hook could alter simulation state
or produce text for the wrong scope, so it is deliberately excluded.

Use the offline resolver instead:

```bash
python3 resolve_event_content.py \
  --states /tmp/iag-stellaris-state-probe.jsonl \
  --game-root "$HOME/.local/share/Steam/steamapps/common/Stellaris" \
  --language simp_chinese \
  --output "$capture/event-content-simp-chinese.json"
```

The resolver reads loose base-game localization and DLC zip members. It keeps
scope tokens and scripted localization as templates and records the exact file
or archive member that supplied each value.

## Hot-path safety

Every hook copies a fixed-size event to an `O_NONBLOCK` pipe and immediately
returns to the original function. JSON, address formatting, localization and
disk I/O happen off the game thread. The state writer rotates at 64 MiB or 15
minutes and respects the same filesystem reserve as the other probes. If the
pipe or writer cannot keep up, evidence is dropped and later records expose the
drop counter; the game is never backpressured.

Event definitions are expanded only once per process. Later executions still
record identity, option index, scope and timing without repeatedly copying all
text keys.

## Command-probe additions

Command schema v3 adds two statically recovered layouts:

| Command | vptr offset | object/captured bytes |
|---|---:|---:|
| `CSetSituationApproachCommand` | `0x42f0560` | `0x50 / 0x50` |
| `CExecuteEventAfterCommand` | `0x437a798` | `0x198 / 0x28` |

It also records eight module-relative virtual-method entries for the first
observation of every command and nested vtable. For an unknown derived
`CDiplomaticAction`, only the statically confirmed 0x50-byte common base prefix
is captured and `known_nested_complete` remains false. This improves later
static matching without guessing derived sizes.

## Long-run coverage and early review

`long_run_capture.py` now consumes command, payload and state streams. Its
`coverage.json` reports unique command/nested/payload types, event keys,
situation type keys and event-chain keys. The following lifecycle targets are
tracked explicitly:

```text
event_executed
event_content
event_options
open_event_added / open_event_removed
situation_created / situation_destroyed
situation_stage_changed
situation_approach_changed
situation_delayed_event
event_chain_started / event_chain_ended
```

`ready_for_early_review` becomes true only after every target has been seen and
the configured no-new-key/type plateau has elapsed. This flag is advisory. The
manager never stops Stellaris, disables `human_ai`, detaches a probe, or deletes
evidence. A human can request a checkpoint at any time and decide that the
remaining rare target is unnecessary.

## Confidence and pending runtime checks

### A. Static analysis and compilation confirm

- symbol identities and the module-relative offsets above;
- exact hook prefixes for the target ELF;
- listed field offsets and bounded string ownership rules;
- a nonblocking, background-writer implementation;
- GCC 13 `-Wall -Wextra -Wpedantic -Werror` build and rotating-log test;
- Python catalog, coverage, state analysis and localization-resolution tests.

### B. High probability; live validation required

- all ten hooks coexist safely in one loaded library;
- begin/end chain boolean return interpretation matches natural gameplay;
- the situation approach key is valid for every observed situation subtype;
- open-event input handles and scopes remain readable at the selected post-call
  observation points.

Validation: pause a disposable observer game, load all three passive libraries
once, verify matching `probe_started` records, trigger one known event and one
situation, then compare JSON identities with the next autosave before
unpausing a long `human_ai` run.

### C. Campaign-dependent

- whether natural AI reaches every rare situation/chain lifecycle in one run;
- which event descriptions use runtime substitutions that cannot be resolved
  to final prose offline;
- which first-seen unknown command fingerprints correspond to reusable action
  families.

These are precisely what the next full run and its intermediate coverage
checkpoints are intended to answer.
