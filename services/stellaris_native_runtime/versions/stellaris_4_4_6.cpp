#include "iag_native_runtime/version_profile.h"

#include <array>

namespace iag::native_runtime {
namespace {

constexpr std::array<unsigned char, 17> kGameIdlerIdlePrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55, 0x41, 0x54,
    0x53, 0x48, 0x81, 0xec, 0x88, 0x01, 0x00, 0x00,
};
constexpr std::array<unsigned char, 12> kPostCommandPrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x53,
    0x50, 0x89, 0xf5, 0x49, 0x89, 0xff,
};
constexpr std::array<unsigned char, 12> kCancelCtorPrefix = {
    0xb8, 0xff, 0xff, 0xff, 0xff, 0x48,
    0x89, 0x47, 0x08, 0xc7, 0x47, 0x10,
};
constexpr std::array<unsigned char, 12> kIsResearchingPrefix = {
    0x48, 0x89, 0xf8, 0x8b, 0x4f, 0x5c,
    0x85, 0xc9, 0x7e, 0x16, 0x48, 0x8b,
};
constexpr std::array<unsigned char, 16> kMoveFleetCtorPrefix = {
    0xb8, 0xff, 0xff, 0xff, 0xff, 0x48, 0x89, 0x47,
    0x08, 0xc7, 0x47, 0x10, 0x00, 0x00, 0xff, 0xff,
};
constexpr std::array<unsigned char, 12> kMoveFleetIsValidPrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41,
    0x55, 0x41, 0x54, 0x53, 0x50, 0x49,
};
constexpr std::array<unsigned char, 12> kCalcFtlPointWithPrefix = {
    0x41, 0x57, 0x41, 0x56, 0x53, 0x48,
    0x89, 0xf3, 0x49, 0x89, 0xfe, 0x48,
};
constexpr std::array<unsigned char, 12> kAttackFleetCtorPrefix = {
    0x44, 0x8a, 0x54, 0x24, 0x08, 0xb8,
    0xff, 0xff, 0xff, 0xff, 0x48, 0x89,
};
constexpr std::array<unsigned char, 12> kAttackFleetIsValidPrefix = {
    0x41, 0x56, 0x53, 0x50, 0x48, 0x89,
    0xfb, 0xbf, 0x58, 0x00, 0x00, 0x00,
};
constexpr std::array<unsigned char, 12> kFleetGetExecutingOrderPrefix = {
    0x48, 0x8b, 0xbf, 0xc8, 0x02, 0x00,
    0x00, 0xe9, 0xf4, 0xcf, 0x06, 0x00,
};
constexpr std::array<unsigned char, 12> kCreateCommandFromBytesPrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x53,
    0x48, 0x81, 0xec, 0xa8, 0x05, 0x00,
};
constexpr std::array<unsigned char, 12> kMarketBuyCtorPrefix = {
    0xb8, 0xff, 0xff, 0xff, 0xff, 0x48,
    0x89, 0x47, 0x08, 0xc7, 0x47, 0x10,
};
constexpr std::array<unsigned char, 12> kGetResourcePrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41,
    0x55, 0x41, 0x54, 0x53, 0x50, 0x44,
};
constexpr std::array<unsigned char, 12> kSelectEventCtorPrefix = {
    0x41, 0x56, 0x53, 0x50, 0x49, 0x89,
    0xd6, 0x48, 0x89, 0xfb, 0xb8, 0xff,
};
constexpr std::array<unsigned char, 12> kGetOpenEventPrefix = {
    0x48, 0x63, 0x8f, 0x8c, 0x01, 0x00,
    0x00, 0x48, 0x85, 0xc9, 0x74, 0x29,
};
constexpr std::array<unsigned char, 12> kEventOptionFirstKeyPrefix = {
    0x41, 0x57, 0x41, 0x56, 0x41, 0x54,
    0x53, 0x50, 0x48, 0x89, 0xfb, 0x83,
};
constexpr std::array<unsigned char, 12> kDiploRespondCtorPrefix = {
    0xb8, 0xff, 0xff, 0xff, 0xff, 0x48,
    0x89, 0x47, 0x08, 0xc7, 0x47, 0x10,
};
constexpr std::array<unsigned char, 12> kCanRespondToDiploActionPrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41,
    0x54, 0x53, 0x48, 0x83, 0xec, 0x70,
};
constexpr std::array<unsigned char, 12> kHasAscensionPerkPrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41,
    0x55, 0x41, 0x54, 0x53, 0x48, 0x83,
};
constexpr std::array<unsigned char, 12> kSpyNetworkGetTargetPrefix = {
    0x48, 0x8b, 0x05, 0x61, 0x26, 0x7e,
    0x03, 0x48, 0x85, 0xc0, 0x74, 0x27,
};
constexpr std::array<unsigned char, 12> kScopeSetCountryPrefix = {
    0x8b, 0x46, 0x20, 0x48, 0xc7, 0x47,
    0x08, 0x04, 0x00, 0x00, 0x00, 0x89,
};

constexpr std::array<FunctionAnchor, 21> kRequiredAnchors = {{
    {"CGameIdler::Idle", 0x17bd4a0, kGameIdlerIdlePrefix.data(),
     kGameIdlerIdlePrefix.size()},
    {"PostCommandToSession", 0x17c2290, kPostCommandPrefix.data(),
     kPostCommandPrefix.size()},
    {"CCancelResearchCommand::CCancelResearchCommand", 0x1f34680,
     kCancelCtorPrefix.data(), kCancelCtorPrefix.size()},
    {"CTechnologyStatus::IsResearching", 0x1d3adb0,
     kIsResearchingPrefix.data(), kIsResearchingPrefix.size()},
    {"CFleetFlyToCoordinatesCommand::CFleetFlyToCoordinatesCommand", 0x1f64c30,
     kMoveFleetCtorPrefix.data(), kMoveFleetCtorPrefix.size()},
    {"CFleetFlyToCoordinatesCommand::IsValid", 0x1f64f50,
     kMoveFleetIsValidPrefix.data(), kMoveFleetIsValidPrefix.size()},
    {"CGalacticObject::CalcFTLPointWith", 0x229b7a0,
     kCalcFtlPointWithPrefix.data(), kCalcFtlPointWithPrefix.size()},
    {"CFollowFleetCommand::CFollowFleetCommand", 0x1f73000,
     kAttackFleetCtorPrefix.data(), kAttackFleetCtorPrefix.size()},
    {"CFollowFleetCommand::IsValid", 0x1f73140,
     kAttackFleetIsValidPrefix.data(), kAttackFleetIsValidPrefix.size()},
    {"CFleet::GetExecutingOrder", 0x25ae690,
     kFleetGetExecutingOrderPrefix.data(),
     kFleetGetExecutingOrderPrefix.size()},
    {"CreateCommand(bytes)", 0x381c8d0,
     kCreateCommandFromBytesPrefix.data(),
     kCreateCommandFromBytesPrefix.size()},
    {"CMarketBuyResourceCommand::CMarketBuyResourceCommand", 0x3f287d0,
     kMarketBuyCtorPrefix.data(), kMarketBuyCtorPrefix.size()},
    {"CStrategicResourceDatabase::GetResource", 0x1d07f70,
     kGetResourcePrefix.data(), kGetResourcePrefix.size()},
    {"CSelectEventOptionCommand::CSelectEventOptionCommand", 0x21e8450,
     kSelectEventCtorPrefix.data(), kSelectEventCtorPrefix.size()},
    {"CGameState::GetOpenPlayerEvent", 0x18127a0,
     kGetOpenEventPrefix.data(), kGetOpenEventPrefix.size()},
    {"CEventOption::GetFirstKey", 0x21f4110,
     kEventOptionFirstKeyPrefix.data(), kEventOptionFirstKeyPrefix.size()},
    {"CDiploActionRespondCommand::CDiploActionRespondCommand", 0x1f57eb0,
     kDiploRespondCtorPrefix.data(), kDiploRespondCtorPrefix.size()},
    {"CCountry::CanRespondToDiploAction", 0x1ff2440,
     kCanRespondToDiploActionPrefix.data(),
     kCanRespondToDiploActionPrefix.size()},
    {"CCountry::HasAscensionPerk", 0x2038130,
     kHasAscensionPerkPrefix.data(), kHasAscensionPerkPrefix.size()},
    {"CSpyNetwork::GetTarget", 0x1caea50,
     kSpyNetworkGetTargetPrefix.data(), kSpyNetworkGetTargetPrefix.size()},
    {"CScopeObjectReference::SetCountry", 0x21f93f0,
     kScopeSetCountryPrefix.data(), kScopeSetCountryPrefix.size()},
}};

const BuildProfile kProfile = {
    .platform_id = "linux-x86_64",
    .game_version = "Stellaris 4.4.6 (fdde)",
    .build_id = "c6969e60fd81d738948222a94c0b5a0841abbffc",
    .core = {
        .game_idler_idle = 0x17bd4a0,
        .post_command_to_session = 0x17c2290,
        .current_game_state = 0x5492098,
        .get_local_observed = 0x180be30,
        .country_id_offset = 0x20,
        .hook_length = 17,
        .pe_timestamp = 0,
        .image_size = 0x05fcd000U,
        .text_rva = 0x01503000U,
        .text_size = 0x02cf2dd1U,
    },
    .c_string = {
        .object_size = 0x30,
        .construct = 0x3e4a740,
        .destroy = 0x16584b0,
        .get_tchar_ptr = 0x3e4be60,
        .get_size = 0x3e4c870,
    },
    .stop_research = {
        .command_size = 0x28,
        .construct_command = 0x1f34680,
        .command_is_valid = 0x1f34790,
        .is_researching_technology = 0x1d3adb0,
        .access_technology = 0x1d284b0,
        .access_technology_module = 0,
        .technology_database_instance = 0x548d890,
        .null_technology_instance = 0x548b828,
        .technology_status_offset = 0x1830,
    },
    .move_fleet = {
        .command_size = 0x50,
        .celestial_coordinate_size = 0x28,
        .construct_command = 0x1f64c30,
        .command_is_valid = 0x1f64f50,
        .calculate_ftl_point_with = 0x229b7a0,
        .fleet_get_controller_ref = 0x2595480,
        .fleet_get_coordinate_origin = 0x25bd960,
        .fleet_count_orders = 0x25ae480,
        .fleet_has_player_movement_order = 0x25ae8f0,
        .fleets = {
            .database_instance = 0x548bc10,
            .null_object_instance = 0x548bc18,
            .object_id_offset = 0x30,
        },
        .galactic_objects = {
            .database_instance = 0x548aec0,
            .null_object_instance = 0x548aec8,
            .object_id_offset = 0x08,
        },
        .command_vtable = 0,
        .clone_command = 0,
        .celestial_coordinate_vtable = 0,
        .fleet_coordinate_provider_offset = 0,
        .fleet_executing_order_offset = 0,
        .order_type_offset = 0,
        .move_order_type = 0,
    },
    .attack_fleet = {
        .command_size = 0x28,
        .construct_command = 0x1f73000,
        .command_is_valid = 0x1f73140,
        .fleet_get_controller_ref = 0x2595480,
        .fleet_get_executing_order = 0x25ae690,
        .follow_fleet_order_vptr = 0x43cfc00,
        .order_target_fleet_offset = 0x24,
        .order_attack_offset = 0x50,
        .order_cancelled_offset = 0x51,
        .fleets = {
            .database_instance = 0x548bc10,
            .null_object_instance = 0x548bc18,
            .object_id_offset = 0x30,
        },
    },
    .market_trade = {
        .command_size = 0x40,
        .construct_buy_command = 0x3f287d0,
        .construct_sell_command = 0x3f28a60,
        .validate_buy_command = 0x3f28810,
        .validate_sell_command = 0x3f28aa0,
        .resource_database_instance = 0x54b22b0,
        .null_resource_instance = 0x548b508,
        .get_resource = 0x1d07f70,
    },
    .open_event = {
        .command_size = 0x1a0,
        .construct_select_command = 0x21e8450,
        .get_open_player_event = 0x18127a0,
        .null_open_player_event_instance = 0x548c2c8,
        .option_is_allowed = 0x21f2a00,
        .option_get_first_key = 0x21f4110,
        .open_events_data_offset = 0x180,
        .open_events_count_offset = 0x18c,
        .open_event_handle_offset = 0x08,
        .open_event_scope_offset = 0x10,
        .open_event_id_offset = 0x180,
        .open_event_country_ref_offset = 0x184,
        .event_definition_id_offset = 0x08,
        .event_title_key_offset = 0x110,
        .event_options_offset = 0x5e0,
        .event_options_data_offset = 0x08,
        .event_options_count_offset = 0x14,
    },
    .diplomatic_action = {
        .propose_command_size = 0x28,
        .construct_propose_command = 0x1f57cc0,
        .respond_command_size = 0x30,
        .construct_respond_command = 0x1f57eb0,
        .vote_command_size = 0x30,
        .construct_vote_command = 0x1f58010,
        .can_respond_to_action = 0x1ff2440,
        .countries = {
            .database_instance = 0x54910b8,
            .null_object_instance = 0x548bdc8,
            .object_id_offset = 0x20,
        },
        .incoming_actions_data_offset = 0x1b60,
        .incoming_actions_count_offset = 0x1b6c,
        .incoming_action_stride = 0x10,
        .incoming_action_pointer_offset = 0x08,
        .action_actor_ref_offset = 0x20,
        .action_recipient_ref_offset = 0x24,
        .action_id_offset = 0x30,
        .action_tag_vtable_offset = 0x78,
        .construct_open_borders_action = 0x22f55a0,
        .construct_close_borders_action = 0x22f4af0,
        .construct_make_rival_action = 0x22f23a0,
        .construct_create_embassy_action = 0x22f6c70,
        .construct_form_commercial_pact_action = 0x22e9fe0,
        .construct_form_defensive_pact_action = 0x22e6580,
        .construct_form_research_agreement_action = 0x22ebe60,
        .construct_form_migration_pact_action = 0x22edbb0,
        .construct_break_migration_pact_action = 0x22eed20,
        .construct_break_commercial_pact_action = 0x22eb720,
        .construct_insult_action = 0x22f4030,
        .select_war_goal_type = 0x2474740,
        .null_war_goal_type_instance = 0x548ca18,
        .construct_war_goal = 0x1dcd990,
        .destroy_war_goal = 0x1dcda10,
        .construct_declare_war_action = 0x22d5470,
        .wars = {
            .database_instance = 0x5492550,
            .null_object_instance = 0x548bf78,
            .object_id_offset = 0x20,
        },
        .construct_peace_offer = 0x1b0ae80,
        .construct_offer_peace_action = 0x22d8400,
        .construct_invite_to_federation_action = 0x22da080,
        .construct_demand_subjugation_action = 0x230ee10,
        .construct_abstract_trade_deal_action = 0x22f1380,
        .offer_trade_deal_vtable = 0x4395f98,
        .trade_deal_access_side = 0x1d672c0,
        .trade_deal_set_resource = 0x1d60e60,
    },
    .governance_commands = {
        .set_policy_command_size = 0x38,
        .construct_set_policy_command = 0x1f3a580,
        .policy_groups = {
            .database_instance = 0x548db90,
            .null_object_instance = 0x548bee8,
            .objects_data_offset = 0x50,
            .objects_count_offset = 0x5c,
            .object_key_offset = 0x10,
        },
        .policy_group_get_option = 0x1b23f70,
        .null_policy_option_instance = 0x548bf00,
        .edict_command_size = 0x58,
        .construct_enable_edict_command = 0x1f39790,
        .construct_disable_edict_command = 0x1f39ca0,
        .tradition_command_size = 0x28,
        .construct_activate_tradition_command = 0x1f3fd00,
        .construct_activate_ascension_perk_command = 0x1f3ff50,
        .country_has_ascension_perk = 0x2038130,
        .traditions = {
            .database_instance = 0x548db48,
            .null_object_instance = 0x548c898,
            .objects_data_offset = 0x50,
            .objects_count_offset = 0x5c,
            .object_key_offset = 0x10,
        },
        .ascension_perks = {
            .database_instance = 0x548dc70,
            .null_object_instance = 0x548c898,
            .objects_data_offset = 0x50,
            .objects_count_offset = 0x5c,
            .object_key_offset = 0x10,
        },
        .council_agenda_command_size = 0x58,
        .construct_set_council_agenda_command = 0x1f3a120,
        .unlock_council_position_command_size = 0x28,
        .construct_unlock_council_position_command = 0x1f376f0,
        .council_positions = {
            .database_instance = 0x548dc98,
            .null_object_instance = 0x548c8f8,
            .objects_data_offset = 0x50,
            .objects_count_offset = 0x5c,
            .object_key_offset = 0x10,
        },
    },
    .leader_commands = {
        .hire_and_assign_command_size = 0x38,
        .construct_hire_and_assign_command = 0x1f38050,
        .assign_command_size = 0x38,
        .construct_assign_command = 0x3f25c70,
        .leaders = {
            .database_instance = 0x54914a8,
            .null_object_instance = 0x548bdf8,
            .object_id_offset = 0x20,
        },
    },
    .galactic_community_commands = {
        .join_command_size = 0x28,
        .construct_join_command = 0x23692c0,
        .propose_resolution_command_size = 0x30,
        .construct_propose_resolution_command = 0x2366250,
        .support_resolution_command_size = 0x28,
        .construct_support_resolution_command = 0x2368180,
        .oppose_resolution_command_size = 0x28,
        .construct_oppose_resolution_command = 0x2368740,
        .withdraw_resolution_command_size = 0x28,
        .construct_withdraw_resolution_command = 0x236ade0,
        .cast_vote_command_size = 0x30,
        .construct_cast_vote_command = 0x2367a10,
        .emergency_measure_command_size = 0x28,
        .construct_emergency_measure_command = 0x236a830,
        .resolution_types = {
            .database_instance = 0x548db58,
            .null_object_instance = 0x548cc70,
            .objects_data_offset = 0x50,
            .objects_count_offset = 0x5c,
            .object_key_offset = 0x10,
        },
        .resolutions = {
            .database_instance = 0x54925c8,
            .null_object_instance = 0x548cc88,
            .object_id_offset = 0x08,
        },
    },
    .claim_war_commands = {
        .add_claim_command_size = 0x30,
        .construct_add_claim_command = 0x1f411b0,
        .remove_claim_command_size = 0x28,
        .construct_remove_claim_command = 0x1f41860,
        .galactic_objects = {
            .database_instance = 0x548aec0,
            .null_object_instance = 0x548aec8,
            .object_id_offset = 0x08,
        },
        .current_game_date_offset = 0xc0,
        .set_defender_war_goal_command_size = 0x48,
        .construct_set_defender_war_goal_command = 0x1f581f0,
        .wars = {
            .database_instance = 0x5492550,
            .null_object_instance = 0x548bf78,
            .object_id_offset = 0x20,
        },
        .war_goal_types = {
            .database_instance = 0x548dcd8,
            .null_object_instance = 0x548ca18,
            .objects_data_offset = 0x50,
            .objects_count_offset = 0x5c,
            .object_key_offset = 0x10,
        },
        .war_goal_size = 0x20,
        .construct_war_goal = 0x1dcd990,
        .destroy_war_goal = 0x1dcda10,
    },
    .species_rights_commands = {
        .set_default_rights_command_size = 0xe8,
        .construct_set_default_rights_command = 0x1f406b0,
        .set_species_rights_command_size = 0xf8,
        .construct_set_species_rights_command = 0x1f40150,
        .species = {
            .database_instance = 0x54910c0,
            .null_object_instance = 0x548b8a0,
            .object_id_offset = 0x10,
        },
        .country_get_species_rights_module = 0x1fec830,
        .get_species_rights_config = 0x1c9e720,
    },
    .situation_espionage_commands = {
        .set_situation_approach_command_size = 0x50,
        .construct_set_situation_approach_command = 0x1f44740,
        .situations = {
            .database_instance = 0x54924d0,
            .null_object_instance = 0x548d050,
            .object_id_offset = 0x08,
        },
        .start_espionage_command_size = 0x78,
        .construct_start_espionage_command = 0x3f22350,
        .cancel_espionage_command_size = 0x28,
        .construct_cancel_espionage_command = 0x3f23060,
        .spy_networks = {
            .database_instance = 0x54925f0,
            .null_object_instance = 0x548cdf8,
            .object_id_offset = 0x08,
        },
        .espionage_operations = {
            .database_instance = 0x54924b8,
            .null_object_instance = 0x548ce58,
            .object_id_offset = 0x08,
        },
        .espionage_operation_types = {
            .database_instance = 0x548dd80,
            .null_object_instance = 0x548ce40,
            .objects_data_offset = 0x50,
            .objects_count_offset = 0x5c,
            .object_key_offset = 0x10,
        },
        .scope_object_reference_size = 0x28,
        .construct_empty_scope_object_reference = 0x21f8bd0,
        .spy_network_get_target = 0x1caea50,
        .scope_object_reference_set_country = 0x21f93f0,
        .destroy_scope_object_reference = 0x2208c60,
    },
    .serialized_command = {
        .create_command_from_bytes = 0x381c8d0,
        .command_serial_offset = 0x08,
        .command_is_valid_vtable_offset = 0x48,
        .command_deleting_destructor_vtable_offset = 0x08,
    },
    .live_verification_override = nullptr,
    .required_anchors = kRequiredAnchors.data(),
    .required_anchor_count = kRequiredAnchors.size(),
};

}  // namespace

const BuildProfile& Stellaris446Profile() { return kProfile; }

}  // namespace iag::native_runtime
