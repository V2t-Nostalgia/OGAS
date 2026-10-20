# Command recovery expansion: Stellaris 4.5.2

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Evidence Boundary

This is the offline expansion after the first two live batches. It does not
supersede their evidence or promote any Action to `live_verified`.
The later expanded acceptance and incremental observer are recorded below and
in [SDK_INCREMENTAL_VALIDATION_4_5_2.md](SDK_INCREMENTAL_VALIDATION_4_5_2.md).
**No new live game probe, submission, injection, restart or save modification
was performed during this offline phase.** Compiling on Ubuntu used new,
independent `/tmp/iag-sdk-recovery-offline-*` directories, never the library
mapped by the previous test process.

Exact inputs:

- Linux Build ID: `121ecb516cbc5f1d39917fbcc36620534384e2c2`.
- Linux SHA256: `1c4c79a0ef8af7b984b797606373eb68b60fe421e4ef54c20e12e4a9398ba86b`.
- Windows SHA256: `400df27c82ddc845aa9dce79bd468d81f18f060d299cd263e3afa93aef4f7a83`.
- Baseline: `.runtime-evidence/sdk-batch-20261019-01/paused-batch/report.json`.
- Final discovery inputs/outputs: `.tmp/sdk-recovery/run-18/`.
- Durable final review bundle: `.runtime-evidence/sdk-recovery-expansion-20261019-01/run18/`.
  Earlier intermediate bundles remain in its parent directory, unchanged.
- Every prior run, checkpoint, raw batch report and generated output remains.
  Consumer headers were updated only after archiving their previous versions.

## Offline Coverage

These are **static eligibility counts**, not executed native calls:

| Metric | Count |
|---|---:|
| Linux command catalog | 351 |
| Recovered Factory/size/VTable/lifecycle/token mechanism | 351 |
| Conservative standalone Factory/Destroy eligibility | 295 |
| Factory/Destroy eligibility including fully populated paths | 311 |
| Complete supported population layout | 229 |
| Eligible to search candidates and invoke IsValid | 172 |
| Previously completed commands still eligible | 40 |
| Newly eligible, excluding existing world-only gaps | 122 |
| Previously missing live CResolution objects, still scene-dependent | 10 |
| Remaining statically blocked commands | 179 |
| New native IsValid calls during this phase | 0 |

The 172 total is `40 + 122 + 10`. The ten resolution-dependent entries were
already structurally eligible in the original runtime; they are **not ten new
recovered capabilities**. An unchanged world without those objects will still
skip them. The old 25-positive/15-negative-only result remains historical,
not a result of the expanded implementation.

| Original gap | Original count | Supported layout now | Static IsValid-ready now |
|---|---:|---:|---:|
| Incomplete/nonflat serializers | 195 | 73 | 65 |
| Missing object resolvers | 50 | 50 | 47 |
| Scalar semantic mapping | 30 | 30 | 1 |
| No object scope | 6 | 6 | 2 |
| Missing live objects | 10 | 10 | 10, conditional on the scene |
| Indirect token getters rejected by old heuristic | 15 | 15 | 2 |
| CRTP queue base/factory mismatch | 5 | 5 | 5 |

All 351 entries, including all original 311 unfinished entries, have individual
field blockers, constructor evidence, callsites and scene prerequisites in
`gap-audit/audit.json` and `gap-audit/audit.md`. Blocker totals are nonexclusive.

## Reusable Recovery

The existing ELF indexer, generator, `NativeCommandBuilder` and Idle queue are
extended; there is no parallel runtime or per-command probe implementation.

- Factory stores identify embedded native VTables and pointer defaults.
  Named constructor initialization is traced to a bounded depth. Nested
  serializers and stack-based reference serializers are retained with their
  identity/offset evidence. 377 nested leaf fields are represented in the final
  population plans; opaque native value recipes avoid flattening owned objects.
- Allocation size comes from the native Factory. Five queue commands now use
  their concrete registered Factory/VTable, not the CRTP base VTable. The base
  serializer remains linked by its exact function address.
- Fifteen template token getters load `CCommandHelper<T>::_Token` from module
  storage. Runtime preflight checks that exact getter shape/address and the
  initialized nonzero, non-sentinel token. A zero file image is not invented
  into a compile-time token or a semantic Action name.
- 54 object databases are recovered from complete typed accessors or agreeing
  independent inlined bounds/index/generation checks. Planet and colony remain
  distinct types and layouts. Full generation-bearing handles are re-resolved
  before use; slot indices are never substituted for IDs.
- 40 typed definition pools cover 38 definition types. Constructor array
  initialization and serializer key access prove their layouts. Const native
  key-lookup code supplies evidence when a database constructor is absent.
  Multiple pools can contain the same C++ type: candidates are interleaved,
  aliases to one object are accepted, and identical keys pointing to different
  objects are rejected rather than resolved last-write-wins.
- Complete-constructor parameter ASTs supply field types and identity-store
  evidence. Base-object ctors with possible hidden VTT arguments, unknown
  aggregate classification and floating-point argument layouts are excluded
  from the integer-register model. 371 fields have constructor evidence.
- Reflected enum token tables provide actual enum domains. 741 direct native
  constructor callsites have verified instruction boundaries. Literal values
  do not propagate across branches or intervening calls. Only bounded named
  quantities can use proven positive literals; IDs and indices do not.
  For example, the claim quantity `1` is recovered from a real native callsite,
  not selected as a guessed object ID.
- Conditional boolean serialization and supported single-byte flag masks are
  recovered without overwriting neighboring flags. ABI alignment gaps and
  proven initializer writes replace the original tightly-packed-POD-only gate;
  arbitrary unrepresented payload gaps remain rejected.

The final generator runs the retained upstream 47 checks, 38 reference-header
checks and 18 OGAS anchors with no mismatches. These are comparisons, never
constants used to repair a discovery.

## Shared Builder Operations

The same builder used by reviewed production adapters supports:

- Typed object references and bounded signed/unsigned scalar writes.
- Recovered enum candidates and raw current-game-date words.
- Borrowed definition pointers resolved from native keys and typed pools.
- Native `CString::operator=(char const*)`, not copied SSO layouts.
- Reference arrays using native `InsertAtEmplace<>(int)`, preserving all ID bits
  and leaving allocation/destruction with the native owning object.
- `CPersistentName` through its native text constructor, native move assignment
  and non-deleting destructor. Its recovered extent is 88 bytes on this ELF;
  CString/vector internals are not reproduced by the bridge.

Every write invalidates prior validation. Factory, VTable, token, field bounds,
type, size and destructor checks remain. Research never releases ownership for
submission. Incomplete population may receive a separately counted
Factory/Destroy-only test **only** when its conservative lifecycle flag permits
it. It never proceeds to IsValid with an unpopulated object.

## Remaining Gaps

This phase did **not** clear all 311 original unfinished entries.

- 122 commands still have unsupported/incomplete composite layouts. These
  include discriminated variants, scope/event-handle serializers, dynamic
  dictionaries, opaque blobs, and complete ship/species/empire/galaxy designs.
  A recovered nested offset is not permission to memcpy a nontrivial object.
- Bare `int`/`uint` declarations do not establish live IDs or selector domains.
  Session/human/lobby IDs need session managers; special projects, control
  groups, individual fleet orders and exhibition indices need the appropriate
  live owner collection. Their callsites are retained instead of filling zero.
- `CChatBuffer` and `CLargeFileHandler` are not treated as galaxy Pdx databases.
  Four commands need these session-specific resolvers.
- Some species/galaxy template definition pointers still lack unique semantic
  type/pool evidence. A type-compatible pointer is not necessarily a legal
  template, civic combination, event scope or gameplay choice.
- Forty commands outside the Factory/Destroy eligibility union have neither a
  conservative standalone lifecycle proof nor a complete usable population
  plan. Their native constructor calls and blockers remain in the audit; they
  are not allocated just to inflate coverage.

DWARF inspection visited 21 compilation units / 55,388 DIEs. None of the 414
requested game/core types was recovered. Presence of `.debug_info` therefore
did not supply missing game layouts. Checked common local/Ubuntu tool roots did
not reveal a usable Ghidra installation/export; no decompiler result is claimed.
Remaining serializers/callers have RVAs for targeted Ghidra follow-up rather
than speculative expansion of the bounded scanner.

## Uniform Acceptance

Finish offline checks before opening the acceptance session. Use a disposable
late-game save with a normal observed/controlled empire, colonies, building
queues, designs, fleets and leaders. Existing wars, resolutions, situations and
operations increase coverage, but the tool does not create them. If the ten
resolution prerequisites are absent, record the missing state rather than
proposing a resolution or advancing time without approval.

Use one fresh process, one load, one injection of the newly built runtime.
Keep it paused and avoid other gameplay writers during the run. Never rebuild
over a loaded library or inject a second active runtime over the old Hook.

```bash
python services/stellaris_native_runtime/tools/validate_recovered_commands.py \
  --output /path/to/new-evidence-directory \
  --candidates 16 --batch-size 16 --interval 0.05 --max-seconds 900
```

The runner discovers the complete compiled catalog and requires research
`probe_revision >= 2`, preventing accidental acceptance against the old binary.
It checks PID, runtime instance, build, catalog and world identity. The actor
stays fixed; `--country` explicitly pins it. Candidate combinations are bounded
and diagonal, not an exhaustive Cartesian search. Native references are
preferred by ownership; fleet targets can prefer foreign fleets. Booleans retain
the conservative `false` default, including force/override flags. This is not an
exhaustive search of every possible legal combination.

One existing Idle callback handles at most one candidate:

`Factory -> typed Populate -> IsValid -> native Destroy`

No `PostCommand`, `Execute`, new Hook, Action registration or `live_verified`
promotion occurs. Paused Idle behavior preserves the existing research-only
scheduler exception, not production execution policy.

Reports separate construction, population, native calls, destruction,
missing parameters, static failure, C++ exception and interruption. Native
reason strings are retained using a native CString lifecycle. `IsValid=false`
is **unclassified** until evidence separates wrong candidates, unmet scene
conditions and possible recovery defects. Constant validators are identified
separately; their `true` result is not substantive gameplay legality proof.

Disconnects/exceptions stop the batch, retain completed rows and the exact last
request, and leave remaining entries untested. There is no automatic replay or
reinjection. Native signals are not made safe by C++ catch blocks.

## Reproduce The Audit

```bash
python services/stellaris_native_runtime/tools/sdk_recovery/audit_recovery.py \
  --sdk .tmp/sdk-recovery/run-18/linux_sdk.json \
  --baseline .runtime-evidence/sdk-batch-20261019-01/paused-batch/report.json \
  --output .tmp/sdk-recovery/new-gap-audit
```

`inspect_dwarf.py --binary ELF --sdk linux_sdk.json --output NEW.json` performs
the supplemental type audit without attaching to a process. All report outputs
are exclusive/new paths. Build/test logs and source/archive fingerprints are
retained in the review bundle. Live acceptance results must be appended as a
new evidence run, not edited into this offline count table.

## Offline Verification

- Full repository Python suite: 448 tests in 63 modules, passed.
- Focused SDK recovery suite: 18 tests, passed (included in that total).
- Generator comparisons: 47 retained upstream checks, 38 pinned-header checks
  and 18 OGAS anchors, all passed.
- Linux Release CMake build: runtime and test targets compiled; CTest 3/3 passed.
- Windows MSVC `/W4 /WX` build: runtime and loader compiled; Action contract and
  shared Builder tests passed; the emitted manifest parsed successfully.
- Ruff checks passed for the owned recovery, client and batch-runner changes.
  Retained upstream vendor files were excluded from this scoped lint check.

Final Linux library SHA256:
`c5302c75041e2db83df6b74959921cdbd120927b7728d642136d7555639cd77a`.
Its immutable build root is
`/tmp/iag-sdk-recovery-offline-58b6400113744df0b85f646a24df918a/`.
The final bundle records source-file hashes, the source archive hash, generated
header hashes and build/test logs. These are offline verification results, not
native game calls or Windows gameplay acceptance.

## Expanded Live Acceptance: 2026-10-19

One new Linux process (PID `273675`), one loaded world and **one Runtime
injection** completed the full directory in **92.878 seconds**. The player
confirmed the disposable save was loaded and paused. This does not rewrite the
offline table or the original two batch records.

| Actual measurement | Count |
|---|---:|
| Directory entries / successful structure preflights | 351 / 351 |
| Distinct commands constructed and destroyed | 309 |
| Distinct commands populated and natively validated | 154 |
| Distinct commands with at least one true / only false | 87 / 67 |
| Distinct commands tested for lifecycle only | 155 |
| Native IsValid calls / true / false | 1,156 / 87 / 1,069 |
| Constructed / destroyed native objects | 1,311 / 1,311 |
| Missing live candidates / statically blocked entries | 18 / 179 |
| C++ exceptions / structure failures / interruptions | 0 / 0 / 0 |

The 18 missing scenes are `CResolution` (11), `CMission` (4),
`CVivariumCritter`, `CFederation` and `CWaystationNetwork` (one each).
All recorded dates were raw `63093912`; world `102024944543984`, PID, runtime
instance and catalog remained consistent. The process remained alive.
All 40 original natively tested classes were tested again; 114 additional
classes reached native validation. Positive coverage rose from 25 to 87, but
`CFleetSetExpansionFlag` changed from true to false in this different world/date
with the same country binding and no native explanation; its cause is left
unclassified, not hidden as an unconditional regression pass.

Two true validators (`force_human_ai_command` and `human_ai_command`) are
constant validators; the other 85 true results used native predicates. None
was submitted. Of the false calls, 622 retained native reason text and 447 did
not. Examples explicitly report ownership, queue priority, missing ascension
slots, no available upgrade or no combat; these explain individual rule
rejections, not every false result or every candidate relationship.

Instrumented probe/validator elapsed sums were 355.395 / 99.760 ms; these are
not CPU samples or a whole-process overhead benchmark. All calls still observed
`run_game_update=true`; pause is established by the player and unchanged dates,
not by equating that flag with the pause state.

Evidence: `.runtime-evidence/sdk-expanded-batch-20261019-01/`. The complete
355-file batch is retained in `batch-evidence.tar.gz` with per-file hashes,
alongside the original remote directory, injection log, baseline comparison and
typed report. A redundant slow individual-file export was stopped after the
complete archive was verified; partial exports were retained, not deleted.
No production Action or verification level was changed.
