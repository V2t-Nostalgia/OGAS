#include "iag_native_runtime/command_producers.h"

#include <algorithm>
#include <array>
#include <cstring>
#include <stdexcept>
#include <utility>

#include "iag_native_runtime/command_builder.h"
#include "iag_native_runtime/game_api.h"

namespace iag::native_runtime {
namespace {

constexpr std::size_t kCandidates = 16U;
constexpr std::size_t kQueryBudget = 64U;

template <typename T>
T Read(const void* object, std::size_t offset) {
  T value{};
  std::memcpy(&value, static_cast<const unsigned char*>(object) + offset, sizeof(T));
  return value;
}

bool AnchorMatches(const GameApi& game, const FunctionAnchor& anchor) {
  return anchor.offset && anchor.prefix && anchor.prefix_size >= 16U && anchor.prefix_size <= 64U &&
      game.IsTextPointer(reinterpret_cast<const void*>(game.Address(anchor.offset))) &&
      game.IsTextPointer(reinterpret_cast<const void*>(game.Address(anchor.offset) + anchor.prefix_size - 1U)) &&
      std::memcmp(reinterpret_cast<const void*>(game.Address(anchor.offset)), anchor.prefix, anchor.prefix_size) == 0;
}

const void* Global(const GameApi& game, std::uintptr_t rva) {
  if (!rva || !game.IsModulePointer(reinterpret_cast<const void*>(game.Address(rva))) ||
      !game.IsModulePointer(reinterpret_cast<const void*>(game.Address(rva) + sizeof(void*) - 1U))) return nullptr;
  return Read<const void*>(reinterpret_cast<const void*>(game.Address(rva)), 0U);
}

const RecoveredObjectDatabase* Database(const RecoveredSdk& sdk, std::string_view type) {
  const RecoveredObjectDatabase* result = nullptr;
  for (const auto& db : sdk.object_databases) {
    if (db.class_name != type) continue;
    if (result != nullptr || !db.database_rva || !db.null_rva) return nullptr;
    result = &db;
  }
  return result;
}

const void* Object(const GameApi& game, const RecoveredSdk& sdk,
                   std::string_view type, std::uint32_t id) {
  const auto* db = Database(sdk, type);
  if (db == nullptr || !game.IsModulePointer(reinterpret_cast<const void*>(game.Address(db->database_rva))) ||
      !game.IsModulePointer(reinterpret_cast<const void*>(game.Address(db->null_rva)))) return nullptr;
  return game.ResolvePdxObject({db->database_rva, db->null_rva, db->id_offset}, id);
}

std::optional<std::uint32_t> Identity(const GameApi& game, const RecoveredSdk& sdk,
                                     std::string_view type, const void* object) {
  const auto* db = Database(sdk, type);
  if (db == nullptr || object == nullptr) return std::nullopt;
  const auto id = Read<std::uint32_t>(object, db->id_offset);
  return Object(game, sdk, type, id) == object ? std::optional{id} : std::nullopt;
}

bool Array(const void* object, std::size_t data_offset, std::size_t count_offset,
           std::size_t maximum, const unsigned char*& data, std::size_t& count) {
  const auto size = Read<std::int32_t>(object, count_offset);
  data = Read<const unsigned char*>(object, data_offset);
  if (size < 0 || static_cast<std::size_t>(size) > maximum || (size && !data)) return false;
  count = static_cast<std::size_t>(size);
  return true;
}

std::string BuildingKey(const GameApi& game, const void* object) {
  const auto& strings = game.profile().c_string;
  const auto offset = game.profile().producer_queries.building_definition_key_offset;
  if (!offset || !strings.get_size || !strings.get_tchar_ptr) return {};
  const auto* key = static_cast<const unsigned char*>(object) + offset;
  const int size = game.FunctionAt<int (*)(const void*)>(strings.get_size)(key);
  if (size <= 0 || size > 256) return {};
  const auto* data = game.FunctionAt<const char* (*)(const void*)>(strings.get_tchar_ptr)(key);
  return data ? std::string(data, static_cast<std::size_t>(size)) : std::string{};
}

bool Research(std::string_view type) {
  return type == "CResearchTechnologyCommand" || type == "CCancelResearchTechnologyCommand";
}

NativeProducerCandidate ResearchCandidate(
    const GameApi& game, const RecoveredSdk& sdk, const RecoveredCommand& command,
    const void* country, std::uint32_t country_id, std::uint32_t index) {
  NativeProducerCandidate result;
  result.country_id = country_id;
  result.source = command.class_name == "CResearchTechnologyCommand" ? "country_research_alternatives" : "country_current_research";
  const auto* status = static_cast<const unsigned char*>(country) + game.profile().producer_queries.technology_status_offset;
  if (Read<const void*>(status, 0x10U) != country) {
    result.reason = "technology_status_country_mismatch";
    return result;
  }
  std::vector<std::pair<const void*, std::string>> candidates;
  for (std::size_t area = 0; area < 3U; ++area) {
    const bool alternatives = command.class_name == "CResearchTechnologyCommand";
    const unsigned char* data = nullptr;
    std::size_t count = 0;
    if (!Array(status, (alternatives ? 0x110U : 0x50U) + area * 24U,
               (alternatives ? 0x11cU : 0x5cU) + area * 24U, 1024U, data, count)) {
      result.reason = "technology_candidate_array_invalid";
      return result;
    }
    const auto scan = std::min(count, kQueryBudget);
    result.truncated = result.truncated || scan != count;
    for (std::size_t i = 0; i < scan; ++i) {
      const auto* technology = Read<const void*>(data, alternatives ? i * 8U : i * 0x28U + 0x18U);
      if (std::any_of(candidates.begin(), candidates.end(), [&](const auto& c) { return c.first == technology; })) continue;
      const auto key = NativeCommandBuilder::DefinitionKeyForObject(game, sdk, "CTechnology", technology);
      if (!key.empty()) candidates.emplace_back(technology, key);
      if (candidates.size() == kCandidates) {
        result.truncated = result.truncated || i + 1U < count || area < 2U;
        break;
      }
    }
    if (candidates.size() == kCandidates) break;
  }
  result.candidate_count = candidates.size();
  if (index >= candidates.size()) {
    result.reason = candidates.empty() ? "no_country_research_candidate" : "candidate_index_exhausted";
    return result;
  }
  result.definition = candidates[index].first;
  result.definition_key = candidates[index].second;
  result.identity = "country=" + std::to_string(country_id) + ";technology=" + result.definition_key;
  if (command.class_name == "CResearchTechnologyCommand") {
    result.native_rule_valid = game.FunctionAt<bool (*)(const void*, const void*, void*)>(
        game.profile().producer_queries.can_queue_research.offset)(status, result.definition, nullptr);
    result.query_calls = 1U;
  }
  return result;
}

// Bound the lists traversed by the native slot query, and validate the returned
// pair against those very lists. Foreign or stale-generation zones never pass.
bool ColonyZones(const GameApi& game, const RecoveredSdk& sdk, const void* colony,
                 std::vector<std::pair<const void*, const void*>>& zones) {
  const unsigned char* districts = nullptr;
  std::size_t count = 0;
  if (!Array(colony, 0x88U, 0x94U, 256U, districts, count)) return false;
  for (std::size_t i = 0; i < count; ++i) {
    const auto* district = Object(game, sdk, "CDistrict", Read<std::uint32_t>(districts, i * 4U));
    if (district == nullptr) return false;
    const unsigned char* data = nullptr;
    std::size_t size = 0;
    if (!Array(district, 0x30U, 0x3cU, 64U, data, size)) return false;
    for (std::size_t j = 0; j < size; ++j) {
      const auto* zone = Object(game, sdk, "CZone", Read<std::uint32_t>(data, j * 4U));
      if (zone == nullptr) return false;
      zones.emplace_back(district, zone);
      if (zones.size() > 1024U) return false;
    }
  }
  return true;
}

NativeProducerCandidate BuildingCandidate(
    const GameApi& game, const RecoveredSdk& sdk, const void* country,
    std::uint32_t country_id, std::uint32_t index) {
  NativeProducerCandidate result;
  result.source = "owned_colony_native_building_slot";
  result.country_id = country_id;
  const auto& bindings = game.profile().producer_queries;
  const void* database = Global(game, bindings.building_types_database);
  const unsigned char* colonies = nullptr;
  const unsigned char* types = nullptr;
  std::size_t colony_count = 0, type_count = 0;
  if (database == nullptr || !Array(database, 0x50U, 0x5cU, 16384U, types, type_count) ||
      !Array(country, bindings.owned_colonies_data_offset, bindings.owned_colonies_count_offset, 4096U, colonies, colony_count)) {
    result.reason = "building_domain_array_invalid_or_unavailable";
    return result;
  }
  std::vector<NativeProducerCandidate> candidates;
  struct ColonyCandidate {
    std::uint32_t id;
    const void* object;
    std::vector<std::pair<const void*, const void*>> zones;
  };
  std::vector<ColonyCandidate> owned;
  for (std::size_t c = 0; c < std::min(colony_count, kCandidates); ++c) {
    const auto id = Read<std::uint32_t>(colonies, c * 4U);
    const auto* colony = Object(game, sdk, "CColony", id);
    if (colony == nullptr) continue;
    ColonyCandidate item{id, colony, {}};
    if (ColonyZones(game, sdk, colony, item.zones)) owned.push_back(std::move(item));
  }
  if (owned.empty()) {
    result.reason = "no_owned_colony_with_bounded_zone_lists";
    return result;
  }
  // Native optional return: engaged byte, padding, district*, zone*. Explicit
  // sret is required on Linux; this function is never called on Windows.
  struct Slot { std::uint64_t engaged; const void* district; const void* zone; };
  static_assert(sizeof(Slot) == 24U);
  using SlotFn = void (*)(Slot*, const void*, const void*, const void*, bool);
  const auto type_scan = std::min<std::size_t>(type_count, 512U);
  for (std::size_t t = 0; t < type_scan && result.query_calls < kQueryBudget; ++t) {
    const auto* definition = Read<const void*>(types, t * 8U);
    if (definition == nullptr) continue;
    const auto key = BuildingKey(game, definition);
    if (key.empty()) continue;
    for (const auto& colony : owned) {
      if (result.query_calls >= kQueryBudget) break;
      Slot slot{};
      ++result.query_calls;
      game.FunctionAt<SlotFn>(bindings.find_building_slot.offset)(&slot, country, colony.object, definition, false);
      if ((slot.engaged & 0xffU) == 0U) continue;
      if (std::find(colony.zones.begin(), colony.zones.end(), std::make_pair(slot.district, slot.zone)) == colony.zones.end() ||
          !Identity(game, sdk, "CDistrict", slot.district)) {
        result.reason = "native_slot_relationship_mismatch";
        return result;
      }
      const auto zone_id = Identity(game, sdk, "CZone", slot.zone);
      if (!zone_id) continue;
      auto candidate = result;
      candidate.colony_id = colony.id;
      candidate.zone_id = *zone_id;
      candidate.colony = colony.object;
      candidate.zone = slot.zone;
      candidate.definition = definition;
      candidate.definition_key = key;
      candidate.native_rule_valid = true;
      candidate.identity = "country=" + std::to_string(country_id) + ";colony=" +
          std::to_string(colony.id) + ";zone=" + std::to_string(*zone_id) + ";building=" + key + ";mode=new";
      candidates.push_back(std::move(candidate));
      if (candidates.size() == kCandidates) break;
    }
    if (candidates.size() == kCandidates) break;
  }
  result.candidate_count = candidates.size();
  result.truncated = result.query_calls == kQueryBudget || candidates.size() == kCandidates || colony_count > kCandidates || type_scan < type_count;
  if (index >= candidates.size()) {
    result.reason = candidates.empty() ? "no_native_building_slot_in_bounded_search" : "candidate_index_exhausted";
    return result;
  }
  auto selected = std::move(candidates[index]);
  selected.query_calls = result.query_calls;
  selected.candidate_count = result.candidate_count;
  selected.truncated = result.truncated;
  return selected;
}

}  // namespace

std::optional<bool> NativeProducerFixturePaused(const GameApi& game) {
  const auto& b = game.profile().producer_queries;
  if (std::string_view(game.profile().platform_id) != "linux-x86_64" ||
      !b.in_game_idler_vtable || !b.idler_paused_offset ||
      !AnchorMatches(game, b.paused_trigger)) return std::nullopt;
  const auto* idler = Global(game, b.current_in_game_idler);
  if (idler == nullptr || Read<std::uintptr_t>(idler, 0U) != game.Address(b.in_game_idler_vtable))
    return std::nullopt;
  const auto paused = Read<unsigned char>(idler, b.idler_paused_offset);
  return paused <= 1U ? std::optional<bool>{paused == 1U} : std::nullopt;
}

std::vector<std::string_view> NativeProducerCommands(const GameApi& game, const RecoveredSdk& sdk) {
  std::vector<std::string_view> result;
  if (sdk.platform != "linux-x86_64" || sdk.platform != game.profile().platform_id || sdk.build_id != game.profile().build_id) return result;
  const auto& b = game.profile().producer_queries;
  if (!b.current_in_game_idler || !b.in_game_idler_vtable || !b.idler_paused_offset ||
      !AnchorMatches(game, b.paused_trigger)) return result;
  for (const auto& command : sdk.commands) {
    if (Research(command.class_name) && b.technology_status_offset && AnchorMatches(game, b.can_queue_research)) result.push_back(command.name);
    if (command.class_name == "CAddBuildableToQueueCommand" && b.owned_colonies_data_offset &&
        b.building_types_database && b.null_building_instance && b.ordinary_buildable_vtable && b.building_definition_key_offset &&
        AnchorMatches(game, b.find_building_slot) && AnchorMatches(game, b.create_building_command) &&
        AnchorMatches(game, b.destroy_building_command_value)) result.push_back(command.name);
  }
  return result;
}

NativeProducerCandidate ResolveNativeProducerCandidate(
    const GameApi& game, const RecoveredSdk& sdk, const RecoveredCommand& command,
    std::uint32_t country_id, std::uint32_t index) {
  const auto supported = NativeProducerCommands(game, sdk);
  NativeProducerCandidate result;
  if (index >= kCandidates || std::find(supported.begin(), supported.end(), command.name) == supported.end()) {
    result.reason = "native_domain_provider_unavailable_for_exact_build";
    return result;
  }
  const auto* country = Object(game, sdk, "CCountry", country_id);
  if (game.CurrentGameState() == nullptr || country == nullptr) {
    result.reason = "native_domain_requires_live_country";
    return result;
  }
  return Research(command.class_name) ? ResearchCandidate(game, sdk, command, country, country_id, index)
                                    : BuildingCandidate(game, sdk, country, country_id, index);
}

bool PopulateNativeProducerCandidate(
    const GameApi& game, const RecoveredSdk& sdk, const NativeProducerCandidate& candidate,
    NativeCommandBuilder& builder, std::string& error) {
  if (!candidate.reason.empty() || candidate.definition == nullptr ||
      Object(game, sdk, "CCountry", candidate.country_id) == nullptr) {
    error = "native_candidate_unresolved_or_stale";
    return false;
  }
  if (Research(builder.metadata().class_name)) {
    return builder.SetObjectId("country", "CCountry", candidate.country_id, error) &&
        builder.SetDefinitionKey("technology", "CTechnology", candidate.definition_key, error);
  }
  if (builder.metadata().class_name != "CAddBuildableToQueueCommand" || builder.metadata().size != 0x30U ||
      Object(game, sdk, "CColony", candidate.colony_id) != candidate.colony ||
      Object(game, sdk, "CZone", candidate.zone_id) != candidate.zone) {
    error = "native_producer_target_or_layout_mismatch";
    return false;
  }
  const auto& b = game.profile().producer_queries;
  const auto* empty_building = Global(game, b.null_building_instance);
  if (empty_building == nullptr) {
    error = "native_null_building_unavailable";
    return false;
  }
  // The native sret function constructs the complete Command and owns its
  // Buildable. Factory allocation + value destructor + sret + deleting dtor
  // avoids both cross-allocator copies and double destruction of scoped_ptr.
  using ProducerFn = void* (*)(void*, std::uint32_t, const void*, const void*, const void*, const void*, bool);
  bool matches = false;
  bool ordinary_branch = false;
  const auto constructed = builder.ReconstructFromProducer(b.destroy_building_command_value.offset,
      [&](void* destination) {
        if (game.FunctionAt<ProducerFn>(b.create_building_command.offset)(destination, candidate.country_id,
            candidate.colony, candidate.zone, candidate.definition, empty_building, false) != destination) return;
        if (Read<std::uintptr_t>(destination, 0U) != game.Address(builder.metadata().vtable_rva)) return;
        const auto* buildable = Read<const void*>(destination, 0x20U);
        if (buildable == nullptr || Read<std::uintptr_t>(buildable, 0U) != game.Address(b.ordinary_buildable_vtable)) return;
        ordinary_branch = true;
        matches = Read<std::uint32_t>(destination, 0x28U) == candidate.country_id &&
            Object(game, sdk, "CConstructionQueue", Read<std::uint32_t>(destination, 0x2cU)) != nullptr &&
            Read<const void*>(buildable, 0x08U) == candidate.definition &&
            Read<std::uint32_t>(buildable, 0x10U) == candidate.colony_id &&
            Read<std::uint32_t>(buildable, 0x14U) == candidate.zone_id &&
            Read<std::uint32_t>(buildable, 0x18U) == Read<std::uint32_t>(empty_building, 8U);
      }, error);
  if (!constructed) return false;
  // Validate only the ordinary new-building branch; other native subtypes are
  // correctly destroyed but not silently assumed to share this semantic mode.
  if (!matches) error = ordinary_branch ? "native_building_producer_branch_or_identity_mismatch"
                                        : "native_building_subtype_not_covered";
  return matches;
}

}  // namespace iag::native_runtime
