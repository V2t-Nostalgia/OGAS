#include <array>
#include <cstdint>
#include <iostream>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "iag_native_runtime/action.h"
#include "iag_native_runtime/version_profile.h"

namespace {

bool Expect(bool condition, const char* message) {
  if (!condition) {
    std::cerr << message << '\n';
  }
  return condition;
}

}  // namespace

int main(int argument_count, char** arguments) {
  using iag::native_runtime::FindActionDescriptor;
  using iag::native_runtime::ParseUint32;
  using iag::native_runtime::ParseUint64;
  using iag::native_runtime::ActiveStellarisProfile;
  using iag::native_runtime::ValidateActionDescriptors;
  using iag::native_runtime::BuildToolManifestJson;

  bool ok = true;
  const auto& profile = ActiveStellarisProfile();
  std::string registry_error;
  ok &= Expect(
      ValidateActionDescriptors(registry_error),
      "self-registered action catalog is invalid");
  if (!ok) {
    return 1;
  }
  if (argument_count == 2 &&
      std::string_view(arguments[1]) == "--dump-manifest") {
    std::cout << BuildToolManifestJson(profile) << '\n';
    return 0;
  }
  ok &= Expect(
      profile.serialized_command.command_serial_offset ==
#if defined(_WIN32)
          0,
#else
          0x08,
#endif
      "command serial offset changed");
#if !defined(_WIN32)
  ok &= Expect(
      profile.serialized_command.command_is_valid_vtable_offset == 0x48,
      "semantic IsValid vtable slot changed");
  ok &= Expect(
      profile.open_event.null_open_player_event_instance == 0x572d728,
      "open-event null-object symbol offset changed");
  ok &= Expect(
      profile.open_event.null_open_player_event_instance <
          profile.core.image_size,
      "open-event null-object symbol lies outside the module image");
  ok &= Expect(
      profile.governance_commands.country_has_ascension_perk == 0x23af390,
      "ascension-perk postcondition binding changed");
  ok &= Expect(
      profile.situation_espionage_commands.spy_network_get_target ==
          0x20174f0,
      "spy-network target binding changed");
  ok &= Expect(
      profile.situation_espionage_commands
              .scope_object_reference_set_country == 0x256bcc0,
      "espionage target-scope binding changed");
  ok &= Expect(
      profile.serialized_command.create_command_from_bytes == 0U,
      "4.4.6 capture templates escaped the 4.5.2 fail-closed gate");
#else
  ok &= Expect(
      profile.core.pe_timestamp == 0x6abeaa3fU,
      "Windows 4.5.2 PE timestamp changed");
  ok &= Expect(
      profile.move_fleet.command_vtable == 0x023a7ae0,
      "Windows move command vtable changed");
#endif

  const auto* move = FindActionDescriptor("move_fleet");
  const auto* attack = FindActionDescriptor("attack_fleet");
  const auto* stop = FindActionDescriptor("stop_research");
  const auto* build = FindActionDescriptor("build_building");
  const auto* coordinate = FindActionDescriptor("move_fleet_to_coordinate");
  const auto* start = FindActionDescriptor("start_research");
  const auto* ship_design = FindActionDescriptor("create_ship_design");
  const auto* market_buy = FindActionDescriptor("market_buy_resource");
  const auto* market_sell = FindActionDescriptor("market_sell_resource");
  const auto* select_event = FindActionDescriptor("select_event_option");
  const auto* respond = FindActionDescriptor("respond_to_diplomatic_action");
  const auto* vote = FindActionDescriptor("vote_on_diplomatic_action");
  ok &= Expect(move != nullptr, "move_fleet descriptor missing");
  ok &= Expect(attack != nullptr, "attack_fleet descriptor missing");
  ok &= Expect(stop != nullptr, "stop_research descriptor missing");
  ok &= Expect(build != nullptr, "build_building descriptor missing");
  ok &= Expect(
      coordinate != nullptr, "move_fleet_to_coordinate descriptor missing");
  ok &= Expect(start != nullptr, "start_research descriptor missing");
  ok &= Expect(ship_design != nullptr, "create_ship_design descriptor missing");
  ok &= Expect(market_buy != nullptr, "market_buy_resource descriptor missing");
  ok &= Expect(
      market_sell != nullptr, "market_sell_resource descriptor missing");
  ok &= Expect(select_event != nullptr, "select_event_option descriptor missing");
  ok &= Expect(respond != nullptr, "diplomatic response descriptor missing");
  ok &= Expect(vote != nullptr, "diplomatic vote descriptor missing");

  constexpr std::array<std::string_view, 16> kDiplomaticProposals = {{
      "open_borders",
      "close_borders",
      "establish_rivalry",
      "declare_war",
      "offer_peace",
      "establish_embassy",
      "form_commercial_pact",
      "form_defensive_pact",
      "form_research_agreement",
      "form_migration_pact",
      "invite_to_federation",
      "offer_trade_deal",
      "demand_subjugation",
      "break_migration_pact",
      "break_commercial_pact",
      "insult_country",
  }};
  for (const auto action_type : kDiplomaticProposals) {
    ok &= Expect(
        FindActionDescriptor(action_type) != nullptr,
        "mapped diplomatic proposal descriptor missing");
  }
  for (const auto action_type : {"open_borders", "close_borders"}) {
    const auto* borders = FindActionDescriptor(action_type);
    ok &= Expect(borders != nullptr, "border-action descriptor missing");
    if (borders != nullptr) {
      ok &= Expect(
          borders->verification_state == "live_verified",
          "border action lost live verification status");
    }
  }

  constexpr std::array<std::string_view, 11> kVerifiedDiplomaticProposals = {{
      "establish_rivalry",
      "declare_war",
      "offer_peace",
      "establish_embassy",
      "form_commercial_pact",
      "form_research_agreement",
      "form_migration_pact",
      "offer_trade_deal",
      "break_migration_pact",
      "break_commercial_pact",
      "insult_country",
  }};
  for (const auto action_type : kVerifiedDiplomaticProposals) {
    const auto* descriptor = FindActionDescriptor(action_type);
    ok &= Expect(
        descriptor != nullptr, "verified diplomatic proposal descriptor missing");
    if (descriptor != nullptr) {
      ok &= Expect(
          descriptor->verification_state == "live_verified",
          "verified diplomatic proposal lost live verification status");
    }
  }

  // This is a baseline-presence check, not a fixed registry-size assertion.
  // Third-party actions remain free to self-register and stage under `etc`.
  constexpr std::array<std::string_view, 3> kPairedTypedStateActions = {{
      "join_galactic_community",
      "propose_emergency_measure",
      "set_defender_war_goal",
  }};
  for (const auto action_type : kPairedTypedStateActions) {
    const auto* descriptor = FindActionDescriptor(action_type);
    ok &= Expect(descriptor != nullptr, "typed state-action descriptor missing");
    if (descriptor != nullptr) {
      ok &= Expect(
          descriptor->verification_state == "paired_capture",
          "unverified typed state action escaped paired_capture staging");
    }
  }

  constexpr std::array<std::string_view, 12> kVerifiedTypedStateActions = {{
      "unlock_council_position",
      "respond_to_diplomatic_action",
      "vote_on_diplomatic_action",
      "propose_resolution",
      "support_proposed_resolution",
      "oppose_proposed_resolution",
      "withdraw_proposed_resolution",
      "cast_resolution_vote",
      "add_system_claim",
      "remove_system_claim",
      "set_default_species_rights",
      "set_species_rights",
  }};
  for (const auto action_type : kVerifiedTypedStateActions) {
    const auto* descriptor = FindActionDescriptor(action_type);
    ok &= Expect(descriptor != nullptr, "verified state-action descriptor missing");
    if (descriptor != nullptr) {
      ok &= Expect(
          descriptor->verification_state == "live_verified",
          "verified state action lost live verification status");
    }
  }

  const auto* ascension = FindActionDescriptor("activate_ascension_perk");
  ok &= Expect(ascension != nullptr, "ascension-perk descriptor missing");
  if (ascension != nullptr) {
    ok &= Expect(
        ascension->verification_state == "live_verified",
        "ascension perk lost live verification status");
  }

  const auto* verified_policy = FindActionDescriptor("set_empire_policy");
  ok &= Expect(
      verified_policy != nullptr, "empire-policy descriptor missing");
  if (verified_policy != nullptr) {
    ok &= Expect(
        verified_policy->verification_state == "live_verified",
        "empire policy lost live verification status");
  }

  for (const auto action_type : {"activate_tradition", "set_council_agenda"}) {
    const auto* governance = FindActionDescriptor(action_type);
    ok &= Expect(governance != nullptr, "governance descriptor missing");
    if (governance != nullptr) {
      ok &= Expect(
          governance->verification_state == "live_verified",
          "governance action lost live verification status");
    }
  }

  const auto* situation = FindActionDescriptor("set_situation_approach");
  ok &= Expect(situation != nullptr, "situation-approach descriptor missing");
  if (situation != nullptr) {
    ok &= Expect(
        situation->verification_state == "live_verified",
        "situation approach lost live verification status");
  }

  for (const auto action_type : {"enable_edict", "disable_edict"}) {
    const auto* edict = FindActionDescriptor(action_type);
    ok &= Expect(edict != nullptr, "edict descriptor missing");
    if (edict != nullptr) {
      ok &= Expect(
          edict->verification_state == "live_verified",
          "edict action lost live verification status");
    }
  }

  for (const auto action_type : {"hire_and_assign_leader", "assign_leader"}) {
    const auto* leader_action = FindActionDescriptor(action_type);
    ok &= Expect(leader_action != nullptr, "leader-action descriptor missing");
    if (leader_action != nullptr) {
      ok &= Expect(
          leader_action->verification_state == "live_verified",
          "leader action lost live verification status");
    }
  }

  ok &= Expect(ParseUint32("0") == std::uint32_t{0}, "zero id rejected");
  ok &= Expect(
      ParseUint32("4294967295") == UINT32_MAX, "maximum id rejected");
  ok &= Expect(!ParseUint32("4294967296").has_value(), "overflow id accepted");
  ok &= Expect(!ParseUint32("-1").has_value(), "negative id accepted");
  ok &= Expect(
      ParseUint64("18446744073709551615") == UINT64_MAX,
      "maximum uint64 rejected");
  ok &= Expect(
      !ParseUint64("18446744073709551616").has_value(),
      "overflow uint64 accepted");
  ok &= Expect(!ParseUint64("-1").has_value(), "negative uint64 accepted");

  if (move != nullptr) {
    std::string error;
    const std::vector<std::string> fields = {"888", "47"};
    auto invocation = move->parse(std::span<const std::string>(fields), error);
    ok &= Expect(invocation != nullptr, "valid move_fleet target rejected");
    if (invocation != nullptr) {
      ok &= Expect(
          invocation->TargetEcho() == "888:47", "move target echo changed");
    }
    const std::vector<std::string> invalid = {"888", "not-an-id"};
    invocation = move->parse(std::span<const std::string>(invalid), error);
    ok &= Expect(invocation == nullptr, "invalid move_fleet target accepted");
  }

  if (attack != nullptr) {
    std::string error;
    const std::vector<std::string> fields = {"888", "220"};
    auto invocation = attack->parse(std::span<const std::string>(fields), error);
    ok &= Expect(invocation != nullptr, "valid attack_fleet target rejected");
    if (invocation != nullptr) {
      ok &= Expect(
          invocation->TargetEcho() == "888:220",
          "attack target echo changed");
    }
    const std::vector<std::string> invalid = {"888", "not-an-id"};
    invocation = attack->parse(std::span<const std::string>(invalid), error);
    ok &= Expect(invocation == nullptr, "invalid attack_fleet target accepted");
  }

  if (stop != nullptr) {
    std::string error;
    const std::vector<std::string> fields = {"tech_shields_2"};
    auto invocation = stop->parse(std::span<const std::string>(fields), error);
    ok &= Expect(invocation != nullptr, "valid stop_research target rejected");
    if (invocation != nullptr) {
      ok &= Expect(
          invocation->TargetEcho() == "tech_shields_2",
          "research target echo changed");
    }
  }

  if (build != nullptr) {
    std::string error;
    const std::vector<std::string> fields = {
        "1", "2", "3", "4", "building_foundry_1"};
    auto invocation = build->parse(std::span<const std::string>(fields), error);
    ok &= Expect(invocation != nullptr, "valid captured building target rejected");
    const std::vector<std::string> incomplete = {
        "1", "2", "3", "4"};
    invocation = build->parse(
        std::span<const std::string>(incomplete), error);
    ok &= Expect(
        invocation == nullptr, "incomplete captured building target accepted");
  }

  if (coordinate != nullptr) {
    std::string error;
    const std::vector<std::string> fields = {"7", "-123", "456", "9"};
    auto invocation = coordinate->parse(
        std::span<const std::string>(fields), error);
    ok &= Expect(
        invocation != nullptr, "valid captured coordinate target rejected");
    const std::vector<std::string> invalid = {"7", "not-int64", "456", "9"};
    invocation = coordinate->parse(
        std::span<const std::string>(invalid), error);
    ok &= Expect(
        invocation == nullptr, "invalid captured coordinate target accepted");
  }

  if (market_buy != nullptr) {
    ok &= Expect(
        market_buy->verification_state == "live_verified",
        "market buy lost live verification status");
    std::string error;
    const std::vector<std::string> fields = {"energy", "3"};
    auto invocation = market_buy->parse(
        std::span<const std::string>(fields), error);
    ok &= Expect(invocation != nullptr, "valid market target rejected");
    const std::vector<std::string> invalid = {"energy", "0"};
    invocation = market_buy->parse(
        std::span<const std::string>(invalid), error);
    ok &= Expect(invocation == nullptr, "zero market lot count accepted");
  }

  if (market_sell != nullptr) {
    ok &= Expect(
        market_sell->verification_state == "live_verified",
        "market sell lost live verification status");
  }

  if (select_event != nullptr) {
    ok &= Expect(
        select_event->verification_state == "live_verified",
        "event selection lost live verification status");
    std::string error;
    const std::vector<std::string> fields = {"41", "2"};
    auto invocation = select_event->parse(
        std::span<const std::string>(fields), error);
    ok &= Expect(invocation != nullptr, "valid event selection rejected");
    const std::vector<std::string> invalid = {"41", "not-an-index"};
    invocation = select_event->parse(
        std::span<const std::string>(invalid), error);
    ok &= Expect(invocation == nullptr, "invalid event selection accepted");
  }

  if (respond != nullptr) {
    std::string error;
    const std::vector<std::string> fields = {
        "18446744073709551615", "1"};
    auto invocation = respond->parse(
        std::span<const std::string>(fields), error);
    ok &= Expect(invocation != nullptr, "valid uint64 diplomatic id rejected");
  }

  if (vote != nullptr) {
    std::string error;
    const std::vector<std::string> invalid = {"55", "maybe"};
    auto invocation = vote->parse(
        std::span<const std::string>(invalid), error);
    ok &= Expect(invocation == nullptr, "invalid diplomatic vote accepted");
  }

  const auto* policy = FindActionDescriptor("set_empire_policy");
  if (policy != nullptr) {
    std::string error;
    const std::vector<std::string> fields = {
        "economic_policy", "economic_policy_military"};
    auto invocation = policy->parse(
        std::span<const std::string>(fields), error);
    ok &= Expect(invocation != nullptr, "valid typed policy target rejected");
    const std::vector<std::string> incomplete = {"economic_policy"};
    invocation = policy->parse(
        std::span<const std::string>(incomplete), error);
    ok &= Expect(invocation == nullptr, "incomplete policy target accepted");
  }

  const auto* assign_leader = FindActionDescriptor("assign_leader");
  if (assign_leader != nullptr) {
    std::string error;
    const std::vector<std::string> council = {
        "17", "council_position", "3", "1"};
    auto invocation = assign_leader->parse(
        std::span<const std::string>(council), error);
    ok &= Expect(invocation != nullptr, "typed council assignment rejected");
    const std::vector<std::string> missing_slot = {
        "17", "council_position", "3"};
    invocation = assign_leader->parse(
        std::span<const std::string>(missing_slot), error);
    ok &= Expect(
        invocation == nullptr, "council assignment without slot accepted");
  }

  const auto* join_community =
      FindActionDescriptor("join_galactic_community");
  if (join_community != nullptr) {
    std::string error;
    const std::vector<std::string> no_fields;
    auto invocation = join_community->parse(
        std::span<const std::string>(no_fields), error);
    ok &= Expect(invocation != nullptr, "targetless community join rejected");
  }

  const auto* cast_vote = FindActionDescriptor("cast_resolution_vote");
  if (cast_vote != nullptr) {
    std::string error;
    const std::vector<std::string> fields = {"27", "abstain"};
    auto invocation = cast_vote->parse(
        std::span<const std::string>(fields), error);
    ok &= Expect(invocation != nullptr, "typed resolution vote rejected");
    const std::vector<std::string> invalid = {"27", "present"};
    invocation = cast_vote->parse(
        std::span<const std::string>(invalid), error);
    ok &= Expect(invocation == nullptr, "unknown resolution vote accepted");
  }

  const auto* species_rights = FindActionDescriptor("set_species_rights");
  if (species_rights != nullptr) {
    std::string error;
    const std::vector<std::string> fields = {"31", "42"};
    auto invocation = species_rights->parse(
        std::span<const std::string>(fields), error);
    ok &= Expect(invocation != nullptr, "typed species-rights target rejected");
  }

  const auto* start_espionage =
      FindActionDescriptor("start_espionage_operation");
  if (start_espionage != nullptr) {
    ok &= Expect(
        start_espionage->verification_state == "live_verified",
        "espionage start lost live verification status");
    std::string error;
    const std::vector<std::string> fields = {
        "11", "operation_gather_information"};
    auto invocation = start_espionage->parse(
        std::span<const std::string>(fields), error);
    ok &= Expect(invocation != nullptr, "typed espionage target rejected");
  }
  const auto* cancel_espionage =
      FindActionDescriptor("cancel_espionage_operation");
  ok &= Expect(cancel_espionage != nullptr, "espionage cancel descriptor missing");
  if (cancel_espionage != nullptr) {
    ok &= Expect(
        cancel_espionage->verification_state == "live_verified",
        "espionage cancel lost live verification status");
  }

  const auto* open_borders = FindActionDescriptor("open_borders");
  if (open_borders != nullptr) {
    std::string error;
    const std::vector<std::string> fields = {"16777226"};
    auto invocation = open_borders->parse(
        std::span<const std::string>(fields), error);
    ok &= Expect(invocation != nullptr, "valid country proposal rejected");
    if (invocation != nullptr) {
      ok &= Expect(
          invocation->TargetEcho() == "16777226",
          "country proposal target echo changed");
    }
  }

  const auto* offer_peace = FindActionDescriptor("offer_peace");
  if (offer_peace != nullptr) {
    std::string error;
    const std::vector<std::string> fields = {"7", "19", "status_quo"};
    auto invocation = offer_peace->parse(
        std::span<const std::string>(fields), error);
    ok &= Expect(invocation != nullptr, "valid peace offer rejected");
    const std::vector<std::string> invalid = {"7", "19", "total_victory"};
    invocation = offer_peace->parse(
        std::span<const std::string>(invalid), error);
    ok &= Expect(invocation == nullptr, "unknown peace offer kind accepted");
  }

  const auto* offer_trade = FindActionDescriptor("offer_trade_deal");
  if (offer_trade != nullptr) {
    std::string error;
    const std::vector<std::string> fields = {"7", "offer", "energy", "500"};
    auto invocation = offer_trade->parse(
        std::span<const std::string>(fields), error);
    ok &= Expect(invocation != nullptr, "valid trade deal rejected");
    const std::vector<std::string> invalid = {"7", "swap", "energy", "500"};
    invocation = offer_trade->parse(
        std::span<const std::string>(invalid), error);
    ok &= Expect(invocation == nullptr, "unknown trade direction accepted");
  }

  ok &= Expect(
      FindActionDescriptor("unknown_action") == nullptr,
      "unknown action descriptor accepted");
  const std::string manifest = BuildToolManifestJson(profile);
  ok &= Expect(
      manifest.find("\"application_id\":\"fleet_operations\"") !=
          std::string::npos,
      "fleet Application assignment missing from manifest");
  ok &= Expect(
      manifest.find("\"name\":\"destination_system_id\"") !=
          std::string::npos,
      "move parameter schema missing from manifest");
#if !defined(_WIN32)
  ok &= Expect(
      manifest.find("\"action_type\":\"declare_war\"") !=
          std::string::npos,
      "mapped diplomatic proposal missing from Linux manifest");
  ok &= Expect(
      manifest.find("\"type\":\"uint64\"") != std::string::npos,
      "uint64 parameter schema missing from Linux manifest");
  ok &= Expect(
      manifest.find("\"application_id\":\"research_strategy\"") !=
          std::string::npos,
      "research Application assignment missing from manifest");
  ok &= Expect(
      manifest.find("\"action_type\":\"build_building\"") ==
          std::string::npos,
      "4.4.6 capture-backed action leaked into 4.5.2 Linux manifest");
  ok &= Expect(
      manifest.find("\"verification_state\":\"paired_capture\"") !=
          std::string::npos,
      "staged typed verification state missing from manifest");
  ok &= Expect(
      manifest.find("\"verification_state\":\"build_validation_pending\"") !=
          std::string::npos,
      "current-build validation gate missing from Linux manifest");
  ok &= Expect(
      manifest.find("\"verification_state\":\"live_verified\"") ==
          std::string::npos,
      "pre-upgrade live evidence leaked into 4.5.2 Linux manifest");
  ok &= Expect(
      manifest.find("\"action_type\":\"set_empire_policy\"") !=
          std::string::npos,
      "typed governance action missing from Linux manifest");
  ok &= Expect(
      manifest.find("\"action_type\":\"cancel_espionage_operation\"") !=
          std::string::npos,
      "typed espionage action missing from Linux manifest");
#else
  ok &= Expect(
      manifest.find("\"verification_state\":\"build_validation_pending\"") !=
          std::string::npos,
      "current-build validation gate missing from Windows manifest");
  ok &= Expect(
      manifest.find("\"verification_state\":\"live_verified\"") ==
          std::string::npos,
      "pre-upgrade live evidence leaked into 4.5.2 Windows manifest");
  ok &= Expect(
      manifest.find("\"action_type\":\"stop_research\"") ==
          std::string::npos,
      "unsupported Windows research action leaked into manifest");
  ok &= Expect(
      manifest.find("\"action_type\":\"build_building\"") ==
          std::string::npos,
      "unsupported Windows capture action leaked into manifest");
  ok &= Expect(
      manifest.find("\"action_type\":\"set_empire_policy\"") ==
          std::string::npos,
      "unsupported Windows typed state action leaked into manifest");
#endif
  return ok ? 0 : 1;
}
