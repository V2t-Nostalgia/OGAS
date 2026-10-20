# Offline Script / Native Candidate Pipeline

Research only. This is not an Action pack, rule-engine replacement, MCP server,
execution queue, or permission to submit Commands. Production Applications,
Broker admission and `live_verified` states are unchanged.

## Pipeline

```text
exact SDK + ELF + token registry
  -> bounded native call/virtual-edge/guard discovery
external game/Mod files -> CWTools ordered AST -> partial script constraints
immutable save -> existing WorldStateIndex -> typed facts / full reference IDs
  -> evidence-ranked, bounded typed candidates
  -> explicit revision-6 research validation window (revision 7 for i64)
  -> existing CGameIdler / NativeCommandBuilder / IsValid / Destroy
  -> journal + native feedback + shared recovery worklist
```

No PostCommand/Execute path exists in this coordinator. A script pass, native
legality, actual execution and synchronization are four different claims.

## Build The Optional Parser

Requires .NET SDK/runtime 9 and the existing Python SDK-recovery dependencies.
No new dependency is added to the production Python installation requirements.
From the repository root, choose a new output directory:

```powershell
python -m pip install -r services/stellaris_native_runtime/tools/sdk_recovery/requirements.txt
dotnet restore services/stellaris_native_runtime/tools/script_candidates/parser/CwtoolsBridge.csproj --source https://api.nuget.org/v3/index.json --locked-mode
dotnet build services/stellaris_native_runtime/tools/script_candidates/parser/CwtoolsBridge.csproj -c Release -o .tmp/cwtools-parser-new --no-restore
dotnet .tmp/cwtools-parser-new/CwtoolsBridge.dll --self-test
```

The bridge uses CWTools 0.6.0-alpha and pins FSharp.Core 9.0.100. Its NuGet graph
currently emits NU1701 for the unused legacy Shared/CSharpHelpers dependencies;
this warning is not suppressed. The parser path was tested on Windows/.NET 9,
including the actual 4.5.2 rule/content corpus. Linux parser execution has not
been tested here; a Linux validation host can consume the generated plans
without running .NET. Do not assume the full CWTools library was validated.

The bridge preserves duplicate entries, comparison operators, anonymous values,
quoted scalar values and source positions. Two lexical compatibility fixes are
bounded: adjacent comparators, and `scope? =` versus CWTools' `scope ?=`. The
latter retains source length/lines; optional-scope evaluation remains UNKNOWN.
Malformed files produce errors, never an empty satisfied rule. Source text,
AST depth/nodes, per-file parser time, search and native batches are bounded.

## Run Offline

Supply the already recovered exact-version files and an archived save. Nothing
in this command connects to a game or runtime:

```powershell
python services/stellaris_native_runtime/tools/plan_script_candidates.py `
  --sdk PATH_TO_LINUX_SDK_JSON `
  --elf PATH_TO_EXACT_LINUX_ELF `
  --tokens PATH_TO_MATCHING_LINUX_TOKENS_JSON `
  --parser-bridge .tmp/cwtools-parser-new/CwtoolsBridge.dll `
  --game-root "C:/Program Files (x86)/Steam/steamapps/common/Stellaris" `
  --save PATH_TO_ARCHIVED_SAVE `
  --output .runtime-evidence/constraint-planning-new
python services/stellaris_native_runtime/tools/validate_constraint_candidates.py `
  --report .runtime-evidence/constraint-planning-new/report.json `
  --output .runtime-evidence/constraint-preflight-new
```

Optional `--content-layers` is an ordered JSON array of additional loose-file
roots and `replace_paths`. Supply a confirmed load order, not an unordered Mod
directory scan. File overlays are resolved; ambiguous duplicate definition keys
remain unbound. Archive expansion and active-engine definition reconciliation
are not implemented. External files are never labelled engine-loaded.

Optional `--fact-cache` reuses only matching save/content/parser/adapter hashes.
No global object pointers, slot-only IDs or persistent native-address cache is
used. `--feedback-report` imports existing exact-build native observations with
provenance, but does not pretend that another world's same numeric IDs prove
the current fixture or a paired capture.

Each output directory must not exist. It retains reports, ordered progress,
rule wrappers, native predicates/functions, save facts, raw input SDK/token/save
copies, parser binaries, source snapshots/hashes and a shared recovery worklist.
Old evidence and caches are never edited or automatically deleted.

## Semantic And Technical Audit

Use the same entry point with `--recover-values --search-game-sources` and
optionally `--audit-baseline PREVIOUS_REPORT` / repeated
`--lifecycle-evidence EXISTING_EXACT_BUILD_BATCH_REPORT`. It still runs offline.
The latter imports only identity-matched Factory/Destroy and typed-input
observations, never another world's legal candidates or production status.

`semantic_audit.json` contains every Command, parameter provenance, native
function/callsite evidence, existing provider requirements and the exclusive
primary classification. Independent dimensions are also counted; they must not
be added together. An unavailable caller name, an unparsed save database and an
unproven owning-value destructor are different findings.

`recovered_linux_sdk.json/.hpp` are NEW private outputs, consumed through the
existing metadata/Builder format. The tool never installs these headers. The
shared enrichment also runs during normal Linux SDK recovery. It recovers
normal-flow Factory evidence (excluding unreachable EH pads), existing native
text-value copies, inline CString initializers, typed fixed-point storage,
named enum-converter inputs and generation-bearing reference-array bindings.
Fixed-point storage alone does not prove units or legal numeric values.

Save manager tables are expanded only when structurally unique, or selected
using a typed native database-base/serializer binding. An unmapped or ambiguous
table is not reported as an absent game object. Fact-cache v3 binds the loaded
adapter, native collection evidence, content, parser and immutable save.

`game_source_references.json` indexes original scripts, GUI and English
localization references. These search matches aid semantic review; they do not
prove ABI, ownership, mandatory rules or currently effective Mod overrides.
The detailed audit and remaining shared recovery paths are documented in
[`COMMAND_SEMANTIC_TECHNICAL_AUDIT_4_5_2.md`](../../../../docs/runtime/COMMAND_SEMANTIC_TECHNICAL_AUDIT_4_5_2.md).

The old `blockers` label now contains technical gaps only. Original independent
candidate-search diagnostics are retained as `candidate_generation_diagnostics`.
An existing native provider awaiting a state query is not a missing ABI.
`can_construct_with_typed_inputs` is a Builder capability, NOT an executable
Application action or proof that all gameplay preconditions are satisfied.

## Explicit Future Native Window

This step was NOT run against Stellaris during offline development. Requires a
fresh authorized disposable paused session with a revision-7 runtime already
loaded once, the exact SDK metadata fingerprint, and a freshly checked context:

```json
{"instance_id": 123, "world_identity": 456, "game_date": 789}
```

Those numbers are current runtime evidence, not examples to reuse, nor values
to derive from a different save. A matching world/date is not proof of full
save equivalence, RNG/cache equality or absence of paused UI actions.

```powershell
python services/stellaris_native_runtime/tools/validate_constraint_candidates.py `
  --report PATH_TO_REPORT --output NEW_OUTPUT_DIRECTORY `
  --native --context PATH_TO_FRESH_CONTEXT --endpoint EXISTING_ENDPOINT
```

The default without `--native` is strictly offline. The runner has no loader,
injection, restart, pause or save-control path. The existing research request is
extended with `constraint_plan`, not registered as a production Action. Runtime
instance, world, date, pause state, active SDK, exact field names/types, enum
domains, generation-bearing refs, lifecycle and destruction are checked again.
No offsets, raw pointers, arbitrary strings or unrestricted scalar values can
be populated through that request. The current constraint gate supports refs,
bool, i32/u32 with recovered domains, and native-resolved definition keys; other
field kinds are skipped, not coerced. Windows still lacks the verified paused
fixture query and consequently fails closed for this new research mode.

Each rejected candidate selects the next ranked candidate; a true result stops
that Command's coverage pass. Calls are sequential and bounded. An uncertain
timeout, native exception, identity change or unpaused fixture stops the batch.
Started-but-uncompleted requests are retained and never automatically replayed.
Feedback is scoped to its actual evidence; a false result does not synthesize
an unproven general constraint, and a true result never promotes an Action.

## Tests And Limits

```powershell
$env:IAG_CWTOOLS_BRIDGE=(Resolve-Path .tmp/cwtools-parser-new/CwtoolsBridge.dll).Path
python scripts/validation/run_tests.py --quiet
```

Without that environment variable the optional CWTools integration tests skip;
all pure evaluator, CFG, candidate, protocol and feedback fixtures still run.
Native C++ fixtures test the shared Builder/IsValid/destructor lane with mock
engine objects; they are not Stellaris live validation.

Unsupported triggers, dynamic flags, hidden state, ambiguous scopes, incomplete
collections, opaque calls and unproven control-flow relationships remain
UNKNOWN. Native reachability and a unique argument type can rank candidates but
cannot establish a mandatory rule. Native payload filters require a proven
rejecting arm AND zero-return bypass paths; implicit register writes, payload
writes and opaque callees invalidate affected input facts. Search truncation is
explicit, so no report claims the complete legal parameter set.

Implementation/results and primary-source references:
[Script/native constraints research](../../../../docs/runtime/SCRIPT_NATIVE_CONSTRAINT_PIPELINE_4_5_2.md).

## Reuse Save Spatial Candidates

Append `--spatial-model-root PATH_TO_SPATIAL_SOURCE` to the existing offline planner
with `--recover-values --tokens EXACT_TOKEN_REGISTRY`. It imports that explicit
repository's `stellaris_save_map` API and rebuilds the same frozen save, not the
latest map from an unrelated campaign. The package is not a required dependency
when this option is omitted. Its six source files and hashes are archived; no
external spatial-model sources or outputs are modified.

`spatial-model/map.json`, `systems.jsonl` and `manifest.json` preserve the original
map model and provenance. Local XY uses each system's own outer radius. Transit
coordinates and inferred hyperlane endpoints are never used as local targets.
Native coordinate member groups keep XY/origin and, when proven, the source
fleet in one domain. Height zero and randomization false come from the exact
native constructor; unknown units, off-lattice values and stale saves fail
closed. For 4.5.2 the recovered scale is 100000, not the legacy 32768 claim.

The existing constraint-plan codec now preserves signed 64-bit values from
Planner through Python, decimal wire encoding, SDK-checked C++ population,
`SetSigned` and numeric JSON echo. `i64` requires probe revision 7; older
runtimes are skipped before sending, not retried as uncertain native calls.
Other probe kinds retain their uint32 representation (including i32 bit
patterns). No u64, pointer or arbitrary-offset write support was added.

Offline communication preflight accepts 166 Commands / 2,548 plans, including
16 plans each for the four newly recovered coordinate Commands. This is not
native game legality or execution evidence. No production Action is registered.
See [coordinate reuse results](../../../../docs/runtime/COORDINATE_VALUE_REUSE_4_5_2.md).

For optional cross-language regression, set `IAG_CONSTRAINT_CODEC_TEST_EXE` to
the built `command_producers_test` executable. Its `--i64-wire BUILD_ID` mode
uses only local mock factories/validators/destructors and stdin/stdout, with
the real Python framing and C++ parser/Builder/serializer. Set
`IAG_CONSTRAINT_PREFLIGHT_REPORT` to an offline planner `report.json` to check
all generated candidates through the Python wire/JSON codec as well. Neither
test connects to Stellaris. `IAG_CWTOOLS_BRIDGE` enables the parser tests.
