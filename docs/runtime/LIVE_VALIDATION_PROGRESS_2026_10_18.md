# Native Runtime Live Validation Checkpoint: 2026-10-18

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope

This note preserves the latest long-running Computer Use validation checkpoint
before work moved to repository comparison. The run used Linux Stellaris
`Pegasus v4.4.6 (fdde)`, ELF Build ID
`c6969e60fd81d738948222a94c0b5a0841abbffc`, acting country `0`, and the
existing native runtime socket and passive command probe.

The evidence below strengthens the positive execution side of six
capture-backed actions. It does **not** promote their descriptors from
`paired_capture`: the semantic-resolver, negative-validation, authority,
staleness, and idempotency gates in
`NATIVE_RUNTIME_ACTION_CATALOG_4_4_6.md` still apply.

## Confirmed action chains

| Semantic action | Request ID | Native command evidence | Save-backed postcondition |
| --- | --- | --- | --- |
| `start_research` | `live-start-research-physics-240803` | Native factory/validator/post path accepted the reconstructed research command | Physics selected `tech_storm_prediction_2` in `2408.05`; progress reached `9260.26315` by `2408.06` |
| `land_armies` | `live-land-appon-240807-transport436` | Probe sequence `40419` (`session_post`) and `40432` (`execute_sync`) both identify `CFleetLandArmiesCommand` | Transport fleet `436208059` disappeared from space and its armies entered `ground_combat=1392508928` on colony `193` in `2409.01`; the invasion was still in progress and was not misreported as conquest |
| `move_fleet_to_coordinate` | `live-coordinate-appon-241003-distinct` | Probe sequence `67558` (`session_post`) and `67559` (`execute_sync`) both identify `CFleetFlyToCoordinatesCommand` | Fleet `251662165` moved in system `322` from approximately `(-24.94649,-202.17867)` to `(99.12957,96.56629)`, with target `(100.0,100.0)` in `2410.04` |
| `set_orbital_bombardment_stance` | `live-bombardment-selective-241003` | Probe sequence `68514` (`session_post`) and `68515` (`execute_sync`) both identify `CSetFleetGroundSupportStanceCommand` | Fleet `251662165` changed from `raiding` to `selective` in `2410.04` |
| `repair_fleet` | `live-repair-fleet4969-241004` | Probe sequence `76331` (`session_post`) and `76332` (`execute_sync`) identify `CQueueFleetOrderCommand` with nested `CRepairFleetOrder` | Fleet `4969` remained on a repair order; mean hull/armor advanced from about `16%/0%` before submission to `36%/20%` in `2410.09` and `95.33%/80%` in `2410.10` |
| `upgrade_fleet` | `live-upgrade-fleet4967-241004` | Probe sequence `77666` (`session_post`) and `77668` (`execute_sync`) both identify `CFleetUpgradeDesignCommand` | Fleet `4967` received an upgrade order and was traveling from system `360` through system `122` toward shipyard system `2` by `2410.10` |

The `upgrade_fleet` evidence confirms accepted routing to the selected
shipyard. A later save is still needed to record completed refitting rather
than only the accepted/traveling state.

## Save evidence

The corresponding local evidence files are kept under `.runtime-evidence/`.
Their SHA-256 values are:

| Snapshot | SHA-256 |
| --- | --- |
| `autosave_2408.04.01.sav` | `9a6db4989639593820410107a842f18a9bb89fc7caaf831ad42a29f6e5c682bd` |
| `autosave_2408.05.01.sav` | `cc02b82086ba65365c882fbc21eaec1e06e2f5c0d7c81e671c0f67c17d13b86f` |
| `autosave_2408.06.01.sav` | `196a6210e01f98d24a134f7426912167569a925e2197559baafe6286d57cef92` |
| `autosave_2408.07.01.sav` | `3a1d5043cfc39649d1230bfaf0ed412c9d639d16443a742206b39d09e2e960cd` |
| `autosave_2409.01.01.sav` | `d903daa9dabf817d0da232abb807b0fb72d9dd0224060622e657c08910201fe4` |
| `autosave_2410.03.01.sav` | `ca98caec6069957869f8b67cf5f4cce68bab587e17e0891b2e0e53c2d45d790c` |
| `autosave_2410.04.01.sav` | `e584834de8951e1ce718fdbf4c10948aad7403175d03717c76141d757a39fa71` |
| `autosave_2410.09.01.sav` | `3e82e229faf78ab06e66dd4ac235680e3494b76dc9094b3fb2dd44eab2997f16` |
| `autosave_2410.10.01.sav` | `329a303bfb7dd361a285890ed05f2cbb98f44cd602a42cb1d02897245cf9ae19` |

The parsed fleet-state companions use the matching `fleet_<date>.json`
filenames. `start_research` also exposed a verifier timing issue: the first
post-save can be earlier than the durable state transition, so save
verification must support a bounded multi-save continuation instead of
declaring failure after one snapshot.

## Current state and next validation batch

At the checkpoint, the game process was alive and the newest observed save was
`autosave_2410.10.01.sav`; the simulation appeared paused. The current country
had no legal colonization candidates, so no colonization action should be
forced merely to increase coverage.

The next feasible batch is:

1. choose a fresh starbase module/building/upgrade candidate, preferring an
   empty slot over destructive replacement;
2. verify the old `build_starbase` order in system `546` against a later save;
3. let fleet `4967` reach the shipyard and verify completed upgrading;
4. derive legal current-state candidates for the three staged outgoing
   diplomacy actions;
5. run invalid-ID, wrong-authority, stale-candidate, illegal-state,
   insufficient-resource, and duplicate-request tests before any descriptor
   promotion.

State-unavailable actions, such as colonization without a legal target, are
recorded as unavailable in this save rather than as runtime failures.
