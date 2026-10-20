# Council Position Live Verification (Stellaris 4.4.6)

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope

This note records the focused validation of `unlock_council_position` on
Linux Stellaris `4.4.6 (fdde)`, ELF Build ID
`c6969e60fd81d738948222a94c0b5a0841abbffc`.

Country `0` submitted:

```text
unlock_council_position(councilor_merchant_guilds)
```

The native definition resolver found the exact static definition, native
validation accepted it, and the command traversed `PostCommandToSession` once.
`council_unlock_merchant_guilds.sav` records:

- `councilor_merchant_guilds` in the country's `picked_council_types`;
- a corresponding council-position database object owned by country `0`;
- no model-supplied object pointer or raw command field.

The descriptor is therefore `live_verified`. Candidate generation must still
select a currently legal position key and all normal Broker authority,
freshness, risk and idempotency checks remain mandatory.
