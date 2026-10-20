#include "iag_native_runtime/version_profile.h"

#if defined(_WIN32)

#include <array>

namespace iag::native_runtime {
namespace {

constexpr std::array<unsigned char, 14> kGameIdlerIdlePrefix = {
    0x48, 0x8b, 0xc4, 0x88, 0x50, 0x10, 0x55,
    0x53, 0x56, 0x57, 0x41, 0x54, 0x41, 0x55,
};
constexpr std::array<unsigned char, 16> kPostCommandPrefix = {
    0x48, 0x89, 0x5c, 0x24, 0x08, 0x48, 0x89, 0x6c,
    0x24, 0x10, 0x48, 0x89, 0x74, 0x24, 0x18, 0x57,
};
constexpr std::array<unsigned char, 12> kMoveIsValidPrefix = {
    0x48, 0x89, 0x5c, 0x24, 0x08, 0x48,
    0x89, 0x74, 0x24, 0x10, 0x57, 0x48,
};
constexpr std::array<unsigned char, 12> kCalcFtlPrefix = {
    0x48, 0x89, 0x5c, 0x24, 0x08, 0x48,
    0x89, 0x6c, 0x24, 0x10, 0x48, 0x89,
};
constexpr std::array<unsigned char, 6> kMoveTokenPrefix = {
    0xb8, 0x55, 0x2c, 0x00, 0x00, 0xc3,
};

constexpr std::array<FunctionAnchor, 5> kRequiredAnchors = {{
    {"CGameIdler::Idle", 0x00332ef0, kGameIdlerIdlePrefix.data(),
     kGameIdlerIdlePrefix.size()},
    {"PostCommandToSession", 0x005f88a0, kPostCommandPrefix.data(),
     kPostCommandPrefix.size()},
    {"CFleetFlyToCoordinatesCommand::IsValid", 0x00a56e40,
     kMoveIsValidPrefix.data(), kMoveIsValidPrefix.size()},
    {"CGalacticObject::CalcFTLPointWith", 0x0086dc40,
     kCalcFtlPrefix.data(), kCalcFtlPrefix.size()},
    {"CFleetFlyToCoordinatesCommand::GetToken", 0x0091d520,
     kMoveTokenPrefix.data(), kMoveTokenPrefix.size()},
}};

const BuildProfile kProfile = {
    .platform_id = "windows-x64",
    .game_version = "Stellaris 4.5.2 (3270), Steam build 25664273",
    .build_id =
        "sha256:400df27c82ddc845aa9dce79bd468d81f18f060d299cd263e3afa93aef4f7a83",
    .core = {
        .game_idler_idle = 0x00332ef0,
        .post_command_to_session = 0x005f88a0,
        .current_game_state = 0,
        .get_local_observed = 0,
        .country_id_offset = 0,
        .hook_length = 14,
        .pe_timestamp = 0x6abeaa3fU,
        .image_size = 0x037f2000U,
        .text_rva = 0x1000,
        .text_size = 0x02214690,
    },
    .c_string = {},
    .stop_research = {},
    .move_fleet = {
        .command_size = 0x58,
        .celestial_coordinate_size = 0x28,
        .construct_command = 0,
        .command_is_valid = 0x00a56e40,
        .calculate_ftl_point_with = 0x0086dc40,
        .fleet_get_controller_ref = 0,
        .fleet_get_coordinate_origin = 0,
        .fleet_count_orders = 0,
        .fleet_has_player_movement_order = 0,
        .fleets = {
            .database_instance = 0x031129d8,
            .null_object_instance = 0x03112eb8,
            .object_id_offset = 0x30,
        },
        .galactic_objects = {
            .database_instance = 0x03114e30,
            .null_object_instance = 0x031146e8,
            .object_id_offset = 0x08,
        },
        .command_vtable = 0x023a7ae0,
        .clone_command = 0x0091d450,
        .celestial_coordinate_vtable = 0x02344df0,
        .fleet_coordinate_provider_offset = 0x38,
        .fleet_executing_order_offset = 0,
        .order_type_offset = 0,
        .move_order_type = 0,
    },
    .attack_fleet = {},
    .market_trade = {},
    .open_event = {},
    .diplomatic_action = {},
    .governance_commands = {},
    .leader_commands = {},
    .galactic_community_commands = {},
    .claim_war_commands = {},
    .species_rights_commands = {},
    .situation_espionage_commands = {},
    .serialized_command = {},
    .live_verification_override = "build_validation_pending",
    .required_anchors = kRequiredAnchors.data(),
    .required_anchor_count = kRequiredAnchors.size(),
};

}  // namespace

const BuildProfile& Stellaris452WindowsProfile() { return kProfile; }
const BuildProfile& Stellaris452Profile() { return kProfile; }
const BuildProfile& ActiveStellarisProfile() { return kProfile; }

}  // namespace iag::native_runtime

#endif
