# State and Diplomacy Command Coverage: Stellaris 4.4.6

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Evidence boundary

This audit answers whether the completed Linux `human_ai` capture contains a
native operation that can anchor each requested semantic action. It combines:

- the durable catalog plus the preserved final partial segment: 2,153,069
  command records, 116 command RTTI types, and zero reported record loss;
- the exact Stellaris 4.4.6 Linux symbol table, used only to distinguish a
  symbol-only candidate from a command actually observed in the capture; and
- the enhanced command-probe segments, which retained nested RTTI for 16
  concrete actions behind `CDiploActionProposeCommand`; and
- static layout recovery for the complete derived objects used by those 16
  actions.

The status labels are deliberately strict:

| Status | Meaning |
| --- | --- |
| `DIRECT` | A final native command was observed at `session_post`; this is an execution anchor, not automatic production approval. |
| `WRAPPER` | The generic proposal wrapper was observed and an exact semantic action class exists, but that subtype is not yet registered. |
| `PAIRED_CAPTURE` | Nested RTTI, layout, semantic parameters, constructor path, and wrapper ownership are mapped; the runtime descriptor remains disabled pending focused live verification. |
| `SYMBOL` | An exact native command exists in the 4.4.6 binary but never appeared in the completed capture. |
| `INDIRECT` | Only a generic policy, event, faction, resolution, or response route is evidenced. More semantic discrimination is required. |
| `NONE` | Neither the capture nor the reviewed symbol inventory provides a sufficiently specific operation. |

`DIRECT` does not mean that constructor layout, candidate enumeration,
authority checks, native validation, postcondition, and save continuation are
complete. Those remain mandatory before Broker enablement.

## Direct command evidence

Counts include the final unrotated command tail.

| Native command | Post | Execute | Primary semantic surface |
| --- | ---: | ---: | --- |
| `CSetPolicyCommand` | 212 | 212 | Any normal empire policy group and option |
| `CAddEdictCommand` | 1,148 | 1,148 | Enable edict |
| `CRemoveEdictCommand` | 935 | 935 | Disable edict |
| `CCountryActivateTraditionCommand` | 538 | 538 | Select tradition |
| `CCountryActivateAscensionPerkCommand` | 79 | 79 | Select ascension perk |
| `CSetCouncilAgendaCommand` | 662 | 662 | Select/set council agenda |
| `CHireAndAssignLeaderCommand` | 618 | 618 | Recruit and immediately assign leader |
| `CAssignLeaderCommand` | 13,951 | 13,885 | Assign/reassign a leader location |
| `CUnlockCouncilPositionCommand` | 100 | 100 | Unlock position, not appoint its leader |
| `CDiploActionProposeCommand` | 2,394 | 2,394 | Polymorphic outgoing diplomacy wrapper |
| `CDiploActionRespondCommand` | 946 | 939 | Accept/reject one pending diplomatic action |
| `CDiploActionVoteCommand` | 287 | 287 | Vote on one pending diplomatic action |
| `CJoinCommunityCommand` | 10 | 10 | Join Galactic Community |
| `CProposeResolutionCommand` | 75 | 75 | Propose resolution |
| `CSupportProposedResolutionCommand` | 843 | 843 | Support/sponsor proposed resolution |
| `COpposeProposedResolutionCommand` | 867 | 867 | Oppose proposed resolution |
| `CWithdrawProposedResolutionCommand` | 6 | 6 | Withdraw proposed resolution |
| `CCastVoteCommand` | 1,526 | 1,526 | Cast or update a resolution vote |
| `CProposeEmergencyMeasureCommand` | 5 | 5 | Mark/propose emergency measure |
| `CAddSystemClaimCommand` | 117 | 117 | Add claim |
| `CRemoveSystemClaimCommand` | 18 | 18 | Remove claim |
| `CDiploActionSetDefenderWarGoalCommand` | 8 | 8 | Set defender war goal after war creation |
| `CCountrySetDefaultSpeciesRightsCommand` | 90 | 90 | Replace default species-rights configuration |
| `CCountrySetSpeciesRightsCommand` | 676 | 676 | Replace one species-rights configuration |
| `CSetSituationApproachCommand` | 893 | 893 | Select/change situation approach |
| `CCreateEspionageOperationCommand` | 180 | 180 | Start espionage operation |
| `CDestroyEspionageOperationCommand` | 8 | 8 | Cancel espionage operation |
| `CSelectEventOptionCommand` | 1,045 | 1,045 | Select event/operation/first-contact option |
| `CMarketBuyResourceCommand` | 23,811 | 23,792 | One-shot market buy |
| `CMarketSellResourceCommand` | 16,155 | 15,779 | One-shot market sell |
| `CSetFleetGroundSupportStanceCommand` | 8,317 | 8,317 | Per-fleet bombardment stance |

Post/execute differences are evidence that posting alone is not success
confirmation.

## Policy, government, council, and leaders

| Requested behavior | Status | Native evidence and limitation |
| --- | --- | --- |
| Empire policy modification | `DIRECT` | `CSetPolicyCommand(group*, option*, country)`; the capture did not retain group/option keys. |
| Enable edict | `DIRECT` | `CAddEdictCommand`. |
| Disable edict | `DIRECT` | `CRemoveEdictCommand`. |
| Select tradition | `DIRECT` | `CCountryActivateTraditionCommand`. |
| Select ascension perk | `DIRECT` | `CCountryActivateAscensionPerkCommand`. |
| Select/start Council Agenda | `DIRECT` | `CSetCouncilAgendaCommand`; setting is observed. Normal agenda progression is engine-owned. |
| Finish or rush Council Agenda | `SYMBOL` | `CFinishAgendaCommand` and `CEarlyFinishAgendaCommand` exist but were not captured. |
| Government reform | `SYMBOL` | `CChangeGovernmentCommand(country, authority, civics[])` exists. `CValidateGovernmentCommand` was captured 15 times but is not the reform payload. |
| Modify Civics | `SYMBOL` | Same `CChangeGovernmentCommand` civic array. |
| Change Authority | `SYMBOL` | Same `CChangeGovernmentCommand` authority pointer. |
| Change Ethics | `INDIRECT` | No direct ethics command was captured. `CExecuteFactionActionCommand` appeared eight times and may cover embracing a faction, but its action subtype was not decoded. |
| Recruit leader | `DIRECT` | `CHireAndAssignLeaderCommand`; standalone `CHireLeaderCommand` is symbol-only. |
| Appoint leader | `DIRECT` | `CAssignLeaderCommand`. |
| Reassign leader | `DIRECT` | `CAssignLeaderCommand`; envoy-specific `CChangeLeaderAssignmentCommand` is symbol-only. |
| Dismiss leader | `SYMBOL` | `CFireLeaderCommand` exists but was not captured. |
| Appoint/adjust Council Position | `SYMBOL` | `CAddToCouncilCommand(position, leader)` exists but was not captured. Captured `CUnlockCouncilPositionCommand` only unlocks a slot. |
| Select Leader Trait | `SYMBOL` | `CAddTraitFromPoolCommand(country, leader, trait)` exists but was not captured. |
| Select Veteran Class | `SYMBOL` | Likely shares the trait-pool route, but no captured record proves the exact contract. |
| Select Destiny Trait | `SYMBOL` | Same limitation as Veteran Class. |
| Ruler-election operations | `SYMBOL` | `CEmergencyElectionCommand` and `CSelectElectionWinnerCommand` exist but were not captured. |
| Support candidate | `SYMBOL` | `CSupportElectionCandidateCommand` exists but was not captured. |

## Bilateral diplomacy, subjects, and federations

The completed capture proves the common proposal, response, and vote pipeline.
Its enhanced segments retain 16 nested RTTI classes. The offline decoder can
recover their shared actor, recipient, generation, and action ID from old
`0x50`-byte prefixes; the rebuilt probe captures each mapped derived object in
full. `PAIRED_CAPTURE` means the runtime adapter exists but is still disabled
by the Broker until live validation and save postconditions are complete.

| Requested behavior | Status | Concrete action or route |
| --- | --- | --- |
| Propose diplomatic action | `DIRECT` | `CDiploActionProposeCommand`; requires a typed nested action. |
| Accept / reject diplomatic action | `DIRECT` | `CDiploActionRespondCommand(pending_action_id, bool)`. |
| Cancel diplomatic relation | `PAIRED_CAPTURE` / `WRAPPER` | Migration and commercial pact cancellation are registered; other `CBreak*` actions remain wrapper-only. |
| Establish / recall embassy | `PAIRED_CAPTURE` / `WRAPPER` | `CCreateEmbassyAction` is registered; recall remains wrapper-only. |
| Improve / harm relations | `WRAPPER` | `CImproveRelationAction`, `CHarmRelationAction`. |
| Assign Envoy | `SYMBOL` | `CChangeLeaderAssignmentCommand(leader, EEnvoyAssignment)`. |
| Open / close borders | `PAIRED_CAPTURE` | `COpenBordersAction`, `CCloseBordersAction`. |
| Establish / cancel Rivalry | `PAIRED_CAPTURE` / `WRAPPER` | `CMakeRivalAction` is registered; end-rivalry remains wrapper-only. |
| Guarantee / revoke independence | `WRAPPER` | `CGuaranteeIndependenceAction`, `CBreakGuaranteeAction`. |
| Non-Aggression Pact | `WRAPPER` | `CFormNonAggressionPactAction`, `CBreakNonAggressionPactAction`. |
| Defensive Pact | `PAIRED_CAPTURE` / `WRAPPER` | Formation is registered; cancellation remains wrapper-only. |
| Commercial Pact | `PAIRED_CAPTURE` | Formation and cancellation are registered. |
| Research Agreement | `PAIRED_CAPTURE` / `WRAPPER` | Formation is registered; cancellation remains wrapper-only. |
| Migration Treaty | `PAIRED_CAPTURE` | Formation and cancellation are registered. |
| Propose subjugation | `PAIRED_CAPTURE` / `WRAPPER` | Default demand is registered; ask-to-become-subjugated remains wrapper-only. |
| Accept / reject subject relationship | `DIRECT` | Generic pending-action response once a subject proposal is identified. |
| Modify/change Subject Agreement | `WRAPPER` | `CNegotiateExistingAgreementAction`. |
| Integrate / cancel integration | `WRAPPER` | `CIntegrateSubjectAction`, `CCancelSubjectIntegrationAction`. |
| Release / ask to be released | `WRAPPER` | `CReleaseSubjectAction`, `CAskTobeReleasedSubjectAction`. |
| Create Federation | `NONE` | No dedicated create/form-federation action was found in the reviewed command/action inventory. |
| Invite / ask to join Federation | `PAIRED_CAPTURE` / `WRAPPER` | Invitation is registered; ask-to-join remains wrapper-only. |
| Accept / reject Federation invitation | `DIRECT` | Generic pending-action response. |
| Leave / ask to leave / kick member | `WRAPPER` | `CLeaveFederationAction`, `CAskToLeaveFederationAction`, `CKickFromFederationAction`. |
| Federation Law / type modification | `WRAPPER` | `CVoteForFederationLawAction`, `CVoteForFederationTypeAction`. |
| Federation Vote | `DIRECT` | Generic `CDiploActionVoteCommand`; a proposed-action candidate query is still needed. |
| Federation War Declaration Vote | `DIRECT` | Same generic vote wrapper, provided the pending action is identified as war declaration. |
| Federation succession decisions | `INDIRECT` | No dedicated captured command; may use law/type vote or events depending on the decision. |
| Federation Fleet national decisions | `NONE` | No sufficiently specific state-level command was identified. |

## Galactic Community and Imperium

| Requested behavior | Status | Native evidence and limitation |
| --- | --- | --- |
| Join Galactic Community | `DIRECT` | `CJoinCommunityCommand`. |
| Leave Galactic Community | `SYMBOL` | `CLeaveCommunityCommand` exists but was not captured. |
| Propose Resolution | `DIRECT` | `CProposeResolutionCommand`. |
| Support / oppose / withdraw support | `DIRECT` | Dedicated support, oppose, and withdraw commands. |
| Abstain | `SYMBOL` | `CAbstainProposedResolutionCommand` exists but was not captured. |
| Cast / modify vote | `DIRECT` | `CCastVoteCommand(resolution, country, EResolutionVote, bool)`. |
| Galactic Council voting | `DIRECT` | Uses the same resolution vote command. |
| Veto | `SYMBOL` | `CVetoResolutionCommand` exists but was not captured. |
| Emergency Measure | `DIRECT` | `CProposeEmergencyMeasureCommand`. |
| Custodian operations | `INDIRECT` | Resolution commands cover election, powers, and term resolutions; no single generic Custodian command was captured. |
| Galactic Imperium operations | `INDIRECT` | Resolution route plus symbol-only `CAdd/Change/RemoveImperialCouncilMemberAction`; concrete proposal subtypes were not retained. |

## Claims, war, and peace

| Requested behavior | Status | Native evidence and limitation |
| --- | --- | --- |
| Establish / revoke Claim | `DIRECT` | `CAddSystemClaimCommand`, `CRemoveSystemClaimCommand`. |
| Select War Goal | `DIRECT` / `WRAPPER` | Defender change is directly captured; attacker goal is embedded in `CDeclareWarAction`. |
| Declare War | `PAIRED_CAPTURE` | Runtime uses `CDeclareWarAction` and the native legal-goal selector. `CAIPrepareWarCommand` remains AI planning state only. |
| Accept / reject war diplomacy | `DIRECT` | Generic pending-action response. |
| Propose Status Quo | `PAIRED_CAPTURE` | `COfferPeaceAction` with native status `0`. |
| Accept / reject Status Quo | `DIRECT` | Generic pending-action response after candidate classification. |
| Propose Surrender | `PAIRED_CAPTURE` | `COfferPeaceAction` with native status `1`; force-demands uses status `2`. |
| Accept / reject Surrender | `DIRECT` | Generic pending-action response after candidate classification. |
| Other war-ending diplomacy | `PAIRED_CAPTURE` / `WRAPPER` | The three base peace offers are registered; view-specific variants remain wrapper-only. |

## Species rights, situations, espionage, and markets

| Requested behavior | Status | Native evidence and limitation |
| --- | --- | --- |
| Species Rights modification | `DIRECT` | `CCountrySetSpeciesRightsCommand` replaces a complete typed configuration. |
| Default Species Rights | `DIRECT` | `CCountrySetDefaultSpeciesRightsCommand`. |
| Citizenship | `DIRECT` | Field inside the shared rights configuration, not a separate command. |
| Living Standard | `DIRECT` | Same aggregate configuration. |
| Military Service | `DIRECT` | Same aggregate configuration. |
| Migration Controls | `DIRECT` | Same aggregate configuration. |
| Population Controls | `DIRECT` | Same aggregate configuration. |
| Slavery Type | `DIRECT` | Same aggregate configuration. |
| Purge Type | `DIRECT` | Same aggregate configuration. |
| Select/change Situation Approach | `DIRECT` | `CSetSituationApproachCommand(situation, approach_key)`. |
| Empire-level Situation decision | `NONE` | No generic final command was identified; individual situations may use events or scripted actions. |
| First Contact national decision | `INDIRECT` | Choices can use `CSelectEventOptionCommand`; symbol-only `CSetFirstContactEventExpiredCommand` is bookkeeping, not a semantic decision API. |
| Build / manage Spy Network | `WRAPPER` | `CBuildSpyNetworkAction` and `CManageSpyNetworkAction` exist behind the proposal wrapper. |
| Assign Envoy to espionage | `SYMBOL` | `CChangeLeaderAssignmentCommand` with `EEnvoyAssignment`. |
| Start Espionage Operation | `DIRECT` | `CCreateEspionageOperationCommand`. |
| Cancel Espionage Operation | `DIRECT` | `CDestroyEspionageOperationCommand`. |
| Espionage-operation decision | `INDIRECT` | Usually the captured event-option route; no dedicated generic decision command was observed. |
| Market buy / sell | `DIRECT` | Dedicated buy and sell commands. |
| Create Monthly Trade | `SYMBOL` | `CAddMonthlyTradeCommand(SMonthlyTradeData)` exists but was not captured. |
| Modify Monthly Trade | `SYMBOL` | `CUpdateMonthlyTradeCommand(SMonthlyTradeData)` exists but was not captured. |
| Cancel Monthly Trade | `SYMBOL` | `CRemoveMonthlyTradeCommand(SMonthlyTradeData)` exists but was not captured. |
| Trade / economic / war policy | `DIRECT` | Policy group and option through `CSetPolicyCommand`. |
| Diplomatic stance | `DIRECT` | Also a policy-group selection; candidate enumeration is still required. |
| Empire bombardment policy | `DIRECT` | Policy route where applicable. Per-fleet bombardment stance has its own heavily observed command. |

## Value of another capture

The enhanced segments already separated 16 high-frequency diplomatic
subclasses, and those are now typed `paired_capture` runtime actions. Another
broad unattended run would mainly add frequency evidence. The useful next run
is a focused validation campaign:

1. Trigger each registered proposal once with a legal target and once with a
   stale or illegal target, retaining a save before and after the action.
2. Exercise symbol-only commands that the 300-year AI campaign never emitted:
   government reform, leader dismissal, council appointment, trait selection,
   elections, monthly trades, leaving the Community, abstention, and veto.
3. Keep the enhanced nested-object probe active so any still-unknown
   diplomatic subclass yields a common prefix and RTTI without guessed fields.

For the first AI battle, policy/edict/progression, leader assignment, generic
diplomatic response/vote, Community resolutions, claims, species rights,
situation approach, espionage operations, market trades, and the existing
military/economy actions already provide the useful core. The wrapper and
symbol-only rows can remain vanilla-AI controlled until individually promoted.
