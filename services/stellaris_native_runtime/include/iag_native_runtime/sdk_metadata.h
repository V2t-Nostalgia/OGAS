#pragma once

#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>

namespace iag::native_runtime {

// Engine structure evidence only. These records never register semantic tools
// or establish live execution evidence.
struct RecoveredField {
  std::string_view name;
  std::string_view storage_kind;
  std::string_view reference_type;
  std::size_t offset;
  std::size_t width;
  bool writable;
  std::string_view native_type{};
  std::uintptr_t assignment_rva = 0;
  std::uint64_t bit_mask = 0;
  std::span<const std::int64_t> scalar_candidates{};
};

struct RecoveredCommand {
  std::string_view name;
  std::string_view class_name;
  std::uint32_t token;
  std::uintptr_t vtable_rva;
  std::uintptr_t factory_rva;
  std::size_t size;
  std::uintptr_t is_valid_rva;
  std::uintptr_t deleting_destructor_rva;
  std::uintptr_t token_getter_rva;
  std::size_t is_valid_slot;
  std::size_t deleting_destructor_slot;
  std::size_t token_slot;
  std::span<const RecoveredField> fields;
  // Conservative serializer coverage, not permission to submit this command.
  bool flat_layout_complete = false;
  bool population_layout_complete = false;
  std::uintptr_t token_global_rva = 0;
  bool lifecycle_probe_safe = false;
  bool context_free_validator = false;
};

struct RecoveredSymbol {
  std::string_view name;
  std::uintptr_t rva;
};

struct RecoveredObjectDatabase {
  std::string_view class_name;
  std::uintptr_t database_rva;
  std::uintptr_t null_rva;
  std::size_t id_offset;
};

struct RecoveredDefinitionDatabase {
  std::string_view class_name;
  std::uintptr_t database_rva;
  std::uintptr_t null_rva;
  std::size_t data_offset;
  std::size_t count_offset;
  std::size_t key_offset;
};

struct RecoveredNativeTextValue {
  std::string_view class_name;
  std::size_t size;
  std::uintptr_t construct_text_rva;
  std::uintptr_t move_assign_rva;
  std::uintptr_t destroy_rva;
};

enum class ScopedIdKind { member_u32, member_u16, definition_index };

// IDs scoped to one proven command-country field, never global TPdxRef values.
struct RecoveredScopedIdBinding {
  std::string_view command_class;
  std::size_t field_offset;
  std::size_t country_field_offset;
  std::string_view class_name;
  ScopedIdKind kind;
  std::uintptr_t lookup_rva;
  std::uintptr_t null_rva;
  std::size_t data_offset;
  std::size_t count_offset;
  std::size_t member_offset;
  bool reverse;
  std::uintptr_t definition_database_rva = 0;
  std::uintptr_t definition_null_rva = 0;
  std::size_t definition_data_offset = 0;
  std::size_t definition_count_offset = 0;
};

struct RecoveredSdk {
  std::string_view platform;
  std::string_view build_id;
  std::string_view binary_sha256;
  std::span<const RecoveredCommand> commands;
  std::span<const RecoveredSymbol> functions;
  std::span<const RecoveredSymbol> globals;
  std::span<const RecoveredObjectDatabase> object_databases{};
  std::span<const RecoveredDefinitionDatabase> definition_databases{};
  std::span<const RecoveredNativeTextValue> native_text_values{};
  std::span<const RecoveredScopedIdBinding> scoped_id_bindings{};
  std::string_view metadata_fingerprint{};
};

[[nodiscard]] const RecoveredSdk& ActiveRecoveredSdk() noexcept;
[[nodiscard]] const RecoveredCommand* FindRecoveredCommand(
    const RecoveredSdk& sdk, std::string_view name) noexcept;

}  // namespace iag::native_runtime
