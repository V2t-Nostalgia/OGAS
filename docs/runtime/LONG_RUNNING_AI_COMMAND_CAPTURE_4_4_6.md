# Long-running AI command capture (Stellaris 4.4.6 Linux)

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


Status: command/payload path live-verified on 2026-10-03; event/state extension
compile-verified and awaiting the next live run.

This runbook describes passive, process-lifetime discovery of native Stellaris
commands while `human_ai` drives countries in observer mode. It is a research
facility, not an Execution Broker backend. It cannot construct, submit,
suppress, or replace a command.

## Safety boundary

The capture preserves the previously verified hot-path design:

```text
CSession::Post / DispatchOrder / synchronous Execute dispatch
event / open-event / situation / event-chain lifecycle hooks
  -> copy one bounded event into an O_NONBLOCK pipe
  -> immediately continue the original Stellaris call

background probe writer
  -> RTTI demangle and JSON serialization
  -> bounded file rotation

long_run_capture.py (separate process, nice +10)
  -> gzip closed segments
  -> update type catalog and health state
  -> validate and archive completed saves
```

The game thread never waits for disk, compression, save parsing, or the capture
manager. A full pipe drops evidence and increments `dropped_before`. A stalled
or full capture filesystem makes the background writer discard evidence; after
capacity returns, the next event records `writer_dropped_before`. The default
filesystem reserve is 5 GiB. Evidence loss is preferable to slowing the game or
endangering its autosaves.

`CTurnTickCommand` remains excluded because it is high-volume clock traffic,
not an action. Every other command reaching the three common command points is
recorded. The payload companion remains deliberately bounded to fleet
order/action polymorphs and `CBuildableBase`; tracing every `CPersistent` write
would capture general state serialization and violate the low-impact goal.

## Version boundary

All three libraries fail closed unless the main executable has ELF Build ID
`c6969e60fd81d738948222a94c0b5a0841abbffc` and every patched function begins
with its reviewed instruction prefix. Offsets and the AI-origin stack marker
are for Stellaris 4.4.6 only.

The long-running manager is version-neutral because it only consumes JSONL and
save files. A future game version still requires new, live-verified probe
signatures before injection.

The state extension, exact offsets, recovered layouts, offline localization
boundary and pending live checks are documented in
[`EVENT_SITUATION_DISCOVERY_4_4_6.md`](EVENT_SITUATION_DISCOVERY_4_4_6.md).

## Rotation and output

Probe defaults:

| Setting | Default |
|---|---:|
| command segment size | 128 MiB |
| payload segment size | 128 MiB |
| state segment size | 64 MiB |
| time rotation | 15 minutes |
| filesystem reserve | 5 GiB |

Environment overrides:

```text
IAG_COMMAND_PROBE_LOG
IAG_COMMAND_PROBE_ROTATE_BYTES
IAG_COMMAND_PROBE_ROTATE_SECONDS
IAG_PAYLOAD_PROBE_LOG
IAG_PAYLOAD_PROBE_ROTATE_BYTES
IAG_PAYLOAD_PROBE_ROTATE_SECONDS
IAG_STATE_PROBE_LOG
IAG_STATE_PROBE_ROTATE_BYTES
IAG_STATE_PROBE_ROTATE_SECONDS
IAG_PROBE_MIN_FREE_BYTES
```

The writer publishes a segment only after closing it:

```text
iag-stellaris-command-probe.jsonl.<pid>.<instance>.<segment>.ready
iag-stellaris-payload-probe.jsonl.<pid>.<instance>.<segment>.ready
iag-stellaris-state-probe.jsonl.<pid>.<instance>.<segment>.ready
```

The manager turns those files into this durable layout:

```text
capture-root/
  session.json
  health.json
  runtime_state.json
  catalog.json
  coverage.json
  segment_index.jsonl
  save_index.jsonl
  segments/
    commands/*.jsonl.*.ready.gz
    payloads/*.jsonl.*.ready.gz
    states/*.jsonl.*.ready.gz
  saves/<game-date>__<source>__<sha12>.sav
```

Raw events remain lossless inside the gzip segments. `catalog.json` is an
index of counts, time/sequence bounds, caller samples, nested types,
first-seen AI stack evidence and event/situation/chain keys. New RTTI names are
not automatically promoted to the Action Registry.

`coverage.json` is a live, idempotent discovery index. It lists unique command,
nested payload, event, situation and event-chain keys, missing lifecycle
targets and a configurable no-new-discovery plateau. Its
`ready_for_early_review` value is advisory and never stops the manager or game.

## Save association

The manager recursively watches the Stellaris save root. It archives a file
only when all of the following hold:

1. size and modification time remain unchanged for the stability interval;
2. the file is a valid ZIP;
3. both `meta` and `gamestate` exist;
4. a copied file has the same SHA-256 as the source;
5. the capture filesystem remains above its reserve.

Each `save_index.jsonl` record includes the game date, source and archive hash,
and command/payload/state sequence high-water marks grouped by probe PID. This makes
monthly save deltas useful for clustering command families across a game
restart, where native sequence counters begin again at one.

The high-water mark is temporal evidence, not an atomic transaction boundary.
Use `realtime_ns`, the save modification time, command phase pairs and visible
save deltas together when assigning semantics.

## Start procedure

Do not reuse active JSONL files from another run. Preserve them first.

1. Build all three probes and the rotation test.
2. Start Stellaris, enter the intended disposable observer save, and pause.
3. Move old `/tmp/iag-stellaris-*-probe.jsonl*` files into a dated legacy
   archive; never silently delete earlier evidence.
4. Start `long_run_capture.py` with an explicit, durable output directory.
5. Attach once and load the three reviewed shared objects while the process is
   stopped in the debugger.
6. Verify all three `probe_started` records, matching PID/build ID, `health.json`,
   and that Stellaris remains alive.
7. Enable `human_ai`, unpause, and allow monthly autosaves to run.

The exact build command is:

```bash
cmake -S services/stellaris_native_runtime/research \
  -B build/stellaris-command-research \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DIAG_STELLARIS_RESEARCH_BUILD_TESTS=ON
cmake --build build/stellaris-command-research --parallel 4
ctest --test-dir build/stellaris-command-research --output-on-failure
```

Start the manager with:

```bash
capture="$HOME/iag-captures/human-ai-$(date -u +%Y%m%dT%H%M%SZ)"
nohup python3 services/stellaris_native_runtime/research/long_run_capture.py \
  --game-pid "$(pgrep -n stellaris)" \
  --save-root "$HOME/.local/share/Paradox Interactive/Stellaris/save games" \
  --output "$capture" \
  >"$capture-manager.log" 2>&1 &
echo $! >"$capture-manager.pid"
```

Load the exact-build probes with one reviewed debugger stop:

```bash
python3 services/stellaris_native_runtime/research/inject_passive_probes.py \
  --pid "$(pgrep -n stellaris)" \
  --build-dir build/stellaris-command-research
```

Probe injection is intentionally not automated by the manager. Repeated or
unattended debugger attachment has a larger failure surface than a single
reviewed load and is unnecessary for a process intended to run continuously.

## Health and recovery

Healthy capture means:

- `game.alive` is true;
- all three active streams are present and their event times advance when the
  corresponding activity occurs;
- `dropped_before` and `writer_dropped_before` remain zero;
- `.ready` files are consumed into `segments/`;
- new autosaves appear in `save_index.jsonl` with matching hashes;
- free space remains comfortably above the reserve.

If the manager exits, the game and probes continue. Restart the manager with
the same output directory; it resumes active-file offsets from
`runtime_state.json` and processes accumulated `.ready` files idempotently by
raw SHA-256.

Stellaris may replace an autosave after it has appeared in a directory scan.
The save watcher therefore treats a file disappearing between enumeration and
`stat()` as an ordinary rotating-save race, skips that path for the current
scan and continues capturing. A transient autosave race must never terminate
the manager.

If Stellaris exits, do not hot-unload any probe. Stop the manager after it has
processed the final `.ready` segments, and preserve the three remaining
active JSONL files as the final partial segments before reusing their paths.
The active files are still raw evidence even though their last 15-minute window
has not received a `.ready` suffix. A new Stellaris process needs a new one-time
injection; probe PIDs keep the sequence ranges distinct.

If disk space reaches the reserve, keep the game running and free or extend
capture storage. Missing evidence will be explicit in later writer-drop
counters. Do not lower the reserve merely to keep the capture complete.

## Analysis boundary

The capture can automatically enumerate command RTTI, phase coverage, callers,
AI-origin stack evidence, nested fleet orders, buildable payload types, event
content keys, situation and event-chain lifecycles, serial fields and save
deltas. It cannot safely infer constructor field semantics,
ownership, validation rules or a production action contract from frequency or
class names alone. Those still require static layout recovery plus focused
runtime validation before a new action file is exposed through the native
runtime and Broker.

## Initial live validation

The first long-running observer session used process `1061097` and capture root
`human-ai-observe-20261003T182154Z`. Both probes loaded through one debugger
pause and emitted matching PID and Build ID headers. Stellaris and the manager
remained alive after detach.

During the first minute of natural AI activity:

- the analyzer read 845 command events and 447 payload events;
- 34 concrete command types carried the
  `CCountryAI::PostAICommandsToSession()` stack marker;
- malformed, pipe-dropped and writer-dropped counts were all zero;
- every final main-thread wrapper had a matching payload;
- `CQueueFleetsOrderCommand -> CReturnFleetOrder`,
  `CQueueFleetOrderCommand -> CMergeFleetOrder`, and
  `CQueueFleetOrderCommand -> CMoveToSystemPointFleetOrder` were observed;
- build payloads included armies, ships, districts, zones, starbase upgrades,
  modules and buildings;
- the first new monthly save, `autosave_2200.02.01.sav`, was verified and
  archived with SHA-256
  `11b8840bdcde89586ff36015e44f450cf45bcddd0a982fa6c85b39ff73e4e78cb`;
- its save record carried command high-water `826` and payload high-water
  `13665` for probe PID `1061097`.

This validates the passive capture, stream supervisor, save watcher and
cross-artifact indexing together. It does not promote any newly observed type
to an executable action.

## First extended checkpoint

The same Stellaris process remained alive for the extended checkpoint. The
durable catalog covered `2026-10-03T18:25:05Z` through
`2026-10-04T03:40:46Z`; the active files continued beyond that window. At the
catalog checkpoint:

- 256,572 command records and 427,671 bounded payload records had been indexed;
- 87 concrete command types had direct
  `CCountryAI::PostAICommandsToSession()` origin evidence;
- 44 fleet-order/action or buildable payload types had been identified;
- malformed, game-thread pipe-drop and background-writer-drop counts remained
  zero;
- 74 rotated segments (37 command and 37 payload) had been consumed;
- the game had advanced from `2200.02.01` into the 2260s.

The next active command window then produced an 88th AI-origin type,
`CUnlockExhibitCommand`, followed by an 89th,
`CActivateFleetCloakingCommand`. The exhibit command's `session_post` record
was followed by an `execute_sync` record about 84 ms later; the cloaking
command posted and executed three times in its first archived window. This is
evidence that the common pipeline continues to reveal previously unseen
systems late in a campaign; neither name is yet a typed Broker action contract.

The discovery curve was strongly front-loaded but did not completely saturate:

| elapsed capture time | cumulative AI-origin command types |
|---:|---:|
| 1 hour | 48 |
| 2 hours | 56 |
| 3 hours | 63 |
| 4 hours | 70 |
| 6 hours | 80 |
| 8 hours | 86 |
| 9 hours | 87 |
| next archived window after 9 hours | 89 |

Fifty-three types appeared after the first-minute sample. High-value additions
included:

- fleet execution: cancel orders, colonize, orbit, land armies, emergency FTL,
  follow, refit, upgrade, disband ships and move ships between fleets;
- war and diplomacy: prepare war, add/remove claims, set a defender war goal,
  propose/respond/vote on diplomatic actions;
- economy and expansion: establish a branch office, build and upgrade
  megastructures, remove queued buildables, destroy buildings/districts and
  enact planetary decisions;
- state systems: espionage create/destroy, species-rights changes, species
  modification, ascension perks, relic/artifact/astral actions and situation
  approaches.

The common wrapper evidence also broadened materially. Final
`CQueueFleetOrderCommand` payload types included `CReturnFleetOrder`,
`CMergeFleetOrder`, `CMoveToSystemPointFleetOrder`, `CFollowFleetOrder`,
`COrbitPlanetFleetOrder`, `CLandArmiesFleetOrder` and
`CScriptedFleetOrder`. `CAddBuildableToQueueCommand` covered buildings,
districts, zones, ships, colony ships, armies, starbase upgrades/modules/
buildings, defense platforms, blocker clearing, decisions, ship upgrades and
building repair. These are good reverse-engineering anchors because a shared
wrapper can be studied once while each typed payload retains its own validated
semantic adapter.

### Important negative and control evidence

`session_post` and `execute_sync` counts were equal for most types, but not all.
For example, the checkpoint contained 17,725 fleet-order posts versus 17,679
executions, 1,337 market-sell posts versus 1,313 executions and 43 fleet-
upgrade posts versus 34 executions. Capture-window boundaries may account for
some gaps; validation or rejection may account for others. In either case,
successful return from native Post is not an authoritative success predicate.
The Broker must keep its existing execution evidence and save-continuation
checks.

No final `CAttackFleetAction` sample appeared. The contemporaneous save had no
active country war entries, although it contained hostile-fauna combat debris.
Therefore the long-running sample neither confirms nor disproves the direct
attack layout. Attack still requires a focused stimulus with a final main-
thread payload and a visible state delta.

### Manager recovery incident

During the run, the capture manager encountered an autosave that disappeared
between recursive enumeration and the sort-time `stat()` call. The manager
exited, but Stellaris and both in-process probes continued normally. Twenty-
five command segments and twenty-five payload segments accumulated as raw
`.ready` files with zero reported drops. After the save watcher was made
race-tolerant, restarting the manager against the same capture root compressed
and catalogued the backlog idempotently while the game kept running.

This incident validates the intended process isolation. Command evidence was
continuous; save snapshots that the game had already removed during the
manager outage could not be reconstructed, so the save index explicitly has a
gap between `2221.04.01` and `2262.01.01`. Future analysis must not imply
monthly state-delta coverage across that gap.

## Final campaign checkpoint

The observer campaign reached its terminal game state at `2504.04.01`. The
capture ran from `2026-10-03T18:21:55Z` through the last command at
`2026-10-05T10:48:39Z`. Stellaris remained open on the terminal screen, so the
process was still alive even though simulation commands had stopped.

The durable catalog and final unrotated tail together contain:

- 2,153,069 command records;
- 2,479,691 bounded payload records;
- 116 concrete command RTTI types, 110 of which have direct AI-origin evidence;
- 49 fleet-order/action or buildable payload types;
- 322 archived probe segments and 3,166 verified save snapshots;
- zero malformed records, game-thread pipe drops or background-writer drops.

The final active files stopped before another write could trigger their
time-based rotation. They were therefore copied without modifying the live
files into
`final-partial-20261005T104839Z/`, together with SHA-256 checksums, health and
the pre-tail catalog.

### End-state transition

The last active window is dominated by fleet cleanup: 1,745 multi-fleet and 19
single-fleet final submissions carried `CReturnFleetOrder`. Near the terminal
transition a generic `COnActionCommand` posted and executed, followed by a
small final batch of diplomacy, market, fleet-template and return-order work.
The final two logical commands were:

```text
CAddCountryControllerCommand
CPauseGame
```

Both final commands posted and executed. Static symbols identify the former as
`CAddCountryControllerCommand(int, TPdxRef<CCountry> const&)`; it is allowed for
observers and during Hot Join. This is strong evidence for controller/observer
transition at the terminal screen, not a normal AI strategic action, and it
must not be promoted as an autonomous country action.

`COnActionCommand` is also not a crisis-specific semantic command. Its native
constructors take an on-action key plus a country or full `CEventScope`, an
execution mode and effect user data. The terminal sample therefore shows that
the crisis ending crosses generic scripted-event machinery; it does not reveal
a dedicated Cetana victory command. Reconstructing a named crisis event stream
requires on-action/event-key observation or save deltas in addition to the
command RTTI catalog.

### Market, events and war coverage

Final post/execute counts, including the unrotated tail, are:

| Command | Post | Execute |
| --- | ---: | ---: |
| `CMarketBuyResourceCommand` | 23,811 | 23,792 |
| `CMarketSellResourceCommand` | 16,155 | 15,779 |
| `CPutSlaveOnMarketCommand` | 97 | 97 |
| `CBuySlaveFromMarketCommand` | 76 | 74 |
| `CSelectEventOptionCommand` | 1,045 | 1,045 |
| `CDiploActionProposeCommand` | 2,394 | 2,394 |
| `CDiploActionRespondCommand` | 946 | 939 |
| `CDiploActionVoteCommand` | 287 | 287 |
| `CAIPrepareWarCommand` | 25 | 25 |
| `CAddSystemClaimCommand` | 117 | 117 |
| `CRemoveSystemClaimCommand` | 18 | 18 |
| `CDiploActionSetDefenderWarGoalCommand` | 8 | 8 |
| `CAIUpdateStrategicWarData` | 68,026 | 68,026 |

The market and diplomatic-response gaps reinforce that successful posting is
not authoritative success. Event-option selection, by contrast, paired in
every captured sample. Formal declarations still appear as a polymorphic
`CDeclareWarAction` owned by `CDiploActionProposeCommand`; the run did not
reveal a separate `CDeclareWarCommand`.

Late discoveries broadened the next candidate set with Galactic Community
resolution proposal/support/opposition/withdrawal, emergency measures and
votes; slave-market listing and purchase; faction actions; government
validation; uplifting; planetary ascension; Shroud delves; and accord
activation. Frequency alone does not make any of these a production adapter.

### Planet-killer order chain

The bounded payload probe captured a previously unseen native chain between
the `2453.12.01` and `2454.04.01` saves:

```text
CDestroyPlanetFleetOrder
  -> CPlanetKillerWeaponWindupFleetOrder
  -> CPlanetKillerWeaponFireFleetOrder
```

The catalog contains five observations of the outer destroy order, three of
the windup order and one fire order. Mutable worker observations show the same
order object advancing over several monthly saves before the fire-stage type
appears. This is a strong reverse-engineering anchor for a future planet-killer
adapter, but the current bounded records do not identify the actor and target
semantics. The chain occurred roughly fifty in-game years before the terminal
state, so it cannot yet be attributed specifically to Cetana merely because
Cetana ultimately won the campaign.
