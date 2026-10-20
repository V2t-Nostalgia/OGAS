# Tradition and Council Agenda Live Verification (Stellaris 4.4.6)

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope

This note records focused live verification of `activate_tradition.v1` and
`set_council_agenda.v1` on Linux Stellaris `4.4.6 (fdde)`, ELF Build ID
`c6969e60fd81d738948222a94c0b5a0841abbffc`.

## Tradition case

- Acting country: `16777221`
- Tradition: `tr_unyielding_fortress_doctrine`
- Request ID: `tradition-country16777221-unyielding-fortress-20261018`

The current save already contained the required
`tr_unyielding_defensive_zeal` prerequisite and sufficient unity. The probe
captured `CCountryActivateTraditionCommand` at `session_post` and
`execute_sync`. The subsequent save contains the requested tradition, records
the unity deduction, and also contains `tr_unyielding_finish`, which the game
awarded because this completed the tree.

An earlier candidate on country `1` was rejected by native `IsValid` before
posting; it is retained as fail-closed evidence and is not counted as a live
success.

## Council agenda case

- Acting country: `16777221`
- Previous agenda: `agenda_military_buildup`
- Requested agenda: `agenda_display_of_power`
- Request ID: `agenda-country16777221-display-power-20261018`

The requested agenda came from the active game definitions and was legal for
the country's ethics. The probe captured `CSetCouncilAgendaCommand` at both
session and execution phases. The next save selects
`agenda_display_of_power` and records `council_agenda_progress=0`, matching the
game's reset semantics when choosing a new agenda.

## Production status

Both exact-build descriptors are `live_verified`. Candidate generation must
still derive definition keys from the current snapshot and effective game
content. The Broker's permission, authority, freshness and idempotency guards
remain mandatory.
