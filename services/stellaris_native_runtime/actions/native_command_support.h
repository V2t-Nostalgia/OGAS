#pragma once

#include <cstddef>
#include <cstdint>
#include <new>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "iag_native_runtime/action.h"
#include "iag_native_runtime/game_api.h"

namespace iag::native_runtime::action_support {

using CStringCtorFn = void (*)(void*, const char*);
using CStringDtorFn = void (*)(void*);

class NativeCString final {
 public:
  NativeCString(const GameApi& game, std::string_view value)
      : game_(game), storage_(game.profile().c_string.object_size) {
    std::string terminated(value);
    game_.FunctionAt<CStringCtorFn>(game_.profile().c_string.construct)(
        storage_.data(), terminated.c_str());
    constructed_ = true;
  }

  NativeCString(const NativeCString&) = delete;
  NativeCString& operator=(const NativeCString&) = delete;

  ~NativeCString() {
    if (constructed_) {
      game_.FunctionAt<CStringDtorFn>(game_.profile().c_string.destroy)(
          storage_.data());
    }
  }

  [[nodiscard]] const void* get() const noexcept { return storage_.data(); }

 private:
  const GameApi& game_;
  std::vector<std::byte> storage_;
  bool constructed_ = false;
};

class PendingSaveInvocation : public ActionInvocation {
 public:
  [[nodiscard]] std::optional<RuntimeResult> Verify(
      const GameApi&,
      std::uint32_t,
      const void*) override {
    return RuntimeResult{
        "pending", "native_posted_awaiting_save_verification"};
  }

  [[nodiscard]] std::string_view TimeoutDetail() const noexcept override {
    return "native_posted_awaiting_save_verification";
  }
};

template <typename Construct>
PrepareResult ConstructValidatedCommand(
    const GameApi& game,
    std::uint32_t country_id,
    std::size_t command_size,
    Construct&& construct) {
  if (command_size == 0U) {
    return PrepareResult::Failed("native_command_binding_missing");
  }
  void* command = ::operator new(command_size, std::nothrow);
  if (command == nullptr) {
    return PrepareResult::Failed("command_allocation_failed");
  }
  construct(command);
  // The acting country belongs to each command's typed constructor fields.
  // The common +0x08 header field is the session-owned command serial.
  (void)country_id;
  game.ResetCommandSerial(command);
  if (!game.IsCommandValid(command)) {
    game.DestroyCommand(command);
    return PrepareResult::Rejected("native_is_valid_false_before_submit");
  }
  return PrepareResult::Ready(command);
}

inline bool CommonBindingsSupported(const BuildProfile& profile) noexcept {
  return profile.core.post_command_to_session != 0U &&
         profile.serialized_command.command_serial_offset != 0U &&
         profile.serialized_command.command_is_valid_vtable_offset != 0U &&
         profile.serialized_command.command_deleting_destructor_vtable_offset !=
             0U;
}

inline bool CStringBindingsSupported(const BuildProfile& profile) noexcept {
  return profile.c_string.object_size != 0U &&
         profile.c_string.construct != 0U && profile.c_string.destroy != 0U &&
         profile.c_string.get_tchar_ptr != 0U &&
         profile.c_string.get_size != 0U;
}

inline bool ParseSemanticKey(
    std::span<const std::string> fields,
    std::string& error_detail,
    std::string& key) {
  if (fields.size() != 1U || !IsSemanticToken(fields[0], 160U)) {
    error_detail = "invalid_semantic_target";
    return false;
  }
  key = fields[0];
  return true;
}

}  // namespace iag::native_runtime::action_support
