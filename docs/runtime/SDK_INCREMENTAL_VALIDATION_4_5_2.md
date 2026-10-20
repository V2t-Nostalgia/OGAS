# Incremental SDK validation: Stellaris 4.5.2

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope And Baseline

The player authorized unattended research while the current game advances
naturally. The completed 351-entry acceptance is immutable: 309 constructed
classes, 154 populated/native-validated classes and 87 classes with a true
candidate. IsValid results do not establish execution or `paired_capture`.

`tools/incremental_recovered_commands.py` is a private research sidecar, not
another execution backend or queue. It uses the existing Native Runtime and
`CGameIdler` validation endpoint. It never loads a library, replaces a Hook,
submits a Command, calls Execute, changes game speed or writes process memory.
Existing Runtime/library files and generated consumer headers are untouched.

## Active Night Window

- Game PID: `273675`; start ticks: `73256903`.
- World identity: `102024944543984`.
- Exact ELF Build ID: `121ecb516cbc5f1d39917fbcc36620534384e2c2`.
- Exact executable SHA256:
  `1c4c79a0ef8af7b984b797606373eb68b60fe421e4ef54c20e12e4a9398ba86b`.
- Runtime instance: `133124130178304`; this remains the same injected Runtime.
- Initial observation window: 2026-10-19 18:01 UTC to 2026-10-20 06:01 UTC.
- Active observer PID: `324712`.
- Active observer source:
  `/tmp/iag-sdk-incremental-v2-eb1bb718960e447c8f432f666c7d1536/`.
- Active evidence:
  `<RESEARCH_HOME>/iag-captures/sdk-incremental-20261019-01-resume1/`.
- Earlier observer evidence:
  `<RESEARCH_HOME>/iag-captures/sdk-incremental-20261019-01/`.
- Local deployment/source/hash/review records:
  `.runtime-evidence/sdk-incremental-20261019-01/observer-v2/` and its parent.

The original observer was stopped at its own checkpoint boundary and resumed
in a new source/output directory to tighten the unchanged-world scheduling
gate. No native Runtime or game process was stopped, patched or reloaded.
The resume required all started requests to have completed. Earlier evidence
and Python source snapshots remain. Sum disjoint request IDs, not repeated
cumulative checkpoint totals, when reporting coverage.

A thread heartbeat (`ogas-4-5-2`) checks this work every 30 minutes, also doing
safe offline recovery when live candidates or connectivity are unavailable.
It is not a replacement for the independent server-side observer. At the end
of this bounded night window, preserve a final review and pause the heartbeat;
do not silently start another experiment or extend the window on resume.

## Selection And Cost Bounds

Only the previous **67 negative-only** and **18 missing-candidate** commands
enter the pending set. Previously positive commands and the 179 static blockers
are not repeatedly traversed or constructed.

- Observe every 30 seconds, without native calls when the global GameDate and
  relevant object-slot fingerprints are unchanged.
- Observe only 27 relevant recovered database types in the current pending set.
- For a missing scene, wait until the required type has occupied, non-sentinel
  slots before spending a native request. Slot headers are discovery hints,
  **not** a claim that an object handle or actor relationship is legal.
- At most three commands and four candidates per command per selected round.
- Per-command cooldown starts at ten minutes and backs off to two hours after
  no progress. An unchanged dependency fingerprint needs a longer fallback
  interval as well as actual global world progress.
- Candidate indices rotate within the existing Runtime's bounded candidate
  selector; no raw object IDs, pointers, field layouts or functions are supplied.
- A new true result removes that command from further legality probing. It
  does not alter Action Registry or Broker verification.

The external reader opens `/proc/PID/mem` with `O_RDONLY`. It checks executable
hash, PID start identity, zero-file-offset ELF mapping and the accepted world.
The global/date locations come from the existing exact-build C++ profile
(`current_game_state=0x5733568`, date offset `0xc0`) and were cross-checked
against the accepted Runtime's world/date. Reads use bounded `pread`; no
debugger attach, breakpoint, native function call or process-memory write is
needed. A changing date during a read defers that observation. Database layouts
come from the generated SDK, and native candidate validity is checked again
inside the game-thread endpoint.

An initial live read-only check resolved all 27 relevant database types. The
five missing-scene types had zero eligible slot headers at that check. The
first observer's three recorded cycles used 0.664, 2.784 and 1.168 CPU seconds;
the middle cycle also archived four initial saves. These are sidecar CPU
measurements, not a game-speed overhead comparison. The current revision limits
save processing to one file per poll and prevents a stationary world from
draining the remaining pending list. Future reviews must measure steady-state
cost rather than reusing startup/backlog numbers as typical overhead.

The resumed observer's reviewed four steady-state cycles each used
0.052-0.054 CPU seconds per roughly 30-second interval, approximately 0.18% of
one logical CPU. They selected zero native requests because raw date/object
state was unchanged. Its 31-cycle review found the worker/game alive, no native
suspension and the original Runtime SHA256 unchanged. Five earlier stable saves
(5,527,328 bytes) were retained; no new save arrived during that reviewed
interval. This is an observed interval, not a promise of later progress or an
estimate of game-speed impact.

## Save And Capture Evidence

The current source campaign is
`~/.local/share/Paradox Interactive/Stellaris/save games/7_1694187993/`.
Stable, new saves are copied with exclusive destination creation and fresh
names, retaining source stat/hash, metadata and raw bytes. Neither source nor
prior archive is modified. A copy whose source changed is kept but marked
untrusted. The archive budget is 2 GiB, with a 2 GiB free-space reserve; reaching
it defers copying rather than deleting old evidence.

The existing `WorldStateIndex` and construction-item parser produce shared
section fingerprints and bounded queue facts once per archived save. Added,
changed and removed queue items are state deltas; removal alone does not prove
completion rather than cancellation. Metadata must identify the exact current
4.5.2 save version. Save dates and native observations are temporally associated,
not falsely claimed to be a single frozen snapshot or a captured native call.

**There is currently no attached, confirmed 4.5.2 passive Command/Payload
capture source in this process.** The observer explicitly records that gap.
Old 4.4.6 captures or old Probe binaries cannot be relabeled current evidence
or injected to fill it. Natural save changes alone cannot create a
`paired_capture` Action. A future valid pair needs a real current-version
command/callsite/payload with provenance and matching object/state evidence;
active submission/execution verification is a separate evidence level.

## Recovery And Safety

Each round has a new directory. Checkpoints use exclusive new filenames;
request journals append flushed start/completion records. The checkpoint stores
the candidate cursor, cooldown, prior observation and accumulated outcomes.

```bash
python services/stellaris_native_runtime/tools/incremental_recovered_commands.py \
  --config /path/to/reviewed-session-config.json \
  --output /path/to/new-output-directory \
  --resume /path/to/old/checkpoints/IMMUTABLE.json
```

Resume only after verifying the old observer is no longer running and reviewing
any unmatched request. Use a **new** output directory and the same reviewed
process/world/runtime configuration; do not replay an indeterminate request.
The original window deadline is inherited, not reset. Configuration contains no
credentials. A `STOP` file in the observer's own output directory, or SIGTERM to
the verified observer PID, ends it safely without controlling the game.

Transient connection/observation failures back off while save collection and
offline work remain available. A changed process/world/runtime suspends native
research, not authorizes reinjection. A native C++ exception or Factory/VTable
mismatch suspends further native calls because integrity is uncertain; this
does not prevent safe save archiving or offline analysis. A single static
structure rejection quarantines its command. C++ catches do not recover native
signals, so a crash/disconnect must not be mislabeled a normal rule rejection.

## Offline Work

Continue from the per-command run-18 gap audit and constructor/serializer
evidence. Prioritize reusable field/ownership/semantic recovery, not guessed
IDs or repeated native calls for 179 statically blocked commands. New binary
work stays in new offline build directories until a future authorized window;
the current native Runtime cannot consume newly generated layouts dynamically.
No production capability or verification level changes automatically.

The first offline follow-up fixed how the completeness checker combines proven
Factory initializer spans with minimal ABI alignment before an embedded native
VTable. It still rejects unrepresented holes, overlapping semantic fields,
out-of-bounds writes and unresolved field types. A regression involving a native
CString's larger alignment and its smaller member stores was caught and fixed
before any generated result was accepted. All interim outputs were retained.

Fresh Linux/Windows generation in `.tmp/sdk-recovery/incremental-offline-21/`
passed 47 upstream, 38 pinned-header and 18 OGAS comparisons. The separate audit
now has 241 supported layouts and 177 statically IsValid-ready entries, with no
lost eligibility among the 154 actually validated classes. Newly static-ready:

- `add_buildable_to_queue_command`
- `deactivate_cloaking`
- `diplo_action_set_defender_war_goal_command`
- `market_buy_resource_command`
- `market_sell_resource_command`

These five are **future-window offline work**, not extra live coverage. The
current generated consumer headers and loaded Runtime remain run-18 versions.
The review bundle is `.runtime-evidence/sdk-incremental-20261019-01/offline-21/`.
The complete repository suite passed 462 tests, including 12 sidecar tests and
20 SDK recovery tests.

The next offline follow-up recognizes a bounded, relative-jump-table enum
serializer, retaining only branches that return constant Tokens. Exact 4.5.2
`EEnvoyAssignment` at `0x1ac7050` supplies eight proven candidates for the
assignment fields in `CAssignLeaderCommand`, `CChangeLeaderAssignmentCommand`
and `CHireAndAssignLeaderCommand`. Index 2 reads current application state and
remains unresolved; index 9 reaches the invalid/default leaf and is excluded.
Byte-sized enum Token tables are also recognized, including pause-lock metadata;
this does not make pause/unpause commands eligible or authorize their use.

The fresh audit in `.tmp/sdk-recovery/incremental-offline-22-20261019T1845Z-audit/`
has 178 statically IsValid-ready commands and 173 static blockers. Its only new
eligible command relative to offline-21 is `change_leader_assignment_command`.
Population layout coverage remains 241, and the 154 actually validated classes
retain eligibility. A separate final-source regression re-extracted all ten
referenced enum serializers (37 field occurrences) without a catalog mismatch.
This remains static evidence, not a new native call or production promotion.
Both-platform generation completed in 264.107 seconds, with all 47 upstream,
38 pinned-header and 18 OGAS comparisons passing. All 464 repository tests,
including 22 SDK recovery tests, passed. Source snapshots, generated metadata,
disassembly, gap audit, test logs and hashes are retained in
`offline-22-20261019T1845Z/` under the local incremental evidence bundle. Both
installed consumer-header hashes still match run-18; no new binary was loaded.

The 18:36 UTC read-only review found the same game start ticks, world, Runtime
instance and loaded library hash; exactly one incremental observer was alive.
The two observer journals contain 93 distinct started/completed requests and
93 paired constructions/destructions, with no interrupted request or exception.
The resumed observer had made no additional native calls through its 60th
cycle: raw GameDate/object fingerprints and the latest source autosave were
unchanged. This is not proof of continued game-time advancement. Recent cycles
used 0.051-0.052 CPU seconds per approximately 30 seconds. The immutable review
is `reviews/20261019T183623Z.json` under the local incremental evidence bundle.

The 19:03 UTC review again found the same PID/start ticks, world, Runtime and
unchanged date/object fingerprints. Old checkpoint hashes still matched, only
one observer was alive, and all 93 disjoint requests/lifecycles remained paired.
No save or native call was added; recent observer cycles used 0.051-0.052 CPU
seconds per 30-second interval. This review and its coverage trend are separate
UTC-named files, not replacements for prior evidence.

The next offline recovery follows direct validator calls to four exact native
`AccessInstance(CCountry&, unsigned int)` accessors. Each recovered body must
match the complete database-null, bounds, full-ID generation-check and sentinel
return pattern, with agreeing named database/null globals. The ID load must be
in the same basic block as the direct call; unknown calls, register clobbers,
truncated pointers and cross-branch provenance are excluded. No classification
is based on the field name or template name alone.

This supplies typed `id` fields for both `CPinSituationLogEntryCommand<T>` and
`CTrackSituationLogEntryCommand<T>` with `T` equal to `CArchaeologicalSite`,
`CAstralRift`, `CFirstContact` or `CSituation`. The existing generated-database
candidate selector and `NativeCommandBuilder` can consume these standard `ref`
fields in a future binary; no separate object-layout or execution path is added.
Other template IDs, including event-chain, point-of-interest and special-project
entries, remain unresolved where the same native resolver proof is unavailable.

Fresh Linux generation in
`.tmp/sdk-recovery/incremental-offline-25-20261019T1915Z/` and its separate audit
report 186 static-ready commands, 165 static blockers and 241 supported layouts.
The eight additions above are static only. All 154 previously native-validated
classes retain eligibility. Intermediate offline-23/24 attempts remain: the
strict initial pattern matched no real accessor until its bounds-edge branch
displacement was corrected, and one direct Python invocation failed on argument
ordering before emitting a catalog. Neither attempt accessed the game.

The Windows catalog from the completed offline-23 generation is reused only
after verifying that all four Linux inputs to Windows matching are byte-identical
to the corrected Linux generation. Fresh cross-platform comparisons passed;
this is not a claim that Windows discovery was rerun in offline-25. Generated
headers remain in research output, not installed into the active Runtime.
All 498 discovered repository tests, including 24 SDK recovery tests, passed. The immutable
bundle `offline-25-20261019T1915Z/` retains the eight field proofs, twelve native
function disassemblies, unresolved accessor candidates, source snapshots, gap
audit and test/hash records. Both consumer-header hashes still match run-18.

A further offline pass recovered two country-scoped member-array lookup
patterns and linked three remaining scalar fields to them, without converting
them to `TPdxRef` or enabling a runtime provider. Special projects use a 32-bit
country-owned ID; point-of-interest lookup compares 16-bit flags. Active event
chains instead join a loaded definition index to country-owned instances.
Details and remaining caller-country binding requirements are in
[`SDK_COUNTRY_SCOPED_IDS_4_5_2.md`](SDK_COUNTRY_SCOPED_IDS_4_5_2.md).
Static-ready coverage remains 186. Offline-26's generated research header is
byte-identical to offline-25; installed headers and the active Runtime stay
unchanged. The 19:34 UTC review and coverage trend found the original identities,
immutable old checkpoints, complete 93-request lifecycle pairing, five archived
saves and unchanged world state. No native request was selected.
All 525 discovered repository tests passed, including 29 SDK recovery tests;
source snapshots and final-source recipe/field checks are retained with offline-26.

The 20:07 UTC review again confirmed the same game/observer start ticks,
world, Runtime instance, mapped library hash and a single observer. All 93
distinct incremental requests still had matching completions and destructions;
none had an exception or submission. Through resumed round 241, date and object
fingerprints were unchanged, as were the five archived saves. Recent observer
cycles used 0.051-0.052 CPU seconds per roughly 30 seconds. The brief game CPU
sample was 128% of one logical CPU, with 5,665,792,000 bytes RSS; this is not a
game-speed or monitoring-overhead benchmark. No new native call was selected.
The immutable review is `reviews/20261019T200740Z.json`, with its own coverage
trend and a retained read-only audit script.

Offline-27 additionally recognizes the exact loaded-definition-to-country-member
join used by `CActiveEventChain::AccessInstance`. It links event-chain pin/track
fields without treating their values as generation-bearing handles. There are
now three scoped lookup recipes and five field links. Country binding and live
candidate providers remain unresolved, so static readiness stays **186** and
native coverage stays **154/87**. No library, consumer header, action admission
or game state changed. See the country-scoped-ID document for the full proof.

The full regression caught automatic test discovery importing historical
`test_*.py` source snapshots from `.runtime-evidence`, including an old recovery
module. That directory is now excluded from maintained tests, without modifying
any evidence. A regression test covers the exclusion. The corrected maintained
suite has **477 passing tests**, including **34 SDK tests**. Earlier totals above
retain their historical archive-inclusive counts; they should not be compared
as a coverage trend. Failed and corrected runs are independently retained in
`offline-27-20261019T2014Z/`.

The 20:33 UTC review found the same game/Runtime/observer identities and immutable
earlier checkpoints. Both journals still have 93 unique completed requests with
93 matching constructions/destructions, no exception and no submitted command.
Through resumed round 292, raw date, object fingerprints and source saves were
unchanged. Recent sidecar cycles used 0.050-0.052 CPU seconds per 30 seconds;
RSS was 53,067,776 bytes, and free disk space was 225,850,384,384 bytes. The brief
game CPU observation was 128%, not proof of simulation advancement. The review
and coverage trend are independently retained as `20261019T203321Z.json`.

Offline-28 proves the native command-country binding for the five scoped fields
by matching the complete generation-checked validator body and existing direct
field/callsite evidence. The audit no longer calls those five bindings unknown,
but continues to reject all five commands because native candidate providers are
not implemented. No other caller is inferred from these matches. Static-ready
coverage stays 186, with 165 blockers; native coverage stays 154/87.
All 482 maintained tests passed, including 39 SDK tests. Complete function
witnesses, final-source checks, audit and hashes are retained independently in
`offline-28-20261019T2043Z/`. The generated research header is unchanged, the
installed consumer headers still match run-18, and the loaded Runtime was not
modified or reinjected.

The 21:03 UTC review (`reviews/20261019T210342Z.json`) retained all original
identities, complete 93-request/lifecycle pairing, five archived saves and
unchanged raw date/object fingerprints through resumed round 353. No new request
was selected. Recent cycles used 0.050-0.052 CPU seconds per 30 seconds; observer
RSS was 53,084,160 bytes. Free disk space was 225,835,364,352 bytes. Game CPU was
115% over the short observation interval, not evidence of simulation progress.

A subsequent one-shot read-only audit used the recovered scoped-ID recipes and
generation-checked country-0 handle to find four special-project hints and four
active-event-chain definition-index hints. The current country had no POI entries.
This is new **object-discovery evidence**, not a native command capture or
legality/execution result. The separate reader fetched 5,348 bytes in 56 bounded
reads, never called a game function and did not change the observer or Runtime.
World/date and selected bytes remained equal; that still does not prove a frozen
snapshot. Detailed limitations, source versions and caller identity clarification
are in `scoped-hints-20261019T2112Z/` and the country-scoped-ID document.
Runtime providers are still missing, so no discovered ID was sent to the current
native endpoint and no verification level or native-coverage count changed.
All 491 maintained tests passed, including 48 SDK tests. Final reader source,
the distinct source actually used for the read, caller-identity clarification,
test logs and hashes are preserved together; source hardening after the read is
not mislabeled a second live test. No new SDK-wide recovery pass was needed for
this isolated reader: offline-28's unchanged metadata remains its input.

## 21:34 UTC Review And Offline Scoped Providers

The immutable `reviews/20261019T213402Z.json` confirms the original game and
observer start ticks, world, Runtime instance, mapped library hash and exactly
one observer. Both journals still contain 93 distinct paired requests and
constructions/destructions, without exceptions or interrupted work. Resumed
round 413 had unchanged raw GameDate, object fingerprints and source saves;
the resumed observer added zero native calls. Recent cycles used 0.051-0.052
CPU seconds per 30 seconds, observer RSS was 53,084,160 bytes and free disk
space was 225,825,693,696 bytes. The short game CPU sample was 128.7%, not proof
that simulation time advanced. Five unique saves occupy 5,527,328 bytes.

Offline-29 implements candidate providers for the five proven scoped fields:
event-chain pin/track, special-project pin/track and point-of-interest track.
`RecoveredScopedIdBinding` connects generator evidence to the existing shared
game-thread probe and `NativeCommandBuilder`; the fields remain `u32`, not
global references. Eligibility requires the complete caller-country proof,
the matching native lookup and a typed country field. Enumeration binds that
same generation-checked country and accepts an ID only when its native lookup
returns the exact enumerated object. Requests still cannot supply arbitrary
field values or raw pointers. No new execution path or Action is introduced.

Country lists scan at most 256 entries, loaded-definition joins at most 4,096
entries, results at most 16 candidates and native scoped lookups at most 256
per request. Negative/excessive counts fail closed; partial scans are marked.
Lookup exceptions prevent Factory/IsValid calls. This catches C++ exceptions,
not native access violations; real object lifetime and lookup behavior still
require a future authorized validation window. These providers are Linux
metadata only; Windows fixture success is not Windows recipe recovery.

Deriving the new table from immutable offline-28 metadata, without rerunning
ELF or Windows discovery, yields **191 static-ready / 160 blocked** commands.
All 154 previously native-validated classes retain eligibility. This is future
probe readiness, not five new native validations. Current live coverage remains
**154 validated / 87 ever true**, and no `paired_capture` or `live_verified`
state changed. Installed headers remain run-18; the loaded Runtime still
reports probe revision 2, while future source reports revision 3. No binary
was deployed, reinjected or hot-replaced.

All **494 maintained tests**, including **50 SDK tests**, pass. Independent
MSVC and Linux g++ builder fixtures pass, covering all three identity families,
same-country binding, native lookup disagreement, bounds, exceptions, limited
enumeration and paired ownership without research submission. Linux builds
ran as short `nice -n 19` subprocesses outside the game; the final build used
9.55 CPU seconds and approximately 195 MiB peak RSS. This is compiler cost,
not an online monitoring overhead benchmark. Initial failed quoting/type-check
runs and corrected runs are retained separately in
`offline-29-20261019T2143Z/`, together with generated metadata/header, source
snapshots, audit, compile logs and hashes. No game-thread provider was exercised
against Stellaris during this heartbeat.

## 22:03 UTC Review And Special-Project Recovery

The separate `reviews/20261019T220330Z.json` retains the original game and
observer start ticks, world, Runtime, mapped library and observer-source hashes.
Exactly one observer was alive; earlier checkpoint hashes still matched.
Resumed round 473 had unchanged raw date/object fingerprints and source saves,
so no new native validation request was selected. Across both disjoint journals,
93 requests and 93 constructions/destructions remain paired, without exceptions
or interruptions. There are still five unique archived saves, 5,527,328 bytes.
Recent cycles used 0.051-0.052 CPU seconds per approximately 30 seconds, observer
RSS was 53,100,544 bytes and free disk space was 225,812,762,624 bytes. Game CPU
was 124% over a short interval; that is not evidence of time advancement.

Offline-30 completes the country/scalar binding for
`CResearchSpecialProjectCommand` and `CCancelResearchSpecialProjectCommand`.
Their native lookup is the const `NSpecialProjectUtil::GetProjectOfCountry`,
not the previously recovered writable accessor. Its separate complete member
search matches the known search byte-for-byte except for a relocation resolving
to the same null object, and uses the same country adjustment. The generator
records this structural equivalence, not a name-based alias assumption. Complete
142/161-byte validator patterns additionally retain generation checks, failure
branches, virtual guards and named research predicates. No unknown branch or
unproven caller is admitted by widening these patterns.

Both commands now use the existing `member_u32` provider and shared Builder;
their special-project field remains a scalar, not a global reference. Seven
scoped bindings are generated, with **193 static-ready / 158 blocked** commands
and no regression among the 154 previously native-validated classes. This is
not native legality or execution evidence. Current live coverage stays
**154 validated / 87 ever true**; no native call or production promotion was
added, and the current observer/Runtime/config/consumer headers are untouched.

A fresh Linux ELF recovery took 71.775 seconds locally. The four Windows
matching inputs remain byte-identical to the earlier completed discovery;
18 OGAS cross-checks pass using that retained Windows catalog. Windows discovery
and native validation were not repeated. All **497 maintained tests**, including
**53 SDK tests**, pass. A separate low-priority Linux fixture compiles the new
seven-entry research header and passes using fake objects, without attaching
to the game; it used 9.38 CPU seconds and approximately 196 MiB peak RSS.
Full bytes, disassemblies, final-source checks, generated metadata/header,
failed and corrected lint runs, fixture logs and hashes are retained in
`offline-30-20261019T2206Z/`. See the country-scoped-ID document for the fleet
special-project branch that remains unresolved rather than being guessed.

## 22:33 UTC Review And Nested Value Recovery

The independent review `reviews/20261019T223256Z.json` confirms the original
game/observer start ticks, world, Runtime instance, mapped library and observer
source, one observer and unchanged previous checkpoint hashes. Both journals
still have 93 unique paired requests and constructions/destructions, without
exceptions or interruption. Through resumed round 531, raw date, slot fingerprints
and source saves were unchanged; no native validation request was added. There
are still five unique archived saves. Recent cycles used 0.051-0.053 CPU seconds
per approximately 30 seconds, observer RSS was 53,116,928 bytes, and free disk
space was 225,806,684,160 bytes. A short game CPU sample was 147.3%, not evidence
of game-time advancement. The observer/config/loaded Runtime remain untouched.

Offline-31 recovers a previously unsupported constant-plus-wrapper-pointer
address expression, supplying fourteen missing ship-design reference field
offsets across five Commands. These are twelve distinct command-relative byte
locations, not fourteen independent objects. Complete native assignment evidence
also proves a derived-state rebuild requirement. Rather than allowing raw writes
now that offsets are known, generated metadata marks the 21 affected serialized
field records read-only and retains their native-assignment population blocker.
The existing shared Builder enforces that mask; no parallel constructor or
execution path is introduced. Details and exact function evidence are in
[`SDK_NESTED_VALUE_RECOVERY_4_5_2.md`](SDK_NESTED_VALUE_RECOVERY_4_5_2.md).

Static readiness remains **193**, with **158** blockers; real coverage stays
**154/87**, with zero new native calls or verification promotions. All **500
maintained tests**, including **56 SDK tests**, pass, as do Windows/Linux
independent Builder fixtures and the fresh catalog audit. The four Windows
matching inputs remain unchanged; retained-catalog checks are not a new Windows
discovery or live test. Source snapshots, complete native bytes, generated
metadata/header, protected-field identities, compiler/test logs and hashes are
retained separately in `offline-31-20261019T2236Z/`. Installed headers are still
run-18. No new library was injected or hot-replaced.

## 23:03 UTC Review And Monthly-Trade Identity

`reviews/20261019T230256Z.json` again confirms the original process start ticks,
world, Runtime instance, mapped library, observer source and prior checkpoint
hashes, with one observer. Through resumed round 591, raw date, object slots
and source autosaves were unchanged. The two journals still contain 93 unique
paired requests and constructions/destructions, all negative, without native
exceptions, interruptions or submissions. The resumed observer added no native
calls and did not consume unchanged-state candidates. Five unique archived
saves total 5,527,328 bytes. Recent cycles used 0.047-0.051 CPU seconds per
approximately 30 seconds; observer RSS was 53,116,928 bytes and free disk space
225,795,428,352 bytes. Short game CPU was 126%, not proof of time advancement.

Offline-32 recovers a complete manager-counter assignment/array-insertion
fingerprint and joins its record-member identity to the shared serializer. The
result identifies the ID used by the three monthly-trade Commands as a manager
order identity, not a resource index. The generated evidence explicitly marks
the native assigning function as mutating and not research-callable. It supplies
no guessed ID, no scalar candidate and no live array provider. All existing
population blockers remain, and the generated executable header is byte-identical
to offline-31. Details are in
[`SDK_MONTHLY_TRADE_IDENTITY_4_5_2.md`](SDK_MONTHLY_TRADE_IDENTITY_4_5_2.md).

An important evidence limit is now explicit: Remove's entire IsValid returns
true without examining the record; Update primarily checks existing same-country
ID membership. Neither result establishes execution readiness or validates an
arbitrary changed amount/price/resource tuple. A future provider must preserve
the existing record's relationships, not choose its fields independently.

Fresh local Linux recovery took 70.387 seconds. All four Windows matching inputs
are unchanged, and 18 retained-Windows-catalog cross-checks pass; no Windows
discovery was rerun. All **504 maintained tests**, including **60 SDK tests**,
pass; lint and diff checks pass. Static readiness remains **193/158** and actual
coverage **154 validated / 87 ever true**. There are zero new native calls,
deployments or verification promotions. No C++ execution code changed, so a
new native binary or duplicate compiler fixture was not needed. Complete native
functions, generated metadata/audit/header, tests, source snapshots and hashes
are retained separately in `offline-32-20261019T2307Z/`; live inputs stay intact.

## 00:08 UTC Review And Correlated Record Hints

The separate `reviews/20261020T000810Z.json` confirms the original game/observer
start ticks, world, Runtime instance, library and observer-source hashes, one
observer and immutable prior checkpoints. Since the 23:34 review the raw date
changed from 63,097,464 to 63,097,608, with construction-item, population-group
and ship-design slot changes. These are state observations, not Command capture
or causal pairing evidence. Source autosaves still have five unique archived
contents; the latest remains `autosave_2233.07.01.sav`.

The observer responded with nine new native legality calls for
`CDismantleMegastructureCommand`, `CDismantleStarbaseCommand` and
`CEarlyFinishAgendaCommand`. All returned false. Across both nonoverlapping
journals, **102 unique requests and 102 constructions/destructions** remain
paired, with no duplicate request IDs, native exceptions, interruption or
submission. These are retries of already negative classes, not new native class
coverage. The v2 journal was separately copied read-only into the offline-33
bundle; it is a validation journal, not a passive gameplay capture.

Through resumed round 719, recent cycles used 0.051-0.053 CPU seconds per
approximately 30 seconds. Observer RSS was 53,252,096 bytes, game RSS
5,654,507,520 bytes, free disk space 225,774,632,960 bytes, and short-interval
game CPU 130.7%. No sampling frequency, game timing or observer configuration
was changed; short CPU measurements do not establish simulation speed.

Offline-33 adds complete native country-record source recovery and a bounded
read-only correlated-tuple decoder, with thirteen new fixture tests passing on
Windows and Ubuntu. It preserves country generation and record relationships,
does not dereference unknown definition pointers, rejects duplicate IDs even
when one duplicate has an unresolved resource, and discards hints after changed
reread bytes. It neither calls native functions nor constitutes a Runtime
provider; no new reader is attached to the game. Details and limits are in the
monthly-trade identity document.

Fresh local ELF recovery took 70.967 seconds; the four Windows matching inputs
remain identical and 18 retained-catalog checks pass. The generated C++ header
is unchanged. All **517 maintained tests**, including **73 SDK tests**, pass;
the initial import-spacing lint failure and corrected run are kept separately.
Static readiness stays **193/158**, real coverage stays **154/87**, and there
are no paired-capture or live-verification promotions. Current Runtime and
observer binaries, source directories and configuration remain untouched.

## Passive Capture Investigation

Exact-build static disassembly is retained in the local bundle's
`offline-queue-investigation/`. It confirms:

- `PostCommandToSession(CCommand*, bool)` at RVA `0x1b02540` delegates to
  `CSession::Post(CCommand*)` at `0x3ca7880` and uses the deleting destructor on
  refusal paths.
- `CSession::Post` reads a transport/player object at session offset `0x60`,
  writes native header fields and delegates through virtual slot `0x30`.
- `GetNumOfCommandsInQueue` at `0x3caa790` combines a transport object's count
  at `0xc4` with another virtual count. This does not establish the queue's
  concrete container, ownership or safe lifetime.
- `PrintCommandLog` at `0x3ca9d60` traverses per-token counters at session
  offsets `0x9c0`/`0x9cc`. Its name is **not** evidence of a retained payload
  history. It was not invoked.

This narrows a possible external read-only queue/counter research path, but no
queue poller or new passive Hook was installed. Render-library `GL`/`SW` command
queues are unrelated and are not Stellaris gameplay command evidence. Confirm
the concrete native transport/container and object lifetime before attempting
payload observation; never assume a count accessor gives stable Command
pointers or silently call virtual native functions from the sidecar.

Local and Ubuntu sidecar tests cover unchanged-date/global-state suppression,
missing candidates, fair bounded selection, backoff, strict non-overwriting
checkpoints, stable save copies, disk limits, positive suppression, transport
interruption and session replacement. These fixtures are distinct from actual
overnight coverage and from the completed 1,156-call acceptance.
