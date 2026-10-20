# Border Diplomacy Live Verification (Stellaris 4.4.6)

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope

This note records a reversible live verification of `open_borders.v1` and
`close_borders.v1` on Linux Stellaris `4.4.6 (fdde)`, ELF Build ID
`c6969e60fd81d738948222a94c0b5a0841abbffc`.

## Test case

- Acting country: `16777218`
- Target country: `1`
- Initial relation state: `closed_borders=yes`
- Open request: `diplo-country16777218-open-borders-country1-20261018`
- Close request: `diplo-country16777218-close-borders-country1-20261018`

## Evidence

Both operations used `CDiploActionProposeCommand`. The command probe preserved
the complete nested action object and identified `COpenBordersAction` for the
first request and `CCloseBordersAction` for the second. Each wrapper reached
`session_post` and `execute_sync`.

The save after opening no longer contained `closed_borders=yes` in country
`16777218`'s relation to country `1`. The following save contained it again
after closing. Relation identity and opinion were otherwise stable.

## Production status

Both exact-build descriptors are `live_verified`. This also confirms that the
shared proposal wrapper can preserve a typed native diplomatic action without
flattening it into an opaque packet. Candidate generation must still use a
current diplomatic relation and all normal Broker guards remain in force.
