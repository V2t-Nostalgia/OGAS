#include "iag_native_runtime/game_api.h"

#include <cstring>

namespace iag::native_runtime {
namespace {

using PostCommandFn = void (*)(void*, bool);
using GetLocalObservedFn = const void* (*)(const void*);
using CreateCommandFromBytesFn = void* (*)(const unsigned char*, unsigned int);
using CommandMethodFn = bool (*)(void*, void*);
using CommandDestructorFn = void (*)(void*);
using CStringDataFn = const char* (*)(const void*);
using CStringSizeFn = int (*)(const void*);

}  // namespace

GameApi::GameApi(std::uintptr_t module_base, const BuildProfile& profile)
    : module_base_(module_base), profile_(profile) {}

const BuildProfile& GameApi::profile() const noexcept { return profile_; }

std::uintptr_t GameApi::Address(std::uintptr_t offset) const noexcept {
  return module_base_ + offset;
}

bool GameApi::IsModulePointer(const void* value) const noexcept {
  if (profile_.core.image_size == 0U) {
    return value != nullptr;
  }
  const auto address = reinterpret_cast<std::uintptr_t>(value);
  return address >= module_base_ &&
         address < module_base_ + profile_.core.image_size;
}

bool GameApi::IsTextPointer(const void* value) const noexcept {
  if (profile_.core.text_size == 0U) {
    return value != nullptr;
  }
  const auto address = reinterpret_cast<std::uintptr_t>(value);
  return address >= module_base_ + profile_.core.text_rva &&
         address < module_base_ + profile_.core.text_rva +
                       profile_.core.text_size;
}

bool GameApi::VerifyRequiredAnchors() const noexcept {
  for (std::size_t index = 0; index < profile_.required_anchor_count; ++index) {
    const auto& anchor = profile_.required_anchors[index];
    if (std::memcmp(
            reinterpret_cast<const void*>(Address(anchor.offset)),
            anchor.prefix,
            anchor.prefix_size) != 0) {
      return false;
    }
  }
  return true;
}

const void* GameApi::LocalObservedCountry() const noexcept {
  if (profile_.core.current_game_state == 0U ||
      profile_.core.get_local_observed == 0U) {
    return nullptr;
  }
  const void* game_state = CurrentGameState();
  if (game_state == nullptr) {
    return nullptr;
  }
  return FunctionAt<GetLocalObservedFn>(profile_.core.get_local_observed)(
      game_state);
}

std::uint32_t GameApi::CountryId(const void* country) const noexcept {
  if (country == nullptr) {
    return UINT32_MAX;
  }
  return *reinterpret_cast<const std::uint32_t*>(
      static_cast<const unsigned char*>(country) +
      profile_.core.country_id_offset);
}

const void* GameApi::ResolvePdxObject(
    const ObjectDatabaseProfile& database_profile,
    std::uint32_t object_id) const noexcept {
  const void* null_object = *reinterpret_cast<void* const*>(
      Address(database_profile.null_object_instance));
  const auto* database = reinterpret_cast<const unsigned char*>(
      *reinterpret_cast<void* const*>(Address(database_profile.database_instance)));
  if (database == nullptr) {
    return nullptr;
  }
  const std::uint32_t index = object_id & 0x00ffffffU;
  const std::uint32_t count =
      *reinterpret_cast<const std::uint32_t*>(database + 0x20);
  if (index >= count) {
    return nullptr;
  }
  const auto* entries = *reinterpret_cast<unsigned char* const*>(database + 0x18);
  if (entries == nullptr) {
    return nullptr;
  }
  const void* object =
      *reinterpret_cast<void* const*>(entries + index * 0x10U + 8U);
  if (object == nullptr || object == null_object) {
    return nullptr;
  }
  const std::uint32_t resolved_id = *reinterpret_cast<const std::uint32_t*>(
      static_cast<const unsigned char*>(object) +
      database_profile.object_id_offset);
  return resolved_id == object_id ? object : nullptr;
}

const void* GameApi::ResolveStaticDefinition(
    const StaticDefinitionDatabaseProfile& database_profile,
    std::string_view key) const noexcept {
  if (key.empty() || database_profile.database_instance == 0U ||
      database_profile.null_object_instance == 0U ||
      profile_.c_string.get_tchar_ptr == 0U ||
      profile_.c_string.get_size == 0U) {
    return nullptr;
  }
  const void* null_object = *reinterpret_cast<void* const*>(
      Address(database_profile.null_object_instance));
  const auto* database = reinterpret_cast<const unsigned char*>(
      *reinterpret_cast<void* const*>(Address(database_profile.database_instance)));
  if (database == nullptr) {
    return nullptr;
  }
  const auto* objects = *reinterpret_cast<void* const* const*>(
      database + database_profile.objects_data_offset);
  const std::int32_t count = *reinterpret_cast<const std::int32_t*>(
      database + database_profile.objects_count_offset);
  if (objects == nullptr || count < 0 || count > 1000000) {
    return nullptr;
  }
  const auto get_data =
      FunctionAt<CStringDataFn>(profile_.c_string.get_tchar_ptr);
  const auto get_size = FunctionAt<CStringSizeFn>(profile_.c_string.get_size);
  for (std::int32_t index = 0; index < count; ++index) {
    const void* object = objects[index];
    if (object == nullptr || object == null_object) {
      continue;
    }
    const auto* object_key = static_cast<const unsigned char*>(object) +
                             database_profile.object_key_offset;
    const int object_key_size = get_size(object_key);
    if (object_key_size < 0 ||
        static_cast<std::size_t>(object_key_size) != key.size()) {
      continue;
    }
    const char* object_key_data = get_data(object_key);
    if (object_key_data != nullptr &&
        std::memcmp(object_key_data, key.data(), key.size()) == 0) {
      return object;
    }
  }
  return nullptr;
}

const void* GameApi::CurrentGameState() const noexcept {
  if (profile_.core.current_game_state == 0U) {
    return nullptr;
  }
  return *reinterpret_cast<void* const*>(
      Address(profile_.core.current_game_state));
}

void* GameApi::CreateSerializedCommand(
    std::span<const unsigned char> command_body) const noexcept {
  const auto& bindings = profile_.serialized_command;
  if (bindings.create_command_from_bytes == 0U || command_body.empty() ||
      command_body.size() > UINT32_MAX) {
    return nullptr;
  }
  return FunctionAt<CreateCommandFromBytesFn>(
      bindings.create_command_from_bytes)(
      command_body.data(), static_cast<unsigned int>(command_body.size()));
}

void GameApi::ResetCommandSerial(void* command) const noexcept {
  if (command == nullptr) {
    return;
  }
  *reinterpret_cast<std::uint32_t*>(
      static_cast<unsigned char*>(command) +
      profile_.serialized_command.command_serial_offset) = 0xffffffffU;
}

bool GameApi::IsCommandValid(void* command) const noexcept {
  if (command == nullptr) {
    return false;
  }
  const auto* vtable = *reinterpret_cast<void* const* const*>(command);
  if (vtable == nullptr) {
    return false;
  }
  const std::size_t index =
      profile_.serialized_command.command_is_valid_vtable_offset /
      sizeof(void*);
  const void* method = vtable[index];
  if (!IsTextPointer(method)) {
    return false;
  }
  return reinterpret_cast<CommandMethodFn>(const_cast<void*>(method))(
      command, nullptr);
}

void GameApi::DestroyCommand(void* command) const noexcept {
  if (command == nullptr) {
    return;
  }
  const auto* vtable = *reinterpret_cast<void* const* const*>(command);
  if (vtable == nullptr) {
    return;
  }
  const std::size_t index =
      profile_.serialized_command.command_deleting_destructor_vtable_offset /
      sizeof(void*);
  const void* method = vtable[index];
  if (!IsTextPointer(method)) {
    return;
  }
  reinterpret_cast<CommandDestructorFn>(const_cast<void*>(method))(command);
}

void GameApi::PostCommand(void* command) const noexcept {
  FunctionAt<PostCommandFn>(profile_.core.post_command_to_session)(command, false);
}

}  // namespace iag::native_runtime
