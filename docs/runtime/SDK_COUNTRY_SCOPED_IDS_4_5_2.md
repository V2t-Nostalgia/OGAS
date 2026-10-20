# Country-Scoped IDs: Stellaris 4.5.2

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Evidence Boundary

These are exact-build **Linux static findings**, not native legality calls,
execution evidence, Windows offsets or production capabilities. Build ID:
`121ecb516cbc5f1d39917fbcc36620534384e2c2`.

Three remaining scalar-ID families do not use a global generation-bearing
`TPdxRef` handle. A field named `id` is not sufficient to choose a resolver.
The current game and its injected Runtime were not changed for this work.

## Special Projects

`CSpecialProjectInstance::AccessInstance` (`0x1fa27f0`) tail-jumps to
`NSpecialProjectUtil::AccessProjectOfCountry` (`0x1faf9e0`). That helper adjusts
the country pointer by `0x2448` before entering
`CCountryEventManager::AccessSpecialProject` (`0x2417f10`).

The complete native lookup checks a signed count, scans a pointer array forward,
compares the object's 32-bit value at `+0x18` with the requested ID, and returns
the class's native null sentinel if absent. Relative to **CCountry**, array data
is at `0x24a8` and count at `0x24b4`; entries are 8-byte pointers.
No global database slot or generation check occurs on this path.

## Points Of Interest

`CPointOfInterest::AccessInstance` (`0x1e52080`) adjusts the country pointer by
`0x2448` and enters `CCountryEventManager::AccessPointOfInterest` (`0x2417330`).
The member method takes `CPdxIntegerFlags::CIntFlag<unsigned short>` and searches
the country's pointer array backward. It compares **16 bits** at object offset
`0x3f0`, not a global object ID. Country-relative data/count locations are
`0x24d8`/`0x24e4`, with 8-byte entries. An absent match returns the native null
sentinel. A future provider must preserve this width and native lookup order.

## Active Event Chains

`CActiveEventChain::AccessInstance` (`0x2415850`) first treats the input as an
index into the current `CEventChainDatabase`: negative/out-of-range values are
rejected, with array/count at database offsets `0x50`/`0x5c`.
It then checks the native definition object and joins it against the country's
active-chain array at `0x2460`/`0x246c`. The active object's pointer at `+0x18`
must equal that definition object. It returns the active-chain null sentinel
when no owned instance matches.

The input is therefore neither an active-instance slot nor a `TPdxRef`. Do not
substitute an index derived from external files or assume definition ordering
survives changes to the loaded content. The offline generator now recognizes
the complete 114-byte join, requiring agreeing named definition-database,
definition-null and active-instance-null globals. Its branch targets, virtual
validation slot (`0x10`), pointer comparison and stride are checked, not inferred
from the accessor's name alone. Extracted offsets remain variable metadata.

This is a **discovery recipe**, not an implemented live candidate provider.
The native instance-count guard only checks for zero; a future bounded provider
must also reject negative and excessive counts. Definition validation remains
an indirect native call; metadata recovery does not execute it or establish
the lifetime of a future selected object.

## Automatic Recovery And Remaining Work

`tools/sdk_recovery/scoped_id_recovery.py` recognizes the two member-array
search bodies and the loaded-definition join above, retaining bounds branches,
identity width or join semantics, loop direction and named null globals.
It follows at most three pure tail thunks,
rejecting cycles, unknown targets and unsupported pointer adjustments. Only
entrypoints that still take an unadjusted country pointer are equivalent;
member methods taking the event-manager pointer are not country entrypoints.

The generator retains these three recipes in `country_scoped_accessors` and
links five validator fields to them: event-chain pin/track, special-project
pin/track and point-of-interest track. The scalar storage remains `u32`.
Event-chain fields retain a distinct loaded-definition-index identity kind.
This is **not** reclassification as a
global reference and does not make the fields writable through another API.

Through offline-28, the audit retains `country_scoped_candidate_provider` and retains
`country_scope_binding_unresolved` where the caller has not been proven.
The native candidate provider still needs implementation and a future validation
window. Future work must use the existing game-thread builder/queue, bind the
same validated country, enforce bounded live arrays and object lifetimes, and
compare selected IDs with the native lookup. Do not inject new code into the
current overnight session to perform that test.

## Proven Caller Bindings

Offline-28 recognizes the complete 117-byte native validator body for the five
fields above. Its command-country field at `+0x1c` is resolved through the
`TPdxRef<CCountry>` database with a slot bound, non-null test and full generation
comparison against the country object's ID at `+0x20`. The native null-country
path and virtual predicate at slot `0x58` are preserved. The same country
pointer remains in callee-saved RBX, becomes RDI, and is paired with the command's
32-bit scoped value at `+0x20` in ESI before the known direct lookup call.

The generator requires the full body and agreeing named country globals, a
known country-scoped lookup and the existing local field-flow proof. It attaches
`country_reference` to each matching field evidence record. Recipe-level caller
binding remains unknown: this proof applies only to these five validators,
not to arbitrary users of the lookup. The virtual predicate is **not** evidence
of permission to act for a foreign country.

| Validator | Linux RVA |
|---|---|
| `CPinSituationLogEntryCommand<CActiveEventChain>::IsValid` | `0x32165d0` |
| `CPinSituationLogEntryCommand<CSpecialProjectInstance>::IsValid` | `0x32169c0` |
| `CTrackSituationLogEntryCommand<CActiveEventChain>::IsValid` | `0x32164f0` |
| `CTrackSituationLogEntryCommand<CPointOfInterest>::IsValid` | `0x32187a0` |
| `CTrackSituationLogEntryCommand<CSpecialProjectInstance>::IsValid` | `0x32168e0` |

The audit removes only the now-resolved caller-binding diagnosis, after checking
its field/callsite/type association. All five commands remain blocked on their
native candidate provider. No C++ Runtime, native API or production eligibility
was changed, and no Windows caller-binding proof is claimed.

Static-ready coverage stays **186**, with **165** static blockers; native
validated/positive coverage stays **154/87**. The generated research C++ header
is byte-identical to offline-25: new information is research metadata only.

The earlier two-recipe/three-field evidence remains in
`.runtime-evidence/sdk-incremental-20261019-01/offline-26-20261019T1950Z/`.
The three-recipe/five-field follow-up is in `offline-27-20261019T2014Z/`, with
complete function bytes/disassembly, final-source re-extraction, gap audit and
tests. Fresh Linux generation took 70.133 seconds. The four inputs consumed by
Windows matching are byte-identical to the completed offline-23 discovery, so
that Windows catalog was reused; 18 OGAS and 38 pinned-header comparisons pass.
Neither Windows discovery nor any native call was repeated for this change.

Current tests cover all fixed instruction-byte mutations of the join, signed
index bounds, changed globals, virtual slot, stride, member offsets and trailing
code. An integration test prevents either scalar-ID family from becoming a
global reference or silently losing its provider/binding blockers.

The earlier reported test totals included four archived test-source modules
under `.runtime-evidence`. This also allowed an old snapshot to shadow the
current recovery module during test discovery. The repository runner now
excludes immutable evidence, with a regression test and no archive changes.
All **477 maintained tests**, including **34 SDK recovery tests**, pass. The
original failed mixed-source run and corrected runs are both retained. These
counts are not directly comparable to the earlier archive-inclusive totals.
Installed Linux/Windows headers still match run-18; the research header is
byte-identical to offline-26. No production capability or verification level
was changed.

The caller-binding follow-up is independently retained in
`offline-28-20261019T2043Z/`. Fresh Linux recovery took 72.313 seconds; all four
Windows discovery inputs and the research C++ header remained byte-identical
to the preceding pass. The 18 OGAS and 38 pinned-header comparisons passed using
the retained Windows catalog, without repeating Windows discovery. All 482
maintained tests passed, including 39 SDK tests. Fixed instruction-byte mutation,
wrong globals/resolvers, invalid offsets, truncated bodies and the audit's
continued provider rejection have regression coverage. Consumer headers remain
run-18, and current native coverage remains 154 validated / 87 ever true.

## External Candidate Hints

`tools/sdk_recovery/scoped_id_candidates.py` is a bounded external-memory
decoder, not a Runtime provider or a second observer. It accepts the existing
generated lookup recipes and a read-only reader; it never calls native functions
or supplies IDs to the current Runtime. It preserves 16/32-bit member-ID width,
forward/reverse lookup order and first-match handling of duplicate values. The
event-chain recipe joins country-owned definition pointers to indices from the
**actual loaded** definition database, excluding null sentinels.

Reads have per-family byte/call limits, signed count checks, truncated-array
markers and a bounded returned-hint count. Selected bytes are reread, but equal
reads do not freeze the world or establish object lifetime, definition validity,
permission, native lookup success or `IsValid`. Results always retain that
distinction and `runtime_candidate_provider_implemented=false`.

A one-shot external read of the unchanged authorized game found these values
for the reviewed country 0. They are **candidate hints only**:

| Family | Country list count | Hints |
|---|---|---|
| Special projects | 4 | `6`, `7`, `8`, `10` |
| Active event chains | 4 | loaded definition indices `16`, `13`, `119`, `137` |
| Points of interest | 0 | none for this country |

The event-chain definition pool had 306 entries. Selected bytes, country handle,
world and raw date were unchanged across the read. The audit performed 56 bounded
reads totaling 5,348 bytes, taking 0.531 CPU seconds including exact-executable
hash verification and imports. This is a one-shot observer cost, not an estimate
of impact on game speed. No native lookup, `IsValid`, submit, hook or injection
was performed. Missing POIs for this country do not establish galaxy-wide absence.

Evidence is retained in `scoped-hints-20261019T2112Z/`. Module-global Token getters
leave these raw catalog token names null; the immutable snapshot reflects that.
A separate `caller-identities.json` supplies exact C++ class names and the
research-only command names returned by the accepted batch, without rewriting
the snapshot or treating those names as public semantic actions.

The recorded source snapshot is the exact reader used for the live read. Later
strict integer-type rejection was added to the editable reader; the live read
was not repeated merely for that hardening. Both source versions are preserved,
and tests cover bounds, search order, duplicate IDs, nulls, definition joins,
changed memory and the absence of native-validation claims. This evidence does
not remove the Runtime candidate-provider blocker or change the 186 static-ready
and 154/87 native-coverage totals.

Do not replay these numeric hints into a later world or Runtime. A future
game-thread provider must enumerate again and verify the selected object's
native lookup and current country relationship. The scoped values do not gain
generation semantics just because the country's own handle was checked.
All 491 maintained tests passed, including 48 SDK tests; nine fixtures cover the
new reader. Existing generated headers and the loaded library remain unchanged.

## Offline Shared Runtime Provider

Offline-29 adds a typed `RecoveredScopedIdBinding` table generated only for
complete, unique, command-bound Linux proofs. The existing shared probe consumes
this table; it does not introduce another Command layout or construction path.
The five command fields remain unsigned scalars and are populated using the
existing `NativeCommandBuilder::SetUnsigned`. Their country field is fixed to
the same validated country used during enumeration, including field names that
are not recognized as conventional actor names. Partial or conflicting proofs
remain blocked by the audit.

The three provider recipes preserve 32-bit member IDs, reverse 16-bit flag
searches and actual loaded-definition index joins, respectively. Every proposed
value must resolve through the recovered native country lookup to the same
enumerated object before Factory/Populate/IsValid/Destroy proceeds. Native
lookups are bounded at 256 per request, country entries at 256, loaded definitions
at 4,096 and returned candidates at 16. Results record truncation and scoped
lookup counts separately from IsValid counts. Invalid bounds are structural
failures, empty valid lists are missing candidates, and C++ lookup exceptions
prevent construction. This is not protection from native access violations;
only a future game-thread validation window can establish live safety.

The generator's static-ready count rises from 186 to **191**, with **160**
remaining static blockers. Native coverage remains **154/87**. No runtime
provider was deployed into the overnight process; its revision-2 binary and
run-18 consumer headers are unchanged. The new source advertises revision 3
for a future binary so an observer can distinguish that capability. The earlier
external hint reader's `runtime_candidate_provider_implemented=false` describes
that immutable read and the active old Runtime, not the new offline source.

The evidence bundle `offline-29-20261019T2143Z/` contains derived Linux metadata,
the generated research header, audit, independent Windows/Linux fixture logs
and source/hash records. The catalog is derived from offline-28; neither ELF
discovery nor Windows matching was rerun. Linux recipe emission is not evidence
of corresponding Windows accessors. Both platform fixtures pass using fake
objects, with no attachment, injection or game commands. All 494 maintained
tests, including 50 SDK recovery tests, pass. The initial Python regression
exposed bool-to-integer coercion in `NativeProbeBinding`; its strict/frozen
contract now rejects that, and the failed and corrected runs are both retained.

At the next suitable validation window, enumerate again on the existing game
thread rather than replaying old hint IDs. Probe the five commands in small
bounded requests, retain native lookup counts and country bindings, and check
Factory/destructor pairing before interpreting IsValid results. An empty POI
list is a scene gap, a false predicate is not an SDK failure, and even a true
predicate remains legality evidence only. Do not inject this source into the
current long-running session or promote production actions from these fixtures.

## Special-Project Research And Cancellation

Offline-30 follows a separate const getter used by two additional commands:

| Function | Linux RVA | Complete body |
|---|---|---|
| `CResearchSpecialProjectCommand::IsValid` | `0x22a4750` | 161 bytes |
| `CCancelResearchSpecialProjectCommand::IsValid` | `0x22a49c0` | 142 bytes |
| `NSpecialProjectUtil::GetProjectOfCountry` | `0x1faf9d0` | 12 bytes |
| `CCountryEventManager::GetSpecialProject` | `0x2418730` | 42 bytes |

The const getter adjusts RDI by `0x2448` and tail-jumps to the const member
search, whereas `AccessProjectOfCountry` at `0x1faf9e0` goes to a different
member body at `0x2417f10`. Treating these as the same address would be wrong.
The two complete 42-byte bodies have identical search/count/stride/ID logic,
with only a RIP displacement differing; both resolve that displacement to the
same `TPdxNullObject<CSpecialProjectInstance>` global. The new generic equivalence
pass accepts only complete pure tail thunks with the same cumulative country
adjustment and complete member-search equivalence, including that resolved
global. It never accepts an event-manager member pointer as a country pointer.

The two command constructors independently copy `TPdxRef<CCountry>` into `+0x1c`
and the pointed-to project's 32-bit member at `+0x18` into command `+0x20`.
The validators generation-check that country, pass it in RDI and load the
scoped ID into ESI before calling the const getter. The generator matches each
entire validator, its failure edges, country/project virtual guards and the
named `CTechnologyStatus::IsResearching` predicate. The research form additionally
retains `CanResearch(country, true, nullptr)`; cancellation requires an already
researching project. These predicates decide game legality; the provider does
not invent an ID or assume all country-owned projects are researchable.

Both fields use the existing `member_u32` provider and Builder, with no C++
execution-path change. There are now seven generated scoped bindings and
**193 static-ready / 158 blocked** commands. All previously validated classes
retain static eligibility. Native coverage is still **154/87**, and the active
revision-2 Runtime/config/run-18 headers are unchanged. A future validation
window must freshly enumerate projects, verify native lookup/object identity
and pair construction/destruction; no historical numeric hint is replayed.

`CCollectDataFleetOrderCommand` was also inspected, but remains blocked. Its
1,316-byte validator derives country from the fleet controller and has distinct
system-wide and individual-project branches. Constructors demonstrate different
system/project sentinel combinations. Automatically combining arbitrary valid
fleet/system/project IDs would not prove those branch dependencies. Its raw
predicate and constructor evidence are retained; no scoped country field or
candidate mapping is fabricated for it.

Evidence in `offline-30-20261019T2206Z/` includes complete native bytes and
disassembly for all of the above, fresh Linux generation, derived field proofs,
the research header and audit. The four Windows matcher inputs are unchanged;
the retained Windows catalog passes 18 OGAS comparisons without new Windows
discovery. All 497 maintained tests, including 53 SDK tests, pass. Tests mutate
complete predicate branches/slots, helper identities, thunk adjustments, search
layout and null targets to check rejection. The new header compiles and passes
the isolated Linux fake-object Builder fixture at `nice -n 19`. That is not a
real Stellaris call or a Windows accessor proof, and no production verification
level was changed.
