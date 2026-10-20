# Diplomatic proposal actions in Stellaris 4.4.6

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


This document records the first typed implementation of the nested
`CDiplomaticAction` objects owned by `CDiploActionProposeCommand`. It applies to
the Linux executable with build ID
`c6969e60fd81d738948222a94c0b5a0841abbffc`.

## Shared native pipeline

All 16 actions use the same game-owned route:

```text
semantic target
  -> resolve current country objects
  -> construct concrete CDiplomaticAction
  -> move ownership into CDiploActionProposeCommand
  -> set command actor
  -> native IsValid / IsProposable
  -> PostCommandToSession
  -> normal session execution and synchronization
```

The proposal command is `0x28` bytes and owns the nested action pointer at
`+0x20`. Its scoped-pointer constructor clears the source pointer. The wrapper
thereafter owns destruction, including failure after the move. Application
inputs never contain vtables, pointers, action instance IDs, command serials,
or native object selectors.

The base action fields shared by all recovered subclasses are:

| Offset | Field |
| --- | --- |
| `+0x20` | generation-bearing actor country reference |
| `+0x24` | generation-bearing recipient country reference |
| `+0x30` | 64-bit diplomatic action instance ID |

## Registered semantic actions

| Semantic action | Native action | Target fields | Native size |
| --- | --- | --- | --- |
| `open_borders` | `COpenBordersAction` | `target_country_id` | `0x50` |
| `close_borders` | `CCloseBordersAction` | `target_country_id` | `0x50` |
| `establish_rivalry` | `CMakeRivalAction` | `target_country_id` | `0x50` |
| `declare_war` | `CDeclareWarAction` | `target_country_id` | `0x90` |
| `offer_peace` | `COfferPeaceAction` | `target_country_id`, `war_id`, `offer_kind` | `0x68` |
| `establish_embassy` | `CCreateEmbassyAction` | `target_country_id` | `0x50` |
| `form_commercial_pact` | `CFormCommercialPactAction` | `target_country_id` | `0x50` |
| `form_defensive_pact` | `CFormDefensivePactAction` | `target_country_id` | `0x50` |
| `form_research_agreement` | `CFormResearchAgreementAction` | `target_country_id` | `0x50` |
| `form_migration_pact` | `CFormMigrationPactAction` | `target_country_id` | `0x50` |
| `invite_to_federation` | `CInviteToFederationAction` | `target_country_id` | `0xb8` |
| `offer_trade_deal` | `COfferTradeDealAction` | `target_country_id`, `direction`, `resource_key`, `amount` | `0x2a0` |
| `demand_subjugation` | `CDemandSubjugationAction` | `target_country_id` | `0x1e0` |
| `break_migration_pact` | `CBreakMigrationPactAction` | `target_country_id` | `0x50` |
| `break_commercial_pact` | `CBreakCommercialPactAction` | `target_country_id` | `0x50` |
| `insult_country` | `CInsultAction` | `target_country_id` | `0x50` |

Every descriptor belongs to the `etc` Application. Focused continuation-save
tests have promoted `establish_rivalry`, `declare_war`,
`establish_embassy`, `form_commercial_pact`, `form_research_agreement`,
`form_migration_pact`, `break_migration_pact`, `break_commercial_pact`,
`offer_trade_deal`, and `insult_country` to `live_verified`; the reversible
border pair was already verified. The other
descriptors remain `paired_capture`, are discoverable through dynamic manifest
overlay, and keep `broker_enabled_backends` empty. See
`DIPLOMACY_WAR_LIVE_VERIFICATION_4_4_6.md` for the exact evidence and negative
results.

## Specialized construction

`declare_war` calls the game's own `NAIUtil::SelectWarGoalType` for the current
actor and target. It constructs a temporary `CWarGoal`, copies it into
`CDeclareWarAction`, then destroys the temporary value. The first contract
therefore chooses the game's highest-weight legal goal. Explicit goal choice
requires a later candidate query keyed by stable war-goal names.

`offer_peace` accepts exactly `force_demands`, `status_quo`, or `surrender`.
The corresponding native `CPeaceOffer` status values are `2`, `0`, and `1`.
The runtime resolves the supplied generation-bearing war ID before building the
action.

`offer_trade_deal` creates one immediate resource line. `direction=offer`
places the resource on the actor's side; `direction=request` places it on the
recipient's side. The resource is resolved by stable database key, and the
amount is converted to Stellaris fixed point with scale `100000`. Multi-line,
monthly, strategic-resource, and favor contracts need separate typed fields.

`demand_subjugation` uses the game's default agreement and an absent optional
initial-loyalty value. `invite_to_federation` uses the constructor's null
persistent-name option.

## Passive capture decoder

`research/diplomatic_action_decoder.py` decodes both capture generations. Old
segments contain the common `0x50`-byte prefix for most subclasses; those
records still yield actor, recipient, generation, and action ID but report
`complete=false`. New probe builds copy the complete known derived size, up to
the `0x2a0`-byte trade-deal object, and report `complete=true`.

The historical long-run capture was reprocessed successfully. It contained all
16 mapped RTTI types. Across all recorded phases the decoder emitted 2,964
records; only the 16 old `CDeclareWarAction` records were complete because that
was the only derived size known by the probe during the run. This verifies old
segment compatibility, not live execution of the new adapters.

## Promotion gates

Each still-staged action remains disabled until a disposable live run proves:

1. a legal request survives native validation and reaches the expected game
   behavior;
2. an illegal or stale country, war, resource, or relation is rejected without
   posting;
3. a later save proves the intended postcondition;
4. retrying the same Broker request ID cannot duplicate the action; and
5. the exact-build signature and ownership path remain intact after failure.

The runtime contract test checks descriptor discovery, schema parsing,
duplicate registration, and manifest output. The Linux production library and
research probe both compile with warnings treated as errors.
