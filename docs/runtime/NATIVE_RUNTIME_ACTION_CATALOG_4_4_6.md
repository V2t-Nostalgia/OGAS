# Native Runtime Action Catalog: Stellaris 4.4.6

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope and status

This catalog describes the Linux `Stellaris 4.4.6 (fdde)` runtime profile with
ELF Build ID `c6969e60fd81d738948222a94c0b5a0841abbffc`. It is generated from the
same self-registered descriptors returned by `describe_tools`; it is not a
claim about Windows offsets or another game build.

The current manifest contains **73** actions:

| Native verification state | Count | Broker treatment of native backend |
| --- | ---: | --- |
| `live_verified` | 42 | May be selected after the normal authority, snapshot, candidate, permission and idempotency checks |
| `paired_capture` | 31 | Visible for diagnostics, but `broker_enabled_backends` is empty and native dispatch is rejected |

`paired_capture` means the runtime has a strict parser and a version-bound
native construction path. It does not mean that an Application can execute the
action. A semantic action may still have a separately verified session-proxy
or carrier backend; the rejection described here is specifically the native
runtime backend.

## Broker-enabled native actions

| Action | Application | Typed target | Runtime postcondition |
| --- | --- | --- | --- |
| `move_fleet` | `fleet_operations` | `fleet_id:uint32, destination_system_id:uint32` | Exact player movement order appears for the fleet |
| `attack_fleet` | `fleet_operations` | `fleet_id:uint32, target_fleet_id:uint32` | Non-cancelled attack order targets the exact fleet |
| `stop_research` | `research_strategy` | `technology_id:string` | The exact technology is no longer researching |
| `market_buy_resource` | `economy_governance` | `resource_key:string, lots:uint32` | Native market validation accepts and the command executes through the session |
| `market_sell_resource` | `economy_governance` | `resource_key:string, lots:uint32` | Native market validation accepts and the command executes through the session |
| `select_event_option` | `etc` | `open_event_id:uint32, option_index:uint32` | The exact open-event instance is consumed or advanced |
| `activate_ascension_perk` | `etc` | `definition_key:string` | `CCountry::HasAscensionPerk` confirms the exact key |
| `start_espionage_operation` | `etc` | `spy_network_id:uint32, operation_type_key:string` | Save continuation contains an operation of the exact type on the exact network and target |
| `cancel_espionage_operation` | `etc` | `spy_network_id:uint32, operation_id:uint32` | Save continuation removes the exact operation from both the network and operation database |
| `set_situation_approach` | `etc` | `situation_id:uint32, approach_key:string` | Save continuation records the exact selected approach on the exact situation |
| `enable_edict` | `etc` | `definition_key:string` | Save continuation adds the exact edict to the acting country's active edicts |
| `disable_edict` | `etc` | `definition_key:string` | Save continuation removes the exact edict from the acting country's active edicts |
| `set_empire_policy` | `etc` | `policy_group_key:string, policy_option_key:string` | Save continuation selects the exact option in the exact policy group |
| `activate_tradition` | `etc` | `definition_key:string` | Save continuation contains the exact adopted tradition and game-awarded tree completion where applicable |
| `set_council_agenda` | `etc` | `definition_key:string` | Save continuation selects the exact agenda and resets its preparation progress |
| `assign_leader` | `etc` | `leader_id:uint32, location_kind:string, location_object_id:uint32, position_index?:uint32` | Save continuation moves the exact owned leader to the exact typed location |
| `hire_and_assign_leader` | `etc` | `leader_id:uint32, location_kind:string, location_object_id:uint32, position_index?:uint32` | Save continuation removes the exact candidate from the pool, adds ownership and assigns the exact location |
| `open_borders` | `etc` | `target_country_id:uint32` | Native proposal wrapper contains `COpenBordersAction`; save continuation removes `closed_borders` for the exact relation |
| `close_borders` | `etc` | `target_country_id:uint32` | Native proposal wrapper contains `CCloseBordersAction`; save continuation restores `closed_borders` for the exact relation |
| `establish_rivalry` | `etc` | `target_country_id:uint32` | Save continuation records the exact rival relation and action history |
| `declare_war` | `etc` | `target_country_id:uint32` | Native war-goal selection succeeds and the save contains the exact attacker, defender and war object |
| `offer_peace` | `etc` | `target_country_id:uint32, war_id:uint32, offer_kind:{force_demands,status_quo,surrender}` | Exact pending peace action preserves the requested status, actor, recipient and war ID |
| `establish_embassy` | `etc` | `target_country_id:uint32` | Exact pending embassy action is accepted and the bilateral relation gains the embassy state |
| `form_commercial_pact` | `etc` | `target_country_id:uint32` | Accepted proposal sets the bilateral `commercial_pact` relation |
| `form_research_agreement` | `etc` | `target_country_id:uint32` | Accepted proposal sets the bilateral `research_agreement` relation |
| `form_migration_pact` | `etc` | `target_country_id:uint32` | Accepted proposal sets the bilateral `migration_access` relation |
| `break_migration_pact` | `etc` | `target_country_id:uint32` | Exact bilateral `migration_access` relation is removed |
| `break_commercial_pact` | `etc` | `target_country_id:uint32` | Exact bilateral `commercial_pact` relation is removed |
| `insult_country` | `etc` | `target_country_id:uint32` | Save continuation records the exact insult action and relation modifier |
| `offer_trade_deal` | `etc` | `target_country_id:uint32, direction:{offer,request}, resource_key:string, amount:uint32` | Pending action, escrow/refund and accepted resource transfer match the exact amount in both directions |
| `respond_to_diplomatic_action` | `etc` | `pending_action_id:uint64, accept:boolean` | Exact pending ID disappears once; embassy and trade accept/reject consequences persist in the next save |
| `vote_on_diplomatic_action` | `etc` | `pending_action_id:uint64, support:boolean` | Exact federation vote is consumed and the approved status-quo proposal advances to the opposing primary country |
| `unlock_council_position` | `etc` | `definition_key:string` | Exact council-position key appears in the country's picked types and council-position database |
| `propose_resolution` | `etc` | `resolution_type_key:string` | Exact resolution type enters `galactic_community.proposed` with the actor as sponsor and initial supporter |
| `support_proposed_resolution` | `etc` | `resolution_id:uint32` | Exact country moves into the proposal's supporters set |
| `oppose_proposed_resolution` | `etc` | `resolution_id:uint32` | Exact country moves into the proposal's opponents set |
| `withdraw_proposed_resolution` | `etc` | `resolution_id:uint32` | Exact country proposal is removed from the active proposal queue |
| `cast_resolution_vote` | `etc` | `resolution_id:uint32, vote:{support,oppose,abstain}` | Active resolution records the actor's opposed vote and synchronized subject votes at the current date |
| `add_system_claim` | `fleet_operations` | `system_id:uint32, claim_count:uint32` | Exact system gains the acting country's claim with the requested count |
| `remove_system_claim` | `fleet_operations` | `system_id:uint32, claim_count:uint32` | Exact claim entry is removed again in the continuation save |
| `set_species_rights` | `etc` | `species_id:uint32, template_species_id:uint32` | Target species copies every current right from a legal explicit template configuration |
| `set_default_species_rights` | `etc` | `template_species_id:uint32` | Default rights copy the legal template configuration and preserve former values plus cooldown dates |

These 42 use semantic object resolution, native validation and
`PostCommandToSession`. Seven have action-specific in-memory postconditions;
the two espionage actions, two edict actions and situation action retain
explicit save-continuation verification. Their
live evidence is recorded in the corresponding move, attack, research,
market/event/governance, espionage, and situation hook documents.

## Newly typed 26-action set

The requested set is complete. Twenty-four actions were added in this change;
the two incoming-diplomacy actions already existed and are covered by the same
baseline test. `activate_ascension_perk` has since completed focused live
verification, espionage start/cancel have completed command plus save
continuation validation, situation approach selection has completed the same
command-plus-save check, and edict enable/disable have completed a reversible
round trip, while policy selection changed the exact policy and corresponding
policy flag. They appear in the enabled table above. The remaining
eight of the initially staged actions have since completed focused live
verification and now appear in the enabled table above. The three descriptors
below deliberately stay `paired_capture`, so the Broker rejects native
execution until focused live validation is attached.

| Action | Application | Typed target | Paired observations |
| --- | --- | --- | ---: |
| `join_galactic_community` | `etc` | no target fields | 10 |
| `propose_emergency_measure` | `etc` | `resolution_id:uint32` | 5 |
| `set_defender_war_goal` | `fleet_operations` | `war_id:uint32, war_goal_type_key:string` | 8 |

All 26 use the common path:

```text
strict positional target parser
  -> generation-bearing object or static-definition resolver
  -> native command constructor
  -> restore the session-owned command serial to `0xffffffff`
  -> native virtual IsValid
  -> common PostCommandToSession ownership transfer
  -> pending save verification
```

The running 4.4.6 process was read without issuing a command and confirmed the
new static-definition layout (`database + 0x50` pointer array, count at
`+0x5c`, definition key at `object + 0x10`). Recognized samples were read from
policy, tradition, council-position, resolution-type, war-goal-type and
espionage-operation registries.

### Deliberate first-stage restrictions

- Leader locations are typed as `colony`, `ship`, `army`, `country`,
  `council_position`, or `patron_relation`. `position_index` is required only
  for a council position.
- Galactic resolution votes map to the statically confirmed native values
  `support=0`, `oppose=1`, and `abstain=2`.
- `claim_count` is the native claim-level/count constructor argument, not a
  boolean.
- Species-rights actions copy a currently valid rights configuration from a
  selected template species. They do not expose unverified nested rights
  pointers as model input.
- Espionage start resolves the generation-bearing spy network, asks the native
  `CSpyNetwork::GetTarget()` accessor for its target country, and constructs a
  country scope with `CScopeObjectReference::SetCountry()`. Arbitrary external
  scope IDs are not accepted.

## Other staged runtime actions

The remaining `paired_capture` actions are also implemented and advertised by
the Linux profile, but the Broker refuses their native backend for the same
reason. In the compact signatures below, IDs, contexts, counts, indices, slots,
growth stages and amounts are `uint32`; keys, names, kinds, coordinates,
stances, levels, designations and hex records are bounded strings. The runtime
manifest remains the machine-readable source of exact bounds and requiredness.

### Economy, construction and research

| Action | Typed/runtime target |
| --- | --- |
| `build_building` | `context_822c, build_queue_id, colony_id, zone_id, building_id` |
| `upgrade_building` | `context_822c, build_queue_id, colony_id, zone_id, building_object_id, building_id` |
| `replace_building` | `context_822c, build_queue_id, colony_id, zone_id, source_building_object_id, building_id` |
| `build_district` | `context_822c, build_queue_id, colony_id, district_type` |
| `build_zone` | `context_822c, build_queue_id, colony_id, district_id, slot_selector, zone_type` |
| `start_research` | `context_822c, technology_id` |

The `context_822c` and queue fields are still private captured representation,
not the desired final Application contract. These actions require semantic
resolvers before native promotion.

### Fleets, armies, expansion, starbases and ship design

| Action | Typed/runtime target |
| --- | --- |
| `move_fleet_to_coordinate` | `source_fleet_object, x_fixed, y_fixed, system_origin` |
| `set_orbital_bombardment_stance` | `source_fleet_object, stance` |
| `land_armies` | `source_fleet_object, target_colony_object` |
| `recruit_army` | `context_822c, army_build_queue_id, army_type, species_id, source_colony_object, recruitment_starbase_object` |
| `repair_fleet` | `context_822c, source_fleet_object` |
| `upgrade_fleet` | `context_822c, source_fleet_object, shipyard_build_queue_id` |
| `configure_ship_automation` | `verified_record_hex` |
| `build_starbase` | `source_fleet_object, target_system_object` |
| `order_colony_ship_and_colonize` | `context_822c, species_id, colony_designation, design_id, upgrade_id, growth_stage, target_planet_id, source_shipyard_build_queue_id, system_name_key` |
| `colonize_with_existing_ship` | `source_fleet_object, target_planet_id, system_name_key` |
| `upgrade_starbase` | `context_822c, build_queue_id, target_level, starbase_object` |
| `set_starbase_module` | `context_822c, build_queue_id, component_id, slot_index, starbase_object` |
| `set_starbase_building` | `context_822c, build_queue_id, component_id, slot_index, starbase_object` |
| `build_ship` | `context_822c, build_queue_id, design_id, upgrade_id, growth_stage, destination_object` |
| `create_ship_design` | `verified_record_hex` |
| `create_fleet_template` | `context_822c` |
| `add_fleet_template_ship` | `context_822c, fleet_template_id, design_id, upgrade_id, growth_stage` |
| `remove_fleet_template_ship` | `fleet_template_id, design_id, upgrade_id, growth_stage` |
| `reinforce_selected_fleet` | `context_822c, fleet_template_id` |

### Event and outgoing diplomacy

| Action group | Actions and target |
| --- | --- |
| Country-only proposals | `form_defensive_pact`, `invite_to_federation`, `demand_subjugation`; each takes `target_country_id` |

## Evidence-to-runtime promotion plan

Promotion is per action, never per source file or command family. Use a
disposable single-player save on the exact supported build and keep production
Broker gating unchanged during the experiment.

### Cross-cutting gates for every action

1. Record the source save hash, country ID, legal candidate identity and exact
   semantic request. Confirm that the candidate is still legal immediately
   before submission.
2. Add representative constructor/validator instruction anchors to the build
   profile so an offset alone cannot enable the action on a changed binary.
3. Through the explicit validation harness, observe one constructor, one
   successful native `IsValid`, and exactly one
   `PostCommandToSession` call for the request ID.
4. Prove an action-specific in-memory transition and then a new-save
   continuation. `posted` or lack of a crash is not success.
5. Run invalid generation ID, wrong country/authority, stale candidate,
   illegal-state and insufficient-resource tests. Each must reject before a
   side effect or remain unchanged in the next save.
6. Retry the identical request ID before and after timeout. The runtime and
   Broker must return the prior result or pending state without a second post.
7. Check command ownership under success, native rejection and timeout; then
   run a mixed ordered batch to expose lifetime or queue corruption.
8. Attach raw probe records, runtime audit lines, before/after save hashes and
   parsed postcondition evidence to the action's evidence document.
9. Only then change that descriptor to `live_verified`, add a focused Broker
   overlay test, and grant the semantic action to its reviewed Application.

### Focused validation batches

1. **Governance:** change one reversible policy, enable then disable one legal
   edict, adopt one tradition and one perk, select one agenda, and unlock one
   council slot. Verify exact keys, resource/cooldown changes and duplicate or
   already-active rejection.
2. **Leaders:** hire one legal candidate and exercise assignment/removal for
   each supported location kind. Verify leader pool membership, assignment
   object and council index; test stale leader and incompatible class.
3. **Incoming diplomacy:** capture a real pending action, test accept and
   reject on separate saves, then repeat for a federation-style vote. Verify
   the pending ID disappears once and the resulting relation/vote state.
4. **Galactic Community:** join, propose, support, oppose, withdraw, cast all
   three vote values, and invoke emergency measure with eligible and ineligible
   actors. Verify proposal queues, support state, vote weight and cooldowns.
5. **Claims and war:** add/remove one claim level and set a defender goal on a
   current war. Verify exact claim count, influence cost, war side and goal;
   reject non-neighbor, stale system and wrong-war candidates.
6. **Species rights:** copy default and species-specific templates, then verify
   every affected rights field and cooldown. Reject an unavailable template
   and a species outside the actor's authority.
7. **Situation and espionage:** change a legal situation approach, start an
   empty-scope operation, and cancel that exact operation. Verify approach,
   operation/network membership, assets/resources and duplicate cancellation.
   Separately reverse and type the scoped-operation target before enabling any
   operation that native validation rejects with an empty scope.

Passing static layout checks or having many paired observations establishes
the constructor schema, not the gameplay postcondition. Until the applicable
batch is complete, the current `paired_capture` and Broker rejection are the
intended production behavior.
