# Galactic Community Live Verification (Stellaris 4.4.6)

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope

This note records focused verification of proposal support state and active
Senate voting on Linux Stellaris `4.4.6 (fdde)`, ELF Build ID
`c6969e60fd81d738948222a94c0b5a0841abbffc`.

The following descriptors are now `live_verified`:

- `propose_resolution`
- `support_proposed_resolution`
- `oppose_proposed_resolution`
- `withdraw_proposed_resolution`
- `cast_resolution_vote`

## Proposal queue operations

Country `50331717` initially sponsored proposal `5`. The runtime withdrew that
proposal, then submitted
`resolution_industry_building_a_better_tomorrow`. Native validation had
previously rejected the exact same key while the sponsor slot was occupied,
which distinguishes a legal static key from a legal current candidate.

The continuation save `galcom_propose_better_tomorrow_50331717.sav` changes
`galactic_community.proposed` by removing `5` and appending `37`. Resolution
object `37` has the exact requested type, `country=50331717`, and the actor as
its sole initial supporter. The save SHA-256 is
`514b98d31886028c99a9488dd3f7335fd82efd885ebf4db2e52e0a3e94bcf676`.

Country `0` exercised support and oppose against proposed resolution `36`.
The continuation saves move the exact country between that resolution's
`supporters` and `opponents` collections:

- `galcom_support_resolution36.sav`
- `galcom_oppose_resolution36.sav`

Country `0` then withdrew its own proposed resolution `30`. The next save,
`galcom_withdraw_resolution30.sav`, no longer contains that proposal in the
active proposal queue. These tests distinguish proposal sponsorship from an
active Senate vote; the vanilla UI uses different native commands for them.

## Active Senate vote

Resolution `31` was the active vote and has type
`resolution_sanctions_military_2`. Countries `0` and `1` were under the
vanilla vote-change cooldown, explaining their native validation failures.
Country `16777227` had no current vote timestamp and was a legal candidate.

The request

```text
cast_resolution_vote(16777227, 31, oppose)
```

posted exactly once and persisted in
`galcom_resolution31_vote_oppose_country16777227.sav`. The resolution moved
country `16777227` and its synchronized subjects from supporters to opponents
and added current-date vote timestamps. This proves the action path and the
statically recovered `oppose` enum. `support=0` and `abstain=2` remain typed
values from the recovered constructor, but those two branches were not
separately exercised in this paused-save run.

## Deliberately not promoted

`join_galactic_community` had no eligible normal non-member in the loaded
save, and no eligible emergency-measure state existed during the active
Senate session. They remain `paired_capture`. The separate federation-style
`vote_on_diplomatic_action` subsequently received focused save-backed
verification and is documented in
`DIPLOMACY_WAR_LIVE_VERIFICATION_4_4_6.md`.
