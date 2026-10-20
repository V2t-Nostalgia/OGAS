# Diplomacy and War Live Verification (Stellaris 4.4.6)

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope

This note records focused native-runtime validation on Linux Stellaris
`4.4.6 (fdde)`, ELF Build ID
`c6969e60fd81d738948222a94c0b5a0841abbffc`. The game remained paused while
commands were posted, authority was switched with the vanilla console, and a
new save was made after each observable transition.

The following descriptors are now `live_verified`:

- `establish_embassy`
- `respond_to_diplomatic_action`
- `vote_on_diplomatic_action`
- `establish_rivalry`
- `insult_country`
- `declare_war`
- `offer_peace`
- `form_commercial_pact`
- `form_research_agreement`
- `form_migration_pact`
- `break_migration_pact`
- `break_commercial_pact`
- `offer_trade_deal`
- `add_system_claim`
- `remove_system_claim`

Every request passed the native `IsValid` check and reached the common
`PostCommandToSession` path exactly once. A posted command alone was not used
as success evidence; the postconditions below came from continuation saves.

## Embassy and pending-action response

Country `0` proposed an embassy to country `1`. The resulting pending action
had ID `8053063680001`; after switching authority to country `1`,
`respond_to_diplomatic_action(..., true)` consumed that exact ID and the next
save contained the embassy relation. A separate embassy proposal from country
`16777218` had ID `8044473745409`; the `false` branch consumed it without
creating an embassy.

Evidence saves:

- `diplo_establish_embassy_country0_to1.sav`
- `diplo_embassy_accept_reject.sav`
- `diplo_establish_embassy_country0_to1_after_tick.sav`

The read-only pending-action query returned an empty list after the completed
responses. This proves both boolean branches and one-shot pending-ID
consumption.

## Rivalry, insult, and war declaration

Country `0` targeted country `16777227` with an insult and then a rivalry.
`diplo_insult_and_rival_country16777227.sav` records both exact action-history
entries at `2406.09.01`; the relation also contains the corresponding rival
and insult state.

`declare_war(16777227)` used the game's own current war-goal selector rather
than accepting a model-supplied goal pointer. The save
`war_country0_vs_country16777227.sav` contains war object `117440513`, country
`0` on the attacker side and country `16777227` on the defender side. This is
the required post-submit game-state transition for the target pair.

## Peace proposal

After an existing peace action was rejected and its pending ID was confirmed
absent, primary attacker country `16777220` submitted
`offer_peace(16777225, 201326592, status_quo)`. The read-only pending-action
query then returned new action `8126094901257` for the exact recipient with
both accept and reject legal.

The continuation save
`offer_peace_status_quo_16777220_to_16777225.sav` contains the exact nested
peace offer fields:

```text
status=status_quo
actor=16777220
recipient=16777225
war=201326592
id=8126094901257
waiting_for_vote=no
```

Its SHA-256 is
`9d35a7b73b2c42f87cdaa13b4f7b7d1523a33348473dc9096be9b53d526f9ec3`.
This verifies the runtime constructor and post path; the test intentionally
does not accept the new proposal, so the active war remains available for
subsequent war-action validation.

## Claims

On country `1`, `add_system_claim(17, 1)` produced an exact system-17 claim:

```text
owner=1
date="2406.09.01"
claims=1
```

The entry is present in `claim_add_country1_system17.sav` and absent again in
`claim_remove_country1_system17.sav` after `remove_system_claim(17, 1)`.

## Immediate trade, escrow, rejection, and acceptance

The trade adapter was tested in both semantic directions with energy between
countries `0` and `1`.

| Step | Country 0 energy | Country 1 energy | Meaning |
| --- | ---: | ---: | --- |
| Pre-offer reference | `62451.38699` | `48410.16727` | Before the 7-energy offer |
| Offer 7 pending | `62444.38699` | `48410.16727` | Exact 7-energy escrow |
| Offer 7 rejected | `62451.38699` | `48410.16727` | Exact refund, no transfer |
| Offer 11 pending | `62440.38699` | `48410.16727` | Exact 11-energy escrow |
| Offer 11 accepted | `62440.38699` | `48421.16727` | Recipient gains exactly 11 |
| Request 13 accepted | `62453.38699` | `48408.16727` | Requester gains and target loses exactly 13 |

The accepted request used pending ID `8096013352961`. A final
`inspect_pending_diplomatic_actions(1)` returned no actions, proving that the
same request was not left reusable.

Evidence saves:

- `trade_energy7_pending_escrow.sav`
- `trade_energy7_rejected_refund.sav`
- `trade_energy11_pending_escrow.sav`
- `trade_energy11_accepted_transfer.sav`
- `trade_energy13_requested_and_accepted.sav`

## Commercial, research, and migration agreements

Country `1` proposed a commercial pact to country `50331717`. Incoming action
`8100358651973` had tag `ACTION_FORM_COMMERCIAL_PACT`; country `50331717`
accepted it, and both relation directions in
`commercial_pact_country1_50331717_accepted.sav` contain
`commercial_pact=yes`.

Country `50331717` then proposed research and migration agreements back to
country `1`. Pending IDs `8104603287553` and `8108898254849` had tags
`ACTION_FORM_RESEARCH_AGREEMENT` and `ACTION_FORM_MIGRATION_PACT`. After both
were accepted, `research_migration_pacts_country1_50331717_accepted.sav`
contains bilateral `research_agreement=yes` and `migration_access=yes` while
preserving the existing commercial pact and embassy.

The two destructive branches were exercised next. In
`migration_pact_country1_50331717_broken.sav`, only `migration_access` is
removed. In `commercial_pact_country1_50331717_broken.sav`, the commercial
pact is also removed while the research agreement and embassy remain. This
proves that each native command changes its own relation field rather than
merely closing a generic diplomatic action.

## Federation diplomatic vote

Federation members `16777225` and `32` had a pending status-quo peace proposal
for war `201326592`. Pending action `8061670391817` initially contained a
`yes` vote from the proposer and a `neutral` vote from country `32`.

After switching vanilla authority to country `32`, the runtime submitted
`vote_on_diplomatic_action(8061670391817, true)` exactly once. In
`federation_vote_support_country32.sav` the federation vote and old pending ID
are consumed, while the opposing primary country receives the resulting peace
proposal as action `8121799933956`. The war remains present because that
recipient has not yet answered. This is the expected non-atomic progression:
the command completes the internal federation vote, then creates the external
peace offer rather than directly ending the war.

Evidence hashes:

- before vote, `galcom_propose_better_tomorrow_50331717.sav`:
  `514b98d31886028c99a9488dd3f7335fd82efd885ebf4db2e52e0a3e94bcf676`;
- after vote, `federation_vote_support_country32.sav`:
  `1b501baa53c168458a6819207a0995540b5a21e1728e45751c9e61ee54d3f2f6`.

## Deliberately not promoted

The defensive-pact constructor rejected the tested country pairs in native
validation. `demand_subjugation` and `invite_to_federation` likewise had no
legal tested candidate. `set_defender_war_goal` was not promoted because the selected war
already had a defender goal. These remain `paired_capture`; none of the
negative results is treated as evidence that their constructors are wrong.
