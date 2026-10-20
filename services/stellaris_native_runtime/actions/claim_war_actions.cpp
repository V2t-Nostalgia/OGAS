#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <utility>
#include <vector>

#include "iag_native_runtime/action.h"
#include "iag_native_runtime/game_api.h"
#include "native_command_support.h"

namespace iag::native_runtime {
namespace {

using action_support::CommonBindingsSupported;
using action_support::ConstructValidatedCommand;
using action_support::CStringBindingsSupported;
using action_support::PendingSaveInvocation;

using AddClaimCtorFn =
    void (*)(void*, const void*, const void*, int, const void*);
using RemoveClaimCtorFn = void (*)(void*, const void*, const void*, int);
using WarGoalCtorFn = void (*)(void*, const void*);
using WarGoalDtorFn = void (*)(void*);
using SetDefenderWarGoalCtorFn =
    void (*)(void*, std::uint32_t, std::uint32_t, const void*);

class ClaimInvocation final : public PendingSaveInvocation {
 public:
  ClaimInvocation(std::uint32_t system_id, int claim_count, bool add)
      : system_id_(system_id), claim_count_(claim_count), add_(add) {}

  [[nodiscard]] std::string_view action_type() const noexcept override {
    return add_ ? "add_system_claim" : "remove_system_claim";
  }

  [[nodiscard]] std::string TargetEcho() const override {
    return std::to_string(system_id_) + ":" + std::to_string(claim_count_);
  }

  [[nodiscard]] PrepareResult Prepare(
      const GameApi& game,
      std::uint32_t country_id,
      const void* local_country) override {
    const auto& bindings = game.profile().claim_war_commands;
    const void* system =
        game.ResolvePdxObject(bindings.galactic_objects, system_id_);
    if (system == nullptr) {
      return PrepareResult::Rejected("unknown_galactic_object_id");
    }
    if (add_) {
      const void* game_state = game.CurrentGameState();
      if (game_state == nullptr) {
        return PrepareResult::Failed("current_game_state_unavailable");
      }
      const void* current_date =
          static_cast<const unsigned char*>(game_state) +
          bindings.current_game_date_offset;
      return ConstructValidatedCommand(
          game, country_id, bindings.add_claim_command_size, [&](void* command) {
            game.FunctionAt<AddClaimCtorFn>(bindings.construct_add_claim_command)(
                command,
                local_country,
                system,
                claim_count_,
                current_date);
          });
    }
    return ConstructValidatedCommand(
        game,
        country_id,
        bindings.remove_claim_command_size,
        [&](void* command) {
          game.FunctionAt<RemoveClaimCtorFn>(
              bindings.construct_remove_claim_command)(
              command, local_country, system, claim_count_);
        });
  }

 private:
  std::uint32_t system_id_;
  int claim_count_;
  bool add_;
};

class DefenderWarGoalInvocation final : public PendingSaveInvocation {
 public:
  DefenderWarGoalInvocation(std::uint32_t war_id, std::string war_goal_type_key)
      : war_id_(war_id), war_goal_type_key_(std::move(war_goal_type_key)) {}

  [[nodiscard]] std::string_view action_type() const noexcept override {
    return "set_defender_war_goal";
  }

  [[nodiscard]] std::string TargetEcho() const override {
    return std::to_string(war_id_) + ":" + war_goal_type_key_;
  }

  [[nodiscard]] PrepareResult Prepare(
      const GameApi& game,
      std::uint32_t country_id,
      const void*) override {
    const auto& bindings = game.profile().claim_war_commands;
    const void* war = game.ResolvePdxObject(bindings.wars, war_id_);
    if (war == nullptr) {
      return PrepareResult::Rejected("unknown_war_id");
    }
    const void* war_goal_type = game.ResolveStaticDefinition(
        bindings.war_goal_types, war_goal_type_key_);
    if (war_goal_type == nullptr) {
      return PrepareResult::Rejected("unknown_war_goal_type_key");
    }

    std::vector<std::byte> war_goal(bindings.war_goal_size);
    game.FunctionAt<WarGoalCtorFn>(bindings.construct_war_goal)(
        war_goal.data(), war_goal_type);
    PrepareResult result = ConstructValidatedCommand(
        game,
        country_id,
        bindings.set_defender_war_goal_command_size,
        [&](void* command) {
          game.FunctionAt<SetDefenderWarGoalCtorFn>(
              bindings.construct_set_defender_war_goal_command)(
              command, country_id, war_id_, war_goal.data());
        });
    game.FunctionAt<WarGoalDtorFn>(bindings.destroy_war_goal)(war_goal.data());
    return result;
  }

 private:
  std::uint32_t war_id_;
  std::string war_goal_type_key_;
};

std::unique_ptr<ActionInvocation> ParseClaim(
    std::span<const std::string> fields,
    std::string& error_detail,
    bool add) {
  if (fields.size() != 2U) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto system_id = ParseUint32(fields[0]);
  const auto count = ParseUint32(fields[1]);
  if (!system_id.has_value() || !count.has_value() || *count == 0U ||
      *count > 0x7fffffffU) {
    error_detail = "invalid_claim_target";
    return nullptr;
  }
  return std::make_unique<ClaimInvocation>(
      *system_id, static_cast<int>(*count), add);
}

std::unique_ptr<ActionInvocation> ParseAddClaim(
    std::span<const std::string> fields,
    std::string& error_detail) {
  return ParseClaim(fields, error_detail, true);
}

std::unique_ptr<ActionInvocation> ParseRemoveClaim(
    std::span<const std::string> fields,
    std::string& error_detail) {
  return ParseClaim(fields, error_detail, false);
}

std::unique_ptr<ActionInvocation> ParseDefenderWarGoal(
    std::span<const std::string> fields,
    std::string& error_detail) {
  if (fields.size() != 2U || !IsSemanticToken(fields[1], 160U)) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto war_id = ParseUint32(fields[0]);
  if (!war_id.has_value()) {
    error_detail = "invalid_war_id";
    return nullptr;
  }
  return std::make_unique<DefenderWarGoalInvocation>(*war_id, fields[1]);
}

bool ClaimsSupported(const BuildProfile& profile) noexcept {
  const auto& value = profile.claim_war_commands;
  return CommonBindingsSupported(profile) && value.add_claim_command_size != 0U &&
         value.construct_add_claim_command != 0U &&
         value.remove_claim_command_size != 0U &&
         value.construct_remove_claim_command != 0U &&
         value.galactic_objects.database_instance != 0U &&
         value.current_game_date_offset != 0U;
}

bool DefenderWarGoalSupported(const BuildProfile& profile) noexcept {
  const auto& value = profile.claim_war_commands;
  return CommonBindingsSupported(profile) && CStringBindingsSupported(profile) &&
         value.set_defender_war_goal_command_size != 0U &&
         value.construct_set_defender_war_goal_command != 0U &&
         value.wars.database_instance != 0U &&
         value.war_goal_types.database_instance != 0U &&
         value.war_goal_size != 0U && value.construct_war_goal != 0U &&
         value.destroy_war_goal != 0U;
}

constexpr std::array<ActionParameterDescriptor, 2> kClaimParameters = {{
    {
        .name = "system_id",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Current galactic-system object identifier.",
        .minimum = 0,
        .maximum = UINT32_MAX,
    },
    {
        .name = "claim_count",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Positive number of claim levels to add or remove.",
        .minimum = 1,
        .maximum = 0x7fffffffU,
    },
}};

constexpr std::array<ActionParameterDescriptor, 2> kWarGoalParameters = {{
    {
        .name = "war_id",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Current war object identifier in which this country is defender.",
        .minimum = 0,
        .maximum = UINT32_MAX,
    },
    {
        .name = "war_goal_type_key",
        .type = ActionParameterType::kString,
        .required = true,
        .description = "Stable legal defender war-goal type key.",
        .maximum_length = 160,
    },
}};

const ActionDescriptor kAddClaimDescriptor = {
    .action_type = "add_system_claim",
    .action_version = 1,
    .application_id = "fleet_operations",
    .description = "Add one or more legal claim levels to a galactic system.",
    .risk_class = "state_change",
    .verification_state = "live_verified",
    .parameters = kClaimParameters,
    .parse = &ParseAddClaim,
    .supported = &ClaimsSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kAddClaimRegistration{
    kAddClaimDescriptor};

const ActionDescriptor kRemoveClaimDescriptor = {
    .action_type = "remove_system_claim",
    .action_version = 1,
    .application_id = "fleet_operations",
    .description = "Remove one or more existing claim levels from a galactic system.",
    .risk_class = "state_change",
    .verification_state = "live_verified",
    .parameters = kClaimParameters,
    .parse = &ParseRemoveClaim,
    .supported = &ClaimsSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kRemoveClaimRegistration{
    kRemoveClaimDescriptor};

const ActionDescriptor kDefenderWarGoalDescriptor = {
    .action_type = "set_defender_war_goal",
    .action_version = 1,
    .application_id = "fleet_operations",
    .description = "Set the legal defender war goal for one active war.",
    .risk_class = "irreversible_state_change",
    .verification_state = "paired_capture",
    .parameters = kWarGoalParameters,
    .parse = &ParseDefenderWarGoal,
    .supported = &DefenderWarGoalSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration
    kDefenderWarGoalRegistration{kDefenderWarGoalDescriptor};

}  // namespace
}  // namespace iag::native_runtime
