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
using action_support::PendingSaveInvocation;

enum class CommunityKind {
  kJoin,
  kPropose,
  kSupport,
  kOppose,
  kWithdraw,
  kCastVote,
  kEmergency,
};

using JoinCtorFn = void (*)(void*, const void*, bool);
using ProposeCtorFn = void (*)(void*, const void*, const void*);
using ResolutionToggleCtorFn = void (*)(void*, const void*, const void*, bool);
using ResolutionCtorFn = void (*)(void*, const void*, const void*);
using CastVoteCtorFn = void (*)(void*, const void*, const void*, int, bool);

std::string_view ActionType(CommunityKind kind) {
  switch (kind) {
    case CommunityKind::kJoin:
      return "join_galactic_community";
    case CommunityKind::kPropose:
      return "propose_resolution";
    case CommunityKind::kSupport:
      return "support_proposed_resolution";
    case CommunityKind::kOppose:
      return "oppose_proposed_resolution";
    case CommunityKind::kWithdraw:
      return "withdraw_proposed_resolution";
    case CommunityKind::kCastVote:
      return "cast_resolution_vote";
    case CommunityKind::kEmergency:
      return "propose_emergency_measure";
  }
  return "unknown_community_action";
}

class CommunityInvocation final : public PendingSaveInvocation {
 public:
  CommunityInvocation(
      CommunityKind kind,
      std::uint32_t resolution_id,
      std::string definition_key,
      int vote)
      : kind_(kind),
        resolution_id_(resolution_id),
        definition_key_(std::move(definition_key)),
        vote_(vote) {}

  [[nodiscard]] std::string_view action_type() const noexcept override {
    return ActionType(kind_);
  }

  [[nodiscard]] std::string TargetEcho() const override {
    if (kind_ == CommunityKind::kJoin) {
      return "join";
    }
    if (kind_ == CommunityKind::kPropose) {
      return definition_key_;
    }
    std::string result = std::to_string(resolution_id_);
    if (kind_ == CommunityKind::kCastVote) {
      result += vote_ == 0 ? ":support" : (vote_ == 1 ? ":oppose" : ":abstain");
    }
    return result;
  }

  [[nodiscard]] PrepareResult Prepare(
      const GameApi& game,
      std::uint32_t country_id,
      const void* local_country) override {
    const auto& bindings = game.profile().galactic_community_commands;
    if (kind_ == CommunityKind::kJoin) {
      return ConstructValidatedCommand(
          game, country_id, bindings.join_command_size, [&](void* command) {
            game.FunctionAt<JoinCtorFn>(bindings.construct_join_command)(
                command, local_country, false);
          });
    }
    if (kind_ == CommunityKind::kPropose) {
      const void* resolution_type = game.ResolveStaticDefinition(
          bindings.resolution_types, definition_key_);
      if (resolution_type == nullptr) {
        return PrepareResult::Rejected("unknown_resolution_type_key");
      }
      return ConstructValidatedCommand(
          game,
          country_id,
          bindings.propose_resolution_command_size,
          [&](void* command) {
            game.FunctionAt<ProposeCtorFn>(
                bindings.construct_propose_resolution_command)(
                command, resolution_type, local_country);
          });
    }

    const void* resolution =
        game.ResolvePdxObject(bindings.resolutions, resolution_id_);
    if (resolution == nullptr) {
      return PrepareResult::Rejected("unknown_resolution_id");
    }
    switch (kind_) {
      case CommunityKind::kSupport:
      case CommunityKind::kOppose: {
        const bool support = kind_ == CommunityKind::kSupport;
        const std::uintptr_t constructor = support
            ? bindings.construct_support_resolution_command
            : bindings.construct_oppose_resolution_command;
        const std::size_t size = support
            ? bindings.support_resolution_command_size
            : bindings.oppose_resolution_command_size;
        return ConstructValidatedCommand(
            game, country_id, size, [&](void* command) {
              game.FunctionAt<ResolutionToggleCtorFn>(constructor)(
                  command, resolution, local_country, false);
            });
      }
      case CommunityKind::kWithdraw:
      case CommunityKind::kEmergency: {
        const bool emergency = kind_ == CommunityKind::kEmergency;
        const std::uintptr_t constructor = emergency
            ? bindings.construct_emergency_measure_command
            : bindings.construct_withdraw_resolution_command;
        const std::size_t size = emergency
            ? bindings.emergency_measure_command_size
            : bindings.withdraw_resolution_command_size;
        return ConstructValidatedCommand(
            game, country_id, size, [&](void* command) {
              game.FunctionAt<ResolutionCtorFn>(constructor)(
                  command, resolution, local_country);
            });
      }
      case CommunityKind::kCastVote:
        return ConstructValidatedCommand(
            game,
            country_id,
            bindings.cast_vote_command_size,
            [&](void* command) {
              game.FunctionAt<CastVoteCtorFn>(
                  bindings.construct_cast_vote_command)(
                  command, resolution, local_country, vote_, false);
            });
      case CommunityKind::kJoin:
      case CommunityKind::kPropose:
        break;
    }
    return PrepareResult::Failed("unsupported_community_action_kind");
  }

 private:
  CommunityKind kind_;
  std::uint32_t resolution_id_;
  std::string definition_key_;
  int vote_;
};

std::unique_ptr<ActionInvocation> ParseJoin(
    std::span<const std::string> fields,
    std::string& error_detail) {
  if (!fields.empty()) {
    error_detail = "join_galactic_community_has_no_target_fields";
    return nullptr;
  }
  return std::make_unique<CommunityInvocation>(
      CommunityKind::kJoin, 0U, std::string{}, 0);
}

std::unique_ptr<ActionInvocation> ParsePropose(
    std::span<const std::string> fields,
    std::string& error_detail) {
  if (fields.size() != 1U || !IsSemanticToken(fields[0], 160U)) {
    error_detail = "invalid_resolution_type_key";
    return nullptr;
  }
  return std::make_unique<CommunityInvocation>(
      CommunityKind::kPropose, 0U, fields[0], 0);
}

template <CommunityKind Kind>
std::unique_ptr<ActionInvocation> ParseResolution(
    std::span<const std::string> fields,
    std::string& error_detail) {
  if (fields.size() != 1U) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto resolution_id = ParseUint32(fields[0]);
  if (!resolution_id.has_value()) {
    error_detail = "invalid_resolution_id";
    return nullptr;
  }
  return std::make_unique<CommunityInvocation>(
      Kind, *resolution_id, std::string{}, 0);
}

std::unique_ptr<ActionInvocation> ParseCastVote(
    std::span<const std::string> fields,
    std::string& error_detail) {
  if (fields.size() != 2U) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto resolution_id = ParseUint32(fields[0]);
  int vote = -1;
  if (fields[1] == "support") {
    vote = 0;
  } else if (fields[1] == "oppose") {
    vote = 1;
  } else if (fields[1] == "abstain") {
    vote = 2;
  }
  if (!resolution_id.has_value() || vote < 0) {
    error_detail = "invalid_resolution_vote";
    return nullptr;
  }
  return std::make_unique<CommunityInvocation>(
      CommunityKind::kCastVote, *resolution_id, std::string{}, vote);
}

bool CommunityBaseSupported(const BuildProfile& profile) noexcept {
  return CommonBindingsSupported(profile) && CStringBindingsSupported(profile);
}

bool JoinSupported(const BuildProfile& profile) noexcept {
  const auto& value = profile.galactic_community_commands;
  return CommunityBaseSupported(profile) && value.join_command_size != 0U &&
         value.construct_join_command != 0U;
}

bool ResolutionCommandsSupported(const BuildProfile& profile) noexcept {
  const auto& value = profile.galactic_community_commands;
  return CommunityBaseSupported(profile) &&
         value.propose_resolution_command_size != 0U &&
         value.construct_propose_resolution_command != 0U &&
         value.support_resolution_command_size != 0U &&
         value.construct_support_resolution_command != 0U &&
         value.oppose_resolution_command_size != 0U &&
         value.construct_oppose_resolution_command != 0U &&
         value.withdraw_resolution_command_size != 0U &&
         value.construct_withdraw_resolution_command != 0U &&
         value.cast_vote_command_size != 0U &&
         value.construct_cast_vote_command != 0U &&
         value.emergency_measure_command_size != 0U &&
         value.construct_emergency_measure_command != 0U &&
         value.resolution_types.database_instance != 0U &&
         value.resolutions.database_instance != 0U;
}

constexpr std::array<ActionParameterDescriptor, 0> kNoParameters = {};
constexpr std::array<ActionParameterDescriptor, 1> kResolutionTypeParameter = {{
    {
        .name = "resolution_type_key",
        .type = ActionParameterType::kString,
        .required = true,
        .description = "Stable resolution-type key from a legal proposal candidate.",
        .maximum_length = 160,
    },
}};
constexpr std::array<ActionParameterDescriptor, 1> kResolutionIdParameter = {{
    {
        .name = "resolution_id",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Current resolution object identifier.",
        .minimum = 0,
        .maximum = UINT32_MAX,
    },
}};
constexpr std::array<ActionParameterDescriptor, 2> kVoteParameters = {{
    kResolutionIdParameter[0],
    {
        .name = "vote",
        .type = ActionParameterType::kString,
        .required = true,
        .description = "One of support, oppose, or abstain.",
        .maximum_length = 16,
    },
}};

const ActionDescriptor kJoinDescriptor = {
    .action_type = "join_galactic_community",
    .action_version = 1,
    .application_id = "etc",
    .description = "Join the Galactic Community when the native rules allow it.",
    .risk_class = "state_change",
    .verification_state = "paired_capture",
    .parameters = kNoParameters,
    .parse = &ParseJoin,
    .supported = &JoinSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kJoinRegistration{
    kJoinDescriptor};

const ActionDescriptor kProposeDescriptor = {
    .action_type = "propose_resolution",
    .action_version = 1,
    .application_id = "etc",
    .description = "Propose one legal Galactic Community resolution type.",
    .risk_class = "state_change",
    .verification_state = "live_verified",
    .parameters = kResolutionTypeParameter,
    .parse = &ParsePropose,
    .supported = &ResolutionCommandsSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kProposeRegistration{
    kProposeDescriptor};

#define IAG_RESOLUTION_DESCRIPTOR(                                                \
    Variable, Action, Kind, Description, Risk, Verification)                     \
  const ActionDescriptor Variable = {                                            \
      .action_type = Action,                                                     \
      .action_version = 1,                                                       \
      .application_id = "etc",                                                  \
      .description = Description,                                                \
      .risk_class = Risk,                                                        \
      .verification_state = Verification,                                       \
      .parameters = kResolutionIdParameter,                                      \
      .parse = &ParseResolution<Kind>,                                            \
      .supported = &ResolutionCommandsSupported,                                 \
  };                                                                             \
  IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration Variable##Registration{\
      Variable}

IAG_RESOLUTION_DESCRIPTOR(
    kSupportDescriptor,
    "support_proposed_resolution",
    CommunityKind::kSupport,
    "Support one currently proposed Galactic Community resolution.",
    "state_change",
    "live_verified");
IAG_RESOLUTION_DESCRIPTOR(
    kOpposeDescriptor,
    "oppose_proposed_resolution",
    CommunityKind::kOppose,
    "Oppose one currently proposed Galactic Community resolution.",
    "state_change",
    "live_verified");
IAG_RESOLUTION_DESCRIPTOR(
    kWithdrawDescriptor,
    "withdraw_proposed_resolution",
    CommunityKind::kWithdraw,
    "Withdraw this country's currently proposed resolution.",
    "state_change",
    "live_verified");
IAG_RESOLUTION_DESCRIPTOR(
    kEmergencyDescriptor,
    "propose_emergency_measure",
    CommunityKind::kEmergency,
    "Mark one eligible resolution as an emergency measure.",
    "state_change",
    "paired_capture");

#undef IAG_RESOLUTION_DESCRIPTOR

const ActionDescriptor kCastVoteDescriptor = {
    .action_type = "cast_resolution_vote",
    .action_version = 1,
    .application_id = "etc",
    .description = "Cast or modify this country's vote on one active resolution.",
    .risk_class = "state_change",
    .verification_state = "live_verified",
    .parameters = kVoteParameters,
    .parse = &ParseCastVote,
    .supported = &ResolutionCommandsSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kCastVoteRegistration{
    kCastVoteDescriptor};

}  // namespace
}  // namespace iag::native_runtime
