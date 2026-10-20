# Leader Assignment Live Verification (Stellaris 4.4.6)

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope

This note records focused live verification of `assign_leader.v1` and
`hire_and_assign_leader.v1` on Linux Stellaris `4.4.6 (fdde)`, ELF Build ID
`c6969e60fd81d738948222a94c0b5a0841abbffc`.

## Existing leader reassignment

- Acting country: `16777221`
- Leader: `234881728` (`official`)
- Previous location: planet `143`
- Requested location: `colony`, object `5`
- Request ID: `leader-country16777221-official234881728-colony5-20261018`

The probe captured `CAssignLeaderCommand` at `session_post` and `execute_sync`.
The following save records the same leader at a planet location with `id=5`.

## Hire and assign

- Acting country: `16777221`
- Recruitment-pool candidate: `134218014` (`official`)
- Requested location: `colony`, object `143`
- Request ID: `leader-hire-country16777221-official134218014-colony143-20261018`

The probe captured `CHireAndAssignLeaderCommand` at both phases. In the next
save candidate `134218014` is absent from the recruitment pool, present in
`owned_leaders`, and has a planet location with `id=143`.

## Production status

Both exact-build descriptors are `live_verified`. Leader and location IDs must
come from a snapshot-derived candidate. The public action retains typed
location semantics; the native `LeaderLocation` layout remains backend-private.
Normal Broker authority, freshness, permission and idempotency checks still
apply.
