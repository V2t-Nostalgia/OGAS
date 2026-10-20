#include <array>
#include <cstdint>
#include <memory>
#include <span>
#include <string>

#include "iag_native_runtime/action.h"
#include "iag_native_runtime/game_api.h"
#include "native_command_support.h"

namespace iag::native_runtime {
namespace {

using action_support::CommonBindingsSupported;
using action_support::ConstructValidatedCommand;
using action_support::PendingSaveInvocation;

using GetSpeciesRightsModuleFn = const void* (*)(const void*);
using GetSpeciesRightsConfigFn = const void* (*)(const void*, const void*);
using SetDefaultRightsCtorFn = void (*)(void*, const void*, const void*);
using SetSpeciesRightsCtorFn =
    void (*)(void*, const void*, const void*, const void*, bool);

class SpeciesRightsInvocation final : public PendingSaveInvocation {
 public:
  SpeciesRightsInvocation(
      std::uint32_t species_id,
      std::uint32_t template_species_id,
      bool set_default)
      : species_id_(species_id),
        template_species_id_(template_species_id),
        set_default_(set_default) {}

  [[nodiscard]] std::string_view action_type() const noexcept override {
    return set_default_ ? "set_default_species_rights" : "set_species_rights";
  }

  [[nodiscard]] std::string TargetEcho() const override {
    if (set_default_) {
      return std::to_string(template_species_id_);
    }
    return std::to_string(species_id_) + ":" +
           std::to_string(template_species_id_);
  }

  [[nodiscard]] PrepareResult Prepare(
      const GameApi& game,
      std::uint32_t country_id,
      const void* local_country) override {
    const auto& bindings = game.profile().species_rights_commands;
    const void* template_species =
        game.ResolvePdxObject(bindings.species, template_species_id_);
    if (template_species == nullptr) {
      return PrepareResult::Rejected("unknown_template_species_id");
    }
    const void* module = game.FunctionAt<GetSpeciesRightsModuleFn>(
        bindings.country_get_species_rights_module)(local_country);
    if (module == nullptr) {
      return PrepareResult::Failed("species_rights_module_unavailable");
    }
    const void* configuration = game.FunctionAt<GetSpeciesRightsConfigFn>(
        bindings.get_species_rights_config)(module, template_species);
    if (configuration == nullptr) {
      return PrepareResult::Rejected(
          "template_species_rights_configuration_unavailable");
    }
    if (set_default_) {
      return ConstructValidatedCommand(
          game,
          country_id,
          bindings.set_default_rights_command_size,
          [&](void* command) {
            game.FunctionAt<SetDefaultRightsCtorFn>(
                bindings.construct_set_default_rights_command)(
                command, local_country, configuration);
          });
    }
    const void* species = game.ResolvePdxObject(bindings.species, species_id_);
    if (species == nullptr) {
      return PrepareResult::Rejected("unknown_species_id");
    }
    return ConstructValidatedCommand(
        game,
        country_id,
        bindings.set_species_rights_command_size,
        [&](void* command) {
          game.FunctionAt<SetSpeciesRightsCtorFn>(
              bindings.construct_set_species_rights_command)(
              command, local_country, species, configuration, false);
        });
  }

 private:
  std::uint32_t species_id_;
  std::uint32_t template_species_id_;
  bool set_default_;
};

std::unique_ptr<ActionInvocation> ParseDefaultRights(
    std::span<const std::string> fields,
    std::string& error_detail) {
  if (fields.size() != 1U) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto template_species_id = ParseUint32(fields[0]);
  if (!template_species_id.has_value()) {
    error_detail = "invalid_template_species_id";
    return nullptr;
  }
  return std::make_unique<SpeciesRightsInvocation>(
      0U, *template_species_id, true);
}

std::unique_ptr<ActionInvocation> ParseSpeciesRights(
    std::span<const std::string> fields,
    std::string& error_detail) {
  if (fields.size() != 2U) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto species_id = ParseUint32(fields[0]);
  const auto template_species_id = ParseUint32(fields[1]);
  if (!species_id.has_value() || !template_species_id.has_value()) {
    error_detail = "invalid_species_rights_target";
    return nullptr;
  }
  return std::make_unique<SpeciesRightsInvocation>(
      *species_id, *template_species_id, false);
}

bool SpeciesRightsSupported(const BuildProfile& profile) noexcept {
  const auto& value = profile.species_rights_commands;
  return CommonBindingsSupported(profile) &&
         value.set_default_rights_command_size != 0U &&
         value.construct_set_default_rights_command != 0U &&
         value.set_species_rights_command_size != 0U &&
         value.construct_set_species_rights_command != 0U &&
         value.species.database_instance != 0U &&
         value.country_get_species_rights_module != 0U &&
         value.get_species_rights_config != 0U;
}

constexpr std::array<ActionParameterDescriptor, 1> kDefaultParameters = {{
    {
        .name = "template_species_id",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Owned species whose current legal rights become the default template.",
        .minimum = 0,
        .maximum = UINT32_MAX,
    },
}};

constexpr std::array<ActionParameterDescriptor, 2> kSpeciesParameters = {{
    {
        .name = "species_id",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Species object whose rights will be replaced.",
        .minimum = 0,
        .maximum = UINT32_MAX,
    },
    kDefaultParameters[0],
}};

const ActionDescriptor kDefaultDescriptor = {
    .action_type = "set_default_species_rights",
    .action_version = 1,
    .application_id = "etc",
    .description = "Copy one owned species' validated rights into the default template.",
    .risk_class = "state_change",
    .verification_state = "live_verified",
    .parameters = kDefaultParameters,
    .parse = &ParseDefaultRights,
    .supported = &SpeciesRightsSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kDefaultRegistration{
    kDefaultDescriptor};

const ActionDescriptor kSpeciesDescriptor = {
    .action_type = "set_species_rights",
    .action_version = 1,
    .application_id = "etc",
    .description = "Copy a validated owned-species rights configuration to another species.",
    .risk_class = "state_change",
    .verification_state = "live_verified",
    .parameters = kSpeciesParameters,
    .parse = &ParseSpeciesRights,
    .supported = &SpeciesRightsSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kSpeciesRegistration{
    kSpeciesDescriptor};

}  // namespace
}  // namespace iag::native_runtime
