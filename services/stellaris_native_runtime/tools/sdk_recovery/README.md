# OGAS SDK recovery

This is an offline engine-structure generator underneath OGAS's existing
Native Runtime. It does not provide an MCP server, execution queue, hook or
Action registration. The current workflow needs the symbolized Linux ELF and
the Windows PE from the same game release. Neither game needs to run.

## Run

```powershell
python -m pip install -r services/stellaris_native_runtime/tools/sdk_recovery/requirements.txt
python services/stellaris_native_runtime/tools/sdk_recovery/recover_sdk.py `
  --linux-binary path/to/linux/stellaris `
  --windows-binary "C:/Program Files (x86)/Steam/steamapps/common/Stellaris/stellaris.exe" `
  --output .tmp/sdk-recovery/new-run
```

The output directory must be empty. Previous runs are never cleared or reused
implicitly. `--reference-header path/to/stellaris_sdk.hpp` additionally compares
six command families against a pinned upstream SDK header. The normal pipeline
also runs the retained upstream 47-field regression and OGAS layout checks.
They are acceptance checks, not input constants used to repair discoveries.

## Pipeline

1. Read the current Windows token registry from registration call sites.
2. Extract Linux `WriteMembers` / `WriteCommandMembers` from current ELF
   symbols and bounded register data flow. The matching release's token names
   label numeric tokens; sampled command token getters are checked across both
   platforms. Linux offsets remain Linux-only.
3. Recover Linux command VTables, semantic `IsValid` slots, deleting
   destructors, token getters and `CommandRegistrator::Create` factories.
   Read allocation sizes from native Factory or Clone calls, including PLT
   `operator new` resolution. A Clone is never relabeled as a no-argument
   Factory.
4. Use the adapted upstream Windows serializer/token matching, field data
   flow and factory discovery. Vote for writer helpers inside already matched
   command serializers, rather than unrelated token-bearing functions.
5. Use current Linux symbol co-occurrence for Windows database candidates and
   the upstream structural fingerprints for common engine functions.
6. Emit OGAS JSON catalogs and C++ metadata headers. No Action is promoted.

The upstream implementation and MIT license are in `vendor/`; its pinned
revision and local modifications are documented in `vendor/UPSTREAM.md`.
The optional upstream Ghidra indexer is retained there. A decompile or DWARF
type evidence can supplement unresolved ELF fields without expanding this
bounded scanner into a decompiler.

## Outputs

- `linux_sdk.json`, `windows_sdk.json`: command class/token, Factory, Size,
  VTable, lifecycle/validator functions, field types, offsets and evidence.
- `linux_index.json`, `linux_index_win.json`, `win_layouts.json`: serializer
  order, unresolved fields, nested objects and cross-platform matching.
- `functions.json`, `globals.json`: recovered Windows engine entry points and
  global candidates, retaining match/vote evidence.
- `stellaris_linux_sdk.hpp`, `stellaris_windows_sdk.hpp`: the exact-build
  `RecoveredSdk` consumed by `command_builder.cpp` and `sdk_probe.cpp`.
- `recovery_report.json`, `*.py.log`: regression results, input identities,
  coverage, timing and stage diagnostics.

After reviewing a run, place its generated headers in
`versions/generated/stellaris_<version>_<platform>_sdk.hpp`. The current
`sdk_metadata.cpp` selects the 4.5.2 headers. The generator never changes a
production profile, an Action descriptor or a Broker verification level.

## Construction contract

`NativeCommandBuilder` is shared by research probes and future reviewed
`ActionInvocation::Prepare()` implementations. On the existing game thread it:

- requires matching SDK/profile identities and a recovered native Factory;
- checks VTable, Token, validator and deleting-destructor addresses;
- creates an initialized engine object using that Factory;
- accepts named, bounded, unambiguous scalar or typed `TPdxRef` fields;
- calls the recovered semantic `IsValid` and owns the object throughout;
- destroys it with the Linux deleting destructor or MSVC scalar deleting
  destructor (`flags=1`), unless ownership was explicitly transferred.

`ReleaseForSubmission()` only transfers a currently validated object. A field
write invalidates the previous validation. A production Action can return that
pointer as `PrepareResult::Ready`; the existing runtime remains responsible for
`PostCommandToSession` and the Action's `Verify()`.

Factoryless commands, positional fields, ambiguous names and unresolved owned
objects are not guessed into writable fields. Proven nested population plans,
native CString/reference-array assignment, typed definition pools and native
value lifecycle recipes are supported without copying their internals.
Seeing a field in a catalog still does not mean it is safely writable.

The expanded recovery, full-directory gap audit and single-session acceptance
procedure are documented in
[`SDK_COMMAND_RECOVERY_EXPANSION_4_5_2.md`](../../../../docs/runtime/SDK_COMMAND_RECOVERY_EXPANSION_4_5_2.md).
`audit_recovery.py` joins each command with its original live result and reports
all remaining blockers. `inspect_dwarf.py` checks actual debug-type coverage.
`linux_constructor_callsites.json` retains verified native constructor callers;
unknown IDs/selectors remain unknown rather than being filled from constants.

The shared `value_recovery.py` / `array_recovery.py` enrichment now distinguishes
normal Factory CFG from unreachable exception cleanup, retains native owning
value recipes, composes named by-value enum layouts and proves reference-array
data/count arguments against their native vptr and insertion function. It does
not infer a writable container merely from a field name or unique RTTI type.
The same catalog can be re-audited with the offline script-candidate entry point;
see its `--recover-values` and `--lifecycle-evidence` options. Existing evidence
can prove an exact-binary Factory/Destroy pair without transferring IsValid
results between worlds. Newly generated headers remain research artifacts until
reviewed and explicitly installed in a future build.

If a native Factory returns an unexpected VTable, the builder rejects the
object and retains the unknown allocation rather than invoking a potentially
wrong destructor. Stop that validation batch and investigate before retrying.

## Batch native legality validation

Use `../validate_recovered_commands.py` to traverse the generated directory in
one running game session. It obtains bounded native object candidates, uses the
shared builder, and performs one Create/Populate/IsValid/Destroy per Idle without
submission. See
[`SDK_BATCH_VALIDATION_4_5_2.md`](../../../../docs/runtime/SDK_BATCH_VALIDATION_4_5_2.md)
for safety filters, reports, limits and live evidence. No per-command probe or
manual ID hunt is required for supported population plans. The expanded runner
requires research probe revision 2 and separates lifecycle-only tests from
populated native-validator calls.

## Single-candidate example

`hire_leader` / `CHireLeaderCommand` is deliberately absent from the production
Action Registry. Its generated fields are `country` and `leader`, with reference
types `CCountry` and `CLeader`; the generic resolver handles them like any other
supported command. Every address, size and offset comes from generated metadata.

After loading the runtime into an authorized test game, use current candidate
IDs:

```bash
python services/stellaris_native_runtime/tools/probe_command.py hire_leader \
  --country 0 --leader CURRENT_RECRUITABLE_LEADER_ID \
  --output new-command-validation.json
```

The generic request runs on the same `CGameIdler` lane, calls the native Factory and
`IsValid`, destroys the object, and returns `submitted=false` and
`execution_verified=false`. `native_is_valid=false` is a valid negative
candidate result. This endpoint cannot choose arbitrary fields, pointers,
functions or raw command bytes, and cannot submit the object.

The v2 record separates structural checks, missing parameters, skips, native
true/false results and exceptions. The evidence levels are separate: `layout_generated` is static recovery,
`native_is_valid` is current native legality, and live execution requires the
existing submit/postcondition/save evidence. The probe cannot establish the
last level or grant production permission.

## Shared Coordinate Values

`coordinate_values.py`, invoked by the existing Linux value refinement, relates
the exact `CCelestialCoordinate` serializer, vtable, constructor, float/fixed
conversion constants and command factory stores. It emits a non-owning native
value region with correlated named members and proven tail padding. It does
not infer a struct from a Command name or serialize a new layout independently
of the shared SDK. Unmatched factories/types remain closed.

The 4.5.2 evidence proves decimal CFixedPoint scale 100000. Physical format is
separate from the semantic domain of experience, quantities or other values;
knowing the scale alone does not generate those parameters. Command field
setters remain the existing NativeCommandBuilder setters. No generated
production header is replaced by the offline planner.
See [4.5.2 coordinate results](../../../../docs/runtime/COORDINATE_VALUE_REUSE_4_5_2.md).
