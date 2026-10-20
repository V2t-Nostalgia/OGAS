#include "iag_native_runtime/state_query.h"

#include <algorithm>
#include <cstddef>
#include <cstring>
#include <sstream>
#include <string_view>
#include <utility>
#include <vector>

#include "iag_native_runtime/game_api.h"
#include "iag_native_runtime/version_profile.h"

namespace iag::native_runtime {
namespace {

constexpr int kMaximumOpenEvents = 64;
constexpr int kMaximumOptionsPerEvent = 64;
constexpr int kMaximumPendingDiplomaticActions = 128;
constexpr std::size_t kMaximumStableTextBytes = 512;

using IsOptionAllowedFn = bool (*)(
    const void*, bool, const void*, int, int, const void*);
using GetFirstKeyFn = void (*)(void*, const void*);
using CStringDtorFn = void (*)(void*);
using CStringGetDataFn = const char* (*)(const void*);
using CStringGetSizeFn = std::uint32_t (*)(const void*);
using CanRespondToActionFn = bool (*)(
    const void*, const void*, bool, void*);
using GetActionTagFn = const char* (*)(const void*);

template <typename Value>
Value ReadField(const void* object, std::size_t offset) {
  Value value{};
  std::memcpy(
      &value,
      static_cast<const std::byte*>(object) + offset,
      sizeof(value));
  return value;
}

std::string JsonEscape(std::string_view value) {
  std::string escaped;
  escaped.reserve(value.size() + 8U);
  for (const unsigned char character : value) {
    switch (character) {
      case '"':
        escaped += "\\\"";
        break;
      case '\\':
        escaped += "\\\\";
        break;
      case '\b':
        escaped += "\\b";
        break;
      case '\f':
        escaped += "\\f";
        break;
      case '\n':
        escaped += "\\n";
        break;
      case '\r':
        escaped += "\\r";
        break;
      case '\t':
        escaped += "\\t";
        break;
      default:
        if (character < 0x20U) {
          static constexpr char kHex[] = "0123456789abcdef";
          escaped += "\\u00";
          escaped.push_back(kHex[character >> 4U]);
          escaped.push_back(kHex[character & 0x0fU]);
        } else {
          escaped.push_back(static_cast<char>(character));
        }
    }
  }
  return escaped;
}

std::string ReadCString(const GameApi& game, const void* value) {
  if (value == nullptr) {
    return {};
  }
  const auto& bindings = game.profile().c_string;
  const std::uint32_t size = game.FunctionAt<CStringGetSizeFn>(
      bindings.get_size)(value);
  const char* data = game.FunctionAt<CStringGetDataFn>(
      bindings.get_tchar_ptr)(value);
  if (data == nullptr || size == 0U) {
    return {};
  }
  return std::string(data, std::min<std::size_t>(size, kMaximumStableTextBytes));
}

std::string ReadBoundedCString(const char* value) {
  if (value == nullptr) {
    return {};
  }
  std::size_t size = 0U;
  while (size < kMaximumStableTextBytes && value[size] != '\0') {
    ++size;
  }
  return std::string(value, size);
}

}  // namespace

bool OpenEventStateSupported(const BuildProfile& profile) noexcept {
  return profile.core.current_game_state != 0U &&
         profile.open_event.open_events_data_offset != 0U &&
         profile.open_event.open_events_count_offset != 0U &&
         profile.open_event.option_is_allowed != 0U &&
         profile.open_event.option_get_first_key != 0U &&
         profile.c_string.object_size != 0U &&
         profile.c_string.destroy != 0U &&
         profile.c_string.get_tchar_ptr != 0U &&
         profile.c_string.get_size != 0U;
}

StateQueryResult InspectOpenEvents(
    const GameApi& game,
    std::uint32_t country_id) {
  if (!OpenEventStateSupported(game.profile())) {
    return {
        "rejected", "-", "open_event_state_unsupported_for_build"};
  }
  const void* game_state = game.CurrentGameState();
  if (game_state == nullptr) {
    return {"rejected", "-", "game_state_unavailable"};
  }
  const auto& bindings = game.profile().open_event;
  const int raw_count = ReadField<int>(
      game_state, bindings.open_events_count_offset);
  const void* const* events = ReadField<const void* const*>(
      game_state, bindings.open_events_data_offset);
  if (raw_count < 0 || raw_count > 4096 || (raw_count != 0 && events == nullptr)) {
    return {"failed", "-", "open_event_array_invalid"};
  }

  const int event_limit = std::min(raw_count, kMaximumOpenEvents);
  std::ostringstream output;
  output << "{\"schema_version\":\"iag.open_event_state.v1\",";
  output << "\"country_id\":" << country_id << ',';
  output << "\"content_mode\":\"stable_keys_no_rng\",";
  output << "\"truncated\":"
         << (raw_count > kMaximumOpenEvents ? "true" : "false") << ',';
  output << "\"events\":[";
  bool first_event = true;
  for (int event_index = 0; event_index < event_limit; ++event_index) {
    const void* open_event = events[event_index];
    if (open_event == nullptr ||
        ReadField<std::uint32_t>(
            open_event, bindings.open_event_country_ref_offset) != country_id) {
      continue;
    }
    const void* handle = ReadField<const void*>(
        open_event, bindings.open_event_handle_offset);
    const void* event =
        handle == nullptr ? nullptr : ReadField<const void*>(handle, 0U);
    if (event == nullptr) {
      continue;
    }
    const void* scope = static_cast<const std::byte*>(open_event) +
                        bindings.open_event_scope_offset;
    const void* options = static_cast<const std::byte*>(event) +
                          bindings.event_options_offset;
    const int raw_option_count = ReadField<int>(
        options, bindings.event_options_count_offset);
    const std::byte* option_entries = ReadField<const std::byte*>(
        options, bindings.event_options_data_offset);
    if (raw_option_count < 0 || raw_option_count > 4096 ||
        (raw_option_count != 0 && option_entries == nullptr)) {
      continue;
    }

    if (!first_event) {
      output << ',';
    }
    first_event = false;
    const auto open_event_id = ReadField<std::uint32_t>(
        open_event, bindings.open_event_id_offset);
    const auto definition_id = ReadField<std::uint32_t>(
        event, bindings.event_definition_id_offset);
    const std::string title_key = ReadCString(
        game,
        static_cast<const std::byte*>(event) +
            bindings.event_title_key_offset);
    output << "{\"open_event_id\":" << open_event_id;
    output << ",\"event_definition_id\":" << definition_id;
    output << ",\"title_key\":\"" << JsonEscape(title_key) << "\"";
    output << ",\"description_state\":\"dynamic_unrendered\"";
    output << ",\"options_truncated\":"
           << (raw_option_count > kMaximumOptionsPerEvent ? "true" : "false");
    output << ",\"options\":[";

    bool first_option = true;
    const int option_limit = std::min(
        raw_option_count, kMaximumOptionsPerEvent);
    for (int option_index = 0; option_index < option_limit; ++option_index) {
      const void* option = ReadField<const void*>(
          option_entries, static_cast<std::size_t>(option_index) * 0x10U);
      if (option == nullptr ||
          !game.FunctionAt<IsOptionAllowedFn>(bindings.option_is_allowed)(
              scope, true, options, option_index, 0, nullptr)) {
        continue;
      }
      std::vector<std::byte> option_key(game.profile().c_string.object_size);
      game.FunctionAt<GetFirstKeyFn>(bindings.option_get_first_key)(
          option_key.data(), option);
      const std::string key = ReadCString(game, option_key.data());
      game.FunctionAt<CStringDtorFn>(game.profile().c_string.destroy)(
          option_key.data());
      if (!first_option) {
        output << ',';
      }
      first_option = false;
      output << "{\"option_index\":" << option_index
             << ",\"text_key\":\"" << JsonEscape(key) << "\"}";
    }
    output << "]}";
  }
  output << "]}";
  std::string payload = output.str();
  if (payload.size() > 60'000U) {
    return {"failed", "-", "open_event_state_response_too_large"};
  }
  return {"confirmed", std::move(payload), "open_event_state_stable_keys"};
}

bool PendingDiplomaticActionStateSupported(
    const BuildProfile& profile) noexcept {
  const auto& bindings = profile.diplomatic_action;
  return bindings.can_respond_to_action != 0U &&
         bindings.countries.database_instance != 0U &&
         bindings.countries.null_object_instance != 0U &&
         bindings.incoming_actions_data_offset != 0U &&
         bindings.incoming_actions_count_offset != 0U &&
         bindings.incoming_action_stride != 0U &&
         bindings.action_id_offset != 0U &&
         bindings.action_tag_vtable_offset != 0U;
}

StateQueryResult InspectPendingDiplomaticActions(
    const GameApi& game,
    std::uint32_t country_id) {
  if (!PendingDiplomaticActionStateSupported(game.profile())) {
    return {
        "rejected", "-", "pending_diplomatic_state_unsupported_for_build"};
  }
  const auto& bindings = game.profile().diplomatic_action;
  const void* country = game.ResolvePdxObject(bindings.countries, country_id);
  if (country == nullptr) {
    return {"rejected", "-", "country_not_found"};
  }
  const int raw_count = ReadField<int>(
      country, bindings.incoming_actions_count_offset);
  const std::byte* entries = ReadField<const std::byte*>(
      country, bindings.incoming_actions_data_offset);
  if (raw_count < 0 || raw_count > 4096 ||
      (raw_count != 0 && entries == nullptr)) {
    return {"failed", "-", "incoming_diplomatic_action_array_invalid"};
  }

  std::ostringstream output;
  output << "{\"schema_version\":\"iag.pending_diplomatic_action_state.v1\",";
  output << "\"country_id\":" << country_id << ',';
  output << "\"truncated\":"
         << (raw_count > kMaximumPendingDiplomaticActions ? "true" : "false")
         << ',';
  output << "\"actions\":[";
  bool first = true;
  const int limit = std::min(raw_count, kMaximumPendingDiplomaticActions);
  for (int index = 0; index < limit; ++index) {
    const auto entry_offset = static_cast<std::size_t>(index) *
                              bindings.incoming_action_stride;
    const void* action = ReadField<const void*>(
        entries,
        entry_offset + bindings.incoming_action_pointer_offset);
    if (action == nullptr) {
      continue;
    }
    const void* vtable = ReadField<const void*>(action, 0U);
    if (vtable == nullptr) {
      continue;
    }
    const void* get_tag = ReadField<const void*>(
        vtable, bindings.action_tag_vtable_offset);
    if (!game.IsTextPointer(get_tag)) {
      continue;
    }
    const std::string action_tag = ReadBoundedCString(
        reinterpret_cast<GetActionTagFn>(const_cast<void*>(get_tag))(action));
    const auto action_id = ReadField<std::uint64_t>(
        action, bindings.action_id_offset);
    if (action_id == 0U || action_tag.empty()) {
      continue;
    }
    const bool can_accept = game.FunctionAt<CanRespondToActionFn>(
        bindings.can_respond_to_action)(country, action, true, nullptr);
    const bool can_reject = game.FunctionAt<CanRespondToActionFn>(
        bindings.can_respond_to_action)(country, action, false, nullptr);
    if (!first) {
      output << ',';
    }
    first = false;
    output << "{\"pending_action_id\":" << action_id;
    output << ",\"action_tag\":\"" << JsonEscape(action_tag) << "\"";
    output << ",\"actor_country_id\":"
           << ReadField<std::uint32_t>(
                  action, bindings.action_actor_ref_offset);
    output << ",\"recipient_country_id\":"
           << ReadField<std::uint32_t>(
                  action, bindings.action_recipient_ref_offset);
    output << ",\"can_accept\":" << (can_accept ? "true" : "false");
    output << ",\"can_reject\":" << (can_reject ? "true" : "false");
    output << '}';
  }
  output << "]}";
  std::string payload = output.str();
  if (payload.size() > 60'000U) {
    return {"failed", "-", "pending_diplomatic_state_response_too_large"};
  }
  return {
      "confirmed",
      std::move(payload),
      "pending_diplomatic_action_state_current_candidates"};
}

}  // namespace iag::native_runtime
