#include "iag_native_runtime/sdk_probe.h"

#include <algorithm>
#include <chrono>
#include <charconv>
#include <cstring>
#include <exception>
#include <map>
#include <optional>
#include <sstream>
#include <vector>

#include "iag_native_runtime/command_builder.h"
#include "iag_native_runtime/command_producers.h"
#include "iag_native_runtime/game_api.h"

namespace iag::native_runtime {
namespace {

constexpr std::size_t kScanLimit = 16384U;
constexpr std::size_t kCandidateLimit = 16U;
using Clock = std::chrono::steady_clock;

template <typename T>
std::optional<T> Number(std::string_view value) {
  T result{};
  const auto parsed = std::from_chars(value.data(), value.data() + value.size(), result);
  if (value.empty() || parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size()) return std::nullopt;
  return result;
}

bool ConstraintToken(std::string_view value, std::size_t maximum) {
  return !value.empty() && value.size() <= maximum && std::all_of(value.begin(), value.end(), [](char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
        c == '_' || c == '.' || c == ':' || c == '-';
  });
}

template <typename T>
T Read(const void* object, std::size_t offset) {
  T value{};
  std::memcpy(&value, static_cast<const unsigned char*>(object) + offset, sizeof(T));
  return value;
}

std::string Quote(std::string_view value) {
  std::string result = "\"";
  for (const unsigned char c : value) {
    if (c == '"' || c == '\\') result += '\\';
    if (c >= 0x20U) result += static_cast<char>(c);
  }
  return result + '"';
}

std::optional<ObjectDatabaseProfile> DatabaseFor(
    const BuildProfile& p, const RecoveredSdk& sdk, std::string_view type) {
  for (const auto& db : sdk.object_databases) {
    if (db.class_name == type) return ObjectDatabaseProfile{db.database_rva, db.null_rva, db.id_offset};
  }
  ObjectDatabaseProfile db{};
  if (type == "CCountry") db = p.diplomatic_action.countries;
  else if (type == "CFleet") db = p.move_fleet.fleets;
  else if (type == "CGalacticObject") db = p.move_fleet.galactic_objects;
  else if (type == "CLeader") db = p.leader_commands.leaders;
  else if (type == "CResolution") db = p.galactic_community_commands.resolutions;
  else if (type == "CWar") db = p.diplomatic_action.wars;
  else if (type == "CSpecies") db = p.species_rights_commands.species;
  else if (type == "CSituation") db = p.situation_espionage_commands.situations;
  else if (type == "CSpyNetwork") db = p.situation_espionage_commands.spy_networks;
  else if (type == "CEspionageOperation") db = p.situation_espionage_commands.espionage_operations;
  if (db.database_instance == 0U || db.null_object_instance == 0U) return std::nullopt;
  return db;
}

struct Candidates {
  std::vector<std::uint32_t> ids;
  bool truncated = false;
};

const RecoveredScopedIdBinding* ScopedBindingFor(
    const RecoveredSdk& sdk, const RecoveredCommand& command, const RecoveredField& field) {
  const RecoveredScopedIdBinding* result = nullptr;
  if (field.storage_kind != "u32" || field.width != 4U || !field.writable) return nullptr;
  for (const auto& binding : sdk.scoped_id_bindings) {
    if (binding.command_class != command.class_name || binding.field_offset != field.offset) continue;
    if (result != nullptr) return nullptr;
    const auto country = std::find_if(command.fields.begin(), command.fields.end(), [&](const auto& f) {
      return f.offset == binding.country_field_offset && f.storage_kind == "ref" &&
          f.reference_type == "CCountry" && f.width == 4U && f.writable;
    });
    if (country == command.fields.end() || binding.country_field_offset == field.offset) return nullptr;
    result = &binding;
  }
  return result;
}

Candidates EnumerateScoped(
    const GameApi& game, const RecoveredScopedIdBinding& binding, const void* country,
    std::size_t& lookup_calls, std::string& error) {
  constexpr std::size_t kMemberScanLimit = 256U;
  Candidates result;
  const auto global = [&](std::uintptr_t rva) -> const void* {
    if (rva == 0U || !game.IsModulePointer(reinterpret_cast<const void*>(game.Address(rva))) ||
        !game.IsModulePointer(reinterpret_cast<const void*>(game.Address(rva) + sizeof(void*) - 1U))) {
      error = "scoped_global_outside_module";
      return nullptr;
    }
    return Read<const void*>(reinterpret_cast<const void*>(game.Address(rva)), 0U);
  };
  if (country == nullptr || binding.lookup_rva == 0U ||
      !game.IsTextPointer(reinterpret_cast<const void*>(game.Address(binding.lookup_rva))) ||
      (binding.kind != ScopedIdKind::member_u32 && binding.kind != ScopedIdKind::member_u16 &&
       binding.kind != ScopedIdKind::definition_index) ||
      binding.data_offset > 65535U || binding.count_offset > 65535U || binding.member_offset > 65535U) {
    error = "scoped_recipe_or_resolver_invalid";
    return result;
  }
  const void* null_object = global(binding.null_rva);
  if (!error.empty()) return result;
  const auto count = Read<std::int32_t>(country, binding.count_offset);
  const auto* objects = Read<const unsigned char*>(country, binding.data_offset);
  if (count < 0 || count > 1000000 || (count != 0 && objects == nullptr)) {
    error = "scoped_array_bounds_invalid";
    return result;
  }
  std::map<const void*, std::uint32_t> definitions;
  if (count != 0 && binding.kind == ScopedIdKind::definition_index) {
    if (binding.definition_data_offset > 65535U || binding.definition_count_offset > 65535U) {
      error = "scoped_definition_offsets_invalid";
      return result;
    }
    const void* database = global(binding.definition_database_rva);
    const void* null_definition = global(binding.definition_null_rva);
    if (!error.empty() || database == nullptr) return result;
    const auto size = Read<std::int32_t>(database, binding.definition_count_offset);
    const auto* data = Read<const unsigned char*>(database, binding.definition_data_offset);
    if (size < 0 || size > 1000000 || (size != 0 && data == nullptr)) {
      error = "scoped_definition_bounds_invalid";
      return result;
    }
    const auto scan = std::min<std::size_t>(static_cast<std::size_t>(size), 4096U);
    result.truncated = static_cast<std::size_t>(size) > scan;
    for (std::size_t index = 0; index < scan; ++index) {
      const void* definition = Read<const void*>(data, index * sizeof(void*));
      if (definition != nullptr && definition != null_definition) {
        definitions.emplace(definition, static_cast<std::uint32_t>(index));
      }
    }
  }
  const auto scan = std::min<std::size_t>(static_cast<std::size_t>(count), kMemberScanLimit);
  result.truncated = result.truncated || static_cast<std::size_t>(count) > scan;
  using LookupFn = const void* (*)(const void*, std::uint32_t);
  const auto lookup = game.FunctionAt<LookupFn>(binding.lookup_rva);
  for (std::size_t i = 0; i < scan; ++i) {
    const auto index = binding.reverse ? static_cast<std::size_t>(count) - i - 1U : i;
    const void* object = Read<const void*>(objects, index * sizeof(void*));
    if (object == nullptr || object == null_object) continue;
    std::uint32_t id;
    if (binding.kind == ScopedIdKind::member_u32) id = Read<std::uint32_t>(object, binding.member_offset);
    else if (binding.kind == ScopedIdKind::member_u16) id = Read<std::uint16_t>(object, binding.member_offset);
    else if (binding.kind == ScopedIdKind::definition_index) {
      const auto found = definitions.find(Read<const void*>(object, binding.member_offset));
      if (found == definitions.end()) continue;
      id = found->second;
    } else {
      error = "scoped_identity_kind_unsupported";
      return {};
    }
    if (std::find(result.ids.begin(), result.ids.end(), id) != result.ids.end()) continue;
    if (lookup_calls >= kMemberScanLimit) {
      result.truncated = true;
      break;
    }
    ++lookup_calls;
    if (lookup(country, id) != object) continue;
    result.ids.push_back(id);
    if (result.ids.size() == kCandidateLimit) {
      result.truncated = result.truncated || i + 1U < scan;
      break;
    }
  }
  return result;
}

Candidates Enumerate(
    const GameApi& game, const ObjectDatabaseProfile& db,
    std::string_view type, std::uint32_t country, bool foreign_fleets = false) {
  Candidates result;
  const auto* global = reinterpret_cast<const void*>(game.Address(db.database_instance));
  const auto* null_global = reinterpret_cast<const void*>(game.Address(db.null_object_instance));
  if (!game.IsModulePointer(global) || !game.IsModulePointer(null_global)) return result;
  const void* database = Read<const void*>(global, 0U);
  const void* null_object = Read<const void*>(null_global, 0U);
  if (database == nullptr) return result;
  const auto count = Read<std::uint32_t>(database, 0x20U);
  const auto* entries = Read<const unsigned char*>(database, 0x18U);
  if (count > 1000000U || entries == nullptr) return result;
  std::vector<std::uint32_t> other;
  const auto scan = std::min<std::size_t>(count, kScanLimit);
  for (std::size_t index = 0; index < scan; ++index) {
    const void* object = Read<const void*>(entries, index * 0x10U + 8U);
    if (object == nullptr || object == null_object) continue;
    const auto id = Read<std::uint32_t>(object, db.object_id_offset);
    if (id == UINT32_MAX || (id & 0x00ffffffU) != index ||
        game.ResolvePdxObject(db, id) != object) continue;
    bool preferred = false;
    if (type == "CFleet" && game.profile().move_fleet.fleet_get_controller_ref != 0U) {
      using ControllerFn = std::uint32_t (*)(const void*);
      const auto owner = game.FunctionAt<ControllerFn>(
          game.profile().move_fleet.fleet_get_controller_ref)(object);
      preferred = foreign_fleets ? owner != country : owner == country;
    } else if (type == "CCountry") {
      preferred = id == country;
    }
    auto& destination = preferred ? result.ids : other;
    if (destination.size() < kCandidateLimit) destination.push_back(id);
    if (result.ids.size() == kCandidateLimit) break;
  }
  result.truncated = count > scan;
  for (const auto id : other) {
    if (result.ids.size() >= kCandidateLimit) break;
    result.ids.push_back(id);
  }
  return result;
}

struct Binding {
  const RecoveredField* field;
  std::uint32_t value;
  std::string text{};
  std::vector<std::uint32_t> ids{};
  std::int64_t signed_value = 0;
};

struct Report {
  std::string status = "not_tested";
  std::string reason;
  bool structure_checked = false;
  bool constructed = false;
  bool destroyed = false;
  bool populated = false;
  std::optional<bool> valid;
  std::optional<bool> fixture_paused;
  std::optional<std::uint32_t> country;
  std::optional<std::uint32_t> date_before;
  std::optional<std::uint32_t> date_after;
  std::uintptr_t world_identity = 0U;
  std::size_t candidate_count = 0;
  bool scan_truncated = false;
  std::size_t scoped_lookup_calls = 0;
  std::vector<Binding> bindings;
  std::string native_reason;
  std::optional<NativeProducerCandidate> producer;
  std::int64_t create_us = 0;
  std::int64_t populate_us = 0;
  std::int64_t validate_us = 0;
  std::int64_t destroy_us = 0;
};

bool PlanConstraintCandidate(
    const GameApi& game, const RecoveredSdk& sdk, const RecoveredCommand& command,
    const RecoveredConstraintCandidate& candidate, Report& report) {
  report.status = "not_tested";
  if (!command.lifecycle_probe_safe) {
    report.reason = "constraint_plan_lifecycle_not_proven_safe";
    return false;
  }
  if (candidate.sdk_fingerprint != sdk.metadata_fingerprint ||
      candidate.expected_world != reinterpret_cast<std::uintptr_t>(game.CurrentGameState()) ||
      !report.date_before || candidate.expected_date != *report.date_before) {
    report.reason = "constraint_plan_stale_world_date_or_sdk";
    return false;
  }
  if (!command.flat_layout_complete && !command.population_layout_complete) {
    report.reason = "incomplete_or_nonflat_serializer_layout";
    return false;
  }
  if (candidate.bindings.empty() || candidate.bindings.size() != command.fields.size()) {
    report.reason = "constraint_plan_incomplete_fields";
    return false;
  }
  for (const auto& value : candidate.bindings) {
    const auto field = std::find_if(command.fields.begin(), command.fields.end(),
        [&](const auto& f) { return f.name == value.field; });
    if (field == command.fields.end() || !field->writable || field->storage_kind != value.storage_kind ||
        std::any_of(report.bindings.begin(), report.bindings.end(), [&](const auto& b) { return b.field == &*field; })) {
      report.reason = "constraint_plan_field_or_type_mismatch";
      return false;
    }
    Binding binding{&*field, 0U};
    if (field->storage_kind == "ref") {
      const auto id = Number<std::uint32_t>(value.value);
      const auto database = DatabaseFor(game.profile(), sdk, field->reference_type);
      if (!id || *id == UINT32_MAX || !database || game.ResolvePdxObject(*database, *id) == nullptr) {
        report.reason = "constraint_plan_reference_generation_unresolved";
        return false;
      }
      binding.value = *id;
    } else if (field->storage_kind == "definition_pointer") {
      if (!ConstraintToken(value.value, 128U)) {
        report.reason = "constraint_plan_invalid_definition_key";
        return false;
      }
      binding.text = value.value;
    } else if (field->storage_kind == "i64") {
      const auto number = Number<std::int64_t>(value.value);
      if (!number || field->width != sizeof(std::int64_t)) {
        report.reason = "constraint_plan_invalid_i64_value_or_width";
        return false;
      }
      if (!field->scalar_candidates.empty() &&
          std::find(field->scalar_candidates.begin(), field->scalar_candidates.end(), *number) == field->scalar_candidates.end()) {
        report.reason = "constraint_plan_i64_outside_recovered_domain";
        return false;
      }
      binding.signed_value = *number;
    } else if (field->storage_kind == "i32" || field->storage_kind == "u32" || field->storage_kind == "bool") {
      const auto number = Number<std::int64_t>(value.value);
      if (!number || (field->storage_kind == "i32" && (*number < INT32_MIN || *number > INT32_MAX)) ||
          (field->storage_kind == "u32" && (*number < 0 || *number > UINT32_MAX)) ||
          (field->storage_kind == "bool" && (*number < 0 || *number > 1)) ||
          (field->storage_kind != "bool" && std::find(field->scalar_candidates.begin(), field->scalar_candidates.end(), *number) == field->scalar_candidates.end())) {
        report.reason = "constraint_plan_scalar_without_recovered_domain";
        return false;
      }
      binding.value = static_cast<std::uint32_t>(*number);
    } else {
      report.reason = "constraint_plan_field_kind_not_supported";
      return false;
    }
    report.bindings.push_back(std::move(binding));
  }
  report.candidate_count = 1U;
  report.status = "not_tested";
  report.reason.clear();
  return true;
}

std::int64_t Elapsed(Clock::time_point start) {
  return std::chrono::duration_cast<std::chrono::microseconds>(Clock::now() - start).count();
}

bool PlanBindings(
    const GameApi& game, const RecoveredSdk& sdk, const RecoveredCommand& command,
    const RecoveredProbeOptions& options, Report& report) {
  if (!command.flat_layout_complete && !command.population_layout_complete) {
    report.reason = "incomplete_or_nonflat_serializer_layout";
    return false;
  }
  bool has_reference = false;
  for (const auto& field : command.fields) {
    const bool scalar_enum = field.storage_kind == "i32" && !field.scalar_candidates.empty();
    const bool text = ((field.storage_kind == "string" && field.native_type == "CString") || field.storage_kind == "native_text_value") &&
        (field.name == "name" || field.name == "male" || field.name == "female");
    const bool scoped_id = ScopedBindingFor(sdk, command, field) != nullptr;
    if (!field.writable || (field.storage_kind != "ref" && field.storage_kind != "bool" &&
        field.storage_kind != "reference_array" && field.storage_kind != "definition_pointer" && field.storage_kind != "game_date32" && !scalar_enum && !text && !scoped_id)) {
      report.reason = "semantic_mapping_required:" + std::string(field.name) + ":" +
                      std::string(field.storage_kind);
      return false;
    }
    if (field.storage_kind == "ref" || field.storage_kind == "reference_array") {
      has_reference = true;
      if (!DatabaseFor(game.profile(), sdk, field.reference_type)) {
        report.reason = "object_resolver_unavailable:" + std::string(field.reference_type);
        return false;
      }
    }
  }
  if (!has_reference && !command.context_free_validator) {
    report.reason = "no_game_object_scope";
    return false;
  }
  if (game.CurrentGameState() == nullptr) {
    report.reason = "probe_requires_loaded_session";
    return false;
  }
  const auto countries = DatabaseFor(game.profile(), sdk, "CCountry");
  if (!countries) {
    report.reason = "object_resolver_unavailable:CCountry";
    return false;
  }
  auto country = options.country_id;
  if (!country) {
    const void* local = game.LocalObservedCountry();
    if (local != nullptr) {
      const auto id = game.CountryId(local);
      if (game.ResolvePdxObject(*countries, id) == local) country = id;
    }
    if (!country) {
      const auto candidates = Enumerate(game, *countries, "CCountry", UINT32_MAX);
      if (!candidates.ids.empty()) country = candidates.ids.front();
    }
  }
  if (!country || game.ResolvePdxObject(*countries, *country) == nullptr) {
    report.status = "missing_parameters";
    report.reason = "no_live_country_candidate";
    return false;
  }
  report.country = country;
  report.world_identity = reinterpret_cast<std::uintptr_t>(game.CurrentGameState());
  std::map<std::pair<std::string_view, bool>, Candidates> pools;
  std::size_t combinations = 1U;
  for (const auto& field : command.fields) {
    if (const auto* scoped = ScopedBindingFor(sdk, command, field)) {
      const void* actor = game.ResolvePdxObject(*countries, *country);
      std::string error;
      const auto candidates = EnumerateScoped(game, *scoped, actor, report.scoped_lookup_calls, error);
      report.scan_truncated = report.scan_truncated || candidates.truncated;
      if (!error.empty()) {
        report.status = "structure_failed";
        report.reason = error;
        return false;
      }
      if (candidates.ids.empty()) {
        report.status = "missing_parameters";
        report.reason = "no_live_scoped_candidate:" + std::string(scoped->class_name);
        return false;
      }
      report.bindings.push_back({&field, candidates.ids[options.candidate_index % candidates.ids.size()]});
      combinations = std::min(kCandidateLimit, combinations * candidates.ids.size());
      continue;
    }
    if (field.storage_kind == "bool") {
      report.bindings.push_back({&field, 0U});
      continue;
    }
    if (field.storage_kind == "game_date32") {
      const auto off = game.profile().claim_war_commands.current_game_date_offset;
      if (off == 0U) {
        report.reason = "game_date_source_unavailable";
        return false;
      }
      report.bindings.push_back({&field, Read<std::uint32_t>(game.CurrentGameState(), off)});
      continue;
    }
    if (field.storage_kind == "i32" && !field.scalar_candidates.empty()) {
      const auto value = field.scalar_candidates[(options.candidate_index + report.bindings.size()) % field.scalar_candidates.size()];
      if (value < 0 || value > UINT32_MAX) {
        report.reason = "enum_candidate_out_of_supported_range";
        return false;
      }
      report.bindings.push_back({&field, static_cast<std::uint32_t>(value)});
      combinations = std::min(kCandidateLimit, combinations * field.scalar_candidates.size());
      continue;
    }
    if (field.storage_kind == "definition_pointer") {
      const auto keys = NativeCommandBuilder::DefinitionCandidates(game, sdk, field.native_type, kCandidateLimit);
      if (keys.empty()) {
        report.status = "missing_parameters";
        report.reason = "definition_candidates_unavailable:" + std::string(field.native_type);
        return false;
      }
      report.bindings.push_back({&field, 0U, keys[(options.candidate_index + report.bindings.size()) % keys.size()]});
      combinations = std::min(kCandidateLimit, combinations * keys.size());
      continue;
    }
    if (field.storage_kind == "string" || field.storage_kind == "native_text_value") {
      report.bindings.push_back({&field, 0U, "OGAS SDK validation"});
      continue;
    }
    std::vector<std::uint32_t> ids;
    if (field.reference_type == "CCountry" &&
        (field.name == "country" || field.name == "actor" || field.name == "owner" ||
         field.name == "paying_country" || field.name.ends_with(".country") ||
         std::any_of(command.fields.begin(), command.fields.end(), [&](const auto& f) {
           const auto* b = ScopedBindingFor(sdk, command, f);
           return b != nullptr && b->country_field_offset == field.offset;
         }))) {
      // Actor roles are fixed; other typed country references are candidates,
      // not a claim that any proposed diplomatic relationship is legal.
      ids.push_back(*country);
    } else if (field.reference_type == "CLeader" && options.leader_id) {
      const auto db = DatabaseFor(game.profile(), sdk, field.reference_type);
      if (game.ResolvePdxObject(*db, *options.leader_id) != nullptr) {
        ids.push_back(*options.leader_id);
      }
    } else {
      const bool foreign = field.reference_type == "CFleet" &&
          (field.name == "target" || field.name == "target_fleet");
      const auto pool_key = std::make_pair(field.reference_type, foreign);
      if (!pools.contains(pool_key)) {
        pools.emplace(pool_key, Enumerate(
            game, *DatabaseFor(game.profile(), sdk, field.reference_type),
            field.reference_type, *country, foreign));
      }
      const auto& pool = pools.at(pool_key);
      ids = pool.ids;
      report.scan_truncated = report.scan_truncated || pool.truncated;
    }
    if (ids.empty()) {
      report.status = "missing_parameters";
      report.reason = "no_live_candidate:" + std::string(field.reference_type);
      return false;
    }
    const auto selection = (options.candidate_index + report.bindings.size()) % ids.size();
    const auto selected = ids[selection];
    Binding binding{&field, selected};
    if (field.storage_kind == "reference_array") {
      binding.ids.push_back(selected);
      if (ids.size() > 1U) binding.ids.push_back(ids[(selection + 1U) % ids.size()]);
    }
    report.bindings.push_back(std::move(binding));
    combinations = std::min(kCandidateLimit, combinations * ids.size());
  }
  report.candidate_count = combinations;
  if (options.candidate_index >= combinations) {
    report.reason = "candidate_index_exhausted";
    return false;
  }
  return true;
}

bool PlanNativeProducer(
    const GameApi& game, const RecoveredSdk& sdk, const RecoveredCommand& command,
    const RecoveredProbeOptions& options, Report& report) {
  const auto countries = DatabaseFor(game.profile(), sdk, "CCountry");
  if (!countries || game.CurrentGameState() == nullptr) {
    report.reason = "native_domain_requires_loaded_country_database";
    return false;
  }
  std::vector<std::uint32_t> ids;
  if (options.country_id) {
    ids.push_back(*options.country_id);
  } else {
    if (const auto* local = game.LocalObservedCountry()) {
      const auto local_id = game.CountryId(local);
      if (game.ResolvePdxObject(*countries, local_id) == local) ids.push_back(local_id);
    }
    for (const auto id : Enumerate(game, *countries, "CCountry", UINT32_MAX).ids) {
      if (ids.size() == kCandidateLimit) break;
      if (std::find(ids.begin(), ids.end(), id) == ids.end()) ids.push_back(id);
    }
  }
  if (ids.empty()) {
    report.status = "missing_parameters";
    report.reason = "no_live_country_candidate";
    return false;
  }
  report.world_identity = reinterpret_cast<std::uintptr_t>(game.CurrentGameState());
  for (const auto id : ids) {
    report.country = id;
    report.producer = ResolveNativeProducerCandidate(game, sdk, command, id, options.candidate_index);
    // Skip empty countries without native calls. Do not multiply the native
    // query budget by scanning many countries after a rule evaluation.
    if (report.producer->reason.empty() || report.producer->query_calls != 0U || options.country_id ||
        report.producer->reason == "native_domain_provider_unavailable_for_exact_build" ||
        report.producer->reason.find("mismatch") != std::string::npos) break;
  }
  report.candidate_count = report.producer->candidate_count;
  report.scan_truncated = report.producer->truncated;
  report.reason = report.producer->reason;
  if (!report.reason.empty()) {
    report.status = report.reason == "native_domain_provider_unavailable_for_exact_build" ? "not_tested" : "missing_parameters";
    return false;
  }
  return true;
}

StateQueryResult Serialize(
    const RecoveredSdk& sdk, const RecoveredCommand* command,
    std::string_view name, const RecoveredProbeOptions& options,
    const Report& r, Clock::time_point start) {
  std::ostringstream out;
  out << "{\"schema_version\":\"iag.native_command_validation.v2\","
      << "\"command_name\":" << Quote(name)
      << ",\"class_name\":" << Quote(command == nullptr ? "" : command->class_name)
      << ",\"build_id\":" << Quote(sdk.build_id)
      << ",\"status\":" << Quote(r.status) << ",\"reason\":" << Quote(r.reason)
      << ",\"structure_checked\":" << (r.structure_checked ? "true" : "false")
      << ",\"constructed_from_generated_metadata\":" << (r.constructed ? "true" : "false")
      << ",\"destroyed\":" << (r.destroyed ? "true" : "false")
      << ",\"parameters_populated\":" << (r.populated ? "true" : "false")
      << ",\"native_is_valid\":" << (r.valid ? (*r.valid ? "true" : "false") : "null")
      << ",\"native_reason\":" << Quote(r.native_reason)
      << ",\"validator_kind\":" << Quote(command != nullptr && command->context_free_validator
          ? "context_free_constant" : "native_predicate")
      << ",\"country_id\":" << (r.country ? std::to_string(*r.country) : "null")
      << ",\"world_identity\":" << r.world_identity
      << ",\"candidate_index\":" << options.candidate_index
      << ",\"candidate_count\":" << r.candidate_count
      << ",\"candidate_scan_truncated\":" << (r.scan_truncated ? "true" : "false")
      << ",\"candidate_source\":" << Quote(options.constraint_candidate ? "constraint_plan" : options.native_domain ? "native_domain" : "legacy_bounded")
      << ",\"parameter_source\":" << Quote(options.constraint_candidate ? "offline_script_native_producer_constraints" : r.producer ? r.producer->source : "legacy_independent_pools")
      << ",\"candidate_identity\":" << Quote(options.constraint_candidate ? options.constraint_candidate->identity : r.producer ? r.producer->identity : "")
      << ",\"domain_query_calls\":" << (r.producer ? r.producer->query_calls : 0U)
      << ",\"native_rule_valid\":" << (r.producer && r.producer->native_rule_valid
            ? (*r.producer->native_rule_valid ? "true" : "false") : "null")
      << ",\"scoped_lookup_calls\":" << r.scoped_lookup_calls
      << ",\"run_game_update\":" << (options.run_game_update ? "true" : "false")
      << ",\"fixture_paused\":" << (r.fixture_paused ? (*r.fixture_paused ? "true" : "false") : "null")
      << ",\"game_date_before\":" << (r.date_before ? std::to_string(*r.date_before) : "null")
      << ",\"game_date_after\":" << (r.date_after ? std::to_string(*r.date_after) : "null")
      << ",\"elapsed_us\":" << Elapsed(start)
      << ",\"create_us\":" << r.create_us << ",\"populate_us\":" << r.populate_us
      << ",\"validate_us\":" << r.validate_us << ",\"destroy_us\":" << r.destroy_us
      << ",\"factory_rva\":" << (command == nullptr ? 0U : command->factory_rva)
      << ",\"vtable_rva\":" << (command == nullptr ? 0U : command->vtable_rva)
      << ",\"object_size\":" << (command == nullptr ? 0U : command->size)
      << ",\"submitted\":false,\"execution_verified\":false,\"bindings\":[";
  bool first = true;
  for (const auto& b : r.bindings) {
    if (!first) out << ',';
    first = false;
    out << "{\"field\":" << Quote(b.field->name)
        << ",\"storage_kind\":" << Quote(b.field->storage_kind)
        << ",\"reference_type\":" << Quote(b.field->reference_type)
        << ",\"value\":";
    if (b.field->storage_kind == "i64") out << b.signed_value;
    else out << b.value;
    out << ",\"text_value\":" << Quote(b.text)
        << ",\"reference_ids\":[";
    for (std::size_t i = 0; i < b.ids.size(); ++i) {
      if (i) out << ',';
      out << b.ids[i];
    }
    out << "]}";
  }
  out << "]}";
  return {"confirmed", out.str(), "native_validation_only_no_submission"};
}

}  // namespace

std::optional<RecoveredConstraintCandidate> ParseRecoveredConstraintCandidate(std::span<const std::string> fields) {
  if (fields.size() != 6U || fields[4].size() > 8192U) return std::nullopt;
  const auto world = Number<std::uint64_t>(fields[0]);
  const auto date = Number<std::uint32_t>(fields[1]);
  const auto instance = Number<std::uint64_t>(fields[5]);
  const auto hash = [](std::string_view text) {
    return text.size() == 64U && std::all_of(text.begin(), text.end(), [](char c) {
      return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
    });
  };
  if (!world || *world == 0U || !date || !instance || *instance == 0U || !hash(fields[2]) || !hash(fields[3])) return std::nullopt;
  RecoveredConstraintCandidate candidate{*world, *date, fields[2], fields[3], {}, *instance};
  std::string_view remaining = fields[4];
  while (!remaining.empty()) {
    if (candidate.bindings.size() >= 32U) return std::nullopt;
    const auto end = remaining.find('|');
    const auto entry = remaining.substr(0U, end);
    const auto first = entry.find('~');
    const auto second = first == std::string_view::npos ? first : entry.find('~', first + 1U);
    if (second == std::string_view::npos || entry.find('~', second + 1U) != std::string_view::npos) return std::nullopt;
    const auto name = entry.substr(0U, first);
    const auto kind = entry.substr(first + 1U, second - first - 1U);
    const auto value = entry.substr(second + 1U);
    if (!ConstraintToken(name, 96U) || value.empty() || value.size() > 128U ||
        (kind != "ref" && kind != "i32" && kind != "i64" && kind != "u32" && kind != "bool" && kind != "definition_pointer")) return std::nullopt;
    if (kind == "definition_pointer" ? !ConstraintToken(value, 128U) : !Number<std::int64_t>(value)) return std::nullopt;
    if (std::any_of(candidate.bindings.begin(), candidate.bindings.end(), [&](const auto& b) { return b.field == name; })) return std::nullopt;
    candidate.bindings.push_back({std::string(name), std::string(kind), std::string(value)});
    if (end == std::string_view::npos) break;
    remaining.remove_prefix(end + 1U);
    if (remaining.empty()) return std::nullopt;
  }
  if (candidate.bindings.empty()) return std::nullopt;
  return candidate;
}

std::string DescribeRecoveredCommands(
    const RecoveredSdk& sdk, std::uint32_t process_id, std::uint64_t instance_id, const GameApi* game) {
  std::ostringstream out;
  out << "{\"schema_version\":\"iag.recovered_command_catalog.v1\",\"build_id\":"
      << Quote(sdk.build_id) << ",\"process_id\":" << process_id
      << ",\"sdk_fingerprint\":" << Quote(sdk.metadata_fingerprint)
      << ",\"instance_id\":" << instance_id << ",\"probe_revision\":7,\"native_candidate_commands\":[";
  bool first_provider = true;
  if (game != nullptr) {
    for (const auto name : NativeProducerCommands(*game, sdk)) {
      if (!first_provider) out << ',';
      first_provider = false;
      out << Quote(name);
    }
  }
  out << "],\"commands\":[";
  bool first = true;
  for (const auto& command : sdk.commands) {
    if (!first) out << ',';
    first = false;
    out << Quote(command.name);
  }
  out << "]}";
  return out.str();
}

StateQueryResult ProbeRecoveredCommand(
    const GameApi& game, const RecoveredSdk& sdk, std::string_view command_name,
    const RecoveredProbeOptions& options) {
  const auto start = Clock::now();
  const auto* command = FindRecoveredCommand(sdk, command_name);
  Report report;
  if (options.constraint_candidate) report.country = options.country_id;
  const void* initial_world = game.CurrentGameState();
  const auto date_offset = game.profile().claim_war_commands.current_game_date_offset;
  if (initial_world != nullptr) {
    report.world_identity = reinterpret_cast<std::uintptr_t>(initial_world);
    if (date_offset) report.date_before = Read<std::uint32_t>(initial_world, date_offset);
  }
  std::string error;
  if (options.native_domain || options.constraint_candidate) report.fixture_paused = NativeProducerFixturePaused(game);
  if (options.candidate_index >= kCandidateLimit) {
    report.reason = "candidate_index_out_of_range";
  } else if ((options.native_domain || options.constraint_candidate) && report.fixture_paused != true) {
    report.reason = report.fixture_paused ? "native_domain_requires_paused_fixture"
                                          : "native_domain_pause_state_unavailable";
  } else if (!NativeCommandBuilder::Preflight(game, sdk, command_name, error)) {
    report.status = "structure_failed";
    report.reason = error;
  } else {
    report.structure_checked = true;
    bool population_ready = false;
    try {
      population_ready = options.constraint_candidate ? PlanConstraintCandidate(game, sdk, *command, *options.constraint_candidate, report)
                          : options.native_domain ? PlanNativeProducer(game, sdk, *command, options, report)
                                               : PlanBindings(game, sdk, *command, options, report);
    } catch (...) {
      report.status = "call_exception";
      report.reason = "native_candidate_resolution_exception";
      return Serialize(sdk, command, command_name, options, report, start);
    }
    const bool lifecycle_only = !options.native_domain && !options.constraint_candidate && !population_ready && report.status != "structure_failed" &&
        command->lifecycle_probe_safe && game.CurrentGameState() != nullptr;
    if (population_ready || lifecycle_only) {
      const void* world = game.CurrentGameState();
      if (world != nullptr && date_offset != 0U) {
        report.date_before = Read<std::uint32_t>(world, date_offset);
      }
      std::unique_ptr<NativeCommandBuilder> builder;
      try {
        auto stage = Clock::now();
        builder = NativeCommandBuilder::Create(game, sdk, command_name, error);
        report.create_us = Elapsed(stage);
        if (builder == nullptr) {
          report.status = "structure_failed";
          report.reason = error;
        } else {
          report.constructed = true;
          stage = Clock::now();
          bool populated = population_ready;
          if (options.native_domain && report.producer) {
            populated = PopulateNativeProducerCandidate(game, sdk, *report.producer, *builder, error);
          }
          for (const auto& b : report.bindings) {
            if (!population_ready) break;
            if (b.field->storage_kind == "ref") populated = builder->SetObjectId(b.field->name, b.field->reference_type, b.value, error);
            else if (b.field->storage_kind == "reference_array") populated = builder->SetReferenceList(b.field->name, b.field->reference_type, b.ids, error);
            else if (b.field->storage_kind == "definition_pointer") populated = builder->SetDefinitionKey(b.field->name, b.field->native_type, b.text, error);
            else if (b.field->storage_kind == "string" || b.field->storage_kind == "native_text_value") populated = builder->SetText(b.field->name, b.text, error);
            else if (b.field->storage_kind == "i64") populated = builder->SetSigned(b.field->name, b.signed_value, error);
            else if (b.field->storage_kind == "i32") populated = builder->SetSigned(b.field->name,
                options.constraint_candidate ? static_cast<std::int32_t>(b.value) : static_cast<std::int64_t>(b.value), error);
            else populated = builder->SetUnsigned(b.field->name, b.value, error);
            if (!populated) break;
          }
          report.populate_us = Elapsed(stage);
          report.populated = populated;
          if (populated) {
            stage = Clock::now();
            report.valid = builder->IsValid(&report.native_reason);
            report.validate_us = Elapsed(stage);
            report.status = *report.valid ? "native_valid" : "native_invalid";
            report.reason = *report.valid ? "native_is_valid_true" : "native_is_valid_false_unclassified";
          } else if (population_ready) {
            report.status = error == "native_building_subtype_not_covered" ? "not_tested" : "structure_failed";
            report.reason = error;
          }
          stage = Clock::now();
          builder.reset();
          report.destroy_us = Elapsed(stage);
          report.destroyed = true;
        }
      } catch (const std::exception&) {
        const bool owned = builder != nullptr && builder->owns_command();
        builder.reset();
        report.destroyed = owned;
        report.status = "call_exception";
        report.reason = "native_cpp_exception";
      } catch (...) {
        const bool owned = builder != nullptr && builder->owns_command();
        builder.reset();
        report.destroyed = owned;
        report.status = "call_exception";
        report.reason = "native_unknown_cpp_exception";
      }
      if (world != nullptr && date_offset != 0U && game.CurrentGameState() == world) {
        report.date_after = Read<std::uint32_t>(world, date_offset);
      }
    }
  }
  if (initial_world != nullptr && date_offset && game.CurrentGameState() == initial_world) {
    report.date_after = Read<std::uint32_t>(initial_world, date_offset);
  }
  if (options.constraint_candidate && report.valid &&
      (game.CurrentGameState() != initial_world || report.date_before != report.date_after ||
       report.date_after != options.constraint_candidate->expected_date || NativeProducerFixturePaused(game) != true)) {
    report.valid.reset();
    report.status = "not_tested";
    report.reason = "constraint_plan_fixture_changed_during_validation";
  }
  return Serialize(sdk, command, command_name, options, report, start);
}

}  // namespace iag::native_runtime
