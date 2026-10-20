# Situation Approach Live Verification (Stellaris 4.4.6)

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope

This note records the focused live verification of
`set_situation_approach.v1` on Linux Stellaris `4.4.6 (fdde)`, ELF Build ID
`c6969e60fd81d738948222a94c0b5a0841abbffc`.

## Test case

- Acting country: `1`
- Situation object: `35`
- Situation type: `situation_experimental_testing`
- Previous approach: `situation_experimental_testing_hold`
- Requested approach: `situation_experimental_testing_physics`
- Request ID: `situation-country1-35-physics-20261018`

The runtime resolved situation `35` from the native situation database,
constructed `CSetSituationApproachCommand`, passed native validation and posted
the command through `PostCommandToSession`.

## Evidence

The command probe captured one `session_post` followed by one `execute_sync`
for `CSetSituationApproachCommand`. A save written after execution contains:

```text
35={
    country=1
    type="situation_experimental_testing"
    approach="situation_experimental_testing_physics"
}
```

The same object used `situation_experimental_testing_hold` before the request.
This establishes construction, native validation, session dispatch, execution,
and save continuation for the exact situation and approach key.

## Production status

The exact-build descriptor is `live_verified`. Applications must still supply
a candidate derived from the current snapshot; arbitrary situation IDs or
approach keys are not model-authoritative inputs. Broker authority, freshness,
permission and idempotency checks remain unchanged.
