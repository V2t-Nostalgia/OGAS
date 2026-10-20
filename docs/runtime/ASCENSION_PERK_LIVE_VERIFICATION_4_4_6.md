# Ascension Perk Native Verification: Stellaris 4.4.6

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope

This note records the focused Linux live verification of
`activate_ascension_perk(definition_key)` on Stellaris `4.4.6 (fdde)`, ELF
Build ID `c6969e60fd81d738948222a94c0b5a0841abbffc`. It does not establish a
Windows binding or grant authority over an AI country merely because that
country is being observed.

## Native chain

```text
semantic definition key
  -> active CAscensionPerk definition database lookup
  -> CCountryActivateAscensionPerkCommand constructor
  -> native IsValid
  -> PostCommandToSession
  -> execute_sync
  -> CCountry::HasAscensionPerk(exact key)
```

The command constructor is at module offset `0x1f3ff50`. The in-memory
postcondition uses the exported Linux symbol
`CCountry::HasAscensionPerk(CString const&) const` at `0x2038130`. Both are
version-bound; the postcondition entry has a required function-prefix anchor.

## Live evidence

The disposable baseline was `autosave_2405.02.01.sav`. Country `0` had seven
completed tradition trees, seven selected perks, and one legal empty perk
slot. The runtime submitted:

```text
activate_ascension_perk(0, ap_archaeoengineers)
request_id=ascension-country0-archaeo-live2-20261018
```

The command probe recorded one `session_post` and one `execute_sync` for
`CCountryActivateAscensionPerkCommand`. The next authoritative save,
`autosave_2405.03.01.sav`, differed in the relevant country state only by the
addition of `ap_archaeoengineers`: the perk count changed from seven to eight,
while its 49 traditions were unchanged. The inspected comparison countries
were unchanged.

Two negative checks completed the execution contract:

- replaying the same request ID returned the cached result and did not add a
  second command-probe record;
- a new request ID for the already owned perk was rejected by native
  `IsValid` before submission and did not add a probe record.

The descriptor is therefore `live_verified`. The runtime now confirms the
exact key in memory instead of reporting a generic save-pending result.

## Authority limitation

`LocalObservedCountry()` identifies the observed country, not necessarily the
country controlled by the local session. During the same investigation, a
command posted while observing an AI country passed preliminary resolution but
did not produce the requested save change. Production callers must still pass
the Broker's authority checks; observer identity is not an authority grant.
