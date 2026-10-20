#include <array>
#include <cstddef>
#include <cstring>
#include <new>
#include <string>

#include "iag_native_runtime/action.h"
#include "iag_native_runtime/game_api.h"

namespace iag::native_runtime {
namespace {

using GetOpenPlayerEventFn = const void* (*)(const void*, int);
using IsOptionAllowedFn = bool (*)(
    const void*, bool, const void*, int, int, const void*);
using SelectEventOptionCtorFn = void (*)(
    void*, const void*, const void*, int, int, int);

template <typename Value>
Value ReadField(const void* object, std::size_t offset) {
  Value value{};
  std::memcpy(
      &value,
      static_cast<const std::byte*>(object) + offset,
      sizeof(value));
  return value;
}

struct OpenEventView {
  const void* event = nullptr;
  const void* handle = nullptr;
  const void* scope = nullptr;
  const void* options = nullptr;
};

std::optional<OpenEventView> ResolveOpenEvent(
    const GameApi& game,
    std::uint32_t country_id,
    std::uint32_t open_event_id,
    std::uint32_t option_index,
    bool require_option) {
  const auto& bindings = game.profile().open_event;
  const void* game_state = game.CurrentGameState();
  if (game_state == nullptr || open_event_id > 0x7fffffffU) {
    return std::nullopt;
  }
  const void* open_event = game.FunctionAt<GetOpenPlayerEventFn>(
      bindings.get_open_player_event)(
      game_state, static_cast<int>(open_event_id));
  const void* const* null_event_slot = reinterpret_cast<void* const*>(
      game.Address(bindings.null_open_player_event_instance));
  if (!game.IsModulePointer(null_event_slot)) {
    return std::nullopt;
  }
  const void* null_event = *null_event_slot;
  if (open_event == nullptr || open_event == null_event ||
      ReadField<std::uint32_t>(
          open_event, bindings.open_event_country_ref_offset) != country_id) {
    return std::nullopt;
  }
  const void* handle = ReadField<const void*>(
      open_event, bindings.open_event_handle_offset);
  const void* event =
      handle == nullptr ? nullptr : ReadField<const void*>(handle, 0U);
  if (event == nullptr) {
    return std::nullopt;
  }
  const void* scope = static_cast<const std::byte*>(open_event) +
                      bindings.open_event_scope_offset;
  const void* options = static_cast<const std::byte*>(event) +
                        bindings.event_options_offset;
  if (require_option) {
    const int count = ReadField<int>(
        options, bindings.event_options_count_offset);
    if (option_index > 0x7fffffffU || count <= 0 ||
        static_cast<int>(option_index) >= count ||
        !game.FunctionAt<IsOptionAllowedFn>(bindings.option_is_allowed)(
            scope,
            true,
            options,
            static_cast<int>(option_index),
            0,
            nullptr)) {
      return std::nullopt;
    }
  }
  return OpenEventView{event, handle, scope, options};
}

class SelectEventOptionInvocation final : public ActionInvocation {
 public:
  SelectEventOptionInvocation(
      std::uint32_t open_event_id,
      std::uint32_t option_index)
      : open_event_id_(open_event_id), option_index_(option_index) {}

  [[nodiscard]] std::string_view action_type() const noexcept override {
    return "select_event_option";
  }

  [[nodiscard]] std::string TargetEcho() const override {
    return std::to_string(open_event_id_) + ":" +
           std::to_string(option_index_);
  }

  [[nodiscard]] PrepareResult Prepare(
      const GameApi& game,
      std::uint32_t country_id,
      const void*) override {
    const auto event = ResolveOpenEvent(
        game, country_id, open_event_id_, option_index_, true);
    if (!event.has_value()) {
      return PrepareResult::Rejected("open_event_or_option_not_currently_legal");
    }
    const auto& bindings = game.profile().open_event;
    void* command = ::operator new(bindings.command_size, std::nothrow);
    if (command == nullptr) {
      return PrepareResult::Failed("command_allocation_failed");
    }
    game.FunctionAt<SelectEventOptionCtorFn>(
        bindings.construct_select_command)(
        command,
        event->handle,
        event->scope,
        static_cast<int>(option_index_),
        static_cast<int>(open_event_id_),
        -1);
    game.ResetCommandSerial(command);
    if (!game.IsCommandValid(command)) {
      game.DestroyCommand(command);
      return PrepareResult::Rejected("native_is_valid_false_before_submit");
    }
    return PrepareResult::Ready(command);
  }

  [[nodiscard]] std::optional<RuntimeResult> Verify(
      const GameApi& game,
      std::uint32_t country_id,
      const void*) override {
    if (!ResolveOpenEvent(
             game, country_id, open_event_id_, option_index_, false)
             .has_value()) {
      return RuntimeResult{
          "confirmed", "native_postcondition_open_event_consumed"};
    }
    return std::nullopt;
  }

  [[nodiscard]] std::string_view TimeoutDetail() const noexcept override {
    return "native_submit_timeout_waiting_for_open_event_consumption";
  }

 private:
  std::uint32_t open_event_id_;
  std::uint32_t option_index_;
};

std::unique_ptr<ActionInvocation> ParseSelectEventOption(
    std::span<const std::string> fields,
    std::string& error_detail) {
  if (fields.size() != 2U) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto open_event_id = ParseUint32(fields[0]);
  const auto option_index = ParseUint32(fields[1]);
  if (!open_event_id.has_value() || *open_event_id > 0x7fffffffU ||
      !option_index.has_value() || *option_index > 0x7fffffffU) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  return std::make_unique<SelectEventOptionInvocation>(
      *open_event_id, *option_index);
}

bool SelectEventOptionSupported(const BuildProfile& profile) noexcept {
  return profile.open_event.command_size != 0U &&
         profile.open_event.construct_select_command != 0U &&
         profile.open_event.get_open_player_event != 0U &&
         profile.open_event.null_open_player_event_instance != 0U &&
         profile.open_event.null_open_player_event_instance <
             profile.core.image_size &&
         profile.open_event.option_is_allowed != 0U;
}

constexpr std::array<ActionParameterDescriptor, 2> kParameters = {{
    {
        .name = "open_event_id",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Current open-event instance identifier from inspect_open_events.",
        .minimum = 0,
        .maximum = 0x7fffffffU,
    },
    {
        .name = "option_index",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Currently legal option index from inspect_open_events.",
        .minimum = 0,
        .maximum = 0x7fffffffU,
    },
}};

const ActionDescriptor kDescriptor = {
    .action_type = "select_event_option",
    .action_version = 1,
    .application_id = "etc",
    .description = "Select one currently legal option on an exact open event instance.",
    .risk_class = "destructive_state_change",
    .verification_state = "live_verified",
    .parameters = kParameters,
    .parse = &ParseSelectEventOption,
    .supported = &SelectEventOptionSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kRegistration{
    kDescriptor};

}  // namespace
}  // namespace iag::native_runtime
