# Stellaris 4.4.6 AI megastructure siting hotspot investigation

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


Status: static call chain confirmed; sampled CPU evidence confirmed; exact-call
probe implemented and fail-closed tested; exact live counts intentionally not
collected from the protected third Observe run.

Target executable:

```text
Stellaris 4.4.6 Linux
ELF Build ID c6969e60fd81d738948222a94c0b5a0841abbffc
```

## Result

The suspected chain is real. `FindBestPositionForMegaStructure()` calls
`CMegaStructureType::CalcAIWeight()`, which evaluates scripted triggers, and the
owned-fleet count trigger materializes and walks the country's fleet ID list.
Existing `perf` windows prove that the complete chain consumes CPU in the live
Mod Observe run.

They do **not** establish an exact call count, repeated-input rate, or safe
cache hit rate. The protected long-running process was not changed or attached
to by the new counter. Consequently, the cache hypothesis remains unproven and
no game AI or trigger code was modified.

## Confirmed native chain

Static analysis of the exact ELF recovered these module-relative entry points:

| Function | Offset | Evidence |
| --- | ---: | --- |
| `CGameState::ProcessAI()` | `0x17d7f00` | symbol plus disassembly |
| `CAIInteriorMinister::HandleCivilianFleets()` | `0x23dfad0` | symbol plus call site |
| `CAIInteriorMinister::HandleConstructors(...)` | `0x23f1440` | symbol plus call site |
| `CAIInteriorMinister::BuildStation(...)` | `0x23f4590` | symbol plus call site |
| `CAIInteriorMinister::BuildMegaStructure(...)` | `0x23f5090` | symbol plus two call sites |
| `CAIInteriorMinister::FindBestPositionForMegaStructure(...)` | `0x24017a0` | symbol plus call site |
| `CMegaStructureType::CalcAIWeight(...) const` | `0x26c83a0` | symbol plus call site |
| `CTrigger::Evaluate(CEventScope&) const` | `0x1da2a20` | symbol and virtual dispatch |
| `CScriptedTrigger::ActualEvaluate(CEventScope&) const` | `0x36baca0` | symbol and sampled stack |
| `CCountInScriptedListTrigger<COwnedFleetListBuilder>::ActualEvaluate(...) const` | `0x355c9e0` | symbol plus calls to `CalculateCount` |
| `CCountInScriptedListTrigger<COwnedFleetListBuilder>::CalculateCount(...) const` | `0x355e090` | symbol plus list walk |

The call sites establish this path:

```text
HandleCivilianFleets
  -> HandleConstructors                 call site 0x23e0b9e
  -> BuildStation                       call site 0x23f149f
  -> BuildMegaStructure                 call site 0x23f4763
  -> FindBestPositionForMegaStructure   call sites 0x23f59df, 0x23f5b83
  -> CMegaStructureType::CalcAIWeight   call site 0x24019a2
  -> CTrigger::Evaluate
  -> CScriptedTrigger::ActualEvaluate
  -> CCountInScriptedListTrigger<COwnedFleetListBuilder>
```

`CalculateCount` acquires an ID array, obtains the country from the scope,
reads the country's fleet collection, materializes fleet IDs, creates a scope
for each fleet, evaluates the child trigger, and releases the array. This
confirms repeated fleet enumeration can occur. It does not show that two
evaluations have equivalent inputs or that their results can be reused.

`CalcAIWeight` also contains the engine's existing script-profiler guard. That
is useful corroboration, but it is not an exact count source for this specific
ancestor path.

## Existing sampled evidence

An offline pass over 725 retained `perf` aggregate windows produced:

| Frame or chain | Inclusive sampled stacks | Windows |
| --- | ---: | ---: |
| `HandleCivilianFleets` | 200 | 29 |
| `HandleConstructors` | 199 | 28 |
| `FindBestPositionForMegaStructure` | 186 | 15 |
| `CalcAIWeight` | 178 | 14 |
| `CTrigger::Evaluate` | 1,949 | 599 |
| `CScriptedTrigger::ActualEvaluate` | 1,151 | 502 |
| owned-fleet `ActualEvaluate` | 142 | 13 |
| owned-fleet `CalculateCount` | 142 | 13 |
| full siting core through `CalcAIWeight` | 178 | n/a |
| deep chain through the owned-fleet trigger | 89 | n/a |

There were 22,403 sampled stacks in that analysis set. The siting core appeared
in about 0.795% and the deep owned-fleet chain in about 0.397% of samples.
These are sampling proportions, not invocation counts. They are sufficient to
prioritize the chain, but not to estimate a cache hit rate.

## Exact-call metrics status

| Requested metric | Protected live run |
| --- | --- |
| `FindBestPositionForMegaStructure` calls | not measured exactly |
| `CalcAIWeight` calls | not measured exactly |
| `CTrigger::Evaluate` calls under this path | not measured exactly |
| owned-fleet trigger calls under this path | not measured exactly |
| same-update repeated opaque inputs | not measured exactly |
| per-country distribution | not measured exactly |
| fleet-list length | deliberately not dereferenced |

This is a deliberate safety result, not missing instrumentation. Injecting a
new high-frequency probe into the current long run would violate the run's
evidence boundary and make an overhead comparison impossible.

## Counter implementation

`ai_megastructure_counter_probe.cpp` provides a research-only exact entry
counter for a later disposable run. It is not linked into the runtime or
Broker. Its safeguards are:

- explicit `IAG_AI_MEGA_COUNTER_ENABLE=1` arming;
- exact ELF Build ID and instruction-prefix checks;
- `outer` mode for `HandleCivilianFleets`, siting and weight calculation;
- opt-in `full` mode for the global trigger and owned-fleet trigger entries;
- thread-local fixed-capacity maps and atomic counters on the hot path;
- no hot-path allocation, symbol lookup, disk I/O, mutex, or pointer chasing;
- a five-second background aggregate writer with bounded rotating output;
- a filesystem pause switch and overflow counters; and
- no argument, return-value, RNG, object, scheduling, or game-state mutation.

One `HandleCivilianFleets` invocation is the initial update boundary. Repeated
tuples are recorded as opaque pointer identities:

```text
CalcAIWeight: (megastructure type, country, candidate)
Trigger:      (trigger, megastructure type, country, candidate)
Owned fleet:  (trigger, country, threshold, optimization)
```

Equality of these tuples is only an upper bound on possible reuse. It does not
prove unchanged flags, date, resources, scoped variables, fleet membership,
random state, or scripted-trigger purity.

The companion `analyze_ai_megastructure_counter.py` keeps exact entry counts,
inclusive thread CPU time, repetition and sampled evidence conceptually
separate. Table overflow changes the repetition classification to a lower
bound instead of silently undercounting it.

## Validation performed

The probe compiled on the Ubuntu target with C++20, warnings-as-errors and
frame pointers. Two fail-closed load tests were run outside Stellaris:

1. no arm variable: status `not_armed`;
2. armed in a non-Stellaris process: `build_id_mismatch`, with no log created.

The Python analyzers have unit coverage for exact/delta counts, overflow
classification and the separation of Mod attribution from structure evidence.
The current Stellaris process never loaded this library, so its deployed
overhead in the third Observe run is exactly zero.

At the final integrity checkpoint for this report, the protected run had
reached `2301.03.01` with 1,167,942 command, 1,526,192 payload and 22,864 state
records. Malformed, probe-dropped and writer-dropped counts were all zero, and
the pending byte backlog had returned to zero. `/proc/<pid>/maps` independently
confirmed that the new counter library was not loaded.

## Required isolated validation

Use a disposable copy of one save and the same game speed for three nearby,
equal-duration phases:

1. existing Observe only;
2. counter in `outer` mode;
3. counter in `full` mode.

For each phase record game-date progress, Stellaris CPU/RSS, capture loss and
backlog, exact counters, table overflow and profiler samples. Abort if existing
capture loss becomes nonzero or game progress materially degrades. Only after
that comparison may `full` mode be considered for a long run.

After exact data exists, a cache is worth considering only if all of these are
demonstrated:

- repetition is concentrated within a well-defined AI update;
- the complete result dependency set is known;
- Mod scripted triggers do not read values that may change inside that scope;
- key construction is cheaper than the avoided evaluation; and
- deterministic results match with and without the proposed cache.

Until then the correct conclusion is: the hotspot and fleet enumeration are
real; redundant and safely cacheable computation is not yet proven.
