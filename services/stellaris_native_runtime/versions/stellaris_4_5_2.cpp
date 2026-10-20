#include "iag_native_runtime/version_profile.h"

#if !defined(_WIN32)

#include <array>

namespace iag::native_runtime {
namespace {

constexpr std::array<unsigned char, 17> kGameIdlerIdlePrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55, 0x41, 0x54,
    0x53, 0x48, 0x81, 0xec, 0xa8, 0x01, 0x00, 0x00,
};
constexpr unsigned char kPausedTriggerPrefix[] = {
    0x48, 0x8d, 0x05, 0x39, 0x95, 0xb4, 0x01, 0x48, 0x8b,
    0x00, 0x80, 0xb8, 0x94, 0x05, 0x00, 0x00, 0x00,
};
constexpr std::array<unsigned char, 16> kPostCommandPrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41, 0x54, 0x53,
    0x89, 0xf5, 0x49, 0x89, 0xff, 0x4c, 0x8d, 0x25,
};
constexpr std::array<unsigned char, 16> kCommandCtorPrefix = {
    0xb8, 0xff, 0xff, 0xff, 0xff, 0x48, 0x89, 0x47,
    0x08, 0xc7, 0x47, 0x10, 0x00, 0x00, 0xff, 0xff,
};
constexpr std::array<unsigned char, 16> kIsResearchingPrefix = {
    0x8b, 0x57, 0x5c, 0x85, 0xd2, 0x7e, 0x2b, 0x4c,
    0x8b, 0x47, 0x50, 0x49, 0x8d, 0x40, 0x18, 0x31,
};
constexpr std::array<unsigned char, 16> kAccessTechnologyModulePrefix = {
    0x53, 0x48, 0x89, 0xfb, 0x48, 0x8b, 0xbf, 0x68,
    0x2a, 0x00, 0x00, 0x48, 0x81, 0xc3, 0x68, 0x2a,
};
constexpr std::array<unsigned char, 16> kMoveFleetIsValidPrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55, 0x41,
    0x54, 0x53, 0x50, 0x49, 0x89, 0xff, 0x4c, 0x8d,
};
constexpr std::array<unsigned char, 16> kCalcFtlPointWithPrefix = {
    0x41, 0x56, 0x53, 0x50, 0x48, 0x89, 0xf3, 0x49,
    0x89, 0xfe, 0x48, 0x8b, 0x02, 0x48, 0x89, 0xd7,
};
constexpr std::array<unsigned char, 16> kAttackFleetCtorPrefix = {
    0x44, 0x8a, 0x54, 0x24, 0x08, 0xb8, 0xff, 0xff,
    0xff, 0xff, 0x48, 0x89, 0x47, 0x08, 0xc7, 0x47,
};
constexpr std::array<unsigned char, 16> kAttackFleetIsValidPrefix = {
    0x41, 0x56, 0x53, 0x50, 0x48, 0x89, 0xfb, 0xbf,
    0x58, 0x00, 0x00, 0x00, 0xe8, 0xbf, 0x25, 0x54,
};
constexpr std::array<unsigned char, 16> kFleetGetExecutingOrderPrefix = {
    0x48, 0x8b, 0xbf, 0xc8, 0x02, 0x00, 0x00, 0xe9,
    0x34, 0x09, 0x07, 0x00, 0x0f, 0x1f, 0x40, 0x00,
};
constexpr std::array<unsigned char, 16> kGetResourcePrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55, 0x41,
    0x54, 0x53, 0x50, 0x44, 0x8b, 0x7f, 0x14, 0x45,
};
constexpr std::array<unsigned char, 16> kSelectEventCtorPrefix = {
    0x41, 0x56, 0x53, 0x50, 0x49, 0x89, 0xd6, 0x48,
    0x89, 0xfb, 0xb8, 0xff, 0xff, 0xff, 0xff, 0x48,
};
constexpr std::array<unsigned char, 16> kGetOpenEventPrefix = {
    0x48, 0x63, 0x8f, 0x8c, 0x01, 0x00, 0x00, 0x48,
    0x85, 0xc9, 0x74, 0x29, 0x48, 0x8b, 0x97, 0x80,
};
constexpr std::array<unsigned char, 16> kEventOptionFirstKeyPrefix = {
    0x53, 0x48, 0x89, 0xfb, 0x48, 0x81, 0xc6, 0xb8,
    0x04, 0x00, 0x00, 0xe8, 0x60, 0x11, 0xfe, 0xff,
};
constexpr std::array<unsigned char, 16> kCanRespondPrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55, 0x41,
    0x54, 0x53, 0x48, 0x83, 0xec, 0x68, 0x48, 0x85,
};
constexpr std::array<unsigned char, 16> kHasAscensionPerkPrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55, 0x41,
    0x54, 0x53, 0x48, 0x83, 0xec, 0x18, 0x48, 0x89,
};
constexpr std::array<unsigned char, 16> kSpyNetworkGetTargetPrefix = {
    0x48, 0x8b, 0x05, 0x91, 0xb0, 0x71, 0x03, 0x48,
    0x85, 0xc0, 0x74, 0x27, 0x8b, 0x4f, 0x1c, 0x89,
};
constexpr std::array<unsigned char, 16> kScopeSetCountryPrefix = {
    0x8b, 0x46, 0x20, 0x48, 0xc7, 0x47, 0x08, 0x04,
    0x00, 0x00, 0x00, 0x89, 0x47, 0x10, 0x0f, 0x57,
};

constexpr std::array<FunctionAnchor, 21> kRequiredAnchors = {{
    {"CGameIdler::Idle", 0x1afd770, kGameIdlerIdlePrefix.data(),
     kGameIdlerIdlePrefix.size()},
    {"PostCommandToSession", 0x1b02540, kPostCommandPrefix.data(),
     kPostCommandPrefix.size()},
    {"CCancelResearchTechnologyCommand::CCancelResearchTechnologyCommand",
     0x22a4330, kCommandCtorPrefix.data(), kCommandCtorPrefix.size()},
    {"CTechnologyStatus::IsResearching", 0x20abe60,
     kIsResearchingPrefix.data(), kIsResearchingPrefix.size()},
    {"CCountry::AccessTechnologyModule", 0x23a8270,
     kAccessTechnologyModulePrefix.data(), kAccessTechnologyModulePrefix.size()},
    {"CFleetFlyToCoordinatesCommand::CFleetFlyToCoordinatesCommand",
     0x22d5240, kCommandCtorPrefix.data(), kCommandCtorPrefix.size()},
    {"CFleetFlyToCoordinatesCommand::IsValid", 0x22d5570,
     kMoveFleetIsValidPrefix.data(), kMoveFleetIsValidPrefix.size()},
    {"CGalacticObject::CalcFTLPointWith", 0x260d110,
     kCalcFtlPointWithPrefix.data(), kCalcFtlPointWithPrefix.size()},
    {"CFollowFleetCommand::CFollowFleetCommand", 0x22e3810,
     kAttackFleetCtorPrefix.data(), kAttackFleetCtorPrefix.size()},
    {"CFollowFleetCommand::IsValid", 0x22e3950,
     kAttackFleetIsValidPrefix.data(), kAttackFleetIsValidPrefix.size()},
    {"CFleet::GetExecutingOrder", 0x2930c70,
     kFleetGetExecutingOrderPrefix.data(),
     kFleetGetExecutingOrderPrefix.size()},
    {"CMarketBuyResourceCommand::CMarketBuyResourceCommand", 0x43281c0,
     kCommandCtorPrefix.data(), kCommandCtorPrefix.size()},
    {"CStrategicResourceDatabase::GetResource", 0x2076700,
     kGetResourcePrefix.data(), kGetResourcePrefix.size()},
    {"CSelectEventOptionCommand::CSelectEventOptionCommand", 0x255b8a0,
     kSelectEventCtorPrefix.data(), kSelectEventCtorPrefix.size()},
    {"CGameState::GetOpenPlayerEvent", 0x1b49110,
     kGetOpenEventPrefix.data(), kGetOpenEventPrefix.size()},
    {"CEventOption::GetFirstKey", 0x2567120,
     kEventOptionFirstKeyPrefix.data(), kEventOptionFirstKeyPrefix.size()},
    {"CDiploActionRespondCommand::CDiploActionRespondCommand", 0x22c8100,
     kCommandCtorPrefix.data(), kCommandCtorPrefix.size()},
    {"CCountry::CanRespondToDiploAction", 0x2365c30,
     kCanRespondPrefix.data(), kCanRespondPrefix.size()},
    {"CCountry::HasAscensionPerk", 0x23af390,
     kHasAscensionPerkPrefix.data(), kHasAscensionPerkPrefix.size()},
    {"CSpyNetwork::GetTarget", 0x20174f0,
     kSpyNetworkGetTargetPrefix.data(), kSpyNetworkGetTargetPrefix.size()},
    {"CScopeObjectReference::SetCountry", 0x256bcc0,
     kScopeSetCountryPrefix.data(), kScopeSetCountryPrefix.size()},
}};

// Optional research bindings, independently byte-checked on every explicit
// native_domain request. Evidence: producer-validation-prep-4.5.2/static-abi.
constexpr unsigned char kCanQueueResearch[] = {
    0x55,0x41,0x57,0x41,0x56,0x41,0x55,0x41,0x54,0x53,0x50,0x49,0x89,0xd6,0x48,0x89};
constexpr unsigned char kFindBuildingSlot[] = {
    0x55,0x41,0x57,0x41,0x56,0x41,0x55,0x41,0x54,0x53,0x48,0x83,0xec,0x38,0x44,0x89};
constexpr unsigned char kCreateBuildingCommand[] = {
    0x55,0x41,0x57,0x41,0x56,0x41,0x55,0x41,0x54,0x53,0x48,0x83,0xec,0x18,0x4d,0x89};
constexpr unsigned char kDestroyBuildingValue[] = {
    0x48,0x8d,0x05,0xa9,0x0b,0xb9,0x02,0x48,0x89,0x07,0x48,0x8b,0x7f,0x20,0x48,0x85};

const BuildProfile kProfile = {
    .platform_id = "linux-x86_64",
    .game_version = "Stellaris 4.5.2 (3270), Steam build 25664273",
    .build_id = "121ecb516cbc5f1d39917fbcc36620534384e2c2",
    .core = {
        .game_idler_idle = 0x1afd770,
        .post_command_to_session = 0x1b02540,
        .current_game_state = 0x5733568,
        .get_local_observed = 0x1b433b0,
        .country_id_offset = 0x20,
        .hook_length = 17,
        .pe_timestamp = 0,
        .image_size = 0x0626f000U,
        .text_rva = 0x01826a90U,
        .text_size = 0x02d918c2U,
    },
    .c_string = {
        .object_size = 0x30,
        .construct = 0x424e020,
        .destroy = 0x198a620,
        .get_tchar_ptr = 0x424f8b0,
        .get_size = 0x4250220,
    },
    .stop_research = {
        .command_size = 0x28,
        .construct_command = 0x22a4330,
        .command_is_valid = 0x22a4450,
        .is_researching_technology = 0x20abe60,
        .access_technology = 0x2098900,
        .access_technology_module = 0x23a8270,
        .technology_database_instance = 0x572ed20,
        .null_technology_instance = 0x572cc08,
        .technology_status_offset = 0,
    },
    .move_fleet = {
        .command_size = 0x50,
        .celestial_coordinate_size = 0x28,
        .construct_command = 0x22d5240,
        .command_is_valid = 0x22d5570,
        .calculate_ftl_point_with = 0x260d110,
        .fleet_get_controller_ref = 0x2916560,
        .fleet_get_coordinate_origin = 0x2942680,
        .fleet_count_orders = 0x2930a80,
        .fleet_has_player_movement_order = 0x2930ef0,
        .fleets = {
            .database_instance = 0x572d078,
            .null_object_instance = 0x572d080,
            .object_id_offset = 0x30,
        },
        .galactic_objects = {
            .database_instance = 0x572c2a0,
            .null_object_instance = 0x572c2a8,
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
        .construct_command = 0x22e3810,
        .command_is_valid = 0x22e3950,
        .fleet_get_controller_ref = 0x2916560,
        .fleet_get_executing_order = 0x2930c70,
        .follow_fleet_order_vptr = 0x526fa30,
        .order_target_fleet_offset = 0x24,
        .order_attack_offset = 0x50,
        .order_cancelled_offset = 0x51,
        .fleets = {
            .database_instance = 0x572d078,
            .null_object_instance = 0x572d080,
            .object_id_offset = 0x30,
        },
    },
    .market_trade = {
        .command_size = 0x40,
        .construct_buy_command = 0x43281c0,
        .construct_sell_command = 0x4328470,
        .validate_buy_command = 0x4328210,
        .validate_sell_command = 0x43284c0,
        .resource_database_instance = 0x57542a0,
        .null_resource_instance = 0x572c8e8,
        .get_resource = 0x2076700,
    },
    .open_event = {
        .command_size = 0x1a0,
        .construct_select_command = 0x255b8a0,
        .get_open_player_event = 0x1b49110,
        .null_open_player_event_instance = 0x572d728,
        .option_is_allowed = 0x2565d00,
        .option_get_first_key = 0x2567120,
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
        .construct_propose_command = 0x22c7f10,
        .respond_command_size = 0x30,
        .construct_respond_command = 0x22c8100,
        .vote_command_size = 0x30,
        .construct_vote_command = 0x22c8270,
        .can_respond_to_action = 0x2365c30,
        .countries = {
            .database_instance = 0x5732588,
            .null_object_instance = 0x572d218,
            .object_id_offset = 0x20,
        },
        .incoming_actions_data_offset = 0x19d0,
        .incoming_actions_count_offset = 0x19dc,
        .incoming_action_stride = 0x10,
        .incoming_action_pointer_offset = 0x08,
        .action_actor_ref_offset = 0x20,
        .action_recipient_ref_offset = 0x24,
        .action_id_offset = 0x30,
        .action_tag_vtable_offset = 0x78,
        .construct_open_borders_action = 0x2669530,
        .construct_close_borders_action = 0x26689c0,
        .construct_make_rival_action = 0x2666040,
        .construct_create_embassy_action = 0x266ad20,
        .construct_form_commercial_pact_action = 0x265d010,
        .construct_form_defensive_pact_action = 0x26595b0,
        .construct_form_research_agreement_action = 0x265eeb0,
        .construct_form_migration_pact_action = 0x2660ea0,
        .construct_break_migration_pact_action = 0x2662220,
        .construct_break_commercial_pact_action = 0x265e850,
        .construct_insult_action = 0x2667f30,
        .select_war_goal_type = 0x27e8d00,
        .null_war_goal_type_instance = 0x572dea8,
        .construct_war_goal = 0x2146750,
        .destroy_war_goal = 0x21467c0,
        .construct_declare_war_action = 0x2647290,
        .wars = {
            .database_instance = 0x5733a88,
            .null_object_instance = 0x572d3e0,
            .object_id_offset = 0x20,
        },
        .construct_peace_offer = 0x1e3daa0,
        .construct_offer_peace_action = 0x264ac00,
        .construct_invite_to_federation_action = 0x264cfe0,
        .construct_demand_subjugation_action = 0x2681750,
        .construct_abstract_trade_deal_action = 0x26646e0,
        .offer_trade_deal_vtable = 0x525dc70,
        .trade_deal_access_side = 0x20da630,
        .trade_deal_set_resource = 0x20d3610,
    },
    .governance_commands = {
        .set_policy_command_size = 0x38,
        .construct_set_policy_command = 0x22aa0d0,
        .policy_groups = {
            .database_instance = 0x572f028,
            .null_object_instance = 0x572d338,
            .objects_data_offset = 0x50,
            .objects_count_offset = 0x5c,
            .object_key_offset = 0x10,
        },
        .policy_group_get_option = 0x1e57bf0,
        .null_policy_option_instance = 0x572d350,
        .edict_command_size = 0x58,
        .construct_enable_edict_command = 0x22a9220,
        .construct_disable_edict_command = 0x22a9770,
        .tradition_command_size = 0x28,
        .construct_activate_tradition_command = 0x22af740,
        .construct_activate_ascension_perk_command = 0x22af970,
        .country_has_ascension_perk = 0x23af390,
        .traditions = {
            .database_instance = 0x572efe0,
            .null_object_instance = 0x572dd28,
            .objects_data_offset = 0x50,
            .objects_count_offset = 0x5c,
            .object_key_offset = 0x10,
        },
        .ascension_perks = {
            .database_instance = 0x572f110,
            .null_object_instance = 0x572dd28,
            .objects_data_offset = 0x50,
            .objects_count_offset = 0x5c,
            .object_key_offset = 0x10,
        },
        .council_agenda_command_size = 0x58,
        .construct_set_council_agenda_command = 0x22a9c10,
        .unlock_council_position_command_size = 0x28,
        .construct_unlock_council_position_command = 0x22a7070,
        .council_positions = {
            .database_instance = 0x572f138,
            .null_object_instance = 0x572dd88,
            .objects_data_offset = 0x50,
            .objects_count_offset = 0x5c,
            .object_key_offset = 0x10,
        },
    },
    .leader_commands = {
        .hire_and_assign_command_size = 0x38,
        .construct_hire_and_assign_command = 0x22a7a10,
        .assign_command_size = 0x38,
        .construct_assign_command = 0x4325970,
        .leaders = {
            .database_instance = 0x5732978,
            .null_object_instance = 0x572d248,
            .object_id_offset = 0x20,
        },
    },
    .galactic_community_commands = {
        .join_command_size = 0x28,
        .construct_join_command = 0x26da250,
        .propose_resolution_command_size = 0x30,
        .construct_propose_resolution_command = 0x26d7150,
        .support_resolution_command_size = 0x28,
        .construct_support_resolution_command = 0x26d8e10,
        .oppose_resolution_command_size = 0x28,
        .construct_oppose_resolution_command = 0x26d94d0,
        .withdraw_resolution_command_size = 0x28,
        .construct_withdraw_resolution_command = 0x26dbf60,
        .cast_vote_command_size = 0x30,
        .construct_cast_vote_command = 0x26d8720,
        .emergency_measure_command_size = 0x28,
        .construct_emergency_measure_command = 0x26db9f0,
        .resolution_types = {
            .database_instance = 0x572eff0,
            .null_object_instance = 0x572e100,
            .objects_data_offset = 0x50,
            .objects_count_offset = 0x5c,
            .object_key_offset = 0x10,
        },
        .resolutions = {
            .database_instance = 0x5733b00,
            .null_object_instance = 0x572e118,
            .object_id_offset = 0x08,
        },
    },
    .claim_war_commands = {
        .add_claim_command_size = 0x30,
        .construct_add_claim_command = 0x22b0ad0,
        .remove_claim_command_size = 0x28,
        .construct_remove_claim_command = 0x22b1100,
        .galactic_objects = {
            .database_instance = 0x572c2a0,
            .null_object_instance = 0x572c2a8,
            .object_id_offset = 0x08,
        },
        .current_game_date_offset = 0xc0,
        .set_defender_war_goal_command_size = 0x48,
        .construct_set_defender_war_goal_command = 0x22c8440,
        .wars = {
            .database_instance = 0x5733a88,
            .null_object_instance = 0x572d3e0,
            .object_id_offset = 0x20,
        },
        .war_goal_types = {
            .database_instance = 0x572f178,
            .null_object_instance = 0x572dea8,
            .objects_data_offset = 0x50,
            .objects_count_offset = 0x5c,
            .object_key_offset = 0x10,
        },
        .war_goal_size = 0x20,
        .construct_war_goal = 0x2146750,
        .destroy_war_goal = 0x21467c0,
    },
    .species_rights_commands = {
        .set_default_rights_command_size = 0xe8,
        .construct_set_default_rights_command = 0x22b00c0,
        .set_species_rights_command_size = 0xf8,
        .construct_set_species_rights_command = 0x22afb70,
        .species = {
            .database_instance = 0x5732598,
            .null_object_instance = 0x572cc80,
            .object_id_offset = 0x10,
        },
        .country_get_species_rights_module = 0x235ea50,
        .get_species_rights_config = 0x2007020,
    },
    .situation_espionage_commands = {
        .set_situation_approach_command_size = 0x50,
        .construct_set_situation_approach_command = 0x22b40f0,
        .situations = {
            .database_instance = 0x5733a10,
            .null_object_instance = 0x572e4e0,
            .object_id_offset = 0x08,
        },
        .start_espionage_command_size = 0x78,
        .construct_start_espionage_command = 0x4322170,
        .cancel_espionage_command_size = 0x28,
        .construct_cancel_espionage_command = 0x4322f80,
        .spy_networks = {
            .database_instance = 0x5733b28,
            .null_object_instance = 0x572e288,
            .object_id_offset = 0x08,
        },
        .espionage_operations = {
            .database_instance = 0x57339f8,
            .null_object_instance = 0x572e2e8,
            .object_id_offset = 0x08,
        },
        .espionage_operation_types = {
            .database_instance = 0x572f220,
            .null_object_instance = 0x572e2d0,
            .objects_data_offset = 0x50,
            .objects_count_offset = 0x5c,
            .object_key_offset = 0x10,
        },
        .scope_object_reference_size = 0x28,
        .construct_empty_scope_object_reference = 0x256b5b0,
        .spy_network_get_target = 0x20174f0,
        .scope_object_reference_set_country = 0x256bcc0,
        .destroy_scope_object_reference = 0,
    },
    // The 4.4.6 capture bodies contain version-bound token/layout bytes. The
    // common virtual slots remain valid for typed commands, but old captured
    // bodies are deliberately disabled until 4.5.2 fixtures are collected.
    .serialized_command = {
        .create_command_from_bytes = 0,
        .command_serial_offset = 0x08,
        .command_is_valid_vtable_offset = 0x48,
        .command_deleting_destructor_vtable_offset = 0x08,
    },
    .live_verification_override = "build_validation_pending",
    .required_anchors = kRequiredAnchors.data(),
    .required_anchor_count = kRequiredAnchors.size(),
    .producer_queries = {
        .can_queue_research = {"CTechnologyStatus::CanQueueResearch", 0x20afa60, kCanQueueResearch, sizeof(kCanQueueResearch)},
        .find_building_slot = {"NPlanetBuildingUtil::FindBestBuildingSlot", 0x2a7e990, kFindBuildingSlot, sizeof(kFindBuildingSlot)},
        .create_building_command = {"NConstruction::CreateAddBuildableCommand", 0x26d2e90, kCreateBuildingCommand, sizeof(kCreateBuildingCommand)},
        .destroy_building_command_value = {"CAddBuildableToQueueCommand::~value", 0x26d13d0, kDestroyBuildingValue, sizeof(kDestroyBuildingValue)},
        .technology_status_offset = 0x15e0,
        .owned_colonies_data_offset = 0x2690,
        .owned_colonies_count_offset = 0x269c,
        .building_types_database = 0x572edd8,
        .null_building_instance = 0x572e198,
        .ordinary_buildable_vtable = 0x5216908,
        // CBuildableBuilding serializer 0x218323e..0x2183250 reads
        // buildable+8 (CBuildingType*) then +0x10 (CString key).
        .building_definition_key_offset = 0x10,
        // CIsPausedTrigger reads this singleton's +0x594; SetPaused writes it.
        // The CGameIdler::Idle(bool) argument is not the simulation pause state.
        .paused_trigger = {"CIsPausedTrigger::ActualEvaluate", 0x3be98a0, kPausedTriggerPrefix, sizeof(kPausedTriggerPrefix)},
        .current_in_game_idler = 0x5732de0,
        .in_game_idler_vtable = 0x51f74e8,
        .idler_paused_offset = 0x594,
    },
};

}  // namespace

const BuildProfile& Stellaris452Profile() { return kProfile; }
const BuildProfile& ActiveStellarisProfile() { return kProfile; }

}  // namespace iag::native_runtime

#endif
