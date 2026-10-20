# Empire Policy Live Verification (Stellaris 4.4.6)

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope

This note records focused live verification of `set_empire_policy.v1` on Linux
Stellaris `4.4.6 (fdde)`, ELF Build ID
`c6969e60fd81d738948222a94c0b5a0841abbffc`.

## Test case

- Acting country: `1`
- Policy group: `economic_policy`
- Previous option: `economic_policy_balanced`
- Requested option: `economic_policy_military`
- Request ID: `policy-country1-economic-military-20261018`

The option key came from the loaded game's policy definitions and was evaluated
against the current country by the native command validator.

## Evidence

The command probe captured `CSetPolicyCommand` at `session_post`, followed by
`execute_sync`. The subsequent save records:

```text
policy="economic_policy"
selected="economic_policy_military"
```

The matching `economic_policy_military` policy flag also appears. The preceding
save selected `economic_policy_balanced` and did not carry that flag.

## Production status

The exact-build descriptor is `live_verified`. The semantic target contains
only stable group and option keys; the native runtime resolves their internal
objects. The Broker retains candidate, authority, freshness, permission and
idempotency checks.
