# Native Runtime static migration: Stellaris 4.5.2

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope and status

This record covers the offline migration from Stellaris 4.4.6 to exact Steam
build `25664273`, game version `Cygnus v4.5.2 (3270)`. It ends at the boundary
before loading either runtime into a live game.

Static recovery, exact-binary verification, compilation and contract tests are
complete on Linux and Windows. No 4.5.2 side-effect action is yet represented
as live-verified. The runtime manifests intentionally report recovered actions
as `build_validation_pending`, so the Broker can display them but cannot select
the Native Runtime backend until current-build evidence is recorded.

## Exact binaries

| Platform | Exact identity | Whole-file SHA-256 | `.text` SHA-256 |
|---|---|---|---|
| Linux x86-64 | ELF Build ID `121ecb516cbc5f1d39917fbcc36620534384e2c2` | `1c4c79a0ef8af7b984b797606373eb68b60fe421e4ef54c20e12e4a9398ba86b` | `d86424ca360674f6f8899aa11014638e9fb460707a41d174c055b5583a21cd8e` |
| Windows x64 | PE timestamp `0x6abeaa3f`, image size `0x37f2000` | `400df27c82ddc845aa9dce79bd468d81f18f060d299cd263e3afa93aef4f7a83` | `0497b32bfc24606277919b01d9a533295fc930450cbf7e262315f4e9006ad5ed` |

Machine-readable evidence lives in
`services/stellaris_native_runtime/versions/manifests/`. The verifier checks
the whole file, build identity, `.text` layout/hash and required instruction
prefixes before any injection is attempted.

## Recovered common pipeline

Both profiles retain the same high-level execution boundary:

```text
semantic action
  -> runtime registry / typed parser
  -> main-thread queue at CGameIdler::Idle
  -> native command construction and IsValid
  -> PostCommandToSession
  -> Stellaris session processing
  -> action-specific postcondition or save continuation
```

Key Linux RVAs are `CGameIdler::Idle = 0x1afd770` and
`PostCommandToSession = 0x1b02540`. Key Windows RVAs are `0x332ef0` and
`0x5f88a0`, respectively. These are module-relative values guarded by binary
identity and instruction anchors, not portable absolute addresses.

The Linux profile was migrated from current symbols, RTTI/vtables,
constructor/validator disassembly and caller/callee neighborhoods. The Windows
move path was matched structurally against the current PE and independently
anchored. The MIT-licensed `Yidhar/stellaris-mcp` generated SDK was used as a
corroborating current-build reference; critical profile values were checked
against the installed binaries and are guarded by this repository's manifests.

## Capability result

The Linux offline manifest contains 48 typed actions:

- 42 `build_validation_pending` actions covering fleet move/attack, research
  cancellation, immediate market trade, event choice, diplomacy and war,
  governance, leaders, Galactic Community, claims, species rights, situations
  and espionage.
- 6 actions remain `paired_capture`: `demand_subjugation`,
  `form_defensive_pact`, `invite_to_federation`,
  `join_galactic_community`, `propose_emergency_measure`, and
  `set_defender_war_goal`.

The Windows manifest contains only `move_fleet.v1`, marked
`build_validation_pending`. No Linux ABI value is used to advertise a Windows
action.

The 4.4.6 serialized capture factory is deliberately zeroed in the 4.5.2
profile. Consequently old captured bodies for construction, colonization,
shipyards and similar commands are absent rather than optimistically replayed.

## Safety changes made for the migration

1. `ActiveStellarisProfile()` selects one current exact profile per platform.
2. A profile-level verification override downgrades only descriptors that
   otherwise claim `live_verified`; existing `paired_capture` actions remain
   staged.
3. The Python runtime client accepts only the two current exact build IDs.
4. The Broker overlay refreshes evidence for an already-known
   action/backend pair instead of skipping it. A pending Native Runtime backend
   is removed from `broker_enabled_backends`, while independently verified
   Session Proxy support remains available.
5. Linux research cancellation uses the recovered
   `CCountry::AccessTechnologyModule` accessor instead of assuming the old
   module offset.
6. Windows fleet movement does not reuse the old executing-order layout. A
   posted command returns provisional/pending until save verification supplies
   a current-build postcondition.
7. `--dump-manifest` provides a deterministic offline capability diff for each
   compiled binary.

## Offline verification completed

- Windows `/W4 /WX` runtime, loader and contract-test build: passed.
- Windows native contract test: passed.
- Windows manifest: 1 tool, 1 `build_validation_pending`, 0
  `live_verified`.
- Linux `-Wall -Wextra -Wpedantic -Werror` CMake build: passed.
- Linux CTest contract and manifest-dump tests: passed.
- Linux manifest: 48 tools, 42 `build_validation_pending`, 6
  `paired_capture`, 0 `live_verified`.
- Python native-runtime and Broker tests: 32 passed during focused validation.
- Exact installed Windows and Linux binary manifests: passed before live load.

## Required live-validation handoff

Use a disposable/copy save and keep the game paused except where an action's
postcondition requires time. Do not validate all actions in one unsafe burst.

1. **Linux loader smoke:** preflight the binary, load the `.so`, call
   `describe_tools`, and run read-only event/diplomacy queries. Confirm the
   game remains stable and the build ID is exact.
2. **Pipeline canary:** issue one reversible `move_fleet` request. Capture the
   runtime response, `PostCommandToSession` evidence and in-game/save
   postcondition. Then test one invalid fleet/system ID and duplicate request ID.
3. **Low-risk families:** test research cancellation, one-unit market
   buy/sell, policy/edict toggles, and a benign fleet attack in a disposable
   war state. Validate exact state transitions, not merely absence of a crash.
4. **Candidate-dependent families:** query current events, diplomatic inbox,
   definitions and owned objects first; invoke only candidates returned legal
   by the current game. Cover governance, leaders, claims, Community,
   situations and espionage in bounded groups.
5. **Windows canary:** separately preflight/load the DLL and submit one fleet
   move. Confirm by a fresh save because the old in-memory order offsets are
   intentionally not trusted.
6. Promote an implementation to `live_verified` only after recording the
   exact 4.5.2 build, request/response, native submission evidence and precise
   postcondition. The six `paired_capture` actions additionally need their
   older semantic-evidence gaps resolved; a successful load alone is not
   sufficient.

The implementation should stop here until the operator starts the 4.5.2 game
session. Static addresses, compilation success and a valid manifest are not
substitutes for live command ownership, thread, lifecycle and postcondition
evidence.
