#include <array>
#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <utility>

#include "iag_native_runtime/action.h"
#include "iag_native_runtime/game_api.h"
#include "native_command_support.h"

namespace iag::native_runtime {
namespace {

using action_support::CommonBindingsSupported;
using action_support::ConstructValidatedCommand;
using action_support::CStringBindingsSupported;
using action_support::NativeCString;
using action_support::PendingSaveInvocation;

enum class GovernanceKind {
  kSetPolicy,
  kEnableEdict,
  kDisableEdict,
  kActivateTradition,
  kActivateAscensionPerk,
  kSetCouncilAgenda,
  kUnlockCouncilPosition,
};

using SetPolicyCtorFn =
    void (*)(void*, const void*, const void*, const std::uint32_t*);
using EdictCtorFn = void (*)(void*, const void*, const std::uint32_t*);
using CountryDefinitionCtorFn = void (*)(void*, const void*, const void*);
using UnlockCouncilPositionCtorFn = void (*)(void*, std::uint32_t, const void*);
using PolicyGroupGetOptionFn = const void* (*)(const void*, const void*);
using CountryHasAscensionPerkFn = bool (*)(const void*, const void*);

std::string_view ActionType(GovernanceKind kind) {
  switch (kind) {
    case GovernanceKind::kSetPolicy:
      return "set_empire_policy";
    case GovernanceKind::kEnableEdict:
      return "enable_edict";
    case GovernanceKind::kDisableEdict:
      return "disable_edict";
    case GovernanceKind::kActivateTradition:
      return "activate_tradition";
    case GovernanceKind::kActivateAscensionPerk:
      return "activate_ascension_perk";
    case GovernanceKind::kSetCouncilAgenda:
      return "set_council_agenda";
    case GovernanceKind::kUnlockCouncilPosition:
      return "unlock_council_position";
  }
  return "unknown_governance_action";
}

class GovernanceInvocation final : public PendingSaveInvocation {
 public:
  GovernanceInvocation(GovernanceKind kind, std::string key, std::string option)
      : kind_(kind), key_(std::move(key)), option_(std::move(option)) {}

  [[nodiscard]] std::string_view action_type() const noexcept override {
    return ActionType(kind_);
  }

  [[nodiscard]] std::string TargetEcho() const override {
    return option_.empty() ? key_ : key_ + ":" + option_;
  }

  [[nodiscard]] PrepareResult Prepare(
      const GameApi& game,
      std::uint32_t country_id,
      const void* local_country) override {
    const auto& bindings = game.profile().governance_commands;
    switch (kind_) {
      case GovernanceKind::kSetPolicy: {
        const void* group =
            game.ResolveStaticDefinition(bindings.policy_groups, key_);
        if (group == nullptr) {
          return PrepareResult::Rejected("unknown_policy_group_key");
        }
        NativeCString option_key(game, option_);
        const void* option = game.FunctionAt<PolicyGroupGetOptionFn>(
            bindings.policy_group_get_option)(group, option_key.get());
        const void* null_option = *reinterpret_cast<void* const*>(
            game.Address(bindings.null_policy_option_instance));
        if (option == nullptr || option == null_option) {
          return PrepareResult::Rejected("unknown_policy_option_key");
        }
        return ConstructValidatedCommand(
            game,
            country_id,
            bindings.set_policy_command_size,
            [&](void* command) {
              game.FunctionAt<SetPolicyCtorFn>(
                  bindings.construct_set_policy_command)(
                  command, group, option, &country_id);
            });
      }
      case GovernanceKind::kEnableEdict:
      case GovernanceKind::kDisableEdict:
      case GovernanceKind::kSetCouncilAgenda: {
        NativeCString key(game, key_);
        const bool agenda = kind_ == GovernanceKind::kSetCouncilAgenda;
        const std::uintptr_t constructor = agenda
            ? bindings.construct_set_council_agenda_command
            : (kind_ == GovernanceKind::kEnableEdict
                   ? bindings.construct_enable_edict_command
                   : bindings.construct_disable_edict_command);
        const std::size_t size = agenda ? bindings.council_agenda_command_size
                                        : bindings.edict_command_size;
        return ConstructValidatedCommand(
            game, country_id, size, [&](void* command) {
              game.FunctionAt<EdictCtorFn>(constructor)(
                  command, key.get(), &country_id);
            });
      }
      case GovernanceKind::kActivateTradition:
      case GovernanceKind::kActivateAscensionPerk: {
        const auto& database = kind_ == GovernanceKind::kActivateTradition
                                   ? bindings.traditions
                                   : bindings.ascension_perks;
        const void* tradition = game.ResolveStaticDefinition(database, key_);
        if (tradition == nullptr) {
          return PrepareResult::Rejected("unknown_tradition_or_perk_key");
        }
        const std::uintptr_t constructor =
            kind_ == GovernanceKind::kActivateTradition
                ? bindings.construct_activate_tradition_command
                : bindings.construct_activate_ascension_perk_command;
        return ConstructValidatedCommand(
            game,
            country_id,
            bindings.tradition_command_size,
            [&](void* command) {
              game.FunctionAt<CountryDefinitionCtorFn>(constructor)(
                  command, local_country, tradition);
            });
      }
      case GovernanceKind::kUnlockCouncilPosition: {
        const void* position =
            game.ResolveStaticDefinition(bindings.council_positions, key_);
        if (position == nullptr) {
          return PrepareResult::Rejected("unknown_council_position_key");
        }
        return ConstructValidatedCommand(
            game,
            country_id,
            bindings.unlock_council_position_command_size,
            [&](void* command) {
              game.FunctionAt<UnlockCouncilPositionCtorFn>(
                  bindings.construct_unlock_council_position_command)(
                  command, country_id, position);
            });
      }
    }
    return PrepareResult::Failed("unsupported_governance_action_kind");
  }

  [[nodiscard]] std::optional<RuntimeResult> Verify(
      const GameApi& game,
      std::uint32_t country_id,
      const void* local_country) override {
    if (kind_ != GovernanceKind::kActivateAscensionPerk) {
      return PendingSaveInvocation::Verify(game, country_id, local_country);
    }
    NativeCString key(game, key_);
    if (game.FunctionAt<CountryHasAscensionPerkFn>(
            game.profile().governance_commands.country_has_ascension_perk)(
            local_country, key.get())) {
      return RuntimeResult{
          "confirmed", "native_postcondition_ascension_perk_active"};
    }
    return std::nullopt;
  }

  [[nodiscard]] std::string_view TimeoutDetail() const noexcept override {
    if (kind_ == GovernanceKind::kActivateAscensionPerk) {
      return "native_submit_timeout_waiting_for_ascension_perk";
    }
    return PendingSaveInvocation::TimeoutDetail();
  }

 private:
  GovernanceKind kind_;
  std::string key_;
  std::string option_;
};

template <GovernanceKind Kind>
std::unique_ptr<ActionInvocation> ParseSingleKey(
    std::span<const std::string> fields,
    std::string& error_detail) {
  if (fields.size() != 1U || !IsSemanticToken(fields[0], 160U)) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  return std::make_unique<GovernanceInvocation>(Kind, fields[0], std::string{});
}

std::unique_ptr<ActionInvocation> ParsePolicy(
    std::span<const std::string> fields,
    std::string& error_detail) {
  if (fields.size() != 2U || !IsSemanticToken(fields[0], 160U) ||
      !IsSemanticToken(fields[1], 160U)) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  return std::make_unique<GovernanceInvocation>(
      GovernanceKind::kSetPolicy, fields[0], fields[1]);
}

bool GovernanceBaseSupported(const BuildProfile& profile) noexcept {
  return CommonBindingsSupported(profile) && CStringBindingsSupported(profile);
}

bool PolicySupported(const BuildProfile& profile) noexcept {
  const auto& value = profile.governance_commands;
  return GovernanceBaseSupported(profile) && value.set_policy_command_size != 0U &&
         value.construct_set_policy_command != 0U &&
         value.policy_groups.database_instance != 0U &&
         value.policy_group_get_option != 0U &&
         value.null_policy_option_instance != 0U;
}

bool EdictsSupported(const BuildProfile& profile) noexcept {
  const auto& value = profile.governance_commands;
  return GovernanceBaseSupported(profile) && value.edict_command_size != 0U &&
         value.construct_enable_edict_command != 0U &&
         value.construct_disable_edict_command != 0U;
}

bool TraditionsSupported(const BuildProfile& profile) noexcept {
  const auto& value = profile.governance_commands;
  return GovernanceBaseSupported(profile) && value.tradition_command_size != 0U &&
         value.construct_activate_tradition_command != 0U &&
         value.traditions.database_instance != 0U;
}

bool AscensionPerksSupported(const BuildProfile& profile) noexcept {
  const auto& value = profile.governance_commands;
  return GovernanceBaseSupported(profile) && value.tradition_command_size != 0U &&
         value.construct_activate_ascension_perk_command != 0U &&
         value.country_has_ascension_perk != 0U &&
         value.ascension_perks.database_instance != 0U;
}

bool AgendaSupported(const BuildProfile& profile) noexcept {
  const auto& value = profile.governance_commands;
  return GovernanceBaseSupported(profile) &&
         value.council_agenda_command_size != 0U &&
         value.construct_set_council_agenda_command != 0U;
}

bool CouncilPositionSupported(const BuildProfile& profile) noexcept {
  const auto& value = profile.governance_commands;
  return GovernanceBaseSupported(profile) &&
         value.unlock_council_position_command_size != 0U &&
         value.construct_unlock_council_position_command != 0U &&
         value.council_positions.database_instance != 0U;
}

constexpr std::array<ActionParameterDescriptor, 2> kPolicyParameters = {{
    {
        .name = "policy_group_key",
        .type = ActionParameterType::kString,
        .required = true,
        .description = "Stable policy-group key from current country state.",
        .maximum_length = 160,
    },
    {
        .name = "policy_option_key",
        .type = ActionParameterType::kString,
        .required = true,
        .description = "Stable option key belonging to the selected policy group.",
        .maximum_length = 160,
    },
}};

constexpr std::array<ActionParameterDescriptor, 1> kKeyParameter = {{
    {
        .name = "definition_key",
        .type = ActionParameterType::kString,
        .required = true,
        .description = "Stable game-definition key from a current legal candidate.",
        .maximum_length = 160,
    },
}};

#define IAG_GOVERNANCE_DESCRIPTOR(                                           \
    Variable, Action, Kind, App, Description, Risk, Verification, Probe)     \
  const ActionDescriptor Variable = {                                                \
      .action_type = Action,                                                         \
      .action_version = 1,                                                           \
      .application_id = App,                                                         \
      .description = Description,                                                    \
      .risk_class = Risk,                                                            \
      .verification_state = Verification,                                            \
      .parameters = kKeyParameter,                                                   \
      .parse = &ParseSingleKey<Kind>,                                                \
      .supported = &Probe,                                                           \
  };                                                                                 \
  IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration Variable##Registration{    \
      Variable}

const ActionDescriptor kPolicyDescriptor = {
    .action_type = "set_empire_policy",
    .action_version = 1,
    .application_id = "etc",
    .description = "Select one legal option in an empire policy group.",
    .risk_class = "state_change",
    .verification_state = "live_verified",
    .parameters = kPolicyParameters,
    .parse = &ParsePolicy,
    .supported = &PolicySupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kPolicyRegistration{
    kPolicyDescriptor};

IAG_GOVERNANCE_DESCRIPTOR(
    kEnableEdictDescriptor,
    "enable_edict",
    GovernanceKind::kEnableEdict,
    "etc",
    "Enable one legal empire edict by definition key.",
    "state_change",
    "live_verified",
    EdictsSupported);
IAG_GOVERNANCE_DESCRIPTOR(
    kDisableEdictDescriptor,
    "disable_edict",
    GovernanceKind::kDisableEdict,
    "etc",
    "Disable one currently active empire edict by definition key.",
    "state_change",
    "live_verified",
    EdictsSupported);
IAG_GOVERNANCE_DESCRIPTOR(
    kTraditionDescriptor,
    "activate_tradition",
    GovernanceKind::kActivateTradition,
    "etc",
    "Adopt one currently legal tradition.",
    "irreversible_state_change",
    "live_verified",
    TraditionsSupported);
const ActionDescriptor kAscensionPerkDescriptor = {
    .action_type = "activate_ascension_perk",
    .action_version = 1,
    .application_id = "etc",
    .description = "Select one currently legal ascension perk.",
    .risk_class = "irreversible_state_change",
    .verification_state = "live_verified",
    .parameters = kKeyParameter,
    .parse = &ParseSingleKey<GovernanceKind::kActivateAscensionPerk>,
    .supported = &AscensionPerksSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration
    kAscensionPerkRegistration{kAscensionPerkDescriptor};
IAG_GOVERNANCE_DESCRIPTOR(
    kCouncilAgendaDescriptor,
    "set_council_agenda",
    GovernanceKind::kSetCouncilAgenda,
    "etc",
    "Select and start one legal council agenda.",
    "state_change",
    "live_verified",
    AgendaSupported);
IAG_GOVERNANCE_DESCRIPTOR(
    kCouncilPositionDescriptor,
    "unlock_council_position",
    GovernanceKind::kUnlockCouncilPosition,
    "etc",
    "Unlock one legal council position by definition key.",
    "irreversible_state_change",
    "live_verified",
    CouncilPositionSupported);

#undef IAG_GOVERNANCE_DESCRIPTOR

}  // namespace
}  // namespace iag::native_runtime
