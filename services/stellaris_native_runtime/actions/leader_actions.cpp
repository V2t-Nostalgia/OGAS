#include <array>
#include <cstdint>
#include <limits>
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
using action_support::PendingSaveInvocation;

struct LeaderLocation {
  std::uint8_t type = 0;
  std::uint8_t padding[3]{};
  std::int32_t envoy_assignment = 0;
  std::uint32_t object_id = UINT32_MAX;
  std::int32_t position_index = -1;
};
static_assert(sizeof(LeaderLocation) == 0x10);

using HireAndAssignCtorFn = void (*)(
    void*, const void*, const std::uint32_t*, const LeaderLocation*, bool);
using AssignCtorFn = void (*)(void*, const void*, const LeaderLocation*, bool);

std::optional<std::uint8_t> ParseLocationType(std::string_view value) {
  if (value == "colony") {
    return std::uint8_t{1};
  }
  if (value == "ship") {
    return std::uint8_t{2};
  }
  if (value == "army") {
    return std::uint8_t{3};
  }
  if (value == "country") {
    return std::uint8_t{4};
  }
  if (value == "council_position") {
    return std::uint8_t{9};
  }
  if (value == "patron_relation") {
    return std::uint8_t{10};
  }
  return std::nullopt;
}

class LeaderAssignmentInvocation final : public PendingSaveInvocation {
 public:
  LeaderAssignmentInvocation(
      std::uint32_t leader_id,
      std::string location_kind,
      LeaderLocation location,
      bool hire)
      : leader_id_(leader_id),
        location_kind_(std::move(location_kind)),
        location_(location),
        hire_(hire) {}

  [[nodiscard]] std::string_view action_type() const noexcept override {
    return hire_ ? "hire_and_assign_leader" : "assign_leader";
  }

  [[nodiscard]] std::string TargetEcho() const override {
    std::string echo = std::to_string(leader_id_) + ":" + location_kind_ +
                       ":" + std::to_string(location_.object_id);
    if (location_.type == 9U) {
      echo += ":" + std::to_string(location_.position_index);
    }
    return echo;
  }

  [[nodiscard]] PrepareResult Prepare(
      const GameApi& game,
      std::uint32_t country_id,
      const void* local_country) override {
    const auto& bindings = game.profile().leader_commands;
    const void* leader = game.ResolvePdxObject(bindings.leaders, leader_id_);
    if (leader == nullptr) {
      return PrepareResult::Rejected("unknown_leader_id");
    }
    if (hire_) {
      return ConstructValidatedCommand(
          game,
          country_id,
          bindings.hire_and_assign_command_size,
          [&](void* command) {
            game.FunctionAt<HireAndAssignCtorFn>(
                bindings.construct_hire_and_assign_command)(
                command, local_country, &leader_id_, &location_, false);
          });
    }
    return ConstructValidatedCommand(
        game, country_id, bindings.assign_command_size, [&](void* command) {
          game.FunctionAt<AssignCtorFn>(bindings.construct_assign_command)(
              command, leader, &location_, false);
        });
  }

 private:
  std::uint32_t leader_id_;
  std::string location_kind_;
  LeaderLocation location_;
  bool hire_;
};

std::unique_ptr<ActionInvocation> ParseAssignment(
    std::span<const std::string> fields,
    std::string& error_detail,
    bool hire) {
  if (fields.size() < 3U || fields.size() > 4U) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto leader_id = ParseUint32(fields[0]);
  const auto location_type = ParseLocationType(fields[1]);
  const auto location_object_id = ParseUint32(fields[2]);
  if (!leader_id.has_value() || !location_type.has_value() ||
      !location_object_id.has_value()) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  LeaderLocation location;
  location.type = *location_type;
  location.object_id = *location_object_id;
  if (*location_type == 9U) {
    if (fields.size() != 4U || fields[3].empty()) {
      error_detail = "council_position_index_required";
      return nullptr;
    }
    const auto position = ParseUint32(fields[3]);
    if (!position.has_value() ||
        *position > static_cast<std::uint32_t>(
                        std::numeric_limits<std::int32_t>::max())) {
      error_detail = "invalid_council_position_index";
      return nullptr;
    }
    location.position_index = static_cast<std::int32_t>(*position);
  } else if (fields.size() == 4U && !fields[3].empty()) {
    error_detail = "position_index_not_valid_for_location_kind";
    return nullptr;
  }
  return std::make_unique<LeaderAssignmentInvocation>(
      *leader_id, fields[1], location, hire);
}

std::unique_ptr<ActionInvocation> ParseHireAndAssign(
    std::span<const std::string> fields,
    std::string& error_detail) {
  return ParseAssignment(fields, error_detail, true);
}

std::unique_ptr<ActionInvocation> ParseAssign(
    std::span<const std::string> fields,
    std::string& error_detail) {
  return ParseAssignment(fields, error_detail, false);
}

bool HireAndAssignSupported(const BuildProfile& profile) noexcept {
  const auto& value = profile.leader_commands;
  return CommonBindingsSupported(profile) &&
         value.hire_and_assign_command_size != 0U &&
         value.construct_hire_and_assign_command != 0U &&
         value.leaders.database_instance != 0U;
}

bool AssignSupported(const BuildProfile& profile) noexcept {
  const auto& value = profile.leader_commands;
  return CommonBindingsSupported(profile) && value.assign_command_size != 0U &&
         value.construct_assign_command != 0U &&
         value.leaders.database_instance != 0U;
}

constexpr std::array<ActionParameterDescriptor, 4> kParameters = {{
    {
        .name = "leader_id",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Current leader object identifier from a legal candidate.",
        .minimum = 0,
        .maximum = UINT32_MAX,
    },
    {
        .name = "location_kind",
        .type = ActionParameterType::kString,
        .required = true,
        .description = "One of colony, ship, army, country, council_position, or patron_relation.",
        .maximum_length = 32,
    },
    {
        .name = "location_object_id",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Object identifier addressed by the selected location kind.",
        .minimum = 0,
        .maximum = UINT32_MAX,
    },
    {
        .name = "position_index",
        .type = ActionParameterType::kUint32,
        .required = false,
        .description = "Required only for council_position; zero-based native council slot.",
        .minimum = 0,
        .maximum = 0x7fffffffU,
    },
}};

const ActionDescriptor kHireDescriptor = {
    .action_type = "hire_and_assign_leader",
    .action_version = 1,
    .application_id = "etc",
    .description = "Hire one available leader and assign a typed destination.",
    .risk_class = "state_change",
    .verification_state = "live_verified",
    .parameters = kParameters,
    .parse = &ParseHireAndAssign,
    .supported = &HireAndAssignSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kHireRegistration{
    kHireDescriptor};

const ActionDescriptor kAssignDescriptor = {
    .action_type = "assign_leader",
    .action_version = 1,
    .application_id = "etc",
    .description = "Assign one owned leader to a typed destination.",
    .risk_class = "state_change",
    .verification_state = "live_verified",
    .parameters = kParameters,
    .parse = &ParseAssign,
    .supported = &AssignSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kAssignRegistration{
    kAssignDescriptor};

}  // namespace
}  // namespace iag::native_runtime
