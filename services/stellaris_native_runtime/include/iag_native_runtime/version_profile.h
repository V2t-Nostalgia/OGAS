#pragma once

#include <cstddef>
#include <cstdint>

namespace iag::native_runtime {

struct FunctionAnchor {
  const char* name;
  std::uintptr_t offset;
  const unsigned char* prefix;
  std::size_t prefix_size;
};

struct ObjectDatabaseProfile {
  std::uintptr_t database_instance;
  std::uintptr_t null_object_instance;
  std::size_t object_id_offset;
};

struct StaticDefinitionDatabaseProfile {
  std::uintptr_t database_instance;
  std::uintptr_t null_object_instance;
  std::size_t objects_data_offset;
  std::size_t objects_count_offset;
  std::size_t object_key_offset;
};

struct CoreBindings {
  std::uintptr_t game_idler_idle;
  std::uintptr_t post_command_to_session;
  std::uintptr_t current_game_state;
  std::uintptr_t get_local_observed;
  std::size_t country_id_offset;
  std::size_t hook_length;
  std::uint32_t pe_timestamp;
  std::size_t image_size;
  std::size_t text_rva;
  std::size_t text_size;
};

struct CStringBindings {
  std::size_t object_size;
  std::uintptr_t construct;
  std::uintptr_t destroy;
  std::uintptr_t get_tchar_ptr;
  std::uintptr_t get_size;
};

struct StopResearchBindings {
  std::size_t command_size;
  std::uintptr_t construct_command;
  std::uintptr_t command_is_valid;
  std::uintptr_t is_researching_technology;
  std::uintptr_t access_technology;
  std::uintptr_t access_technology_module;
  std::uintptr_t technology_database_instance;
  std::uintptr_t null_technology_instance;
  std::size_t technology_status_offset;
};

struct MoveFleetBindings {
  std::size_t command_size;
  std::size_t celestial_coordinate_size;
  std::uintptr_t construct_command;
  std::uintptr_t command_is_valid;
  std::uintptr_t calculate_ftl_point_with;
  std::uintptr_t fleet_get_controller_ref;
  std::uintptr_t fleet_get_coordinate_origin;
  std::uintptr_t fleet_count_orders;
  std::uintptr_t fleet_has_player_movement_order;
  ObjectDatabaseProfile fleets;
  ObjectDatabaseProfile galactic_objects;
  // A zero clone address selects the constructor ABI used by the Linux
  // profile. The verified Windows profile builds the native value layout and
  // transfers a game-allocated clone instead.
  std::uintptr_t command_vtable;
  std::uintptr_t clone_command;
  std::uintptr_t celestial_coordinate_vtable;
  std::size_t fleet_coordinate_provider_offset;
  std::size_t fleet_executing_order_offset;
  std::size_t order_type_offset;
  std::uint32_t move_order_type;
};

struct AttackFleetBindings {
  std::size_t command_size;
  std::uintptr_t construct_command;
  std::uintptr_t command_is_valid;
  std::uintptr_t fleet_get_controller_ref;
  std::uintptr_t fleet_get_executing_order;
  std::uintptr_t follow_fleet_order_vptr;
  std::size_t order_target_fleet_offset;
  std::size_t order_attack_offset;
  std::size_t order_cancelled_offset;
  ObjectDatabaseProfile fleets;
};

struct MarketTradeBindings {
  std::size_t command_size;
  std::uintptr_t construct_buy_command;
  std::uintptr_t construct_sell_command;
  std::uintptr_t validate_buy_command;
  std::uintptr_t validate_sell_command;
  std::uintptr_t resource_database_instance;
  std::uintptr_t null_resource_instance;
  std::uintptr_t get_resource;
};

struct OpenEventBindings {
  std::size_t command_size;
  std::uintptr_t construct_select_command;
  std::uintptr_t get_open_player_event;
  std::uintptr_t null_open_player_event_instance;
  std::uintptr_t option_is_allowed;
  std::uintptr_t option_get_first_key;
  std::size_t open_events_data_offset;
  std::size_t open_events_count_offset;
  std::size_t open_event_handle_offset;
  std::size_t open_event_scope_offset;
  std::size_t open_event_id_offset;
  std::size_t open_event_country_ref_offset;
  std::size_t event_definition_id_offset;
  std::size_t event_title_key_offset;
  std::size_t event_options_offset;
  std::size_t event_options_data_offset;
  std::size_t event_options_count_offset;
};

struct DiplomaticActionBindings {
  std::size_t propose_command_size;
  std::uintptr_t construct_propose_command;
  std::size_t respond_command_size;
  std::uintptr_t construct_respond_command;
  std::size_t vote_command_size;
  std::uintptr_t construct_vote_command;
  std::uintptr_t can_respond_to_action;
  ObjectDatabaseProfile countries;
  std::size_t incoming_actions_data_offset;
  std::size_t incoming_actions_count_offset;
  std::size_t incoming_action_stride;
  std::size_t incoming_action_pointer_offset;
  std::size_t action_actor_ref_offset;
  std::size_t action_recipient_ref_offset;
  std::size_t action_id_offset;
  std::size_t action_tag_vtable_offset;

  // Actions whose entire semantic payload is actor + recipient use the
  // common two-country constructor ABI.
  std::uintptr_t construct_open_borders_action;
  std::uintptr_t construct_close_borders_action;
  std::uintptr_t construct_make_rival_action;
  std::uintptr_t construct_create_embassy_action;
  std::uintptr_t construct_form_commercial_pact_action;
  std::uintptr_t construct_form_defensive_pact_action;
  std::uintptr_t construct_form_research_agreement_action;
  std::uintptr_t construct_form_migration_pact_action;
  std::uintptr_t construct_break_migration_pact_action;
  std::uintptr_t construct_break_commercial_pact_action;
  std::uintptr_t construct_insult_action;

  std::uintptr_t select_war_goal_type;
  std::uintptr_t null_war_goal_type_instance;
  std::uintptr_t construct_war_goal;
  std::uintptr_t destroy_war_goal;
  std::uintptr_t construct_declare_war_action;

  ObjectDatabaseProfile wars;
  std::uintptr_t construct_peace_offer;
  std::uintptr_t construct_offer_peace_action;
  std::uintptr_t construct_invite_to_federation_action;
  std::uintptr_t construct_demand_subjugation_action;

  std::uintptr_t construct_abstract_trade_deal_action;
  std::uintptr_t offer_trade_deal_vtable;
  std::uintptr_t trade_deal_access_side;
  std::uintptr_t trade_deal_set_resource;
};

struct GovernanceCommandBindings {
  std::size_t set_policy_command_size;
  std::uintptr_t construct_set_policy_command;
  StaticDefinitionDatabaseProfile policy_groups;
  std::uintptr_t policy_group_get_option;
  std::uintptr_t null_policy_option_instance;

  std::size_t edict_command_size;
  std::uintptr_t construct_enable_edict_command;
  std::uintptr_t construct_disable_edict_command;

  std::size_t tradition_command_size;
  std::uintptr_t construct_activate_tradition_command;
  std::uintptr_t construct_activate_ascension_perk_command;
  std::uintptr_t country_has_ascension_perk;
  StaticDefinitionDatabaseProfile traditions;
  StaticDefinitionDatabaseProfile ascension_perks;

  std::size_t council_agenda_command_size;
  std::uintptr_t construct_set_council_agenda_command;

  std::size_t unlock_council_position_command_size;
  std::uintptr_t construct_unlock_council_position_command;
  StaticDefinitionDatabaseProfile council_positions;
};

struct LeaderCommandBindings {
  std::size_t hire_and_assign_command_size;
  std::uintptr_t construct_hire_and_assign_command;
  std::size_t assign_command_size;
  std::uintptr_t construct_assign_command;
  ObjectDatabaseProfile leaders;
};

struct GalacticCommunityCommandBindings {
  std::size_t join_command_size;
  std::uintptr_t construct_join_command;
  std::size_t propose_resolution_command_size;
  std::uintptr_t construct_propose_resolution_command;
  std::size_t support_resolution_command_size;
  std::uintptr_t construct_support_resolution_command;
  std::size_t oppose_resolution_command_size;
  std::uintptr_t construct_oppose_resolution_command;
  std::size_t withdraw_resolution_command_size;
  std::uintptr_t construct_withdraw_resolution_command;
  std::size_t cast_vote_command_size;
  std::uintptr_t construct_cast_vote_command;
  std::size_t emergency_measure_command_size;
  std::uintptr_t construct_emergency_measure_command;
  StaticDefinitionDatabaseProfile resolution_types;
  ObjectDatabaseProfile resolutions;
};

struct ClaimWarCommandBindings {
  std::size_t add_claim_command_size;
  std::uintptr_t construct_add_claim_command;
  std::size_t remove_claim_command_size;
  std::uintptr_t construct_remove_claim_command;
  ObjectDatabaseProfile galactic_objects;
  std::size_t current_game_date_offset;

  std::size_t set_defender_war_goal_command_size;
  std::uintptr_t construct_set_defender_war_goal_command;
  ObjectDatabaseProfile wars;
  StaticDefinitionDatabaseProfile war_goal_types;
  std::size_t war_goal_size;
  std::uintptr_t construct_war_goal;
  std::uintptr_t destroy_war_goal;
};

struct SpeciesRightsCommandBindings {
  std::size_t set_default_rights_command_size;
  std::uintptr_t construct_set_default_rights_command;
  std::size_t set_species_rights_command_size;
  std::uintptr_t construct_set_species_rights_command;
  ObjectDatabaseProfile species;
  std::uintptr_t country_get_species_rights_module;
  std::uintptr_t get_species_rights_config;
};

struct SituationEspionageCommandBindings {
  std::size_t set_situation_approach_command_size;
  std::uintptr_t construct_set_situation_approach_command;
  ObjectDatabaseProfile situations;

  std::size_t start_espionage_command_size;
  std::uintptr_t construct_start_espionage_command;
  std::size_t cancel_espionage_command_size;
  std::uintptr_t construct_cancel_espionage_command;
  ObjectDatabaseProfile spy_networks;
  ObjectDatabaseProfile espionage_operations;
  StaticDefinitionDatabaseProfile espionage_operation_types;
  std::size_t scope_object_reference_size;
  std::uintptr_t construct_empty_scope_object_reference;
  std::uintptr_t spy_network_get_target;
  std::uintptr_t scope_object_reference_set_country;
  std::uintptr_t destroy_scope_object_reference;
};

// Stellaris' own binary-persistence command factory. The input is the command
// object body beginning with its token (the six-byte reliable-stream record
// envelope is deliberately excluded). This keeps capture-backed actions on the
// same native object, validator, session-post and ownership path as UI actions.
struct SerializedCommandBindings {
  std::uintptr_t create_command_from_bytes;
  std::size_t command_serial_offset;
  std::size_t command_is_valid_vtable_offset;
  std::size_t command_deleting_destructor_vtable_offset;
};

// Reviewed domain queries, not AI updates or UI callbacks. Optional and checked
// only for an explicitly requested research probe; never required by production.
struct ProducerQueryBindings {
  FunctionAnchor can_queue_research{};
  FunctionAnchor find_building_slot{};
  FunctionAnchor create_building_command{};
  FunctionAnchor destroy_building_command_value{};
  std::size_t technology_status_offset = 0;
  std::size_t owned_colonies_data_offset = 0;
  std::size_t owned_colonies_count_offset = 0;
  std::uintptr_t building_types_database = 0;
  std::uintptr_t null_building_instance = 0;
  std::uintptr_t ordinary_buildable_vtable = 0;
  std::size_t building_definition_key_offset = 0;
  FunctionAnchor paused_trigger{};
  std::uintptr_t current_in_game_idler = 0;
  std::uintptr_t in_game_idler_vtable = 0;
  std::size_t idler_paused_offset = 0;
};

struct BuildProfile {
  const char* platform_id;
  const char* game_version;
  const char* build_id;
  CoreBindings core;
  CStringBindings c_string;
  StopResearchBindings stop_research;
  MoveFleetBindings move_fleet;
  AttackFleetBindings attack_fleet;
  MarketTradeBindings market_trade;
  OpenEventBindings open_event;
  DiplomaticActionBindings diplomatic_action;
  GovernanceCommandBindings governance_commands;
  LeaderCommandBindings leader_commands;
  GalacticCommunityCommandBindings galactic_community_commands;
  ClaimWarCommandBindings claim_war_commands;
  SpeciesRightsCommandBindings species_rights_commands;
  SituationEspionageCommandBindings situation_espionage_commands;
  SerializedCommandBindings serialized_command;
  // Exact-build migrations may expose statically recovered actions for
  // validation without granting production Broker access.  Only descriptors
  // that would otherwise claim live_verified are downgraded by this value;
  // paired_capture actions retain their stricter staging state.
  const char* live_verification_override;
  const FunctionAnchor* required_anchors;
  std::size_t required_anchor_count;
  ProducerQueryBindings producer_queries{};
};

// Version-specific profiles remain available to offline tests and evidence
// tooling. Production runtime code uses ActiveStellarisProfile(), keeping
// action handlers independent from the selected exact game build.
const BuildProfile& ActiveStellarisProfile();
const BuildProfile& Stellaris446Profile();
const BuildProfile& Stellaris452Profile();
#if defined(_WIN32)
const BuildProfile& Stellaris446WindowsProfile();
const BuildProfile& Stellaris452WindowsProfile();
#endif

}  // namespace iag::native_runtime
