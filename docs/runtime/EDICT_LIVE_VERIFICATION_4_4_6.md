# Edict Live Verification (Stellaris 4.4.6)

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope

This note records the reversible focused verification of `enable_edict.v1` and
`disable_edict.v1` on Linux Stellaris `4.4.6 (fdde)`, ELF Build ID
`c6969e60fd81d738948222a94c0b5a0841abbffc`.

## Test case

- Acting country: `1`
- Edict: `fleet_supremacy`
- Disable request: `edict-disable-fleet-supremacy-country1-20261018`
- Enable request: `edict-enable-fleet-supremacy-country1-20261018`

The starting save listed `fleet_supremacy` among country `1`'s active edicts.
The runtime first submitted `CRemoveEdictCommand`, then restored the same edict
with `CAddEdictCommand`.

## Evidence

For each request the command probe recorded a `session_post` followed by an
`execute_sync` for the expected native command type. The save after removal did
not contain `edict="fleet_supremacy"` in country `1`'s edict collection. The
next save contained it again. Other sampled active edicts were retained.

This establishes the exact semantic key, native validation, session dispatch,
execution and save continuation in both directions without a net change to the
test country's active-edict state.

## Production status

Both exact-build descriptors are `live_verified`. Candidate generation remains
snapshot-derived and the Broker still applies application permission,
freshness, authority and idempotency checks before choosing the native backend.
