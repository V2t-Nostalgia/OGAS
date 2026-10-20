# Batch native Command legality research: 4.5.2

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


This extends SDK recovery into one-session, non-submitting runtime research.
It does not add Actions, Broker capabilities, another queue, or another Hook.

The first-batch measurements below are historical. Expanded population and
recovery eligibility, remaining gaps and the revision-2 acceptance procedure
are in [SDK_COMMAND_RECOVERY_EXPANSION_4_5_2.md](SDK_COMMAND_RECOVERY_EXPANSION_4_5_2.md).

## Run one complete directory

Build the runtime with the current generated SDK, load an authorized test save,
and inject that runtime **once** using the existing exact-binary loader. Leave
the game paused; no manual recruitment, object IDs or per-command clicks are
required. Do not hot-replace a library already loaded into a process.

```bash
python services/stellaris_native_runtime/tools/validate_recovered_commands.py \
  --output /path/to/new-evidence-directory \
  --candidates 16 --batch-size 16 --interval 0.05
```

`--endpoint` selects the existing Unix socket or Windows pipe. `--country` can
pin an existing native country; by default the resolver uses the observed
country, or a live database country in observer mode. The tool does not call
the loader, load saves, start the game, or run production actions. Re-running
requires a new output directory; existing evidence is never replaced.

The command directory comes from the SDK compiled into the running runtime,
not an independently maintained list in the Python runner. The same PID,
runtime instance, build and catalog are checked every batch and at completion.
The game-thread probe also returns its world identity to detect reloads.

For a single candidate the same generic implementation is available as:

```bash
python services/stellaris_native_runtime/tools/probe_command.py finish_agenda_command \
  --output new-candidate.json
```

## Safety and scheduling

The population limitations in this section describe the original first-batch
implementation. The expansion document linked above defines the current
revision-2 supported population plans and resolver coverage; the safety and
non-submission invariants remain unchanged.

Each existing `CGameIdler` dispatch handles at most one candidate:

```text
generated metadata preflight
  -> bounded native database candidate selection
  -> NativeCommandBuilder::Create
  -> named typed Populate
  -> native IsValid
  -> native deleting destructor
```

No research code calls `ReleaseForSubmission`, `PostCommand` or `Execute`.
Production Actions still use their original update-gated Prepare/Post/Verify.
Only `validate_recovered_command` can run when `run_game_update=false`; event
queries and production requests retain their old scheduling behavior. A loaded
world and resolvable country are required before calling a Factory. The
`run_game_update` flag is reported, but is not itself a game-pause indicator.

The generator marks only tightly covered, named, writable POD/reference
payloads as flat. Delegated/nested serializers, gaps, duplicated fields and
uncertain offsets are excluded. In particular, uniform-list serializer count
arguments are **containers**, not scalar payloads. Preflight verifies native
Factory/IsValid/destructor/Token entry points and VTable slots before allocation;
the actual Factory result must have the expected VTable.

Automatic population currently supports known-profile `TPdxRef` databases for
country, fleet, system, leader, resolution, war, species, situation, spy network
and espionage operation. Handles include their generation bits and are checked
with the existing object resolver. The scan is bounded to 16,384 slots and 16
candidates per type; fleets controlled by the selected country are preferred.
Only IDs survive parameter selection, and they are resolved anew each request.
Booleans default to false, including force/override flags. Foreign-country roles
remain on the selected country until a semantic selector is reviewed. Numeric
indices, enums, strings, static-definition pointers and nested ownership are not
guessed. Missing databases, relationships and scalar semantics are research
gaps, not evidence that those commands are unusable.

One candidate is processed per request. A false result can select the next
bounded combination on a later Idle; true results stop that command's search.
The runner adds a configurable delay and checks its wall-clock budget. This
limits *dispatch* work, but cannot preempt a native `IsValid` already executing.
No unsafe signal-based recovery or additional invasive Hook is installed.

## Evidence

The directory contains:

- `catalog.json`: exact runtime PID/instance/build and the complete SDK directory.
- `progress.jsonl`: flushed started/completed records for every attempted request.
- `command-NNNN.json`: each completed command's candidate results.
- `report.json`, `report.md`: all catalog entries, totals, skips and unresolved semantics.

The typed `iag.native_command_validation.v2` record distinguishes:

| Status/flag | Meaning |
|---|---|
| `structure_checked` | Runtime VTable/Token/lifecycle metadata passed preflight; no Factory claim. |
| `native_valid` | Create/Populate/IsValid=true/Destroy completed. |
| `native_invalid` | Same lifecycle completed, but game rules rejected the candidate. |
| `structure_failed` | Factory/lifecycle/layout evidence did not agree. |
| `missing_parameters` | The required live object is absent or not safely resolvable. |
| `not_tested` | Unsafe layout, missing semantics, exhausted candidate index, or batch not reached. |
| `call_exception` | A C++ exception escaped the native call; batch stops. |
| `interrupted` (runner) | A request started without a correlated result; not a claimed native fault. |

Timings are game-thread **elapsed microseconds**, not CPU samples or inferred
function call counts. Raw GameDate words are included where the exact profile
provides that field. A finite set of negative candidates is not proof that no
legal candidate exists. A false native result is not a reverse-engineering
failure, and a true result is not execution evidence.

Native memory faults cannot safely be recovered by ordinary C++ catch blocks.
A transport interruption therefore aborts the runner, retains completed
records, leaves the remaining entries untested, and identifies the last started
request without asserting that it caused a game crash. No automatic reinjection
or replay occurs. A Factory/VTable mismatch also stops the batch because its
unknown allocation cannot safely be destroyed.

The Windows build shares this endpoint and safety checks, but its automatic
object resolver coverage depends on the current Windows profile. Linux results
must not be represented as Windows runtime validation.

## Tests

The native fixture uses real builder/probe code with controlled native-style
databases. It covers automatic selection, true/false validity, C++ exceptions,
destruction, missing candidates, unsafe layouts and the paused/production
scheduling truth table. Python tests cover complete catalog traversal, bounded
retry, session replacement, connection loss, immutable evidence directories,
and rejection of false lifecycle/execution claims.

See the live-run record below for measured coverage. Neither this batch nor SDK
discovery changes production verification levels.

## Live run: 2026-10-19

Run `sdk-batch-abf65646014041b5948bd4afad406a1b` completed in **65.082 seconds**
on the already-running Linux PID **39175**. There was **one Runtime injection**,
no game restart and no save load during testing. The initial/end catalogs and
all nonzero world identities agree. The game remained alive after completion.

- ELF Build ID: `121ecb516cbc5f1d39917fbcc36620534384e2c2`.
- Runtime SHA-256: `52e0313156fce1b3c47fcb092300e48e7ccba7423635579ba746faec27af74dd`.
- World identity: `0x55e11a1321a0`; selected country: `0` throughout.
- Remote evidence: `<RESEARCH_HOME>/iag-captures/sdk-batch-20261019-01/`.
- Preserved source/build: `/tmp/iag-sdk-batch-20261019-01/` (do not rebuild the
  mapped shared-library file while this game process is running).
- Local [complete report](https://github.com/V2t-Nostalgia/OGAS-research-evidence/blob/ccd7bfdfa33e749d2ea3bffd4586573a629ee08b/paths/50/504902766beb17eb9025e6523c35e8ef3cb358e783ffeece86ef730b5383c4d3.md)
  and [per-command table](https://github.com/V2t-Nostalgia/OGAS-research-evidence/blob/ccd7bfdfa33e749d2ea3bffd4586573a629ee08b/paths/6c/6cdf682f8cc94c4786995ab28b75b9a0241893c42a70408c01fbde5368c4051a.md).

| Measured coverage | Count |
|---|---:|
| SDK directory entries traversed | 351 |
| Runtime structure preflight passed | 331 |
| Distinct Commands constructed, populated, validated and destroyed | 40 |
| Distinct Commands with at least one IsValid=true | 24 |
| Distinct Commands with only sampled IsValid=false results | 16 |
| Native validator calls | 227 |
| True / false native returns | 24 / 203 |
| Constructed / destroyed native objects | 227 / 227 |
| C++ exceptions / transport interruptions / batch aborts | 0 / 0 / 0 |
| Missing live candidates | 10 |
| Unsafe or unmapped entries skipped | 281 |
| Structure/lifecycle preflight failures, without allocation | 20 |

The 20 preflight failures comprise 15 unresolved `token_0_*` entries and five
queue-item priority/removal templates without a resolved Factory/lifecycle.
They never reached construction. Of the 281 other skips, 195 have nonflat or
incomplete serializer layouts, 50 lack a typed object resolver, and 36 lack
scalar semantics or an eligible game-object scope. All 10 missing-candidate
cases require a `CResolution` absent from this world.

Examples returned by the same generic implementation (not bespoke probes):

| Command | Automatically populated native fields | Result |
|---|---|---|
| `CHireLeaderCommand` | country `0`, leader `83886080` | true |
| `CCreateNewFleetTemplateCommand` | country `0`, is_human_request `false` | true |
| `CCountryResetSpeciesRightsCommand` | country `0`, species `0` | true |
| `CSetForceEvasivePathfindingCommand` | fleet `0`, value `false` | true |
| `CFinishAgendaCommand` | country `0` | true |

The Leader handle includes generation bits (`5 << 24`), obtained from the
native database rather than guessed from a slot number. None of these objects
was submitted. Some native validators are permissive: true does not establish
the desired gameplay semantics, authority, resource reservation or execution.

Reported probe timing fields sum to **34.696 ms**; the validator timing fields
sum to **1.324 ms**. Maximum recorded probe/validator times were **292 / 176 us**.
These are instrumented elapsed intervals, not process CPU overhead measurements;
they exclude IPC, throttling and the tail of JSON serialization. The full
65-second run includes those waits and the intentional inter-request delay.

This first live batch was **not paused**: raw GameDate advanced from `63018864`
to `63022272`, and all 227 native calls observed `run_game_update=true`. Thus it
does not claim to verify the false-flag path or real paused-game behavior.
The subsequent paused repeat below uses that same process/library without
another injection. The false-flag scheduling truth table remains fixture-tested.

Next coverage work is explicit in the report: recover typed object resolvers
for colony/planet/building/queue/template and other missing classes, then map
enums/indices, definition pointers, strings and nested ownership. Do not obtain
coverage by weakening the flat-layout filter or guessing pointer values.

The initial loader's stdout was lost to an evidence-export error after loading;
the empty `injection.log` was preserved rather than overwritten. No second
injection was attempted. `/proc` mappings, the runtime-ready log and the live
catalog's PID/instance confirm the existing load; `session.json` records this
evidence limitation explicitly.

## Paused repeat in the same process

After the player paused the existing game, the complete directory was processed
again, with no restart, save load, library rebuild or reinjection. The runner
checked the first run's catalog against the current PID/instance before starting.
Run ID: `sdk-batch-f7885f371219446182cfdb400e3fd685`.

| Paused-run measurement | Result |
|---|---:|
| Wall-clock duration | 37.235 s |
| Catalog entries / structure preflights passed | 351 / 331 |
| Distinct Commands with native validation | 40 |
| Commands with true / only false results | 25 / 15 |
| Native calls / true returns / false returns | 229 / 25 / 204 |
| Missing candidates / skipped / preflight failures | 10 / 281 / 20 |
| Raw GameDate, before and after every sampled call | 63093168 |
| Distinct GameDate values observed | 1 |
| C++ exceptions / interruptions / aborts | 0 / 0 / 0 |

All 229 paused-game native calls completed while `run_game_update=true`. Thus
**this flag is not the game-pause state**, and its original guard did not block
research in this paused 4.5.2 session. The research-only false-flag allowance is
separately fixture-tested; it has not been observed live and is not claimed as
live-verified. Production Prepare/Post/Verify retain their original guard.

The two runs together made **456 native validator calls** across the same 40
distinct Commands, with **456 constructed and 456 destroyed objects**. Across
both rounds, 25 distinct Commands returned true at least once; the other 15 only
returned false for sampled candidates. The newly positive command in the paused
round was `set_espionage_operation_auto_accept_event_command`.
No Post/Execute or production verification promotion occurred.
The game's PID, runtime instance and loaded-world identity stayed unchanged.

Paused-run probe/validator recorded intervals totalled **39.386 / 2.097 ms**;
their maxima were **246 / 159 us**. As above, these are elapsed timing fields,
not CPU usage percentages or a profiling-overhead benchmark.

The paused JSON report is
[`paused-batch/report.json`](https://github.com/V2t-Nostalgia/OGAS-research-evidence/blob/ccd7bfdfa33e749d2ea3bffd4586573a629ee08b/paths/49/498606de0b8f65cee1fd83780441cd8acb6dc10517611d288ac496896efde467.md);
its full per-command table and journal are alongside it. `post_batch_health.log`
preserves the surviving process, mapped library and runtime-ready log line.
