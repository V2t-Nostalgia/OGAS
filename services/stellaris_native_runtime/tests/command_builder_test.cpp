#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <new>

#include "iag_native_runtime/command_builder.h"
#include "iag_native_runtime/game_api.h"
#include "iag_native_runtime/sdk_probe.h"

namespace {

using namespace iag::native_runtime;

struct NativeRefArray {
  std::uintptr_t vtable = 0;
  std::uint32_t* data = nullptr;
  std::int32_t capacity = 0;
  std::int32_t count = 0;
};

struct CoordinateValueFixture {
  std::uintptr_t vtable = 0xc001U;
  std::int64_t x = INT64_MIN;
  std::int64_t y = INT64_MIN;
  std::int64_t height = 0;
  std::uint32_t origin = UINT32_MAX;
  std::uint8_t internal_flag = 0;
  std::uint8_t randomized = 0;
  std::array<unsigned char, 2> tail_padding{};
};
static_assert(sizeof(CoordinateValueFixture) == 40U);
static_assert(offsetof(CoordinateValueFixture, randomized) == 37U);

struct TestCommand {
  std::uintptr_t vtable = 0;
  std::array<unsigned char, 24> header{};
  std::uint32_t country = UINT32_MAX;
  std::uint32_t leader = UINT32_MAX;
  NativeRefArray refs{};
  std::string text{};
  std::int32_t quantity = 0;
  std::uint8_t flags = 0xaaU;
  const void* definition = nullptr;
  CoordinateValueFixture coordinate{};
  ~TestCommand() { delete[] refs.data; }
};

std::array<std::uintptr_t, 24> g_vtable{};
std::array<unsigned char, 6> g_token_getter{{0xb8, 0x34, 0x12, 0, 0, 0xc3}};
std::array<unsigned char, 16> g_dynamic_token_getter{};
std::uint32_t g_dynamic_token = 0x4321U;
TestCommand* g_last_command = nullptr;
int g_constructed = 0;
int g_destroyed = 0;
int g_validated = 0;
int g_posted = 0;
bool g_allow_valid = true;
bool g_throw_validator = false;
bool g_reason_enabled = false;
std::uint32_t g_validated_country = UINT32_MAX;
std::uint32_t g_validated_scoped_id = UINT32_MAX;

void* InsertReference(void* object, int index) {
  auto& array = *static_cast<NativeRefArray*>(object);
  if (index != array.count || index < 0 || index >= 16) return nullptr;
  auto* replacement = new std::uint32_t[static_cast<std::size_t>(index + 2)];
  for (int i = 0; i < index; ++i) replacement[i] = array.data[i];
  delete[] array.data;
  array.data = replacement;
  array.capacity = index + 2;
  array.count = index + 1;
  return &array.data[index];
}

void TextConstruct(void* value, const char* text) { new (value) std::string(text); }
void TextDestroy(void* value) { static_cast<std::string*>(value)->~basic_string(); }
void TextAssign(void* value, const char* text) { *static_cast<std::string*>(value) = text; }
void TextValueConstruct(void* value, const char* text, bool literal) {
  new (value) std::string(literal ? text : "wrong literal flag");
}
void TextValueMove(void* value, void* from) {
  *static_cast<std::string*>(value) = std::move(*static_cast<std::string*>(from));
}
const char* TextData(const void* value) { return static_cast<const std::string*>(value)->data(); }
int TextSize(const void* value) { return static_cast<int>(static_cast<const std::string*>(value)->size()); }

void* MakeCommand() {
  ++g_constructed;
  auto* command = new TestCommand;
  g_last_command = command;
  command->vtable = reinterpret_cast<std::uintptr_t>(g_vtable.data());
  return command;
}

bool Validate(const void* value, void* reason) {
  ++g_validated;
  if (g_throw_validator) throw std::runtime_error("fixture");
  const auto& command = *static_cast<const TestCommand*>(value);
  g_validated_country = command.country;
  std::memcpy(&g_validated_scoped_id, &command.quantity, sizeof(g_validated_scoped_id));
  if (g_reason_enabled && reason != nullptr) *static_cast<std::string*>(reason) = "fixture rule rejection";
  return g_allow_valid && command.country == 7U && command.leader == 42U;
}

#if defined(_WIN32)
void* Destroy(void* command, unsigned int flags) {
  if (flags != 1U) {
    return nullptr;
  }
  ++g_destroyed;
  delete static_cast<TestCommand*>(command);
  return nullptr;
}
constexpr std::string_view kPlatform = "windows-x64";
constexpr std::size_t kValidSlot = 8U;
constexpr std::size_t kDestructorSlot = 0U;
constexpr std::size_t kTokenSlot = 10U;
#else
void Destroy(void* command) {
  ++g_destroyed;
  delete static_cast<TestCommand*>(command);
}
constexpr std::string_view kPlatform = "linux-x86_64";
constexpr std::size_t kValidSlot = 9U;
constexpr std::size_t kDestructorSlot = 1U;
constexpr std::size_t kTokenSlot = 11U;
#endif

void Post(void* command, bool) {
  ++g_posted;
#if defined(_WIN32)
  Destroy(command, 1U);
#else
  Destroy(command);
#endif
}

bool Expect(bool result, const char* message) {
  if (!result) {
    std::cerr << message << '\n';
  }
  return result;
}

struct DatabaseEntry {
  std::uint64_t unused = 0;
  const void* object = nullptr;
};

struct Database {
  std::array<unsigned char, 0x18> padding{};
  const DatabaseEntry* entries = nullptr;
  std::uint32_t count = 0;
};

const void* g_local_country = nullptr;
const void* LocalCountry(const void*) { return g_local_country; }

struct ScopedObjectFixture {
  std::uint32_t id;
  const void* definition;
};
struct ScopedCountryFixture {
  std::uint32_t id = 7U;
  const ScopedObjectFixture* const* objects = nullptr;
  std::int32_t count = 0;
};
const ScopedCountryFixture* g_scoped_country = nullptr;
ScopedIdKind g_scoped_kind = ScopedIdKind::member_u32;
bool g_scoped_reverse = false;
bool g_scoped_throw = false;
bool g_scoped_mismatch = false;
std::array<const void*, 3> g_scoped_definitions{};

const void* ScopedLookup(const void* country, std::uint32_t id) {
  if (g_scoped_throw) throw std::runtime_error("scoped fixture");
  if (g_scoped_mismatch || country != g_scoped_country) return nullptr;
  for (int i = 0; i < g_scoped_country->count; ++i) {
    const int index = g_scoped_reverse ? g_scoped_country->count - i - 1 : i;
    const auto* object = g_scoped_country->objects[index];
    if (object == nullptr) continue;
    if (g_scoped_kind == ScopedIdKind::definition_index) {
      if (id < g_scoped_definitions.size() && object->definition == g_scoped_definitions[id]) return object;
    } else if ((g_scoped_kind == ScopedIdKind::member_u16 ? object->id & 0xffffU : object->id) == id) {
      return object;
    }
  }
  return nullptr;
}

}  // namespace

int main() {
  bool ok = true;
  const auto& generated = ActiveRecoveredSdk();
  const auto& current = ActiveStellarisProfile();
  ok &= Expect(generated.build_id == current.build_id, "generated SDK/build mismatch");
  const auto* hire = FindRecoveredCommand(generated, "hire_leader");
  ok &= Expect(hire != nullptr && hire->factory_rva != 0U && hire->size != 0U,
               "new non-Action command lacks an automatically recovered factory");

  BuildProfile profile{};
  profile.platform_id = kPlatform.data();
  profile.build_id = "test-fixture";
  profile.core.post_command_to_session = reinterpret_cast<std::uintptr_t>(&Post);
  GameApi game(0, profile);
  g_vtable[kValidSlot] = reinterpret_cast<std::uintptr_t>(&Validate);
  g_vtable[kDestructorSlot] = reinterpret_cast<std::uintptr_t>(&Destroy);
  g_vtable[kTokenSlot] = reinterpret_cast<std::uintptr_t>(g_token_getter.data());
  const std::array<RecoveredField, 3> fields{{
      {"country", "ref", "CCountry", offsetof(TestCommand, country), 4, true},
      {"leader", "ref", "CLeader", offsetof(TestCommand, leader), 4, true},
      {"uncertain", "u32", "", sizeof(TestCommand) - 1, 4, true},
  }};
  std::array<RecoveredCommand, 1> commands{{
      {"hire_leader", "CHireLeaderCommand", 0x1234,
       reinterpret_cast<std::uintptr_t>(g_vtable.data()),
       reinterpret_cast<std::uintptr_t>(&MakeCommand), sizeof(TestCommand),
       reinterpret_cast<std::uintptr_t>(&Validate),
       reinterpret_cast<std::uintptr_t>(&Destroy),
       reinterpret_cast<std::uintptr_t>(g_token_getter.data()),
       kValidSlot, kDestructorSlot, kTokenSlot, fields},
  }};
  RecoveredSdk sdk{kPlatform, "test-fixture", "fixture", commands, {}, {}};
  std::string error;
  {
    auto builder = NativeCommandBuilder::Create(game, sdk, "hire_leader", error);
    ok &= Expect(builder != nullptr, "generated factory construction failed");
    if (builder == nullptr) {
      return 1;
    }
    ok &= Expect(builder->SetObjectId("country", "CCountry", 7, error), "country write failed");
    ok &= Expect(!builder->SetObjectId("leader", "CFleet", 42, error), "wrong reference type accepted");
    ok &= Expect(!builder->SetUnsigned("leader", 42, error), "untyped write to reference accepted");
    ok &= Expect(!builder->SetUnsigned("uncertain", 42, error), "out-of-bounds field accepted");
    ok &= Expect(builder->SetObjectId("leader", "CLeader", 42, error), "leader write failed");
    ok &= Expect(builder->IsValid(), "populated metadata command failed IsValid");
  }
  ok &= Expect(g_constructed == 1 && g_destroyed == 1 && g_validated == 1 && g_posted == 0,
               "non-submitting validation violated lifecycle or submitted a command");
  {
    auto builder = NativeCommandBuilder::Create(game, sdk, "hire_leader", error);
    ok &= Expect(builder != nullptr && !builder->IsValid(), "invalid candidate was not rejected");
    if (builder != nullptr) {
      ok &= Expect(builder->ReleaseForSubmission() == nullptr, "invalid command ownership released");
    }
  }
  ok &= Expect(g_constructed == 2 && g_destroyed == 2 && g_posted == 0,
               "rejected command was not destroyed");
  {
    // A future reviewed Action::Prepare can transfer the very same builder's
    // command into the established common submit path.
    auto builder = NativeCommandBuilder::Create(game, sdk, "hire_leader", error);
    if (builder == nullptr) {
      return 1;
    }
    ok &= Expect(builder->SetObjectId("country", "CCountry", 7, error), "country write failed");
    ok &= Expect(builder->SetObjectId("leader", "CLeader", 42, error), "leader write failed");
    ok &= Expect(builder->IsValid(), "submission candidate validation failed");
    game.PostCommand(builder->ReleaseForSubmission());
  }
  ok &= Expect(g_constructed == 3 && g_destroyed == 3 && g_posted == 1,
               "ownership transfer caused double deletion or lost the command");
  sdk.build_id = "different-build";
  ok &= Expect(NativeCommandBuilder::Create(game, sdk, "hire_leader", error) == nullptr,
               "wrong-build metadata accepted");
  sdk.build_id = "test-fixture";
  commands[0].factory_rva = 0;
  ok &= Expect(NativeCommandBuilder::Create(game, sdk, "hire_leader", error) == nullptr,
               "factoryless command was guessed into existence");
  commands[0].factory_rva = reinterpret_cast<std::uintptr_t>(&MakeCommand);
  g_token_getter[1] = 0;
  ok &= Expect(NativeCommandBuilder::Create(game, sdk, "hire_leader", error) == nullptr,
               "vtable token mismatch accepted");
  ok &= Expect(g_constructed == 3, "a failed preflight still called a factory");

  // The generic probe uses native database handles, not hand-supplied IDs.
  g_token_getter[1] = 0x34;
  commands[0].fields = std::span<const RecoveredField>(fields).first(2U);
  commands[0].flat_layout_complete = true;
  std::uint32_t country_id = 7U;
  std::uint32_t leader_id = 42U;
  g_local_country = &country_id;
  std::array<DatabaseEntry, 64> country_entries{};
  std::array<DatabaseEntry, 64> leader_entries{};
  country_entries[7].object = &country_id;
  leader_entries[42].object = &leader_id;
  Database country_database{{}, country_entries.data(), 64U};
  Database leader_database{{}, leader_entries.data(), 64U};
  const void* country_database_ptr = &country_database;
  const void* leader_database_ptr = &leader_database;
  const void* null_object = nullptr;
  const void* state = &country_database;
  profile.core.current_game_state = reinterpret_cast<std::uintptr_t>(&state);
  profile.core.get_local_observed = reinterpret_cast<std::uintptr_t>(&LocalCountry);
  profile.diplomatic_action.countries = {
      reinterpret_cast<std::uintptr_t>(&country_database_ptr),
      reinterpret_cast<std::uintptr_t>(&null_object), 0U};
  profile.leader_commands.leaders = {
      reinterpret_cast<std::uintptr_t>(&leader_database_ptr),
      reinterpret_cast<std::uintptr_t>(&null_object), 0U};
  const RecoveredProbeOptions automatic{};
  const auto valid_report = ProbeRecoveredCommand(game, sdk, "hire_leader", automatic);
  ok &= Expect(valid_report.payload.find("\"status\":\"native_valid\"") != std::string::npos,
               "automatic database-backed probe did not validate");
  ok &= Expect(valid_report.payload.find("\"run_game_update\":false") != std::string::npos,
               "paused probe did not retain scheduler evidence");
  g_allow_valid = false;
  const auto invalid_report = ProbeRecoveredCommand(game, sdk, "hire_leader", automatic);
  ok &= Expect(invalid_report.payload.find("\"status\":\"native_invalid\"") != std::string::npos,
               "native rule rejection was confused with a reverse-engineering failure");
  g_allow_valid = true;
  g_throw_validator = true;
  const auto exception_report = ProbeRecoveredCommand(game, sdk, "hire_leader", automatic);
  ok &= Expect(exception_report.payload.find("\"status\":\"call_exception\"") != std::string::npos,
               "C++ validator exception was not recorded");
  g_throw_validator = false;
  ok &= Expect(g_constructed == 6 && g_destroyed == 6 && g_posted == 1,
               "generic research probe posted a command or failed cleanup");
  leader_entries[42].object = nullptr;
  const auto missing_report = ProbeRecoveredCommand(game, sdk, "hire_leader", automatic);
  ok &= Expect(missing_report.payload.find("no_live_candidate:CLeader") != std::string::npos,
               "missing candidate was not distinguished from a native rejection");
  commands[0].flat_layout_complete = false;
  const auto skipped_report = ProbeRecoveredCommand(game, sdk, "hire_leader", automatic);
  ok &= Expect(skipped_report.payload.find("incomplete_or_nonflat") != std::string::npos,
               "unsafe layout was constructed");
  ok &= Expect(g_constructed == 6, "a skipped probe still called a factory");
  ok &= Expect(ShouldDispatchPending(false, true) && !ShouldDispatchPending(false, false) &&
                   ShouldDispatchPending(true, true) && ShouldDispatchPending(true, false),
               "paused scheduling changed production execution semantics");
  const auto catalog = DescribeRecoveredCommands(sdk, 123U, 456U);
  ok &= Expect(catalog.find("hire_leader") != std::string::npos &&
                   catalog.find("\"process_id\":123") != std::string::npos,
               "recovered command catalog lost identity or command coverage");

  const int before_lifecycle = g_constructed;
  const int before_validator = g_validated;
  commands[0].lifecycle_probe_safe = true;
  const auto lifecycle_report = ProbeRecoveredCommand(game, sdk, "hire_leader", automatic);
  ok &= Expect(lifecycle_report.payload.find("\"constructed_from_generated_metadata\":true") != std::string::npos &&
                   lifecycle_report.payload.find("\"native_is_valid\":null") != std::string::npos &&
                   lifecycle_report.payload.find("\"destroyed\":true") != std::string::npos &&
                   lifecycle_report.payload.find("\"parameters_populated\":false") != std::string::npos,
               "incomplete population was confused with a completed validator call");
  ok &= Expect(g_constructed == before_lifecycle + 1 && g_validated == before_validator && g_posted == 1,
               "lifecycle-only probe called a validator or submitted a command");

  g_dynamic_token_getter = {0x48, 0x8d, 0x05, 0, 0, 0, 0, 0x8b, 0, 0xc3};
  const auto delta = static_cast<std::int32_t>(reinterpret_cast<std::intptr_t>(&g_dynamic_token) -
      reinterpret_cast<std::intptr_t>(g_dynamic_token_getter.data()) - 7);
  std::memcpy(g_dynamic_token_getter.data() + 3U, &delta, sizeof(delta));
  commands[0].token_getter_rva = reinterpret_cast<std::uintptr_t>(g_dynamic_token_getter.data());
  commands[0].token_global_rva = reinterpret_cast<std::uintptr_t>(&g_dynamic_token);
  g_vtable[kTokenSlot] = commands[0].token_getter_rva;
  ok &= Expect(NativeCommandBuilder::Preflight(game, sdk, "hire_leader", error), "registered dynamic token was rejected");
  g_dynamic_token = 0U;
  ok &= Expect(!NativeCommandBuilder::Preflight(game, sdk, "hire_leader", error), "unregistered dynamic token was accepted");
  commands[0].token_global_rva = 0U;
  commands[0].token_getter_rva = reinterpret_cast<std::uintptr_t>(g_token_getter.data());
  g_vtable[kTokenSlot] = commands[0].token_getter_rva;

  std::array<RecoveredObjectDatabase, 1> recovered_databases{{{"CLeader",
      reinterpret_cast<std::uintptr_t>(&leader_database_ptr), reinterpret_cast<std::uintptr_t>(&null_object), 0U}}};
  sdk.object_databases = recovered_databases;
  leader_id = 0x0300002aU;
  leader_entries[42].object = &leader_id;
  commands[0].flat_layout_complete = true;
  const auto generated_database_report = ProbeRecoveredCommand(game, sdk, "hire_leader", automatic);
  ok &= Expect(generated_database_report.payload.find("50331690") != std::string::npos &&
                   generated_database_report.payload.find("\"parameters_populated\":true") != std::string::npos,
               "generated database lost the handle generation bits or failed population");

  profile.c_string = {sizeof(std::string), reinterpret_cast<std::uintptr_t>(&TextConstruct),
      reinterpret_cast<std::uintptr_t>(&TextDestroy), reinterpret_cast<std::uintptr_t>(&TextData),
      reinterpret_cast<std::uintptr_t>(&TextSize)};
  std::string definition_key = "native_definition";
  std::array<const void*, 1> definition_objects{{&definition_key}};
  struct DefinitionDatabaseFixture { const void* const* data; std::int32_t count; };
  DefinitionDatabaseFixture definition_database{definition_objects.data(), 1};
  const void* definition_database_ptr = &definition_database;
  std::array<RecoveredDefinitionDatabase, 1> definitions{{{"CDefinition",
      reinterpret_cast<std::uintptr_t>(&definition_database_ptr),
      reinterpret_cast<std::uintptr_t>(&null_object), offsetof(DefinitionDatabaseFixture, data),
      offsetof(DefinitionDatabaseFixture, count), 0U}}};
  sdk.definition_databases = definitions;
  const std::array<RecoveredField, 5> complex_fields{{
      {"ships", "reference_array", "CShip", offsetof(TestCommand, refs), sizeof(NativeRefArray), true,
       "", reinterpret_cast<std::uintptr_t>(&InsertReference)},
      {"name", "string", "", offsetof(TestCommand, text), sizeof(std::string), true,
       "CString", reinterpret_cast<std::uintptr_t>(&TextAssign)},
      {"quantity", "i32", "", offsetof(TestCommand, quantity), 4U, true},
      {"flag", "bool", "", offsetof(TestCommand, flags), 1U, true, "", 0U, 4U},
      {"definition", "definition_pointer", "", offsetof(TestCommand, definition), sizeof(void*), true, "CDefinition"},
  }};
  commands[0].fields = complex_fields;
  {
    auto builder = NativeCommandBuilder::Create(game, sdk, "hire_leader", error);
    if (builder == nullptr) return 1;
    const std::array<std::uint32_t, 2> ids{{0x03000001U, 0x05000002U}};
    ok &= Expect(!builder->SetReferenceList("ships", "CFleet", ids, error), "wrong array reference type accepted");
    ok &= Expect(builder->SetReferenceList("ships", "CShip", ids, error), "native array emplacement failed");
    ok &= Expect(!builder->SetReferenceList("ships", "CShip", ids, error), "nonempty array silently overwritten");
    ok &= Expect(builder->SetText("name", "SDK probe", error), "native string assignment failed");
    ok &= Expect(!builder->SetText("name", std::string(513U, 'x'), error), "oversized string accepted");
    ok &= Expect(builder->SetSigned("quantity", -7, error), "signed field was not type-safe");
    ok &= Expect(!builder->SetSigned("quantity", INT64_MAX, error), "signed overflow accepted");
    ok &= Expect(builder->SetUnsigned("flag", 1U, error), "bit-field assignment failed");
    const auto keys = NativeCommandBuilder::DefinitionCandidates(game, sdk, "CDefinition", 16U);
    ok &= Expect(keys.size() == 1U && keys[0] == definition_key, "native definitions were not enumerated");
    ok &= Expect(!builder->SetDefinitionKey("definition", "WrongType", definition_key, error), "wrong definition type accepted");
    ok &= Expect(builder->SetDefinitionKey("definition", "CDefinition", definition_key, error), "definition key resolution failed");
    ok &= Expect(g_last_command->refs.count == 2 && g_last_command->refs.data[0] == ids[0] &&
                     g_last_command->refs.data[1] == ids[1] && g_last_command->text == "SDK probe" &&
                     g_last_command->quantity == -7 && g_last_command->flags == 0xaeU &&
                     g_last_command->definition == &definition_key,
                 "native population corrupted a sibling field, generation bits or ownership");
    std::string native_reason;
    g_reason_enabled = true;
    ok &= Expect(!builder->IsValid(&native_reason) && native_reason == "fixture rule rejection", "native reason CString lifecycle failed");
    g_reason_enabled = false;
    // A successful validator is not required for the ownership/lifecycle test.
  }
  ok &= Expect(g_destroyed == g_constructed && g_posted == 1,
               "complex population leaked, double-destroyed or posted an object");
  auto native_value_fields = complex_fields;
  native_value_fields[1].storage_kind = "native_text_value";
  native_value_fields[1].native_type = "CTestPersistentName";
  native_value_fields[1].assignment_rva = reinterpret_cast<std::uintptr_t>(&TextValueMove);
  std::array<RecoveredNativeTextValue, 1> value_types{{{"CTestPersistentName", sizeof(std::string),
      reinterpret_cast<std::uintptr_t>(&TextValueConstruct), reinterpret_cast<std::uintptr_t>(&TextValueMove),
      reinterpret_cast<std::uintptr_t>(&TextDestroy)}}};
  sdk.native_text_values = value_types;
  commands[0].fields = native_value_fields;
  {
    auto builder = NativeCommandBuilder::Create(game, sdk, "hire_leader", error);
    if (builder == nullptr) return 1;
    const std::string heap_text(200U, 'a');
    ok &= Expect(builder->SetText("name", heap_text, error) && g_last_command->text == heap_text,
                 "nontrivial native text value did not transfer ownership");
    ok &= Expect(builder->SetText("name", "replacement", error) && g_last_command->text == "replacement",
                 "nontrivial value replacement failed to release previous storage");
  }
  ok &= Expect(g_destroyed == g_constructed && g_posted == 1,
               "native value move assignment leaked or double-freed its members");
  std::string second_key = "second_definition";
  std::array<const void*, 1> second_objects{{&second_key}};
  DefinitionDatabaseFixture second_database{second_objects.data(), 1};
  const void* second_database_ptr = &second_database;
  std::array<RecoveredDefinitionDatabase, 2> multi_definitions{{definitions[0], definitions[0]}};
  multi_definitions[1].database_rva = reinterpret_cast<std::uintptr_t>(&second_database_ptr);
  sdk.definition_databases = multi_definitions;
  {
    auto builder = NativeCommandBuilder::Create(game, sdk, "hire_leader", error);
    if (builder == nullptr) return 1;
    const auto keys = NativeCommandBuilder::DefinitionCandidates(game, sdk, "CDefinition", 16U);
    ok &= Expect(keys.size() == 2U && builder->SetDefinitionKey("definition", "CDefinition", second_key, error) &&
                     g_last_command->definition == &second_key,
                 "same C++ definition type could not use multiple native databases");
    second_key = definition_key;
    ok &= Expect(!builder->SetDefinitionKey("definition", "CDefinition", definition_key, error) &&
                     error == "ambiguous_live_definition_key",
                 "colliding keys from different objects silently selected a database");
    ok &= Expect(NativeCommandBuilder::DefinitionCandidates(game, sdk, "CDefinition", 16U).empty(),
                 "ambiguous definition keys were exposed as candidates");
    second_objects[0] = &definition_key;
    ok &= Expect(builder->SetDefinitionKey("definition", "CDefinition", definition_key, error),
                 "database aliases to the same native object were incorrectly rejected");
  }
  ok &= Expect(g_destroyed == g_constructed && g_posted == 1,
               "multi-database lookup changed ownership or submitted a command");

  ScopedObjectFixture scoped_a{0xffff0033U, &country_id};
  ScopedObjectFixture scoped_b{0x44U, &leader_id};
  const std::array<const ScopedObjectFixture*, 2> scoped_objects{{&scoped_a, &scoped_b}};
  ScopedCountryFixture scoped_country{7U, scoped_objects.data(), 2};
  g_scoped_country = &scoped_country;
  country_entries[7].object = &scoped_country;
  g_local_country = &scoped_country;
  const std::array<RecoveredField, 2> scoped_fields{{
      {"requester", "ref", "CCountry", offsetof(TestCommand, country), 4U, true},
      {"id", "u32", "", offsetof(TestCommand, quantity), 4U, true},
  }};
  commands[0].class_name = "CScopedFixture";
  commands[0].fields = scoped_fields;
  std::array<RecoveredScopedIdBinding, 1> scoped_bindings{{{
      "CScopedFixture", offsetof(TestCommand, quantity), offsetof(TestCommand, country),
      "CTestScoped", ScopedIdKind::member_u32, reinterpret_cast<std::uintptr_t>(&ScopedLookup),
      reinterpret_cast<std::uintptr_t>(&null_object), offsetof(ScopedCountryFixture, objects),
      offsetof(ScopedCountryFixture, count), offsetof(ScopedObjectFixture, id), false}}};
  sdk.scoped_id_bindings = scoped_bindings;
  RecoveredProbeOptions scoped_options{};
  scoped_options.country_id = 7U;
  scoped_options.candidate_index = 1U;
  const auto scoped_report = ProbeRecoveredCommand(game, sdk, "hire_leader", scoped_options);
  ok &= Expect(scoped_report.payload.find("\"parameters_populated\":true") != std::string::npos &&
                   scoped_report.payload.find("\"scoped_lookup_calls\":2") != std::string::npos &&
                   g_validated_country == 7U && g_validated_scoped_id == 0x44U,
               "scoped values lost their command-country binding or full-width identity");
  g_scoped_kind = ScopedIdKind::member_u16;
  g_scoped_reverse = true;
  scoped_bindings[0].kind = g_scoped_kind;
  scoped_bindings[0].reverse = true;
  const auto flags_report = ProbeRecoveredCommand(game, sdk, "hire_leader", scoped_options);
  ok &= Expect(flags_report.payload.find("\"parameters_populated\":true") != std::string::npos &&
                   g_validated_scoped_id == 0x33U, "reverse 16-bit scoped lookup used a global handle or high bits");

  struct ScopedDefinitionFixture { const void* const* data; std::int32_t count; };
  g_scoped_definitions = {nullptr, &leader_id, &country_id};
  ScopedDefinitionFixture scoped_definitions{g_scoped_definitions.data(), 3};
  const void* scoped_definitions_ptr = &scoped_definitions;
  scoped_bindings[0].kind = g_scoped_kind = ScopedIdKind::definition_index;
  scoped_bindings[0].reverse = g_scoped_reverse = false;
  scoped_bindings[0].member_offset = offsetof(ScopedObjectFixture, definition);
  scoped_bindings[0].definition_database_rva = reinterpret_cast<std::uintptr_t>(&scoped_definitions_ptr);
  scoped_bindings[0].definition_null_rva = reinterpret_cast<std::uintptr_t>(&null_object);
  scoped_bindings[0].definition_data_offset = offsetof(ScopedDefinitionFixture, data);
  scoped_bindings[0].definition_count_offset = offsetof(ScopedDefinitionFixture, count);
  const auto chain_report = ProbeRecoveredCommand(game, sdk, "hire_leader", scoped_options);
  ok &= Expect(chain_report.payload.find("\"parameters_populated\":true") != std::string::npos &&
                   g_validated_scoped_id == 1U, "definition join used an instance ID rather than a loaded index");
  const int before_scoped_error = g_constructed;
  const int before_scoped_validate = g_validated;
  scoped_country.count = -1;
  const auto bounds_report = ProbeRecoveredCommand(game, sdk, "hire_leader", scoped_options);
  ok &= Expect(bounds_report.payload.find("scoped_array_bounds_invalid") != std::string::npos &&
                   g_constructed == before_scoped_error, "bad scoped bounds still called a factory");
  scoped_country.count = 2;
  g_scoped_throw = true;
  const auto scope_exception = ProbeRecoveredCommand(game, sdk, "hire_leader", scoped_options);
  ok &= Expect(scope_exception.payload.find("native_candidate_resolution_exception") != std::string::npos &&
                   g_constructed == before_scoped_error && g_validated == before_scoped_validate,
               "candidate resolver exception escaped or called a factory/validator");
  g_scoped_throw = false;
  g_scoped_mismatch = true;
  const auto mismatch_report = ProbeRecoveredCommand(game, sdk, "hire_leader", scoped_options);
  ok &= Expect(mismatch_report.payload.find("no_live_scoped_candidate:CTestScoped") != std::string::npos &&
                   g_validated == before_scoped_validate, "an ID whose native lookup disagreed reached IsValid");
  g_scoped_mismatch = false;
  scoped_bindings[0].kind = g_scoped_kind = ScopedIdKind::member_u32;
  scoped_bindings[0].member_offset = offsetof(ScopedObjectFixture, id);
  std::array<ScopedObjectFixture, 17> many_scoped{};
  std::array<const ScopedObjectFixture*, 17> many_scoped_pointers{};
  for (std::size_t i = 0; i < many_scoped.size(); ++i) {
    many_scoped[i].id = static_cast<std::uint32_t>(i);
    many_scoped_pointers[i] = &many_scoped[i];
  }
  scoped_country.objects = many_scoped_pointers.data();
  scoped_country.count = static_cast<std::int32_t>(many_scoped.size());
  const auto bounded_report = ProbeRecoveredCommand(game, sdk, "hire_leader", scoped_options);
  ok &= Expect(bounded_report.payload.find("\"candidate_scan_truncated\":true") != std::string::npos &&
                   bounded_report.payload.find("\"candidate_count\":16") != std::string::npos &&
                   bounded_report.payload.find("\"scoped_lookup_calls\":16") != std::string::npos,
               "bounded scoped enumeration hid unvisited candidates or exceeded its result limit");
  // A recovered offset can remain read-only until native composite assignment
  // and derived-state rebuilding have a reviewed adapter.
  auto read_only_fields = scoped_fields;
  for (auto& field : read_only_fields) field.writable = false;
  commands[0].fields = read_only_fields;
  {
    auto builder = NativeCommandBuilder::Create(game, sdk, "hire_leader", error);
    if (builder == nullptr) return 1;
    const auto previous_country = g_last_command->country;
    const auto previous_value = g_last_command->quantity;
    ok &= Expect(!builder->SetObjectId("requester", "CCountry", 7U, error) &&
                     error == "recovered_field_not_safely_writable",
                 "read-only reference metadata accepted a raw field write");
    ok &= Expect(!builder->SetUnsigned("id", 42U, error) &&
                     error == "recovered_field_not_safely_writable" &&
                     g_last_command->country == previous_country &&
                     g_last_command->quantity == previous_value,
                 "read-only scalar metadata accepted a write or changed a sibling");
  }
  ok &= Expect(g_destroyed == g_constructed && g_posted == 1,
               "scoped candidate probing leaked ownership or submitted a command");
  // Shared generated primitive setters already support the non-owning native
  // coordinate. No Command-specific constructor or foreign nested allocation.
  const std::size_t coord = offsetof(TestCommand, coordinate);
  const std::array<RecoveredField, 5> coordinate_fields{{
      {"point.x", "i64", "", coord + offsetof(CoordinateValueFixture, x), 8U, true, "CFixedPoint"},
      {"point.y", "i64", "", coord + offsetof(CoordinateValueFixture, y), 8U, true, "CFixedPoint"},
      {"point.visual_height", "i64", "", coord + offsetof(CoordinateValueFixture, height), 8U, true, "CFixedPoint"},
      {"point.origin", "ref", "CGalacticObject", coord + offsetof(CoordinateValueFixture, origin), 4U, true},
      {"point.randomized", "bool", "", coord + offsetof(CoordinateValueFixture, randomized), 1U, true},
  }};
  commands[0].fields = coordinate_fields;
  const int before_coordinate_validations = g_validated;
  {
    auto builder = NativeCommandBuilder::Create(game, sdk, "hire_leader", error);
    if (builder == nullptr) return 1;
    ok &= Expect(builder->SetSigned("point.x", 1212500, error) &&
                     builder->SetSigned("point.y", -350000, error) &&
                     builder->SetSigned("point.visual_height", 0, error) &&
                     builder->SetObjectId("point.origin", "CGalacticObject", 0x0600002aU, error) &&
                     builder->SetUnsigned("point.randomized", 0U, error),
                 "shared Builder failed generated coordinate primitive population");
    ok &= Expect(!builder->SetUnsigned("point.x", 12U, error) &&
                     !builder->SetObjectId("point.origin", "CPlanet", 42U, error),
                 "coordinate field accepted the wrong signed/reference type");
    const auto& value = g_last_command->coordinate;
    ok &= Expect(value.x == 1212500 && value.y == -350000 && value.height == 0 &&
                     value.origin == 0x0600002aU && value.randomized == 0 &&
                     value.internal_flag == 0 && value.vtable == 0xc001U &&
                     value.tail_padding == std::array<unsigned char, 2>{},
                 "coordinate population altered origin generation, native header or padding");
  }
  ok &= Expect(g_destroyed == g_constructed && g_posted == 1 &&
                   g_validated == before_coordinate_validations,
               "coordinate construction test submitted, validated or leaked a command");
  return ok ? 0 : 1;
}
