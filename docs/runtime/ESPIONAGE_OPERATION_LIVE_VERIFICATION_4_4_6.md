# Espionage Operation Live Verification: Stellaris 4.4.6

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope

This note records the focused Linux validation of `start_espionage_operation`
and `cancel_espionage_operation` on Stellaris `4.4.6 (fdde)`, ELF Build ID
`c6969e60fd81d738948222a94c0b5a0841abbffc`.

## Root cause and native target construction

The first implementation default-constructed `CScopeObjectReference` and
passed that empty scope to `CCreateEspionageOperationCommand`. Its native
`IsValid` rejected the command before posting. Static analysis confirmed that
the validator first requires a valid scope and later calls both
`CEspionageOperationType::IsAllowed` and `IsTargetAllowed`.

The vanilla AI path in `CAIEspionage::CreateNewOperation` selects a legal
`CScopeObjectReference` before constructing the command. For the semantic
runtime action, the non-model-controlled equivalent is deterministic:

```text
ResolvePdxObject(spy_network_id)
  -> CSpyNetwork::GetTarget()                    stellaris+0x1caea50
  -> CScopeObjectReference::SetCountry(target)   stellaris+0x21f93f0
  -> CCreateEspionageOperationCommand            stellaris+0x3f22350
  -> virtual IsValid                             vtable +0x48
  -> PostCommandToSession
```

Both new accessors are exact-build bindings with required instruction-prefix
anchors. The public target remains only `spy_network_id` plus
`operation_type_key`; callers cannot supply an arbitrary scope or country ID.

## Start evidence

- Acting country: `1`
- Spy network: `16778622`
- Network target country: `16777221`
- Operation type: `operation_gather_information`
- Request: `espionage-start-gather-country1-scopefix-20261018`
- Native command: `CCreateEspionageOperationCommand`
- Probe phases: one `session_post`, followed by one `execute_sync`
- Save: `espionage_scopefix.sav`
- Created operation object: `1845493761`

The save continued the exact network with `active_operations={1845493761}`.
The operation database contained object `1845493761` with:

```text
spy_network=16778622
type="operation_gather_information"
target={ type=country id=16777221 }
days_left=30
```

## Cancel evidence

- Request: `espionage-cancel-country1-1845493761-20261018`
- Native command: `CDestroyEspionageOperationCommand`
- Probe phases: one `session_post`, followed by one `execute_sync`
- Save: `espionage_cancel_scopefix.sav`

The continued network no longer contained `active_operations`, and operation
object `1845493761` was absent from the global espionage-operation database.

## Production status

Both descriptors are `live_verified` and Broker-selectable on the exact Linux
profile. They deliberately retain `pending save verification`: game commands
are ordered side effects and do not imply rollback or transactional atomicity.
The runtime still runs native `IsValid` before posting, while save continuation
provides the authoritative durable postcondition.
