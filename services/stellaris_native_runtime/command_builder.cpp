#include "iag_native_runtime/command_builder.h"

#include <cstring>
#include <algorithm>
#include <optional>
#include <stdexcept>
#include <utility>

#include "iag_native_runtime/game_api.h"

namespace iag::native_runtime {
namespace {

using FactoryFn = void* (*)();
using IsValidFn = bool (*)(const void*, void*);
using LinuxDeletingDestructorFn = void (*)(void*);
using WindowsDeletingDestructorFn = void* (*)(void*, unsigned int);

template <typename T>
T Read(const void* object, std::size_t offset) {
  T result{};
  std::memcpy(&result, static_cast<const unsigned char*>(object) + offset, sizeof(T));
  return result;
}

std::vector<StaticDefinitionDatabaseProfile> DefinitionDatabases(
    const GameApi& game, const RecoveredSdk& sdk, std::string_view type) {
  std::vector<StaticDefinitionDatabaseProfile> result;
  for (const auto& db : sdk.definition_databases) {
    if (db.class_name == type) result.push_back({
        db.database_rva, db.null_rva, db.data_offset, db.count_offset, db.key_offset});
  }
  if (!result.empty()) return result;
  const auto& p = game.profile();
  StaticDefinitionDatabaseProfile db{};
  if (type == "CPolicyGroup") db = p.governance_commands.policy_groups;
  else if (type == "CTradition") db = p.governance_commands.traditions;
  else if (type == "CAscensionPerk") db = p.governance_commands.ascension_perks;
  else if (type == "CGovernmentCouncilorType") db = p.governance_commands.council_positions;
  else if (type == "CResolutionType") db = p.galactic_community_commands.resolution_types;
  else if (type == "CWarGoalType") db = p.claim_war_commands.war_goal_types;
  else if (type == "CEspionageOperationType") db = p.situation_espionage_commands.espionage_operation_types;
  if (db.database_instance && db.null_object_instance) result.push_back(db);
  return result;
}

const void* ResolveDefinitionKey(
    const GameApi& game, std::span<const StaticDefinitionDatabaseProfile> databases,
    std::string_view key, bool& ambiguous) {
  const void* result = nullptr;
  ambiguous = false;
  for (const auto& db : databases) {
    const void* object = game.ResolveStaticDefinition(db, key);
    if (object == nullptr) continue;
    if (result != nullptr && result != object) {
      ambiguous = true;
      return nullptr;
    }
    result = object;
  }
  return result;
}

class NativeReason final {
 public:
  explicit NativeReason(const GameApi& game, bool enabled) : game_(game) {
    if (!enabled) return;
    const auto& c = game.profile().c_string;
    if (c.object_size == 0U || c.object_size > 256U || c.construct == 0U ||
        c.destroy == 0U || c.get_tchar_ptr == 0U || c.get_size == 0U) return;
    for (const auto rva : {c.construct, c.destroy, c.get_tchar_ptr, c.get_size}) {
      if (!game.IsTextPointer(reinterpret_cast<const void*>(game.Address(rva)))) return;
    }
    storage_.resize(c.object_size);
    game.FunctionAt<void (*)(void*, const char*)>(c.construct)(storage_.data(), "");
    constructed_ = true;
  }
  ~NativeReason() {
    if (constructed_) game_.FunctionAt<void (*)(void*)>(game_.profile().c_string.destroy)(storage_.data());
  }
  void* get() { return constructed_ ? storage_.data() : nullptr; }
  std::string text() {
    if (!constructed_) return {};
    const auto& c = game_.profile().c_string;
    const auto size = game_.FunctionAt<int (*)(const void*)>(c.get_size)(storage_.data());
    if (size <= 0 || size > 4096) return {};
    const auto* data = game_.FunctionAt<const char* (*)(const void*)>(c.get_tchar_ptr)(storage_.data());
    return data != nullptr ? std::string(data, static_cast<std::size_t>(size)) : std::string{};
  }
 private:
  const GameApi& game_;
  std::vector<unsigned char> storage_;
  bool constructed_ = false;
};

bool VerifyVtable(const GameApi& game, const RecoveredCommand& command) {
  const auto* table = reinterpret_cast<const std::uintptr_t*>(
      game.Address(command.vtable_rva));
  if (!game.IsModulePointer(table) ||
      command.is_valid_slot > 64U || command.deleting_destructor_slot > 64U ||
      command.token_slot > 64U ||
      !game.IsModulePointer(table + command.is_valid_slot) ||
      !game.IsModulePointer(table + command.deleting_destructor_slot) ||
      !game.IsModulePointer(table + command.token_slot) ||
      !game.IsTextPointer(reinterpret_cast<const void*>(game.Address(command.factory_rva))) ||
      !game.IsTextPointer(reinterpret_cast<const void*>(game.Address(command.is_valid_rva))) ||
      !game.IsTextPointer(reinterpret_cast<const void*>(game.Address(command.deleting_destructor_rva))) ||
      !game.IsTextPointer(reinterpret_cast<const void*>(game.Address(command.token_getter_rva)))) {
    return false;
  }
  if (table[command.is_valid_slot] != game.Address(command.is_valid_rva) ||
      table[command.deleting_destructor_slot] != game.Address(command.deleting_destructor_rva) ||
      table[command.token_slot] != game.Address(command.token_getter_rva)) {
    return false;
  }
  const auto* getter = reinterpret_cast<const unsigned char*>(
      game.Address(command.token_getter_rva));
  if (command.token_global_rva != 0U) {
    std::int32_t displacement = 0;
    std::memcpy(&displacement, getter + 3U, sizeof(displacement));
    const auto global = game.Address(command.token_getter_rva) + 7U + displacement;
    return getter[0] == 0x48U && getter[1] == 0x8dU && getter[2] == 0x05U &&
        getter[7] == 0x8bU && getter[8] == 0U && getter[9] == 0xc3U &&
        global == game.Address(command.token_global_rva) &&
        game.IsModulePointer(reinterpret_cast<const void*>(global + 3U)) &&
        Read<std::uint32_t>(reinterpret_cast<const void*>(global), 0U) != 0U &&
        Read<std::uint32_t>(reinterpret_cast<const void*>(global), 0U) != UINT32_MAX;
  }
  std::uint32_t token = 0;
  std::memcpy(&token, getter + 1, sizeof(token));
  return getter[0] == 0xb8U && getter[5] == 0xc3U && token == command.token;
}

void Destroy(const GameApi& game, const RecoveredCommand& metadata, void* command) {
  if (game.profile().platform_id == std::string_view{"windows-x64"}) {
    game.FunctionAt<WindowsDeletingDestructorFn>(metadata.deleting_destructor_rva)(command, 1U);
  } else {
    game.FunctionAt<LinuxDeletingDestructorFn>(metadata.deleting_destructor_rva)(command);
  }
}

}  // namespace

const RecoveredCommand* FindRecoveredCommand(
    const RecoveredSdk& sdk, std::string_view name) noexcept {
  const RecoveredCommand* result = nullptr;
  for (const auto& command : sdk.commands) {
    if (command.name == name || (!command.class_name.empty() && command.class_name == name)) {
      if (result != nullptr) {
        return nullptr;
      }
      result = &command;
    }
  }
  return result;
}

NativeCommandBuilder::NativeCommandBuilder(
    const GameApi& game, const RecoveredSdk& sdk,
    const RecoveredCommand& metadata, void* command)
    : game_(game), sdk_(sdk), metadata_(metadata), command_(command) {}

bool NativeCommandBuilder::Preflight(
    const GameApi& game, const RecoveredSdk& sdk,
    std::string_view command_name, std::string& error) {
  if (sdk.build_id != game.profile().build_id || sdk.platform != game.profile().platform_id) {
    error = "recovered_sdk_build_mismatch";
    return false;
  }
  const auto* metadata = FindRecoveredCommand(sdk, command_name);
  if (metadata == nullptr || metadata->factory_rva == 0U || metadata->size < 0x20U ||
      metadata->size > 1024U * 1024U || metadata->is_valid_rva == 0U ||
      metadata->deleting_destructor_rva == 0U || metadata->token_getter_rva == 0U) {
    error = "recovered_factory_or_lifecycle_unresolved";
    return false;
  }
  if (!VerifyVtable(game, *metadata)) {
    error = "recovered_vtable_or_token_mismatch";
    return false;
  }
  error.clear();
  return true;
}

std::unique_ptr<NativeCommandBuilder> NativeCommandBuilder::Create(
    const GameApi& game, const RecoveredSdk& sdk,
    std::string_view command_name, std::string& error) {
  if (!Preflight(game, sdk, command_name, error)) {
    return nullptr;
  }
  const auto* metadata = FindRecoveredCommand(sdk, command_name);
  void* command = game.FunctionAt<FactoryFn>(metadata->factory_rva)();
  if (command == nullptr) {
    error = "native_factory_returned_null";
    return nullptr;
  }
  std::uintptr_t actual_vtable = 0;
  std::memcpy(&actual_vtable, command, sizeof(actual_vtable));
  if (actual_vtable != game.Address(metadata->vtable_rva)) {
    // The generated factory and object disagree; no arbitrary destructor call.
    error = "native_factory_vtable_mismatch";
    return nullptr;
  }
  error.clear();
  return std::unique_ptr<NativeCommandBuilder>(
      new NativeCommandBuilder(game, sdk, *metadata, command));
}

NativeCommandBuilder::~NativeCommandBuilder() {
  if (command_ != nullptr) {
    Destroy(game_, metadata_, command_);
  }
}

const RecoveredField* NativeCommandBuilder::FindField(
    std::string_view name, std::string& error) const {
  const RecoveredField* result = nullptr;
  for (const auto& field : metadata_.fields) {
    if (field.name == name) {
      if (result != nullptr) {
        error = "ambiguous_recovered_field";
        return nullptr;
      }
      result = &field;
    }
  }
  if (command_ == nullptr || result == nullptr || !result->writable || result->offset < 0x1cU ||
      result->offset >= metadata_.size || result->width == 0U ||
      result->width > metadata_.size - result->offset) {
    error = "recovered_field_not_safely_writable";
    return nullptr;
  }
  return result;
}

bool NativeCommandBuilder::SetObjectId(
    std::string_view name, std::string_view object_class,
    std::uint32_t id, std::string& error) {
  const auto* field = FindField(name, error);
  if (field == nullptr) {
    return false;
  }
  if (field->storage_kind != "ref" || field->reference_type != object_class || field->width != 4U) {
    error = "recovered_reference_type_mismatch";
    return false;
  }
  std::memcpy(static_cast<unsigned char*>(command_) + field->offset, &id, sizeof(id));
  native_validated_ = false;
  return true;
}

bool NativeCommandBuilder::SetUnsigned(
    std::string_view name, std::uint64_t value, std::string& error) {
  const auto* field = FindField(name, error);
  if (field == nullptr) {
    return false;
  }
  const bool bool_ok = field->storage_kind == "bool" && field->width == 1U && value <= 1U;
  const bool u8_ok = field->storage_kind == "u8" && field->width == 1U && value <= UINT8_MAX;
  const bool u32_ok = (field->storage_kind == "u32" || field->storage_kind == "game_date32") && field->width == 4U && value <= UINT32_MAX;
  const bool u64_ok = field->storage_kind == "u64" && field->width == 8U;
  if (!bool_ok && !u8_ok && !u32_ok && !u64_ok) {
    error = "recovered_scalar_type_or_range_mismatch";
    return false;
  }
  if (bool_ok && field->bit_mask != 0U) {
    if (field->bit_mask > UINT8_MAX || (field->bit_mask & (field->bit_mask - 1U)) != 0U) {
      error = "recovered_bit_mask_invalid";
      return false;
    }
    const auto previous = Read<std::uint8_t>(command_, field->offset);
    value = value ? previous | field->bit_mask : previous & ~field->bit_mask;
  }
  std::memcpy(static_cast<unsigned char*>(command_) + field->offset, &value, field->width);
  native_validated_ = false;
  return true;
}

bool NativeCommandBuilder::SetSigned(
    std::string_view name, std::int64_t value, std::string& error) {
  const auto* field = FindField(name, error);
  if (field == nullptr) return false;
  if (!((field->storage_kind == "i32" && field->width == 4U && value >= INT32_MIN && value <= INT32_MAX) ||
        (field->storage_kind == "i64" && field->width == 8U))) {
    error = "recovered_signed_type_or_range_mismatch";
    return false;
  }
  std::memcpy(static_cast<unsigned char*>(command_) + field->offset, &value, field->width);
  native_validated_ = false;
  return true;
}

bool NativeCommandBuilder::SetText(
    std::string_view name, std::string_view value, std::string& error) {
  const auto* field = FindField(name, error);
  if (field == nullptr) return false;
  if (value.size() > 512U || value.find('\0') != std::string_view::npos) {
    error = "native_text_value_invalid";
    return false;
  }
  if (field->storage_kind == "native_text_value") {
    const auto type = std::find_if(sdk_.native_text_values.begin(), sdk_.native_text_values.end(),
        [&](const auto& v) { return v.class_name == field->native_type; });
    if (type == sdk_.native_text_values.end() || type->size != field->width ||
        type->size > 4096U || type->move_assign_rva != field->assignment_rva) {
      error = "native_text_value_lifecycle_unresolved";
      return false;
    }
    for (const auto rva : {type->construct_text_rva, type->move_assign_rva, type->destroy_rva}) {
      if (rva == 0U || !game_.IsTextPointer(reinterpret_cast<const void*>(game_.Address(rva)))) {
        error = "native_text_value_lifecycle_outside_text";
        return false;
      }
    }
    std::vector<unsigned char> temporary(type->size);
    const std::string text(value);
    game_.FunctionAt<void (*)(void*, const char*, bool)>(type->construct_text_rva)(temporary.data(), text.c_str(), true);
    try {
      game_.FunctionAt<void (*)(void*, void*)>(type->move_assign_rva)(
          static_cast<unsigned char*>(command_) + field->offset, temporary.data());
    } catch (...) {
      game_.FunctionAt<void (*)(void*)>(type->destroy_rva)(temporary.data());
      throw;
    }
    game_.FunctionAt<void (*)(void*)>(type->destroy_rva)(temporary.data());
    native_validated_ = false;
    return true;
  }
  if (field->storage_kind != "string" || field->native_type != "CString" ||
      field->width != game_.profile().c_string.object_size || field->assignment_rva == 0U ||
      !game_.IsTextPointer(reinterpret_cast<const void*>(game_.Address(field->assignment_rva))) ||
      value.size() > 512U || value.find('\0') != std::string_view::npos) {
    error = "native_string_assignment_unavailable_or_invalid";
    return false;
  }
  const std::string terminated(value);
  game_.FunctionAt<void (*)(void*, const char*)>(field->assignment_rva)(
      static_cast<unsigned char*>(command_) + field->offset, terminated.c_str());
  native_validated_ = false;
  return true;
}

std::vector<std::string> NativeCommandBuilder::DefinitionCandidates(
    const GameApi& game, const RecoveredSdk& sdk, std::string_view type, std::size_t limit) {
  std::vector<std::string> result;
  const auto databases = DefinitionDatabases(game, sdk, type);
  const auto& c = game.profile().c_string;
  if (databases.empty() || databases.size() > 16U || c.get_size == 0U || c.get_tchar_ptr == 0U || limit > 16U) return result;
  struct Pool { const void* const* objects; std::int32_t count; std::size_t key_offset; };
  std::vector<Pool> pools;
  std::int32_t max_count = 0;
  for (const auto& db : databases) {
    const auto* global = reinterpret_cast<const void*>(game.Address(db.database_instance));
    if (!game.IsModulePointer(global)) continue;
    const void* database = Read<const void*>(global, 0U);
    if (database == nullptr) continue;
    const auto count = Read<std::int32_t>(database, db.objects_count_offset);
    const auto* objects = Read<const void* const*>(database, db.objects_data_offset);
    if (count < 0 || count > 1000000 || objects == nullptr) continue;
    pools.push_back({objects, count, db.object_key_offset});
    max_count = std::max(max_count, count);
  }
  for (std::int32_t i = 0; i < std::min(max_count, 16384) && result.size() < limit; ++i) {
    for (const auto& pool : pools) {
      if (i >= pool.count || pool.objects[i] == nullptr) continue;
      const auto* key = static_cast<const unsigned char*>(pool.objects[i]) + pool.key_offset;
      const int size = game.FunctionAt<int (*)(const void*)>(c.get_size)(key);
      if (size <= 0 || size > 256) continue;
      const auto* data = game.FunctionAt<const char* (*)(const void*)>(c.get_tchar_ptr)(key);
      if (data == nullptr) continue;
      std::string value(data, static_cast<std::size_t>(size));
      bool ambiguous = false;
      if (ResolveDefinitionKey(game, databases, value, ambiguous) == pool.objects[i] &&
          !ambiguous && std::find(result.begin(), result.end(), value) == result.end()) result.push_back(std::move(value));
      if (result.size() == limit) break;
    }
  }
  return result;
}

std::string NativeCommandBuilder::DefinitionKeyForObject(
    const GameApi& game, const RecoveredSdk& sdk, std::string_view type,
    const void* object) {
  if (object == nullptr || game.profile().c_string.get_size == 0U ||
      game.profile().c_string.get_tchar_ptr == 0U) return {};
  const auto databases = DefinitionDatabases(game, sdk, type);
  for (const auto& db : databases) {
    if (!db.database_instance || !game.IsModulePointer(
            reinterpret_cast<const void*>(game.Address(db.database_instance)))) continue;
    const auto* database = Read<const void*>(reinterpret_cast<const void*>(game.Address(db.database_instance)), 0U);
    if (database == nullptr) continue;
    const auto count = Read<std::int32_t>(database, db.objects_count_offset);
    const auto* data = Read<const void* const*>(database, db.objects_data_offset);
    if (count <= 0 || count > 16384 || data == nullptr) continue;
    if (std::find(data, data + count, object) == data + count) continue;
    const auto* key = static_cast<const unsigned char*>(object) + db.object_key_offset;
    const int size = game.FunctionAt<int (*)(const void*)>(game.profile().c_string.get_size)(key);
    if (size <= 0 || size > 256) return {};
    const auto* text = game.FunctionAt<const char* (*)(const void*)>(game.profile().c_string.get_tchar_ptr)(key);
    if (text == nullptr) return {};
    std::string value(text, static_cast<std::size_t>(size));
    bool ambiguous = false;
    return ResolveDefinitionKey(game, databases, value, ambiguous) == object && !ambiguous ? value : "";
  }
  return {};
}

bool NativeCommandBuilder::ReconstructFromProducer(
    std::uintptr_t value_destructor_rva,
    const std::function<void(void*)>& construct, std::string& error) {
  // This first adapter is the proven Itanium/SysV primary value destructor.
  // A Windows scalar-deleting destructor is not an equivalent ABI.
  const auto* table = reinterpret_cast<const std::uintptr_t*>(game_.Address(metadata_.vtable_rva));
  if (sdk_.platform != "linux-x86_64" || command_ == nullptr || !construct ||
      !metadata_.lifecycle_probe_safe || value_destructor_rva == 0U ||
      value_destructor_rva == metadata_.deleting_destructor_rva ||
      !game_.IsTextPointer(reinterpret_cast<const void*>(game_.Address(value_destructor_rva))) ||
      table[0] != game_.Address(value_destructor_rva)) {
    error = "native_producer_value_lifecycle_unresolved";
    return false;
  }
  void* allocation = command_;
  command_ = nullptr;
  native_validated_ = false;
  game_.FunctionAt<void (*)(void*)>(value_destructor_rva)(allocation);
  construct(allocation);
  if (Read<std::uintptr_t>(allocation, 0U) != game_.Address(metadata_.vtable_rva)) {
    // No safe dynamic type/lifetime can be assumed for this allocation now.
    throw std::runtime_error("native_producer_vtable_mismatch_object_quarantined");
  }
  command_ = allocation;
  error.clear();
  return true;
}

bool NativeCommandBuilder::SetDefinitionKey(
    std::string_view name, std::string_view type, std::string_view key, std::string& error) {
  const auto* field = FindField(name, error);
  if (field == nullptr) return false;
  const auto databases = DefinitionDatabases(game_, sdk_, type);
  if (field->storage_kind != "definition_pointer" || field->native_type != type ||
      field->width != sizeof(void*) || databases.empty() || databases.size() > 16U) {
    error = "recovered_definition_type_or_resolver_mismatch";
    return false;
  }
  bool ambiguous = false;
  const void* object = ResolveDefinitionKey(game_, databases, key, ambiguous);
  if (ambiguous) {
    error = "ambiguous_live_definition_key";
    return false;
  }
  if (object == nullptr) {
    error = "no_live_definition_candidate";
    return false;
  }
  std::memcpy(static_cast<unsigned char*>(command_) + field->offset, &object, sizeof(object));
  native_validated_ = false;
  return true;
}

bool NativeCommandBuilder::SetReferenceList(
    std::string_view name, std::string_view type,
    std::span<const std::uint32_t> ids, std::string& error) {
  const auto* field = FindField(name, error);
  if (field == nullptr) return false;
  if (field->storage_kind != "reference_array" || field->reference_type != type ||
      field->width != 24U || field->assignment_rva == 0U || ids.empty() || ids.size() > 16U ||
      !game_.IsTextPointer(reinterpret_cast<const void*>(game_.Address(field->assignment_rva)))) {
    error = "recovered_reference_array_type_or_assignment_mismatch";
    return false;
  }
  auto* array = static_cast<unsigned char*>(command_) + field->offset;
  if (Read<std::int32_t>(array, 20U) != 0) {
    error = "native_array_not_empty";
    return false;
  }
  for (std::size_t i = 0; i < ids.size(); ++i) {
    void* reference = game_.FunctionAt<void* (*)(void*, int)>(field->assignment_rva)(array, static_cast<int>(i));
    const auto* data = Read<const unsigned char*>(array, 8U);
    if (reference == nullptr || data == nullptr || reference != data + i * sizeof(std::uint32_t) ||
        Read<std::int32_t>(array, 20U) != static_cast<std::int32_t>(i + 1U)) {
      error = "native_array_assignment_result_mismatch";
      return false;
    }
    std::memcpy(reference, &ids[i], sizeof(ids[i]));
  }
  native_validated_ = false;
  return true;
}

bool NativeCommandBuilder::IsValid(std::string* reason) {
  NativeReason text(game_, reason != nullptr);
  native_validated_ = command_ != nullptr &&
      game_.FunctionAt<IsValidFn>(metadata_.is_valid_rva)(command_, reason != nullptr ? text.get() : nullptr);
  if (reason != nullptr) *reason = text.text();
  return native_validated_;
}

void* NativeCommandBuilder::ReleaseForSubmission() noexcept {
  if (!native_validated_) {
    return nullptr;
  }
  void* result = command_;
  command_ = nullptr;
  return result;
}

const RecoveredCommand& NativeCommandBuilder::metadata() const noexcept {
  return metadata_;
}

}  // namespace iag::native_runtime
