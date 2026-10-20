# OGAS Stellaris Native Runtime

This directory contains the production-side in-process runtime for verified
Stellaris native commands. It is deliberately separate from packet execution
and from reverse-engineering probes.

The active profiles target exact Stellaris `4.5.2 (3270)`, Steam build
`25664273`:

- Linux ELF build ID `121ecb516cbc5f1d39917fbcc36620534384e2c2` exposes
  48 typed actions. Forty-two previously live-verified implementations are
  intentionally reported as `build_validation_pending` until the 4.5.2 live
  batch completes; six retain the stricter `paired_capture` state.
- Windows executable SHA-256
  `400df27c82ddc845aa9dce79bd468d81f18f060d299cd263e3afa93aef4f7a83`
  exposes only `move_fleet.v1`, also as `build_validation_pending`.
- Version-bound 4.4.6 captured command bodies are disabled on both profiles.
  They cannot enter the manifest merely because their old fixtures exist.

`build_validation_pending` is discoverable but not Broker-executable. The
runtime/Broker overlay removes that exact backend from the enabled set while
preserving independently verified backends for the same semantic action.
Promotion to `live_verified` is therefore an explicit exact-build evidence
change, not a side effect of compiling against a new address table.

The earlier Windows 4.4.6 move chain was structure-matched from Linux symbols
and independently live-verified in a `TestMove` save. The 4.5.2 structural
match is complete but does not inherit that live status. Linux offsets and ABI
assumptions are never reused on Windows: each platform selects its own exact
profile and only advertises actions whose required bindings are present.

The library fails closed unless the build ID and key function prefixes match.
Its socket thread only validates and queues semantic requests. A guarded
trampoline on `CGameIdler::Idle(true)` transfers pending work onto the main
game thread immediately before `CGameApplication::Update()` and the session
update. The runtime resolves the technology key, verifies the local country,
checks both the command's `IsValid` and
`CTechnologyStatus::IsResearching`, then submits it through
`PostCommandToSession`. After the native update it confirms that the exact
technology is no longer being researched. Fleet movement resolves generation-
checked fleet/system objects, verifies local control, asks Stellaris for the
correct FTL point, calls the native command validator, and confirms that a
player movement order appeared. Fleet attack resolves both generation-checked
fleet objects, verifies source ownership and native command validity, then
confirms that the executing order is a non-cancelled attack against the exact
target fleet. The runtime never calls a command's business `Execute()` method
directly.

At startup each `actions/*.cpp` translation unit self-registers an
`ActionDescriptor`. `describe_tools` returns one strict manifest containing the
action name/version, owning Application, risk and verification state, plus the
ordered parameter names, types and bounds. The Python Broker intersects that
runtime-owned catalog with its semantic policy. An action whose permanent
domain has not been reviewed uses the explicit `etc` Application.

Read-only native state is a separate surface from side-effect actions.
`inspect_open_events(country_id)` returns exact open-event IDs and currently
legal option indices with stable localization keys. It deliberately avoids
dynamic event-text renderers that can touch the game's RNG. The query can read
an explicitly selected AI country in observer mode; it does not grant that
country's execution authority. `inspect_pending_diplomatic_actions(country_id)`
likewise returns current incoming diplomatic-action IDs, native tags, parties,
and accept/reject legality without changing diplomacy or granting authority.

The production runtime is split by responsibility:

```text
runtime*.cpp                       platform hook/IPC, idempotency, submit
game_api.cpp                        shared access to the verified game ABI
state_query.cpp                     bounded read-only native state queries
versions/*.cpp                      build IDs, offsets and instruction anchors
actions/action_registry.cpp         self-registration and manifest machinery
actions/<semantic_action>.cpp       metadata, target parser, builder, verification
include/iag_native_runtime/*.h      contributor-facing native contracts
research/                           probes only; never a production action source
tools/sdk_recovery/                 offline ELF/PE serializer and Command discovery
versions/generated/                 exact-build recovered Command/engine metadata
command_builder.cpp                 shared Factory construction, IsValid and ownership
sdk_probe.cpp                       bounded non-submitting new-Command research mapping
```

Adding an action does not add another game-loop hook and must not call a
business `Execute()` method. Follow
[`docs/runtime/NATIVE_RUNTIME_ACTION_CONTRIBUTING.md`](../../docs/runtime/NATIVE_RUNTIME_ACTION_CONTRIBUTING.md).

The historical 4.4.6 live chain, offsets, signatures, object layout and
validation evidence used as the semantic migration baseline are recorded in
[`docs/runtime/NATIVE_RESEARCH_HOOK_4_4_6.md`](../../docs/runtime/NATIVE_RESEARCH_HOOK_4_4_6.md).
Fleet movement evidence is recorded in
[`docs/runtime/NATIVE_FLEET_MOVE_HOOK_4_4_6.md`](../../docs/runtime/NATIVE_FLEET_MOVE_HOOK_4_4_6.md),
fleet attack evidence in
[`docs/runtime/NATIVE_FLEET_ATTACK_HOOK_4_4_6.md`](../../docs/runtime/NATIVE_FLEET_ATTACK_HOOK_4_4_6.md),
the shared capture-backed factory and its staged action catalog in
[`docs/runtime/CAPTURE_BACKED_NATIVE_ACTIONS_4_4_6.md`](../../docs/runtime/CAPTURE_BACKED_NATIVE_ACTIONS_4_4_6.md),
the complete 73-action manifest, Broker status and promotion checklist in
[`docs/runtime/NATIVE_RUNTIME_ACTION_CATALOG_4_4_6.md`](../../docs/runtime/NATIVE_RUNTIME_ACTION_CATALOG_4_4_6.md),
with the wider command/order family map in
[`docs/runtime/FLEET_MOVEMENT_NATIVE_4_4_6.md`](../../docs/runtime/FLEET_MOVEMENT_NATIVE_4_4_6.md).
The separate single-player observer takeover proposal and its recovered
per-country AI queue boundary are recorded in
[`docs/runtime/OBSERVER_AI_COUNTRY_TAKEOVER_4_4_6.md`](../../docs/runtime/OBSERVER_AI_COUNTRY_TAKEOVER_4_4_6.md).

Build on the Linux game host:

```bash
cmake -S services/stellaris_native_runtime \
  -B build/stellaris_native_runtime \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build/stellaris_native_runtime --parallel
```

Build on Windows with Visual Studio Build Tools (this also runs the native
contract test):

```powershell
./scripts/build/Build-StellarisNativeRuntime.ps1
```

Compile and run the native contract tests with:

```bash
cmake -S services/stellaris_native_runtime \
  -B build/stellaris_native_runtime-tests \
  -DIAG_NATIVE_RUNTIME_BUILD_TESTS=ON
cmake --build build/stellaris_native_runtime-tests --parallel
ctest --test-dir build/stellaris_native_runtime-tests --output-on-failure
```

The Linux endpoint is `/tmp/iag-stellaris-native.sock`; Windows uses
`\\.\pipe\iag-stellaris-native`. Set
`IAG_NATIVE_RUNTIME_SOCKET` before the game starts to choose another absolute
Unix-socket path. The packaged Windows Agent contains the exact-build DLL and
loader and only loads them when native runtime execution is enabled. Linux
loading remains an explicit operator/deployment concern.

Discovery scripts and raw runtime traces belong under `research/`; unknown
commands must not be added to this production runtime.

## Exact-build preflight

Before loading the runtime, verify the installed executable against its
checked-in evidence manifest:

```bash
python3 services/stellaris_native_runtime/tools/version_profile/verify_binary.py \
  --manifest services/stellaris_native_runtime/versions/manifests/stellaris_4_5_2_linux.json \
  --binary ~/.steam/steam/steamapps/common/Stellaris/stellaris
```

```powershell
python services/stellaris_native_runtime/tools/version_profile/verify_binary.py `
  --manifest services/stellaris_native_runtime/versions/manifests/stellaris_4_5_2_windows.json `
  --binary "C:\Program Files (x86)\Steam\steamapps\common\Stellaris\stellaris.exe"
```

The verifier checks the whole-file hash, platform build identity, image and
`.text` geometry/hash, and every required instruction prefix. The native
contract-test executable can show the exact catalog compiled for one platform:

```text
iag_native_runtime_action_contract_test --dump-manifest
```

The 4.5.2 mapping and live-validation handoff are recorded in
[`docs/runtime/NATIVE_RUNTIME_4_5_2_STATIC_MIGRATION.md`](../../docs/runtime/NATIVE_RUNTIME_4_5_2_STATIC_MIGRATION.md).

Automatic SDK recovery and the new-command construction sample are recorded in
[`docs/runtime/SDK_RECOVERY_4_5_2.md`](../../docs/runtime/SDK_RECOVERY_4_5_2.md).
To regenerate the engine metadata, follow
[`tools/sdk_recovery/README.md`](tools/sdk_recovery/README.md). Recovery never
adds an Action or upgrades its verification state.

For the one-session non-submitting batch validator and its live coverage, see
[`docs/runtime/SDK_BATCH_VALIDATION_4_5_2.md`](../../docs/runtime/SDK_BATCH_VALIDATION_4_5_2.md).

For exact-build domain parameter providers, shared native Producer construction,
and the prepared one-session validation window (no submission), see
[`PRODUCER_VALIDATION_WINDOW_4_5_2.md`](../../docs/runtime/PRODUCER_VALIDATION_WINDOW_4_5_2.md).
