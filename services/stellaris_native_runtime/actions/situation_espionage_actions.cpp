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
using action_support::NativeCString;
using action_support::PendingSaveInvocation;

using SituationApproachCtorFn = void (*)(void*, std::uint32_t, const void*);
using ScopeCtorFn = void (*)(void*);
using SpyNetworkGetTargetFn = const void* (*)(const void*);
using ScopeSetCountryFn = void (*)(void*, const void*);
using StartEspionageCtorFn = void (*)(
    void*, std::uint32_t, std::uint32_t, const void*, const void*, bool);
using CancelEspionageCtorFn =
    void (*)(void*, std::uint32_t, std::uint32_t, std::uint32_t);

class SituationApproachInvocation final : public PendingSaveInvocation {
 public:
  SituationApproachInvocation(
      std::uint32_t situation_id,
      std::string approach_key)
      : situation_id_(situation_id), approach_key_(std::move(approach_key)) {}

  [[nodiscard]] std::string_view action_type() const noexcept override {
    return "set_situation_approach";
  }

  [[nodiscard]] std::string TargetEcho() const override {
    return std::to_string(situation_id_) + ":" + approach_key_;
  }

  [[nodiscard]] PrepareResult Prepare(
      const GameApi& game,
      std::uint32_t country_id,
      const void*) override {
    const auto& bindings = game.profile().situation_espionage_commands;
    if (game.ResolvePdxObject(bindings.situations, situation_id_) == nullptr) {
      return PrepareResult::Rejected("unknown_situation_id");
    }
    NativeCString approach(game, approach_key_);
    return ConstructValidatedCommand(
        game,
        country_id,
        bindings.set_situation_approach_command_size,
        [&](void* command) {
          game.FunctionAt<SituationApproachCtorFn>(
              bindings.construct_set_situation_approach_command)(
              command, situation_id_, approach.get());
        });
  }

 private:
  std::uint32_t situation_id_;
  std::string approach_key_;
};

class StartEspionageInvocation final : public PendingSaveInvocation {
 public:
  StartEspionageInvocation(
      std::uint32_t spy_network_id,
      std::string operation_type_key)
      : spy_network_id_(spy_network_id),
        operation_type_key_(std::move(operation_type_key)) {}

  [[nodiscard]] std::string_view action_type() const noexcept override {
    return "start_espionage_operation";
  }

  [[nodiscard]] std::string TargetEcho() const override {
    return std::to_string(spy_network_id_) + ":" + operation_type_key_;
  }

  [[nodiscard]] PrepareResult Prepare(
      const GameApi& game,
      std::uint32_t country_id,
      const void*) override {
    const auto& bindings = game.profile().situation_espionage_commands;
    const void* spy_network =
        game.ResolvePdxObject(bindings.spy_networks, spy_network_id_);
    if (spy_network == nullptr) {
      return PrepareResult::Rejected("unknown_spy_network_id");
    }
    const void* operation_type = game.ResolveStaticDefinition(
        bindings.espionage_operation_types, operation_type_key_);
    if (operation_type == nullptr) {
      return PrepareResult::Rejected("unknown_espionage_operation_type_key");
    }
    std::vector<std::byte> scope(bindings.scope_object_reference_size);
    game.FunctionAt<ScopeCtorFn>(
        bindings.construct_empty_scope_object_reference)(scope.data());
    const void* target_country = game.FunctionAt<SpyNetworkGetTargetFn>(
        bindings.spy_network_get_target)(spy_network);
    if (target_country == nullptr) {
      return PrepareResult::Rejected("spy_network_target_unavailable");
    }
    game.FunctionAt<ScopeSetCountryFn>(
        bindings.scope_object_reference_set_country)(
        scope.data(), target_country);
    PrepareResult result = ConstructValidatedCommand(
        game,
        country_id,
        bindings.start_espionage_command_size,
        [&](void* command) {
          game.FunctionAt<StartEspionageCtorFn>(
              bindings.construct_start_espionage_command)(
              command,
              country_id,
              spy_network_id_,
              operation_type,
              scope.data(),
              false);
        });
    // The exported CScopeObjectReference destructor is the deleting destructor
    // (it immediately calls operator delete). The empty scope owns no storage,
    // so stack-backed scratch memory must not be passed to that entry point.
    return result;
  }

 private:
  std::uint32_t spy_network_id_;
  std::string operation_type_key_;
};

class CancelEspionageInvocation final : public PendingSaveInvocation {
 public:
  CancelEspionageInvocation(
      std::uint32_t spy_network_id,
      std::uint32_t operation_id)
      : spy_network_id_(spy_network_id), operation_id_(operation_id) {}

  [[nodiscard]] std::string_view action_type() const noexcept override {
    return "cancel_espionage_operation";
  }

  [[nodiscard]] std::string TargetEcho() const override {
    return std::to_string(spy_network_id_) + ":" +
           std::to_string(operation_id_);
  }

  [[nodiscard]] PrepareResult Prepare(
      const GameApi& game,
      std::uint32_t country_id,
      const void*) override {
    const auto& bindings = game.profile().situation_espionage_commands;
    if (game.ResolvePdxObject(bindings.spy_networks, spy_network_id_) == nullptr) {
      return PrepareResult::Rejected("unknown_spy_network_id");
    }
    if (game.ResolvePdxObject(
            bindings.espionage_operations, operation_id_) == nullptr) {
      return PrepareResult::Rejected("unknown_espionage_operation_id");
    }
    return ConstructValidatedCommand(
        game,
        country_id,
        bindings.cancel_espionage_command_size,
        [&](void* command) {
          game.FunctionAt<CancelEspionageCtorFn>(
              bindings.construct_cancel_espionage_command)(
              command, country_id, spy_network_id_, operation_id_);
        });
  }

 private:
  std::uint32_t spy_network_id_;
  std::uint32_t operation_id_;
};

std::unique_ptr<ActionInvocation> ParseSituationApproach(
    std::span<const std::string> fields,
    std::string& error_detail) {
  if (fields.size() != 2U || !IsSemanticToken(fields[1], 160U)) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto situation_id = ParseUint32(fields[0]);
  if (!situation_id.has_value()) {
    error_detail = "invalid_situation_id";
    return nullptr;
  }
  return std::make_unique<SituationApproachInvocation>(
      *situation_id, fields[1]);
}

std::unique_ptr<ActionInvocation> ParseStartEspionage(
    std::span<const std::string> fields,
    std::string& error_detail) {
  if (fields.size() != 2U || !IsSemanticToken(fields[1], 160U)) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto network_id = ParseUint32(fields[0]);
  if (!network_id.has_value()) {
    error_detail = "invalid_spy_network_id";
    return nullptr;
  }
  return std::make_unique<StartEspionageInvocation>(*network_id, fields[1]);
}

std::unique_ptr<ActionInvocation> ParseCancelEspionage(
    std::span<const std::string> fields,
    std::string& error_detail) {
  if (fields.size() != 2U) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto network_id = ParseUint32(fields[0]);
  const auto operation_id = ParseUint32(fields[1]);
  if (!network_id.has_value() || !operation_id.has_value()) {
    error_detail = "invalid_espionage_operation_target";
    return nullptr;
  }
  return std::make_unique<CancelEspionageInvocation>(
      *network_id, *operation_id);
}

bool SituationSupported(const BuildProfile& profile) noexcept {
  const auto& value = profile.situation_espionage_commands;
  return CommonBindingsSupported(profile) && CStringBindingsSupported(profile) &&
         value.set_situation_approach_command_size != 0U &&
         value.construct_set_situation_approach_command != 0U &&
         value.situations.database_instance != 0U;
}

bool EspionageSupported(const BuildProfile& profile) noexcept {
  const auto& value = profile.situation_espionage_commands;
  return CommonBindingsSupported(profile) && CStringBindingsSupported(profile) &&
         value.start_espionage_command_size != 0U &&
         value.construct_start_espionage_command != 0U &&
         value.cancel_espionage_command_size != 0U &&
         value.construct_cancel_espionage_command != 0U &&
         value.spy_networks.database_instance != 0U &&
         value.espionage_operations.database_instance != 0U &&
         value.espionage_operation_types.database_instance != 0U &&
         value.scope_object_reference_size != 0U &&
         value.construct_empty_scope_object_reference != 0U &&
         value.spy_network_get_target != 0U &&
         value.scope_object_reference_set_country != 0U;
}

constexpr std::array<ActionParameterDescriptor, 2> kSituationParameters = {{
    {
        .name = "situation_id",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Current empire situation object identifier.",
        .minimum = 0,
        .maximum = UINT32_MAX,
    },
    {
        .name = "approach_key",
        .type = ActionParameterType::kString,
        .required = true,
        .description = "Stable approach key exposed by the current situation.",
        .maximum_length = 160,
    },
}};

constexpr std::array<ActionParameterDescriptor, 2> kStartParameters = {{
    {
        .name = "spy_network_id",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Current owned spy-network object identifier.",
        .minimum = 0,
        .maximum = UINT32_MAX,
    },
    {
        .name = "operation_type_key",
        .type = ActionParameterType::kString,
        .required = true,
        .description = "Legal espionage operation type for the network target.",
        .maximum_length = 160,
    },
}};

constexpr std::array<ActionParameterDescriptor, 2> kCancelParameters = {{
    kStartParameters[0],
    {
        .name = "operation_id",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Current espionage-operation object identifier to cancel.",
        .minimum = 0,
        .maximum = UINT32_MAX,
    },
}};

const ActionDescriptor kSituationDescriptor = {
    .action_type = "set_situation_approach",
    .action_version = 1,
    .application_id = "etc",
    .description = "Change one empire situation to a legal approach.",
    .risk_class = "state_change",
    .verification_state = "live_verified",
    .parameters = kSituationParameters,
    .parse = &ParseSituationApproach,
    .supported = &SituationSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kSituationRegistration{
    kSituationDescriptor};

const ActionDescriptor kStartDescriptor = {
    .action_type = "start_espionage_operation",
    .action_version = 1,
    .application_id = "etc",
    .description = "Start a legal espionage operation against the network target.",
    .risk_class = "state_change",
    .verification_state = "live_verified",
    .parameters = kStartParameters,
    .parse = &ParseStartEspionage,
    .supported = &EspionageSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kStartRegistration{
    kStartDescriptor};

const ActionDescriptor kCancelDescriptor = {
    .action_type = "cancel_espionage_operation",
    .action_version = 1,
    .application_id = "etc",
    .description = "Cancel one current espionage operation in its spy network.",
    .risk_class = "destructive_state_change",
    .verification_state = "live_verified",
    .parameters = kCancelParameters,
    .parse = &ParseCancelEspionage,
    .supported = &EspionageSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kCancelRegistration{
    kCancelDescriptor};

}  // namespace
}  // namespace iag::native_runtime
