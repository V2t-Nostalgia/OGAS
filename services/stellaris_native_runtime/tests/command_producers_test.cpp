#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <new>
#include <stdexcept>
#include <string>
#include <vector>

#include "iag_native_runtime/command_builder.h"
#include "iag_native_runtime/command_producers.h"
#include "iag_native_runtime/game_api.h"
#include "iag_native_runtime/sdk_probe.h"

namespace {
using namespace iag::native_runtime;
constexpr std::uint32_t kCountry = 0x03000003U;
constexpr std::uint32_t kColony = 0x04000004U;
constexpr std::uint32_t kZone = 0x05000005U;
constexpr std::uint32_t kDistrict = 0x06000006U;
constexpr std::uint32_t kQueue = 0x07000007U;

template <typename T> void Put(void* at, std::size_t offset, T value) {
  std::memcpy(static_cast<unsigned char*>(at) + offset, &value, sizeof(value));
}
template <typename T> T Read(const void* at, std::size_t offset) {
  T value{}; std::memcpy(&value, static_cast<const unsigned char*>(at) + offset, sizeof(value)); return value;
}
bool Expect(bool value, const char* message) {
  if (!value) std::cerr << message << '\n';
  return value;
}

std::array<std::uintptr_t, 12> g_table{};
std::array<unsigned char, 6> g_token{0xb8, 0x34, 0x12, 0, 0, 0xc3};
std::uintptr_t g_buildable_vtable = 0;
int g_factories = 0, g_value_dtors = 0, g_deleting_dtors = 0;
int g_children = 0, g_child_dtors = 0, g_validators = 0, g_producers = 0, g_queries = 0;
bool g_rule = true, g_bad_zone = false, g_bad_producer = false, g_throw_producer = false;
bool g_capture_i64 = false;
std::array<std::int64_t, 2> g_populated_i64{};
std::size_t g_factory_size = 0x30U;
void* g_last_allocation = nullptr;
std::array<unsigned char, 0x2800> g_country{};
std::array<unsigned char, 0xa0> g_colony{};
std::array<unsigned char, 0x40> g_district{};
std::array<unsigned char, 0x20> g_zone{}, g_queue{}, g_null_building{};

void DestroyValue(void* object) {
  ++g_value_dtors;
  if (auto* child = Read<unsigned char*>(object, 0x20U)) {
    ++g_child_dtors; delete[] child;
  }
}
void Delete(void* object) {
  ++g_deleting_dtors; DestroyValue(object);
  if (g_last_allocation == object) g_last_allocation = nullptr;
  ::operator delete(object);
}
void* Factory() {
  ++g_factories;
  auto* object = ::operator new(g_factory_size);
  g_last_allocation = object;
  std::memset(object, 0, g_factory_size);
  Put(object, 0U, reinterpret_cast<std::uintptr_t>(g_table.data()));
  return object;
}
bool Validate(const void* object, void*) {
  ++g_validators;
  if (g_capture_i64) g_populated_i64 = {Read<std::int64_t>(object, 0x30U), Read<std::int64_t>(object, 0x38U)};
  return Read<std::uint32_t>(object, 0x28U) == kCountry && g_rule;
}

struct Definition { std::array<unsigned char, 16> pad{}; std::string key; };
Definition g_building{{}, "building_fixture"}, g_tech{{}, "tech_fixture"};
struct Slot { std::uint64_t engaged; const void* district; const void* zone; };
void FindSlot(Slot* slot, const void* country, const void* colony, const void* type, bool mode) {
  ++g_queries;
  if (country != g_country.data() || colony != g_colony.data() || type != &g_building || mode) throw std::runtime_error("wrong query context");
  *slot = {1U, g_district.data(), g_bad_zone ? g_queue.data() : g_zone.data()};
}
void* Produce(void* destination, std::uint32_t country, const void* colony, const void* zone,
              const void* type, const void* building, bool mode) {
  ++g_producers;
  if (g_throw_producer) throw std::runtime_error("fixture constructor failed");
  if (country != kCountry || colony != g_colony.data() || zone != g_zone.data() ||
      type != &g_building || building != g_null_building.data() || mode) throw std::runtime_error("wrong producer ABI/arguments");
  auto* child = new unsigned char[0x20U]{}; ++g_children;
  Put(child, 0U, g_buildable_vtable);
  Put(child, 8U, type); Put(child, 0x10U, kColony); Put(child, 0x14U, kZone);
  Put(child, 0x18U, UINT32_MAX);
  Put(destination, 0U, reinterpret_cast<std::uintptr_t>(g_table.data()));
  Put(destination, 0x20U, child); Put(destination, 0x28U, country);
  Put(destination, 0x2cU, g_bad_producer ? UINT32_MAX : kQueue);
  return destination;
}
bool CanResearch(const void* status, const void* technology, void*) {
  ++g_queries;
  if (status != g_country.data() + 0x15e0U || technology != &g_tech) throw std::runtime_error("wrong research context");
  return g_rule;
}
void TextConstruct(void* value, const char* text) { new (value) std::string(text); }
void TextDestroy(void* value) { static_cast<std::string*>(value)->~basic_string(); }
const char* TextData(const void* value) { return static_cast<const std::string*>(value)->data(); }
int TextSize(const void* value) { return static_cast<int>(static_cast<const std::string*>(value)->size()); }

struct Entry { std::uintptr_t pad; const void* object; };
struct ObjectDb { std::array<unsigned char, 24> pad{}; const Entry* entries; std::uint32_t count; };
struct DefinitionDb { std::array<unsigned char, 0x50> pad{}; const void* const* data; std::uint32_t capacity; std::int32_t count; };

FunctionAnchor Anchor(const char* name, std::uintptr_t address, std::array<unsigned char, 16>& prefix) {
  std::memcpy(prefix.data(), reinterpret_cast<const void*>(address), prefix.size());
  return {name, address, prefix.data(), prefix.size()};
}

// Test-only stdio transport for the real Python codec and C++ probe/Builder.
// All function pointers, objects and database entries belong to this fixture.
int ConstraintWireFixture(const GameApi& game, const RecoveredSdk& sdk, const void* state) {
  std::cout << "{\"world_identity\":" << reinterpret_cast<std::uintptr_t>(state)
            << ",\"game_date\":12345,\"country_id\":" << kCountry << ",\"queue_id\":" << kQueue
            << ",\"catalog\":" << DescribeRecoveredCommands(sdk, 1U, 99U) << "}\n" << std::flush;
  std::string line;
  while (std::getline(std::cin, line)) {
    std::vector<std::string> fields;
    std::size_t start = 0U;
    for (;;) {
      const auto end = line.find('\t', start);
      fields.push_back(line.substr(start, end == std::string::npos ? end : end - start));
      if (end == std::string::npos) break;
      start = end + 1U;
    }
    if (fields.size() != 14U || fields[0] != "IAG1" || fields[2] != "validate_recovered_command" ||
        fields[4] != "coordinate_fixture" || fields[7] != "constraint_plan") return 2;
    auto candidate = ParseRecoveredConstraintCandidate(std::span<const std::string>(fields).subspan(8U));
    if (!candidate || candidate->expected_instance != 99U) return 2;
    RecoveredProbeOptions options{}; options.constraint_candidate = &*candidate;
    const int before = g_factories;
    const auto result = ProbeRecoveredCommand(game, sdk, fields[4], options);
    for (const auto& binding : candidate->bindings) {
      if (binding.storage_kind == "i64") {
        const auto index = binding.field == "point.x" ? 0U : 1U;
        if (g_populated_i64[index] != std::stoll(binding.value)) return 3;
      }
    }
    if (g_factories != before + 1 || g_factories != g_deleting_dtors || g_producers != 0) return 3;
    std::cout << "IAG1\t" << fields[1] << '\t' << fields[2] << '\t' << result.outcome << '\t'
              << sdk.build_id << '\t' << fields[3] << '\t' << result.payload << '\t' << result.detail
              << '\n' << std::flush;
  }
  return 0;
}
}  // namespace

int main(int argc, char** argv) {
  bool ok = true;
  BuildProfile profile{};
  profile.platform_id = "linux-x86_64"; profile.build_id = "producer-fixture";
  profile.claim_war_commands.current_game_date_offset = 8U;
  profile.c_string = {sizeof(std::string), reinterpret_cast<std::uintptr_t>(&TextConstruct),
      reinterpret_cast<std::uintptr_t>(&TextDestroy), reinterpret_cast<std::uintptr_t>(&TextData), reinterpret_cast<std::uintptr_t>(&TextSize)};
  std::array<unsigned char, 16> query_prefix{}, slot_prefix{}, producer_prefix{}, destructor_prefix{};
  auto& b = profile.producer_queries;
  b.can_queue_research = Anchor("rule", reinterpret_cast<std::uintptr_t>(&CanResearch), query_prefix);
  b.find_building_slot = Anchor("slot", reinterpret_cast<std::uintptr_t>(&FindSlot), slot_prefix);
  b.create_building_command = Anchor("producer", reinterpret_cast<std::uintptr_t>(&Produce), producer_prefix);
  b.destroy_building_command_value = Anchor("dtor", reinterpret_cast<std::uintptr_t>(&DestroyValue), destructor_prefix);
  b.technology_status_offset = 0x15e0U; b.owned_colonies_data_offset = 0x2690U; b.owned_colonies_count_offset = 0x269cU;
  b.building_definition_key_offset = 0x10U;
  b.paused_trigger = b.can_queue_research;
  std::array<unsigned char, 16> idler{};
  const void* idler_pointer = idler.data();
  b.current_in_game_idler = reinterpret_cast<std::uintptr_t>(&idler_pointer);
  b.in_game_idler_vtable = reinterpret_cast<std::uintptr_t>(g_table.data());
  b.idler_paused_offset = 8U;
  Put(idler.data(), 0U, b.in_game_idler_vtable);
  Put(idler.data(), 8U, static_cast<unsigned char>(1U));
  b.ordinary_buildable_vtable = reinterpret_cast<std::uintptr_t>(&g_buildable_vtable);
  g_buildable_vtable = b.ordinary_buildable_vtable;
  g_table[0] = reinterpret_cast<std::uintptr_t>(&DestroyValue);
  g_table[1] = reinterpret_cast<std::uintptr_t>(&Delete);
  g_table[9] = reinterpret_cast<std::uintptr_t>(&Validate);
  g_table[11] = reinterpret_cast<std::uintptr_t>(g_token.data());
  const std::array<RecoveredField, 2> fields{{
      {"country", "ref", "CCountry", 0x28U, 4U, true},
      {"queue", "ref", "CConstructionQueue", 0x2cU, 4U, true}}};
  std::array<RecoveredCommand, 1> commands{{{"building", "CAddBuildableToQueueCommand", 0x1234U,
      reinterpret_cast<std::uintptr_t>(g_table.data()), reinterpret_cast<std::uintptr_t>(&Factory), 0x30U,
      g_table[9], g_table[1], g_table[11], 9U, 1U, 11U, fields, false, false, 0U, true, false}}};
  RecoveredSdk sdk{"linux-x86_64", "producer-fixture", "fixture", commands, {}, {}};
  std::array<Entry, 8> entries{};
  entries[3].object = g_country.data(); entries[4].object = g_colony.data(); entries[5].object = g_zone.data();
  entries[6].object = g_district.data(); entries[7].object = g_queue.data();
  ObjectDb db{{}, entries.data(), static_cast<std::uint32_t>(entries.size())};
  const void* database = &db;
  const void* null_object = nullptr;
  std::array<RecoveredObjectDatabase, 5> objects{{
      {"CCountry", reinterpret_cast<std::uintptr_t>(&database), reinterpret_cast<std::uintptr_t>(&null_object), 0x20U},
      {"CColony", reinterpret_cast<std::uintptr_t>(&database), reinterpret_cast<std::uintptr_t>(&null_object), 0x10U},
      {"CZone", reinterpret_cast<std::uintptr_t>(&database), reinterpret_cast<std::uintptr_t>(&null_object), 8U},
      {"CDistrict", reinterpret_cast<std::uintptr_t>(&database), reinterpret_cast<std::uintptr_t>(&null_object), 8U},
      {"CConstructionQueue", reinterpret_cast<std::uintptr_t>(&database), reinterpret_cast<std::uintptr_t>(&null_object), 8U}}};
  sdk.object_databases = objects;
  profile.diplomatic_action.countries = {objects[0].database_rva, objects[0].null_rva, 0x20U};
  std::array<unsigned char, 16> world{};
  Put(world.data(), 8U, std::uint32_t{12345}); const void* state = world.data();
  profile.core.current_game_state = reinterpret_cast<std::uintptr_t>(&state);
  Put(g_country.data(), 0x20U, kCountry); Put(g_colony.data(), 0x10U, kColony);
  Put(g_zone.data(), 8U, kZone); Put(g_district.data(), 8U, kDistrict); Put(g_queue.data(), 8U, kQueue);
  Put(g_null_building.data(), 8U, UINT32_MAX);
  const void* empty_building = g_null_building.data();
  b.null_building_instance = reinterpret_cast<std::uintptr_t>(&empty_building);
  std::array<std::uint32_t, 1> colonies{kColony}, districts{kDistrict}, zones{kZone};
  Put(g_country.data(), 0x2690U, colonies.data()); Put(g_country.data(), 0x269cU, std::int32_t{1});
  Put(g_colony.data(), 0x88U, districts.data()); Put(g_colony.data(), 0x94U, std::int32_t{1});
  Put(g_district.data(), 0x30U, zones.data()); Put(g_district.data(), 0x3cU, std::int32_t{1});
  std::array<const void*, 1> building_types{&g_building}, technologies{&g_tech};
  DefinitionDb types{{}, building_types.data(), 1U, 1}; const void* types_ptr = &types;
  b.building_types_database = reinterpret_cast<std::uintptr_t>(&types_ptr);
  GameApi game(0U, profile);
  const std::array<RecoveredField, 4> coordinate_fields{{
      fields[0], fields[1], {"point.x", "i64", "", 0x30U, 8U, true}, {"point.y", "i64", "", 0x38U, 8U, true}}};
  if (argc == 3 && std::string_view(argv[1]) == "--i64-wire") {
    const std::string fingerprint(64U, 'a');
    profile.build_id = argv[2];
    sdk.build_id = argv[2];
    sdk.metadata_fingerprint = fingerprint;
    commands[0].name = "coordinate_fixture";
    commands[0].fields = coordinate_fields;
    commands[0].size = g_factory_size = 0x40U;
    commands[0].flat_layout_complete = true;
    g_capture_i64 = true;
    return ConstraintWireFixture(game, sdk, state);
  }
  if (argc != 1) return 2;
  RecoveredProbeOptions options{}; options.country_id = kCountry; options.native_domain = true;
  const auto first = ProbeRecoveredCommand(game, sdk, "building", options);
  ok &= Expect(first.payload.find("\"native_is_valid\":true") != std::string::npos &&
      first.payload.find("building=building_fixture;mode=new") != std::string::npos &&
      first.payload.find(std::to_string(kCountry)) != std::string::npos, "producer did not preserve correlated IDs/key or validate");
  ok &= Expect(g_producers == 1 && g_factories == 1 && g_validators == 1 && g_deleting_dtors == 1 &&
      g_value_dtors == 2 && g_children == g_child_dtors, "factory/value/owned child lifetime was not paired");
  const auto repeated = ProbeRecoveredCommand(game, sdk, "building", options);
  ok &= Expect(repeated.payload.find("building=building_fixture;mode=new") != std::string::npos &&
      g_children == g_child_dtors, "same state repeated construction lost semantic identity or ownership");
  // A generated constraint plan uses the exact same factory/field setters/
  // IsValid/destructor lane. No native producer or session submission is used.
  const std::string fingerprint(64U, 'a');
  sdk.metadata_fingerprint = fingerprint;
  const std::array<std::string, 6> constraint_fields{{
      std::to_string(reinterpret_cast<std::uintptr_t>(state)), "12345", std::string(64U, 'b'), fingerprint,
      "country~ref~" + std::to_string(kCountry) + "|queue~ref~" + std::to_string(kQueue), "99"}};
  auto constraint = ParseRecoveredConstraintCandidate(constraint_fields);
  ok &= Expect(constraint.has_value(), "typed constraint plan did not parse");
  auto invalid_fields = constraint_fields;
  invalid_fields[4] += "|country~ref~1";
  ok &= Expect(!ParseRecoveredConstraintCandidate(invalid_fields), "duplicate constraint fields accepted");
  invalid_fields[4] = "country~raw_pointer~123";
  ok &= Expect(!ParseRecoveredConstraintCandidate(invalid_fields), "raw pointer field accepted");
  invalid_fields = constraint_fields; invalid_fields[0] = "18446744073709551616";
  ok &= Expect(!ParseRecoveredConstraintCandidate(invalid_fields), "overflowing world identity accepted");
  if (!constraint) return 1;
  RecoveredProbeOptions constraint_options{};
  constraint_options.constraint_candidate = &*constraint;
  commands[0].flat_layout_complete = true;
  const int constraint_factory_before = g_factories, constraint_validator_before = g_validators;
  const int constraint_producer_before = g_producers;
  const auto constraint_result = ProbeRecoveredCommand(game, sdk, "building", constraint_options);
  ok &= Expect(constraint_result.payload.find("\"candidate_source\":\"constraint_plan\"") != std::string::npos &&
      constraint_result.payload.find("\"native_is_valid\":true") != std::string::npos &&
      g_factories == constraint_factory_before + 1 && g_validators == constraint_validator_before + 1 &&
      g_factories == g_deleting_dtors && g_producers == constraint_producer_before,
      "constraint plan did not share the paired non-submitting Builder lane");
  constraint->expected_date = 12346U;
  const auto stale_constraint = ProbeRecoveredCommand(game, sdk, "building", constraint_options);
  ok &= Expect(stale_constraint.payload.find("constraint_plan_stale_world_date_or_sdk") != std::string::npos &&
      g_factories == constraint_factory_before + 1, "stale constraint plan called a factory");
  constraint->expected_date = 12345U;
  constraint->bindings[0].value = "3";  // same slot, wrong generation
  const auto wrong_generation = ProbeRecoveredCommand(game, sdk, "building", constraint_options);
  ok &= Expect(wrong_generation.payload.find("constraint_plan_reference_generation_unresolved") != std::string::npos &&
      g_factories == constraint_factory_before + 1, "stale reference reached a factory");
  constraint->bindings[0].value = std::to_string(kCountry);
  constraint->bindings[0].storage_kind = "u32";
  const auto wrong_type = ProbeRecoveredCommand(game, sdk, "building", constraint_options);
  ok &= Expect(wrong_type.payload.find("constraint_plan_field_or_type_mismatch") != std::string::npos &&
      g_factories == constraint_factory_before + 1, "wrong typed field reached a factory");
  commands[0].lifecycle_probe_safe = false;
  const auto unproven_lifecycle = ProbeRecoveredCommand(game, sdk, "building", constraint_options);
  ok &= Expect(unproven_lifecycle.payload.find("constraint_plan_lifecycle_not_proven_safe") != std::string::npos &&
      g_factories == constraint_factory_before + 1, "unproven lifecycle reached a factory");
  commands[0].lifecycle_probe_safe = true;
  {
    const auto original = commands[0];
    commands[0].fields = coordinate_fields;
    commands[0].size = g_factory_size = 0x40U;
    g_capture_i64 = true;
    const std::array<std::int64_t, 8> values{{INT64_MIN, -4294967297LL, -1, 0, INT32_MAX, 4294967296LL,
                                             9007199254740993LL, INT64_MAX}};
    for (const auto number : values) {
      auto input = constraint_fields;
      const auto opposite = number == INT64_MIN ? INT64_MAX : -number;
      input[4] += "|point.x~i64~" + std::to_string(number) + "|point.y~i64~" + std::to_string(opposite);
      const auto parsed = ParseRecoveredConstraintCandidate(input);
      if (!Expect(parsed.has_value(), "i64 boundary did not parse")) return 1;
      RecoveredProbeOptions signed_options{}; signed_options.constraint_candidate = &*parsed;
      const int factories_before = g_factories;
      const int validators_before = g_validators;
      const auto result = ProbeRecoveredCommand(game, sdk, "building", signed_options);
      ok &= Expect(g_factories == factories_before + 1 && g_factories == g_deleting_dtors &&
          g_validators == validators_before + 1 && g_populated_i64[0] == number && g_populated_i64[1] == opposite &&
          result.payload.find("\"native_is_valid\":true") != std::string::npos &&
          result.payload.find("\"value\":" + std::to_string(number) + ",") != std::string::npos &&
          result.payload.find("\"value\":" + std::to_string(opposite) + ",") != std::string::npos,
          "i64 wire/population/JSON echo truncated, changed sign or lost lifecycle pairing");
    }
    for (const auto* invalid : {"-9223372036854775809", "9223372036854775808", "18446744073709551615",
                                "+1", "1.0", "1e2", " 1", "1 ", "0x10", "1junk"}) {
      auto input = constraint_fields;
      input[4] += "|point.x~i64~" + std::string(invalid);
      ok &= Expect(!ParseRecoveredConstraintCandidate(input), "invalid or overflowing i64 wire accepted");
    }
    auto input = constraint_fields;
    input[4] += "|point.x~i64~-1|point.y~i64~9223372036854775807";
    auto parsed = ParseRecoveredConstraintCandidate(input);
    if (!parsed) return 1;
    RecoveredProbeOptions signed_options{}; signed_options.constraint_candidate = &*parsed;
    const int factories_before = g_factories;
    auto wrong_fields = coordinate_fields;
    const std::array<std::int64_t, 1> recovered_domain{{0}};
    wrong_fields[2].scalar_candidates = recovered_domain;
    commands[0].fields = wrong_fields;
    const auto domain = ProbeRecoveredCommand(game, sdk, "building", signed_options);
    ok &= Expect(domain.payload.find("constraint_plan_i64_outside_recovered_domain") != std::string::npos &&
        g_factories == factories_before, "i64 bypassed an SDK recovered scalar domain");
    wrong_fields = coordinate_fields;
    wrong_fields[2].width = 4U;
    const auto width = ProbeRecoveredCommand(game, sdk, "building", signed_options);
    ok &= Expect(width.payload.find("constraint_plan_invalid_i64_value_or_width") != std::string::npos &&
        g_factories == factories_before, "i64 with incorrect SDK width reached the factory");
    wrong_fields = coordinate_fields; wrong_fields[2].writable = false;
    const auto read_only = ProbeRecoveredCommand(game, sdk, "building", signed_options);
    ok &= Expect(read_only.payload.find("constraint_plan_field_or_type_mismatch") != std::string::npos &&
        g_factories == factories_before, "read-only i64 reached the factory");
    wrong_fields = coordinate_fields; wrong_fields[2].offset = commands[0].size - 4U;
    const int validators_before = g_validators;
    const auto bounds = ProbeRecoveredCommand(game, sdk, "building", signed_options);
    ok &= Expect(bounds.payload.find("recovered_field_not_safely_writable") != std::string::npos &&
        g_factories == factories_before + 1 && g_factories == g_deleting_dtors &&
        g_validators == validators_before, "out-of-bounds i64 reached validation or bypassed cleanup");
    commands[0] = original;
    g_factory_size = original.size;
    g_capture_i64 = false;
  }
  commands[0].flat_layout_complete = false;
  const int before = g_factories;
  g_bad_zone = true;
  const auto foreign = ProbeRecoveredCommand(game, sdk, "building", options);
  ok &= Expect(foreign.payload.find("native_slot_relationship_mismatch") != std::string::npos && g_factories == before,
      "foreign native slot reached a factory"); g_bad_zone = false;
  colonies[0] = 4U;  // same slot, wrong generation
  const auto stale = ProbeRecoveredCommand(game, sdk, "building", options);
  ok &= Expect(stale.payload.find("no_owned_colony_with_bounded_zone_lists") != std::string::npos && g_factories == before,
      "stale generation was silently repaired"); colonies[0] = kColony;
  slot_prefix[0] ^= 1U;
  const auto anchor = ProbeRecoveredCommand(game, sdk, "building", options);
  ok &= Expect(anchor.payload.find("provider_unavailable") != std::string::npos && g_factories == before,
      "mismatched function signature still invoked producer"); slot_prefix[0] ^= 1U;
  profile.platform_id = "windows-x64";
  ok &= Expect(NativeProducerCommands(game, sdk).empty(), "unrecovered Windows producer ABI advertised");
  profile.platform_id = "linux-x86_64";
  options.run_game_update = true;
  Put(idler.data(), 8U, static_cast<unsigned char>(0U));
  const auto unpaused = ProbeRecoveredCommand(game, sdk, "building", options);
  ok &= Expect(unpaused.payload.find("requires_paused_fixture") != std::string::npos && g_factories == before,
      "unpaused native domain query reached a factory");
  Put(idler.data(), 8U, static_cast<unsigned char>(1U));
  Put(idler.data(), 0U, std::uintptr_t{1U});
  const auto unknown_pause = ProbeRecoveredCommand(game, sdk, "building", options);
  ok &= Expect(unknown_pause.payload.find("pause_state_unavailable") != std::string::npos && g_factories == before,
      "unknown idler layout authorized a native query");
  Put(idler.data(), 0U, b.in_game_idler_vtable);
  const auto updating = ProbeRecoveredCommand(game, sdk, "building", options);
  ok &= Expect(updating.payload.find("\"native_is_valid\":true") != std::string::npos &&
      updating.payload.find("\"fixture_paused\":true") != std::string::npos && g_factories == before + 1,
      "Idle(true) incorrectly rejected a natively paused fixture"); options.run_game_update = false;
  const int after_paused = g_validators;
  g_bad_producer = true;
  const auto wrong = ProbeRecoveredCommand(game, sdk, "building", options);
  ok &= Expect(wrong.payload.find("branch_or_identity_mismatch") != std::string::npos &&
      g_children == g_child_dtors && g_validators == after_paused, "mismatched produced identity was validated or leaked");
  g_bad_producer = false;
  g_throw_producer = true;
  const int before_exception = g_validators;
  const auto exception = ProbeRecoveredCommand(game, sdk, "building", options);
  ok &= Expect(exception.payload.find("\"status\":\"call_exception\"") != std::string::npos &&
      exception.payload.find("\"destroyed\":false") != std::string::npos && g_validators == before_exception,
      "constructor exception claimed successful cleanup or continued validation");
  // Only this fixture knows that its throwing constructor wrote nothing.
  // Real runtime code must quarantine, stop, and never guess a destructor.
  ::operator delete(g_last_allocation); g_last_allocation = nullptr;
  g_throw_producer = false;

  // Research candidates must come from this country's alternatives/tasks and
  // also belong to the effective definition database, not the first global IDs.
  Put(g_country.data(), 0x15e0U + 0x10U, static_cast<const void*>(g_country.data()));
  Put(g_country.data(), 0x15e0U + 0x110U, technologies.data());
  Put(g_country.data(), 0x15e0U + 0x11cU, std::int32_t{1});
  DefinitionDb tech_db{{}, technologies.data(), 1U, 1}; const void* tech_db_ptr = &tech_db;
  std::array<RecoveredDefinitionDatabase, 1> definitions{{{"CTechnology", reinterpret_cast<std::uintptr_t>(&tech_db_ptr),
      reinterpret_cast<std::uintptr_t>(&null_object), 0x50U, 0x5cU, 0x10U}}};
  sdk.definition_databases = definitions;
  commands[0].name = "research"; commands[0].class_name = "CResearchTechnologyCommand";
  const auto candidate = ResolveNativeProducerCandidate(game, sdk, commands[0], kCountry, 0U);
  ok &= Expect(candidate.definition == &g_tech && candidate.definition_key == "tech_fixture" &&
      candidate.native_rule_valid == true && candidate.candidate_count == 1U, "research did not bind country alternatives + native rules");
  g_rule = false;
  const auto rejected = ResolveNativeProducerCandidate(game, sdk, commands[0], kCountry, 0U);
  ok &= Expect(rejected.definition == &g_tech && rejected.native_rule_valid == false,
      "normal rule false was misclassified as structure failure");
  g_rule = true;
  const auto exhausted = ResolveNativeProducerCandidate(game, sdk, commands[0], kCountry, 1U);
  ok &= Expect(exhausted.reason == "candidate_index_exhausted", "candidate exhaustion wrapped and replayed another input");
  Put(g_country.data(), 0x15e0U + 0x10U, static_cast<const void*>(g_colony.data()));
  const auto owner_mismatch = ResolveNativeProducerCandidate(game, sdk, commands[0], kCountry, 0U);
  ok &= Expect(owner_mismatch.reason == "technology_status_country_mismatch", "foreign country status accepted");
  ok &= Expect(g_children == g_child_dtors && g_deleting_dtors + 1 == g_factories,
      "producer tests leaked or double deleted a command outside the explicit quarantine");
  return ok ? 0 : 1;
}
