# Automatic SDK recovery: Stellaris 4.5.2

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Result

OGAS now has a reproducible binary-to-SDK pipeline and a shared native Command
builder. It retains `CGameIdler`, the Application/Broker/Native Runtime chain,
the existing registry and typed Actions, native submission, and postcondition
verification. No upstream MCP service, DXGI hook or execution runtime is used.

The initial demonstration command was `CHireLeaderCommand`, the separate recruit-only
operation. Existing OGAS supports hire-and-assign but has no production
`hire_leader` descriptor. Its research probe uses generated Factory, Size,
VTable, field and destructor metadata, not an existing Action's `Prepare()`.
The subsequent [batch validation](SDK_BATCH_VALIDATION_4_5_2.md) replaces the
single-command mapping with generic, SDK-driven candidate construction.

## Measured offline recovery

The final complete run took **211.193 seconds** against the installed 4.5.2
Linux/Windows binaries identified in the static migration record.

| Recovered item | Result |
|---|---:|
| Current token names | 10,004 |
| Linux serializers indexed | 1,060 |
| Linux Command VTables | 351 |
| Linux no-argument Command factories | 346 |
| Linux Command allocation sizes | 351 |
| Linux named global candidates | 2,286 |
| Windows serializers matched | 843 / 1,060 |
| Windows serializer fields with recovered offsets | 3,557 / 3,972 |
| Windows Commands discovered | 366 |
| Windows nonzero native factories | 353 |
| Windows engine functions recovered | 104 |
| Windows global candidates resolved | 73 |

These are static coverage measurements. Global candidates are not all databases,
votes are not live type checks, and a recovered command is not automatically
constructible or production-approved.

Regression results:

- Retained upstream hand-checked Windows layouts: **47 passed, 0 mismatches**.
- Six-family comparison with the pinned upstream 4.5.2 header: **38 passed,
  0 mismatches**. Samples cover recruit Leader, research/cancel research, fleet
  movement, nested market trade data and construction queues.
- OGAS Linux/sample layout and cross-platform token checks: **18 passed,
  0 mismatches**. Fourteen checks cover existing research/movement/market
  layouts; four constrain the new recruit-only sample. The new sample's
  constraints are static evidence, not prior live evidence.
- Repeated runs emitted byte-identical Linux and Windows C++ metadata headers.

The generated summary is
`services/stellaris_native_runtime/versions/generated/stellaris_4_5_2_sdk_report.json`.
Full raw JSON and per-stage logs remain in the local run directory
`.tmp/sdk-recovery/run-07/`. Inputs, old runs and earlier research evidence were
preserved.

## New Command recovered automatically

| Property | Linux x86-64 | Windows x64 |
|---|---|---|
| Native type | `CHireLeaderCommand` | `CHireLeaderCommand` |
| Token | `0x40aa` | `0x40aa` |
| Factory RVA | `0x22bd510` | `0x6d1fa0` |
| VTable RVA | `0x5221108` | `0x23949c0` |
| Allocation size | `0x28` | `0x28` |
| `country` | `+0x1c`, `TPdxRef<CCountry>` | `+0x20`, `TPdxRef<CCountry>` |
| `leader` | `+0x20`, `TPdxRef<CLeader>` | `+0x24`, `TPdxRef<CLeader>` |
| Semantic `IsValid` RVA | `0x22a7870` | `0x6be7b0` |
| Deleting destructor RVA | `0x22b8ee0` | `0x1af5b0` |
| `IsValid` / destructor / Token slot | 9 / 1 / 11 | 8 / 0 / 10 |

The generic mapping in `sdk_probe.cpp` supplies typed references and boolean values.
The Factory initializes the command header and members. The builder checks the
actual returned VTable, calls the recovered `IsValid`, and owns destruction.
It does not call `Execute` or submit the command.

The same `NativeCommandBuilder` is available to a reviewed Action's `Prepare()`.
An Action can resolve authorized candidates, populate generated fields, call
`IsValid`, and return `ReleaseForSubmission()`. Its existing runtime submit and
`Verify()` remain responsible for proving execution. Discovery and production
therefore share the construction metadata and implementation.

## Validation and lifecycle

The new C++ test uses a controlled factory/validator/destructor fixture and the
real builder. It checks successful and unsuccessful validation, reference type
mismatch, bounds rejection, exact-build mismatch, missing Factory, changed
Token, automatic destruction, prohibited release of an invalid command, and
single ownership transfer to the common submit API.

The native builds pass `/W4 /WX` on Windows and
`-Wall -Wextra -Wpedantic -Werror` on Linux. Linux CTest passes 3/3, including
the generated builder test. These tests do not execute a real game Factory.
The repository Python suite passes **435 tests** and the new/changed Python
code passes Ruff.

The private `validate_recovered_command` request uses the current runtime's
serialized `CGameIdler` queue and generated command layouts. It returns
a typed `iag.native_command_validation.v2` record separating structural checks,
parameter/semantic gaps, native true/false validity and exceptions. Every record
has explicit `submitted=false` and `execution_verified=false`; `destroyed=true`
is reported only after a constructed command's destructor returned.
It is absent from the production Action manifest and does not change Broker
capabilities or verification levels.

## Limits and batch live check

The Linux scanner implements bounded argument data flow, not general control
flow or type recovery. Positional and ambiguous fields remain non-writable.
The current builder handles typed references and a small set of POD scalars.
It rejects absent factories and does not invent string/nested object ownership.

DWARF sections exist in this ELF, but inspected compilation units are from
libgcc/Breakpad. The presence of `.debug_info` alone does not prove game Command
types are available. Ghidra's richer decompilation and DWARF are retained as
supplementary paths for future unresolved cases; no complete Ghidra export is
required for this run.

The next acceptance level is a complete generated-directory traversal in one
running test session, not successive manual Leader/UI samples. The reusable
batch tool, safety filters, per-command reports and actual live results are in
[SDK_BATCH_VALIDATION_4_5_2.md](SDK_BATCH_VALIDATION_4_5_2.md). Native legality is
not submission/postcondition evidence. No `live_verified` promotion is made.

Usage, artifacts and attribution are documented in
`services/stellaris_native_runtime/tools/sdk_recovery/README.md`.
