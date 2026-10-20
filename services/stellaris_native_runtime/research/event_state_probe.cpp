#include <algorithm>
#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <elf.h>
#include <errno.h>
#include <fcntl.h>
#include <link.h>
#include <limits>
#include <pthread.h>
#include <string>
#include <string_view>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <utility>
#include <unistd.h>

#include "rotating_probe_log.h"

namespace {

constexpr char kExpectedBuildId[] =
    "c6969e60fd81d738948222a94c0b5a0841abbffc";
constexpr char kDefaultLogPath[] = "/tmp/iag-stellaris-state-probe.jsonl";
constexpr char kSchema[] = "iag.stellaris.event_state_probe.v1";

// Stellaris 4.4.6 (fdde), Linux ELF build-id c6969e60... . Every hook is
// guarded by the build ID and the exact instruction bytes it replaces.
constexpr std::uintptr_t kAddOpenPlayerEventOffset = 0x18124c0;
constexpr std::uintptr_t kOpenPlayerEventUninitializeOffset = 0x21cead0;
constexpr std::uintptr_t kCreateSituationOffset = 0x1811f00;
constexpr std::uintptr_t kDestroySituationOffset = 0x1811f20;
constexpr std::uintptr_t kUpdateSituationStageOffset = 0x1c17750;
constexpr std::uintptr_t kSetSituationApproachOffset = 0x1c19f00;
constexpr std::uintptr_t kAddSituationDelayedEventOffset = 0x1c1c650;
constexpr std::uintptr_t kBeginEventChainOffset = 0x20a2d80;
constexpr std::uintptr_t kEndEventChainOffset = 0x20a2e60;
constexpr std::uintptr_t kExecuteEventOffset = 0x21d3560;

constexpr std::uintptr_t kCStringDestroyOffset = 0x16584b0;
constexpr std::uintptr_t kCStringGetDataOffset = 0x3e4be60;
constexpr std::uintptr_t kCStringGetSizeOffset = 0x3e4c870;
constexpr std::uintptr_t kEventGetFirstDescriptionKeyOffset = 0x21d61b0;
constexpr std::uintptr_t kEventOptionGetFirstKeyOffset = 0x21f4110;
constexpr std::uintptr_t kEventManagerInstanceOffset = 0x54e4648;
constexpr std::uintptr_t kEventManagerGetLogIdOffset = 0x21eff10;

constexpr std::size_t kAbsoluteJumpLength = 14;
constexpr std::size_t kRelativeJumpLength = 5;
constexpr std::size_t kEventScopeSize = 0x170;
constexpr std::size_t kScopeObjectReferenceSize = 0x28;
constexpr std::size_t kCStringSize = 0x30;
constexpr std::size_t kKeyCapacity = 128;
constexpr std::size_t kOptionKeyCapacity = 80;
constexpr std::size_t kOptionCapacity = 16;
constexpr std::size_t kSeenEventCapacity = 8192;
constexpr std::size_t kCountryEventManagerOffset = 0x26c8;

constexpr std::array<unsigned char, 14> kAddOpenPlayerEventPrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55,
    0x41, 0x54, 0x53, 0x48, 0x83, 0xec, 0x28,
};
constexpr std::array<unsigned char, 14> kOpenPlayerEventUninitializePrefix = {
    0x53, 0x48, 0x89, 0xfb, 0x48, 0x8b, 0xbf,
    0x98, 0x01, 0x00, 0x00, 0x48, 0x85, 0xff,
};
constexpr std::array<unsigned char, 15> kCreateSituationPrefix = {
    0x48, 0x89, 0xf0, 0xbe, 0x30, 0x0e, 0x00, 0x00,
    0x48, 0x03, 0xb7, 0x30, 0x09, 0x00, 0x00,
};
constexpr std::array<unsigned char, 15> kDestroySituationPrefix = {
    0xb8, 0x30, 0x0e, 0x00, 0x00, 0x48, 0x03, 0x87,
    0x30, 0x09, 0x00, 0x00, 0x48, 0x89, 0xc7,
};
constexpr std::array<unsigned char, 17> kUpdateSituationStagePrefix = {
    0x41, 0x57, 0x41, 0x56, 0x53, 0x48, 0x83, 0xec, 0x30,
    0x49, 0x89, 0xfe, 0x40, 0x88, 0x74, 0x24, 0x0b,
};
constexpr std::array<unsigned char, 17> kSetSituationApproachPrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55, 0x41, 0x54,
    0x53, 0x48, 0x81, 0xec, 0xa8, 0x01, 0x00, 0x00,
};
constexpr std::array<unsigned char, 14> kAddSituationDelayedEventPrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55,
    0x41, 0x54, 0x53, 0x48, 0x83, 0xec, 0x78,
};
constexpr std::array<unsigned char, 14> kBeginEventChainPrefix = {
    0x41, 0x57, 0x41, 0x56, 0x41, 0x54, 0x53,
    0x50, 0x49, 0x89, 0xd6, 0x48, 0x89, 0xf3,
};
constexpr std::array<unsigned char, 14> kEndEventChainPrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55,
    0x41, 0x54, 0x53, 0x48, 0x83, 0xec, 0x18,
};
constexpr std::array<unsigned char, 14> kExecuteEventPrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55,
    0x41, 0x54, 0x53, 0x48, 0x83, 0xec, 0x38,
};

enum class EventKind : std::uint8_t {
  kEventExecuted = 1,
  kOpenEventAdded = 2,
  kOpenEventRemoved = 3,
  kSituationCreated = 4,
  kSituationDestroyed = 5,
  kSituationStageChanged = 6,
  kSituationApproachChanged = 7,
  kSituationDelayedEvent = 8,
  kEventChainStarted = 9,
  kEventChainEnded = 10,
};

struct OptionKey {
  std::int32_t index = -1;
  std::uint16_t size = 0;
  std::array<char, kOptionKeyCapacity> text{};
};

struct StateEvent {
  std::uint64_t sequence = 0;
  std::uint64_t monotonic_ns = 0;
  std::uint64_t realtime_ns = 0;
  std::uint64_t thread_id = 0;
  std::uint64_t dropped_before = 0;
  std::uintptr_t source_object = 0;
  std::uintptr_t definition_object = 0;
  std::uintptr_t caller = 0;
  std::uint64_t scope_type = 0;
  std::uint64_t scope_hash = 0;
  std::int64_t progress_before = 0;
  std::int64_t progress_after = 0;
  std::uint32_t country_id = 0xffffffffU;
  std::uint32_t scope_object_id = 0xffffffffU;
  std::uint32_t event_definition_id = 0xffffffffU;
  std::uint32_t open_event_id = 0xffffffffU;
  std::uint32_t situation_id = 0xffffffffU;
  std::uint32_t event_chain_definition_id = 0xffffffffU;
  std::int32_t option_index = -1;
  std::int32_t execution_mode = -1;
  std::int32_t delay_days = -1;
  std::int32_t stage_before = -1;
  std::int32_t stage_after = -1;
  std::uint16_t event_key_size = 0;
  std::uint16_t title_key_size = 0;
  std::uint16_t description_key_size = 0;
  std::uint16_t approach_key_size = 0;
  std::uint16_t raw_option_count = 0;
  std::uint8_t captured_option_count = 0;
  std::uint8_t text_truncated = 0;
  std::uint8_t content_included = 0;
  std::uint8_t flag = 0;
  EventKind kind = EventKind::kEventExecuted;
  std::array<char, kKeyCapacity> event_key{};
  std::array<char, kKeyCapacity> title_key{};
  std::array<char, kKeyCapacity> description_key{};
  std::array<char, kKeyCapacity> approach_key{};
  std::array<OptionKey, kOptionCapacity> options{};
};

static_assert(sizeof(StateEvent) <= 3072);

struct MainModuleIdentity {
  std::uintptr_t base = 0;
  std::uintptr_t end = 0;
  std::string build_id;
};

struct HookPatch {
  unsigned char* target = nullptr;
  void* trampoline = nullptr;
  void* relay = nullptr;
  std::size_t length = 0;
  std::array<unsigned char, 32> original{};
  bool applied = false;
};

struct alignas(16) CStringStorage {
  std::array<std::byte, kCStringSize> bytes{};
};

struct SituationSnapshot {
  std::uint32_t id = 0xffffffffU;
  std::uint32_t country_id = 0xffffffffU;
  std::int32_t stage = -1;
  std::int64_t progress = 0;
  const void* type = nullptr;
};

using AddOpenPlayerEventFn =
    void (*)(void*, const void*, const void*, const void*, int, bool);
using OpenPlayerEventUninitializeFn = void (*)(void*);
using CreateSituationFn =
    std::uint32_t (*)(void*, const void*, std::uint32_t, const void*);
using DestroySituationFn = void (*)(void*, std::uint32_t);
using UpdateSituationStageFn = void (*)(void*, bool);
using SetSituationApproachFn = void (*)(void*, const void*);
using AddSituationDelayedEventFn =
    void (*)(void*, const void*, const void*, int);
using BeginEventChainFn = bool (*)(void*, const void*, const void*);
using EndEventChainFn = bool (*)(void*, const void*);
using ExecuteEventFn = void (*)(const void*, void*, int, int, const void*);
using CStringDestroyFn = void (*)(void*);
using CStringGetDataFn = const char* (*)(const void*);
using CStringGetSizeFn = std::uint32_t (*)(const void*);
using GetOwnedCStringFn = void (*)(void*, const void*);
using EventManagerGetLogIdFn = void (*)(void*, const void*, int);

std::uintptr_t g_module_base = 0;
std::uintptr_t g_module_end = 0;
AddOpenPlayerEventFn g_original_add_open_event = nullptr;
OpenPlayerEventUninitializeFn g_original_uninitialize_open_event = nullptr;
CreateSituationFn g_original_create_situation = nullptr;
DestroySituationFn g_original_destroy_situation = nullptr;
UpdateSituationStageFn g_original_update_situation_stage = nullptr;
SetSituationApproachFn g_original_set_situation_approach = nullptr;
AddSituationDelayedEventFn g_original_add_situation_delayed_event = nullptr;
BeginEventChainFn g_original_begin_event_chain = nullptr;
EndEventChainFn g_original_end_event_chain = nullptr;
ExecuteEventFn g_original_execute_event = nullptr;
HookPatch g_add_open_event_patch;
HookPatch g_uninitialize_open_event_patch;
HookPatch g_create_situation_patch;
HookPatch g_destroy_situation_patch;
HookPatch g_update_situation_stage_patch;
HookPatch g_set_situation_approach_patch;
HookPatch g_add_situation_delayed_event_patch;
HookPatch g_begin_event_chain_patch;
HookPatch g_end_event_chain_patch;
HookPatch g_execute_event_patch;
std::array<std::atomic<std::uintptr_t>, kSeenEventCapacity>
    g_seen_event_definitions{};
std::atomic<std::uint64_t> g_sequence{0};
std::atomic<std::uint64_t> g_dropped{0};
int g_event_read_fd = -1;
int g_event_write_fd = -1;
iag::stellaris::research::RotatingProbeLog g_event_log;
char g_probe_status[256] = "not_initialized";

std::size_t Align4(std::size_t value) {
  return (value + 3U) & ~std::size_t{3U};
}

int ReadMainModuleIdentity(dl_phdr_info* info, std::size_t, void* opaque) {
  if (info->dlpi_name != nullptr && info->dlpi_name[0] != '\0') {
    return 0;
  }
  auto* identity = static_cast<MainModuleIdentity*>(opaque);
  identity->base = static_cast<std::uintptr_t>(info->dlpi_addr);
  for (ElfW(Half) index = 0; index < info->dlpi_phnum; ++index) {
    const auto& header = info->dlpi_phdr[index];
    if (header.p_type == PT_LOAD) {
      const auto end = identity->base + header.p_vaddr + header.p_memsz;
      if (end > identity->end) {
        identity->end = end;
      }
    }
    if (header.p_type != PT_NOTE) {
      continue;
    }
    const auto* cursor = reinterpret_cast<const unsigned char*>(
        identity->base + header.p_vaddr);
    const auto* end = cursor + header.p_memsz;
    while (cursor + sizeof(ElfW(Nhdr)) <= end) {
      const auto* note = reinterpret_cast<const ElfW(Nhdr)*>(cursor);
      cursor += sizeof(ElfW(Nhdr));
      const std::size_t name_size = Align4(note->n_namesz);
      const std::size_t description_size = Align4(note->n_descsz);
      if (cursor + name_size + description_size > end) {
        break;
      }
      const auto* name = cursor;
      const auto* description = cursor + name_size;
      if (note->n_type == NT_GNU_BUILD_ID && note->n_namesz == 4 &&
          std::memcmp(name, "GNU", 4) == 0) {
        static constexpr char kHex[] = "0123456789abcdef";
        identity->build_id.reserve(note->n_descsz * 2U);
        for (std::size_t byte = 0; byte < note->n_descsz; ++byte) {
          identity->build_id.push_back(kHex[description[byte] >> 4U]);
          identity->build_id.push_back(kHex[description[byte] & 0x0fU]);
        }
      }
      cursor += name_size + description_size;
    }
  }
  return 1;
}

template <std::size_t Size>
bool HasPrefix(
    std::uintptr_t address,
    const std::array<unsigned char, Size>& expected) {
  return std::memcmp(
             reinterpret_cast<const void*>(address), expected.data(), Size) == 0;
}

void WriteAbsoluteJump(unsigned char* destination, const void* target) {
  destination[0] = 0xff;
  destination[1] = 0x25;
  std::memset(destination + 2, 0, 4);
  const auto value = reinterpret_cast<std::uintptr_t>(target);
  std::memcpy(destination + 6, &value, sizeof(value));
}

bool PrepareHook(HookPatch* patch, std::uintptr_t address, std::size_t length) {
  if (length < kRelativeJumpLength || length > patch->original.size()) {
    std::snprintf(g_probe_status, sizeof(g_probe_status), "invalid_hook_length");
    return false;
  }
  patch->target = reinterpret_cast<unsigned char*>(address);
  patch->length = length;
  std::memcpy(patch->original.data(), patch->target, length);
  const std::size_t trampoline_size = length + kAbsoluteJumpLength;
  patch->trampoline = ::mmap(
      nullptr,
      trampoline_size,
      PROT_READ | PROT_WRITE | PROT_EXEC,
      MAP_PRIVATE | MAP_ANONYMOUS,
      -1,
      0);
  if (patch->trampoline == MAP_FAILED) {
    patch->trampoline = nullptr;
    std::snprintf(g_probe_status, sizeof(g_probe_status), "trampoline_mmap_failed");
    return false;
  }
  std::memcpy(patch->trampoline, patch->target, length);
  WriteAbsoluteJump(
      static_cast<unsigned char*>(patch->trampoline) + length,
      patch->target + length);
  __builtin___clear_cache(
      static_cast<char*>(patch->trampoline),
      static_cast<char*>(patch->trampoline) + trampoline_size);
  if (::mprotect(patch->trampoline, trampoline_size, PROT_READ | PROT_EXEC) != 0) {
    std::snprintf(
        g_probe_status, sizeof(g_probe_status), "trampoline_mprotect_failed");
    return false;
  }
  return true;
}

bool SetTargetProtection(const HookPatch& patch, int protection) {
  const long page_size = ::sysconf(_SC_PAGESIZE);
  if (page_size <= 0) {
    return false;
  }
  const auto page_mask = static_cast<std::uintptr_t>(page_size - 1);
  const auto first_page =
      reinterpret_cast<std::uintptr_t>(patch.target) & ~page_mask;
  const auto last_byte = reinterpret_cast<std::uintptr_t>(patch.target) +
                         patch.length - 1U;
  const auto last_page = last_byte & ~page_mask;
  const auto size = static_cast<std::size_t>(last_page - first_page) +
                    static_cast<std::size_t>(page_size);
  return ::mprotect(reinterpret_cast<void*>(first_page), size, protection) == 0;
}

bool ApplyHook(HookPatch* patch, void* hook) {
  patch->relay = ::mmap(
      nullptr,
      kAbsoluteJumpLength,
      PROT_READ | PROT_WRITE | PROT_EXEC,
      MAP_PRIVATE | MAP_ANONYMOUS | MAP_32BIT,
      -1,
      0);
  if (patch->relay == MAP_FAILED) {
    patch->relay = nullptr;
    std::snprintf(g_probe_status, sizeof(g_probe_status), "relay_mmap_failed");
    return false;
  }
  const auto relative_distance =
      reinterpret_cast<std::intptr_t>(patch->relay) -
      (reinterpret_cast<std::intptr_t>(patch->target) +
       static_cast<std::intptr_t>(kRelativeJumpLength));
  if (relative_distance < std::numeric_limits<std::int32_t>::min() ||
      relative_distance > std::numeric_limits<std::int32_t>::max()) {
    std::snprintf(g_probe_status, sizeof(g_probe_status), "relay_out_of_range");
    return false;
  }
  WriteAbsoluteJump(static_cast<unsigned char*>(patch->relay), hook);
  __builtin___clear_cache(
      static_cast<char*>(patch->relay),
      static_cast<char*>(patch->relay) + kAbsoluteJumpLength);
  if (::mprotect(patch->relay, kAbsoluteJumpLength, PROT_READ | PROT_EXEC) != 0) {
    std::snprintf(g_probe_status, sizeof(g_probe_status), "relay_mprotect_failed");
    return false;
  }
  if (!SetTargetProtection(*patch, PROT_READ | PROT_WRITE | PROT_EXEC)) {
    std::snprintf(g_probe_status, sizeof(g_probe_status), "hook_mprotect_failed");
    return false;
  }
  std::array<unsigned char, 32> bytes{};
  bytes.fill(0x90);
  bytes[0] = 0xe9;
  const auto encoded_distance = static_cast<std::int32_t>(relative_distance);
  std::memcpy(bytes.data() + 1, &encoded_distance, sizeof(encoded_distance));
  std::memcpy(patch->target, bytes.data(), patch->length);
  __builtin___clear_cache(
      reinterpret_cast<char*>(patch->target),
      reinterpret_cast<char*>(patch->target) + patch->length);
  patch->applied = true;
  if (!SetTargetProtection(*patch, PROT_READ | PROT_EXEC)) {
    std::snprintf(
        g_probe_status, sizeof(g_probe_status), "hook_restore_protection_failed");
    return false;
  }
  return true;
}

void RestoreHook(HookPatch* patch) {
  if (!patch->applied ||
      !SetTargetProtection(*patch, PROT_READ | PROT_WRITE | PROT_EXEC)) {
    return;
  }
  std::memcpy(patch->target, patch->original.data(), patch->length);
  __builtin___clear_cache(
      reinterpret_cast<char*>(patch->target),
      reinterpret_cast<char*>(patch->target) + patch->length);
  (void)SetTargetProtection(*patch, PROT_READ | PROT_EXEC);
  patch->applied = false;
}

std::uint64_t ClockNanoseconds(clockid_t clock) {
  timespec value{};
  if (::clock_gettime(clock, &value) != 0) {
    return 0;
  }
  return static_cast<std::uint64_t>(value.tv_sec) * 1000000000ULL +
         static_cast<std::uint64_t>(value.tv_nsec);
}

template <typename Value>
Value ReadField(const void* object, std::size_t offset) {
  Value value{};
  if (object != nullptr) {
    std::memcpy(
        &value, static_cast<const std::byte*>(object) + offset, sizeof(value));
  }
  return value;
}

std::uint64_t HashBytes(const void* value, std::size_t size) {
  if (value == nullptr) {
    return 0;
  }
  constexpr std::uint64_t kOffset = 1469598103934665603ULL;
  constexpr std::uint64_t kPrime = 1099511628211ULL;
  std::uint64_t hash = kOffset;
  const auto* bytes = static_cast<const unsigned char*>(value);
  for (std::size_t index = 0; index < size; ++index) {
    hash ^= bytes[index];
    hash *= kPrime;
  }
  return hash;
}

void CaptureScope(StateEvent* event, const void* scope, std::size_t size) {
  if (scope == nullptr || size < 0x14U) {
    return;
  }
  event->scope_type = ReadField<std::uint64_t>(scope, 0x08);
  event->scope_object_id = ReadField<std::uint32_t>(scope, 0x10);
  event->scope_hash = HashBytes(scope, size);
}

bool ClaimFirstEventDefinition(std::uintptr_t event_definition) {
  std::size_t slot = (event_definition >> 4U) % kSeenEventCapacity;
  for (std::size_t probe = 0; probe < 32; ++probe) {
    auto& entry = g_seen_event_definitions[(slot + probe) % kSeenEventCapacity];
    std::uintptr_t observed = entry.load(std::memory_order_relaxed);
    if (observed == event_definition) {
      return false;
    }
    if (observed == 0 && entry.compare_exchange_strong(
                             observed,
                             event_definition,
                             std::memory_order_relaxed)) {
      return true;
    }
  }
  return false;
}

template <std::size_t Capacity>
bool CopyCString(
    const void* value,
    std::array<char, Capacity>* destination,
    std::uint16_t* copied_size) {
  *copied_size = 0;
  if (value == nullptr) {
    return false;
  }
  const auto get_size = reinterpret_cast<CStringGetSizeFn>(
      g_module_base + kCStringGetSizeOffset);
  const auto get_data = reinterpret_cast<CStringGetDataFn>(
      g_module_base + kCStringGetDataOffset);
  const std::uint32_t raw_size = get_size(value);
  const char* data = get_data(value);
  if (data == nullptr || raw_size == 0U) {
    return false;
  }
  const auto copy_size = std::min<std::size_t>(raw_size, Capacity);
  std::memcpy(destination->data(), data, copy_size);
  *copied_size = static_cast<std::uint16_t>(copy_size);
  return raw_size > Capacity;
}

template <std::size_t Capacity>
bool CopyDatabaseKey(
    const void* definition,
    std::array<char, Capacity>* destination,
    std::uint16_t* copied_size) {
  return definition != nullptr &&
         CopyCString(
             static_cast<const std::byte*>(definition) + 0x10,
             destination,
             copied_size);
}

void CaptureOwnedCString(
    StateEvent* event,
    GetOwnedCStringFn getter,
    const void* source,
    std::array<char, kKeyCapacity>* destination,
    std::uint16_t* copied_size) {
  CStringStorage storage;
  getter(storage.bytes.data(), source);
  if (CopyCString(storage.bytes.data(), destination, copied_size)) {
    event->text_truncated = 1;
  }
  reinterpret_cast<CStringDestroyFn>(
      g_module_base + kCStringDestroyOffset)(storage.bytes.data());
}

void CaptureEventDefinition(StateEvent* event, const void* definition) {
  if (definition == nullptr) {
    return;
  }
  event->content_included = 1;
  event->definition_object = reinterpret_cast<std::uintptr_t>(definition);
  event->event_definition_id = ReadField<std::uint32_t>(definition, 0x08);

  const void* manager = *reinterpret_cast<void* const*>(
      g_module_base + kEventManagerInstanceOffset);
  if (manager != nullptr) {
    CStringStorage storage;
    reinterpret_cast<EventManagerGetLogIdFn>(
        g_module_base + kEventManagerGetLogIdOffset)(
        storage.bytes.data(), manager, static_cast<int>(event->event_definition_id));
    if (CopyCString(
            storage.bytes.data(), &event->event_key, &event->event_key_size)) {
      event->text_truncated = 1;
    }
    reinterpret_cast<CStringDestroyFn>(
        g_module_base + kCStringDestroyOffset)(storage.bytes.data());
  }

  if (CopyCString(
          static_cast<const std::byte*>(definition) + 0x110,
          &event->title_key,
          &event->title_key_size)) {
    event->text_truncated = 1;
  }
  CaptureOwnedCString(
      event,
      reinterpret_cast<GetOwnedCStringFn>(
          g_module_base + kEventGetFirstDescriptionKeyOffset),
      definition,
      &event->description_key,
      &event->description_key_size);

  const void* options = static_cast<const std::byte*>(definition) + 0x5e0;
  const int raw_count = ReadField<int>(options, 0x14);
  const std::byte* entries = ReadField<const std::byte*>(options, 0x08);
  if (raw_count < 0 || raw_count > 4096 ||
      (raw_count != 0 && entries == nullptr)) {
    return;
  }
  event->raw_option_count = static_cast<std::uint16_t>(
      std::min(raw_count, static_cast<int>(std::numeric_limits<std::uint16_t>::max())));
  const int limit = std::min(raw_count, static_cast<int>(kOptionCapacity));
  for (int index = 0; index < limit; ++index) {
    const void* option = ReadField<const void*>(
        entries, static_cast<std::size_t>(index) * 0x10U);
    if (option == nullptr) {
      continue;
    }
    OptionKey& target = event->options[event->captured_option_count];
    target.index = index;
    CStringStorage storage;
    reinterpret_cast<GetOwnedCStringFn>(
        g_module_base + kEventOptionGetFirstKeyOffset)(
        storage.bytes.data(), option);
    if (CopyCString(storage.bytes.data(), &target.text, &target.size)) {
      event->text_truncated = 1;
    }
    reinterpret_cast<CStringDestroyFn>(
        g_module_base + kCStringDestroyOffset)(storage.bytes.data());
    ++event->captured_option_count;
  }
  if (raw_count > limit) {
    event->text_truncated = 1;
  }
}

void CaptureEventDefinitionOnce(StateEvent* event, const void* definition) {
  if (definition == nullptr) {
    return;
  }
  event->definition_object = reinterpret_cast<std::uintptr_t>(definition);
  event->event_definition_id = ReadField<std::uint32_t>(definition, 0x08);
  if (ClaimFirstEventDefinition(
          reinterpret_cast<std::uintptr_t>(definition))) {
    CaptureEventDefinition(event, definition);
  }
}

const void* EventFromHandle(const void* handle) {
  return handle == nullptr ? nullptr : ReadField<const void*>(handle, 0x00);
}

SituationSnapshot ReadSituation(const void* situation) {
  SituationSnapshot snapshot;
  if (situation == nullptr) {
    return snapshot;
  }
  snapshot.id = ReadField<std::uint32_t>(situation, 0x08);
  snapshot.country_id = ReadField<std::uint32_t>(situation, 0x204);
  snapshot.type = ReadField<const void*>(situation, 0x208);
  snapshot.progress = ReadField<std::int64_t>(situation, 0x218);
  snapshot.stage = ReadField<std::int32_t>(situation, 0x570);
  return snapshot;
}

void FillSituation(StateEvent* event, const void* situation) {
  const SituationSnapshot snapshot = ReadSituation(situation);
  event->source_object = reinterpret_cast<std::uintptr_t>(situation);
  event->situation_id = snapshot.id;
  event->country_id = snapshot.country_id;
  event->stage_after = snapshot.stage;
  event->progress_after = snapshot.progress;
  event->definition_object = reinterpret_cast<std::uintptr_t>(snapshot.type);
  if (CopyDatabaseKey(
          snapshot.type,
          &event->event_key,
          &event->event_key_size)) {
    event->text_truncated = 1;
  }
}

void Emit(StateEvent event) {
  if (g_event_write_fd < 0) {
    return;
  }
  event.sequence = g_sequence.fetch_add(1, std::memory_order_relaxed) + 1U;
  event.monotonic_ns = ClockNanoseconds(CLOCK_MONOTONIC);
  event.realtime_ns = ClockNanoseconds(CLOCK_REALTIME);
  event.thread_id = static_cast<std::uint64_t>(::syscall(SYS_gettid));
  event.dropped_before = g_dropped.exchange(0, std::memory_order_relaxed);
  const ssize_t written = ::write(g_event_write_fd, &event, sizeof(event));
  if (written != static_cast<ssize_t>(sizeof(event))) {
    g_dropped.fetch_add(event.dropped_before + 1U, std::memory_order_relaxed);
  }
}

void AddOpenPlayerEventHook(
    void* game_state,
    const void* country,
    const void* handle,
    const void* scope,
    int open_event_id,
    bool flag) {
  g_original_add_open_event(
      game_state, country, handle, scope, open_event_id, flag);
  StateEvent event;
  event.kind = EventKind::kOpenEventAdded;
  event.caller = reinterpret_cast<std::uintptr_t>(__builtin_return_address(0));
  event.open_event_id = static_cast<std::uint32_t>(open_event_id);
  event.country_id = ReadField<std::uint32_t>(country, 0x20);
  event.flag = flag ? 1U : 0U;
  CaptureScope(&event, scope, kEventScopeSize);
  CaptureEventDefinitionOnce(&event, EventFromHandle(handle));
  Emit(event);
}

void OpenPlayerEventUninitializeHook(void* open_event) {
  StateEvent event;
  event.kind = EventKind::kOpenEventRemoved;
  event.caller = reinterpret_cast<std::uintptr_t>(__builtin_return_address(0));
  event.source_object = reinterpret_cast<std::uintptr_t>(open_event);
  event.open_event_id = ReadField<std::uint32_t>(open_event, 0x180);
  event.country_id = ReadField<std::uint32_t>(open_event, 0x184);
  const void* handle = ReadField<const void*>(open_event, 0x08);
  CaptureEventDefinitionOnce(&event, EventFromHandle(handle));
  Emit(event);
  g_original_uninitialize_open_event(open_event);
}

std::uint32_t CreateSituationHook(
    void* game_state,
    const void* situation_type,
    std::uint32_t country_id,
    const void* target) {
  const std::uint32_t situation_id = g_original_create_situation(
      game_state, situation_type, country_id, target);
  StateEvent event;
  event.kind = EventKind::kSituationCreated;
  event.caller = reinterpret_cast<std::uintptr_t>(__builtin_return_address(0));
  event.situation_id = situation_id;
  event.country_id = country_id;
  event.definition_object = reinterpret_cast<std::uintptr_t>(situation_type);
  CaptureScope(&event, target, kScopeObjectReferenceSize);
  if (CopyDatabaseKey(
          situation_type,
          &event.event_key,
          &event.event_key_size)) {
    event.text_truncated = 1;
  }
  Emit(event);
  return situation_id;
}

void DestroySituationHook(void* game_state, std::uint32_t situation_id) {
  g_original_destroy_situation(game_state, situation_id);
  StateEvent event;
  event.kind = EventKind::kSituationDestroyed;
  event.caller = reinterpret_cast<std::uintptr_t>(__builtin_return_address(0));
  event.situation_id = situation_id;
  Emit(event);
}

void UpdateSituationStageHook(void* situation, bool force) {
  const SituationSnapshot before = ReadSituation(situation);
  g_original_update_situation_stage(situation, force);
  const SituationSnapshot after = ReadSituation(situation);
  if (before.stage == after.stage && before.progress == after.progress) {
    return;
  }
  StateEvent event;
  event.kind = EventKind::kSituationStageChanged;
  event.caller = reinterpret_cast<std::uintptr_t>(__builtin_return_address(0));
  FillSituation(&event, situation);
  event.stage_before = before.stage;
  event.stage_after = after.stage;
  event.progress_before = before.progress;
  event.progress_after = after.progress;
  event.flag = force ? 1U : 0U;
  Emit(event);
}

void SetSituationApproachHook(void* situation, const void* approach) {
  g_original_set_situation_approach(situation, approach);
  StateEvent event;
  event.kind = EventKind::kSituationApproachChanged;
  event.caller = reinterpret_cast<std::uintptr_t>(__builtin_return_address(0));
  FillSituation(&event, situation);
  if (approach != nullptr &&
      CopyCString(
          static_cast<const std::byte*>(approach) + 0x08,
          &event.approach_key,
          &event.approach_key_size)) {
    event.text_truncated = 1;
  }
  Emit(event);
}

void AddSituationDelayedEventHook(
    void* situation,
    const void* handle,
    const void* scope,
    int delay_days) {
  g_original_add_situation_delayed_event(
      situation, handle, scope, delay_days);
  StateEvent event;
  event.kind = EventKind::kSituationDelayedEvent;
  event.caller = reinterpret_cast<std::uintptr_t>(__builtin_return_address(0));
  FillSituation(&event, situation);
  event.delay_days = delay_days;
  CaptureScope(&event, scope, kEventScopeSize);
  CaptureEventDefinitionOnce(&event, EventFromHandle(handle));
  Emit(event);
}

bool BeginEventChainHook(
    void* manager, const void* definition, const void* scope) {
  const bool started = g_original_begin_event_chain(manager, definition, scope);
  if (!started) {
    return false;
  }
  StateEvent event;
  event.kind = EventKind::kEventChainStarted;
  event.caller = reinterpret_cast<std::uintptr_t>(__builtin_return_address(0));
  event.source_object = reinterpret_cast<std::uintptr_t>(manager);
  event.definition_object = reinterpret_cast<std::uintptr_t>(definition);
  const void* country = static_cast<const std::byte*>(manager) -
                        kCountryEventManagerOffset;
  event.country_id = ReadField<std::uint32_t>(country, 0x20);
  event.event_chain_definition_id = ReadField<std::uint32_t>(definition, 0x08);
  CaptureScope(&event, scope, kEventScopeSize);
  if (CopyDatabaseKey(
          definition, &event.event_key, &event.event_key_size)) {
    event.text_truncated = 1;
  }
  Emit(event);
  return true;
}

bool EndEventChainHook(void* manager, const void* definition) {
  const bool ended = g_original_end_event_chain(manager, definition);
  if (!ended) {
    return false;
  }
  StateEvent event;
  event.kind = EventKind::kEventChainEnded;
  event.caller = reinterpret_cast<std::uintptr_t>(__builtin_return_address(0));
  event.source_object = reinterpret_cast<std::uintptr_t>(manager);
  event.definition_object = reinterpret_cast<std::uintptr_t>(definition);
  const void* country = static_cast<const std::byte*>(manager) -
                        kCountryEventManagerOffset;
  event.country_id = ReadField<std::uint32_t>(country, 0x20);
  event.event_chain_definition_id = ReadField<std::uint32_t>(definition, 0x08);
  if (CopyDatabaseKey(
          definition, &event.event_key, &event.event_key_size)) {
    event.text_truncated = 1;
  }
  Emit(event);
  return true;
}

void ExecuteEventHook(
    const void* definition,
    void* scope,
    int option_index,
    int execution_mode,
    const void* user_data) {
  g_original_execute_event(
      definition, scope, option_index, execution_mode, user_data);
  StateEvent event;
  event.kind = EventKind::kEventExecuted;
  event.caller = reinterpret_cast<std::uintptr_t>(__builtin_return_address(0));
  event.source_object = reinterpret_cast<std::uintptr_t>(definition);
  event.definition_object = reinterpret_cast<std::uintptr_t>(definition);
  event.option_index = option_index;
  event.execution_mode = execution_mode;
  CaptureScope(&event, scope, kEventScopeSize);
  CaptureEventDefinitionOnce(&event, definition);
  Emit(event);
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

std::string Hex(std::uintptr_t value) {
  char buffer[2 + sizeof(value) * 2 + 1]{};
  std::snprintf(
      buffer,
      sizeof(buffer),
      "0x%lx",
      static_cast<unsigned long>(value));
  return buffer;
}

std::string AddressLabel(std::uintptr_t address) {
  if (address >= g_module_base && address < g_module_end) {
    return "stellaris+" + Hex(address - g_module_base);
  }
  Dl_info information{};
  if (::dladdr(reinterpret_cast<void*>(address), &information) != 0 &&
      information.dli_fname != nullptr && information.dli_fbase != nullptr) {
    std::string module(information.dli_fname);
    const std::size_t slash = module.find_last_of('/');
    if (slash != std::string::npos) {
      module.erase(0, slash + 1U);
    }
    return module + "+" +
           Hex(address - reinterpret_cast<std::uintptr_t>(information.dli_fbase));
  }
  return Hex(address);
}

std::string_view TextView(
    const std::array<char, kKeyCapacity>& text, std::uint16_t size) {
  return std::string_view(text.data(), std::min<std::size_t>(size, text.size()));
}

std::string_view OptionTextView(const OptionKey& option) {
  return std::string_view(
      option.text.data(),
      std::min<std::size_t>(option.size, option.text.size()));
}

const char* KindName(EventKind kind) {
  switch (kind) {
    case EventKind::kEventExecuted:
      return "event_executed";
    case EventKind::kOpenEventAdded:
      return "open_event_added";
    case EventKind::kOpenEventRemoved:
      return "open_event_removed";
    case EventKind::kSituationCreated:
      return "situation_created";
    case EventKind::kSituationDestroyed:
      return "situation_destroyed";
    case EventKind::kSituationStageChanged:
      return "situation_stage_changed";
    case EventKind::kSituationApproachChanged:
      return "situation_approach_changed";
    case EventKind::kSituationDelayedEvent:
      return "situation_delayed_event";
    case EventKind::kEventChainStarted:
      return "event_chain_started";
    case EventKind::kEventChainEnded:
      return "event_chain_ended";
  }
  return "unknown";
}

void AppendText(
    std::string* output,
    std::string_view name,
    std::string_view value) {
  *output += ",\"";
  *output += name;
  *output += "\":\"";
  *output += JsonEscape(value);
  output->push_back('"');
}

std::string SerializeEvent(
    const StateEvent& event, std::uint64_t writer_dropped_before) {
  std::string output;
  output.reserve(4096);
  output += "{\"schema\":\"";
  output += kSchema;
  output += "\",\"kind\":\"";
  output += KindName(event.kind);
  output += "\",\"sequence\":" + std::to_string(event.sequence);
  output += ",\"monotonic_ns\":" + std::to_string(event.monotonic_ns);
  output += ",\"realtime_ns\":" + std::to_string(event.realtime_ns);
  output += ",\"thread_id\":" + std::to_string(event.thread_id);
  output += ",\"dropped_before\":" + std::to_string(event.dropped_before);
  output += ",\"writer_dropped_before\":" +
            std::to_string(writer_dropped_before);
  output += ",\"source_object\":\"" + Hex(event.source_object) + "\"";
  output += ",\"definition_object\":\"" + Hex(event.definition_object) + "\"";
  AppendText(&output, "caller", AddressLabel(event.caller));
  output += ",\"country_id\":" + std::to_string(event.country_id);
  output += ",\"scope_type\":" + std::to_string(event.scope_type);
  output += ",\"scope_object_id\":" + std::to_string(event.scope_object_id);
  output += ",\"scope_hash\":\"" + Hex(event.scope_hash) + "\"";
  output += ",\"event_definition_id\":" +
            std::to_string(event.event_definition_id);
  output += ",\"open_event_id\":" + std::to_string(event.open_event_id);
  output += ",\"situation_id\":" + std::to_string(event.situation_id);
  output += ",\"event_chain_definition_id\":" +
            std::to_string(event.event_chain_definition_id);
  output += ",\"option_index\":" + std::to_string(event.option_index);
  output += ",\"execution_mode\":" + std::to_string(event.execution_mode);
  output += ",\"delay_days\":" + std::to_string(event.delay_days);
  output += ",\"stage_before\":" + std::to_string(event.stage_before);
  output += ",\"stage_after\":" + std::to_string(event.stage_after);
  output += ",\"progress_before_raw\":" +
            std::to_string(event.progress_before);
  output += ",\"progress_after_raw\":" +
            std::to_string(event.progress_after);
  output += ",\"flag\":" + std::string(event.flag ? "true" : "false");
  output += ",\"content_included\":" +
            std::string(event.content_included ? "true" : "false");
  output += ",\"text_truncated\":" +
            std::string(event.text_truncated ? "true" : "false");
  AppendText(
      &output, "event_or_type_key", TextView(event.event_key, event.event_key_size));
  AppendText(
      &output, "title_key", TextView(event.title_key, event.title_key_size));
  AppendText(
      &output,
      "description_key",
      TextView(event.description_key, event.description_key_size));
  AppendText(
      &output,
      "approach_key",
      TextView(event.approach_key, event.approach_key_size));
  output += ",\"raw_option_count\":" +
            std::to_string(event.raw_option_count);
  output += ",\"options\":[";
  for (std::size_t index = 0; index < event.captured_option_count; ++index) {
    if (index != 0U) {
      output.push_back(',');
    }
    output += "{\"option_index\":" +
              std::to_string(event.options[index].index);
    output += ",\"text_key\":\"" +
              JsonEscape(OptionTextView(event.options[index])) + "\"}";
  }
  output += "]}\n";
  return output;
}

void* WriterThread(void*) {
  StateEvent event;
  std::uint64_t writer_dropped = 0;
  while (true) {
    const ssize_t received = ::read(g_event_read_fd, &event, sizeof(event));
    if (received == static_cast<ssize_t>(sizeof(event))) {
      const std::string line = SerializeEvent(event, writer_dropped);
      if (g_event_log.Write(line, event.monotonic_ns)) {
        writer_dropped = 0;
      } else {
        ++writer_dropped;
      }
      continue;
    }
    if (received < 0 && errno == EINTR) {
      continue;
    }
    if (received == 0) {
      break;
    }
  }
  return nullptr;
}

bool OpenEventStream() {
  const char* configured_path = std::getenv("IAG_STATE_PROBE_LOG");
  const char* log_path = configured_path != nullptr && configured_path[0] != '\0'
                             ? configured_path
                             : kDefaultLogPath;
  int descriptors[2]{};
  if (::pipe2(descriptors, O_CLOEXEC) != 0) {
    std::snprintf(g_probe_status, sizeof(g_probe_status), "pipe_create_failed");
    return false;
  }
  g_event_read_fd = descriptors[0];
  g_event_write_fd = descriptors[1];
  const int write_flags = ::fcntl(g_event_write_fd, F_GETFL, 0);
  if (write_flags < 0 ||
      ::fcntl(g_event_write_fd, F_SETFL, write_flags | O_NONBLOCK) != 0) {
    std::snprintf(g_probe_status, sizeof(g_probe_status), "pipe_nonblock_failed");
    return false;
  }

  std::string header = "{\"schema\":\"";
  header += kSchema;
  header += "\",\"kind\":\"probe_started\",\"pid\":";
  header += std::to_string(static_cast<unsigned long>(::getpid()));
  header += ",\"build_id\":\"";
  header += kExpectedBuildId;
  header += "\",\"execute_event_offset\":\"" + Hex(kExecuteEventOffset);
  header += "\",\"add_open_event_offset\":\"" + Hex(kAddOpenPlayerEventOffset);
  header += "\",\"create_situation_offset\":\"" + Hex(kCreateSituationOffset);
  header += "\",\"begin_event_chain_offset\":\"" + Hex(kBeginEventChainOffset);
  header += "\"}\n";
  if (!g_event_log.Open(
          log_path,
          std::move(header),
          "IAG_STATE_PROBE_ROTATE_BYTES",
          "IAG_STATE_PROBE_ROTATE_SECONDS",
          "IAG_PROBE_MIN_FREE_BYTES",
          64ULL * 1024ULL * 1024ULL,
          15ULL * 60ULL,
          5ULL * 1024ULL * 1024ULL * 1024ULL)) {
    std::snprintf(
        g_probe_status, sizeof(g_probe_status), "%s", g_event_log.error());
    return false;
  }
  pthread_t thread{};
  if (::pthread_create(&thread, nullptr, &WriterThread, nullptr) != 0) {
    std::snprintf(g_probe_status, sizeof(g_probe_status), "writer_thread_failed");
    return false;
  }
  (void)::pthread_detach(thread);
  return true;
}

bool VerifyExecutable() {
  MainModuleIdentity identity;
  ::dl_iterate_phdr(ReadMainModuleIdentity, &identity);
  if (identity.build_id != kExpectedBuildId) {
    std::snprintf(
        g_probe_status,
        sizeof(g_probe_status),
        "build_id_mismatch:%s",
        identity.build_id.c_str());
    return false;
  }
  g_module_base = identity.base;
  g_module_end = identity.end;
  const bool valid =
      HasPrefix(
          g_module_base + kAddOpenPlayerEventOffset,
          kAddOpenPlayerEventPrefix) &&
      HasPrefix(
          g_module_base + kOpenPlayerEventUninitializeOffset,
          kOpenPlayerEventUninitializePrefix) &&
      HasPrefix(g_module_base + kCreateSituationOffset, kCreateSituationPrefix) &&
      HasPrefix(g_module_base + kDestroySituationOffset, kDestroySituationPrefix) &&
      HasPrefix(
          g_module_base + kUpdateSituationStageOffset,
          kUpdateSituationStagePrefix) &&
      HasPrefix(
          g_module_base + kSetSituationApproachOffset,
          kSetSituationApproachPrefix) &&
      HasPrefix(
          g_module_base + kAddSituationDelayedEventOffset,
          kAddSituationDelayedEventPrefix) &&
      HasPrefix(g_module_base + kBeginEventChainOffset, kBeginEventChainPrefix) &&
      HasPrefix(g_module_base + kEndEventChainOffset, kEndEventChainPrefix) &&
      HasPrefix(g_module_base + kExecuteEventOffset, kExecuteEventPrefix);
  if (!valid) {
    std::snprintf(
        g_probe_status, sizeof(g_probe_status), "function_signature_mismatch");
  }
  return valid;
}

bool PrepareHooks() {
  if (!PrepareHook(
          &g_add_open_event_patch,
          g_module_base + kAddOpenPlayerEventOffset,
          kAddOpenPlayerEventPrefix.size()) ||
      !PrepareHook(
          &g_uninitialize_open_event_patch,
          g_module_base + kOpenPlayerEventUninitializeOffset,
          kOpenPlayerEventUninitializePrefix.size()) ||
      !PrepareHook(
          &g_create_situation_patch,
          g_module_base + kCreateSituationOffset,
          kCreateSituationPrefix.size()) ||
      !PrepareHook(
          &g_destroy_situation_patch,
          g_module_base + kDestroySituationOffset,
          kDestroySituationPrefix.size()) ||
      !PrepareHook(
          &g_update_situation_stage_patch,
          g_module_base + kUpdateSituationStageOffset,
          kUpdateSituationStagePrefix.size()) ||
      !PrepareHook(
          &g_set_situation_approach_patch,
          g_module_base + kSetSituationApproachOffset,
          kSetSituationApproachPrefix.size()) ||
      !PrepareHook(
          &g_add_situation_delayed_event_patch,
          g_module_base + kAddSituationDelayedEventOffset,
          kAddSituationDelayedEventPrefix.size()) ||
      !PrepareHook(
          &g_begin_event_chain_patch,
          g_module_base + kBeginEventChainOffset,
          kBeginEventChainPrefix.size()) ||
      !PrepareHook(
          &g_end_event_chain_patch,
          g_module_base + kEndEventChainOffset,
          kEndEventChainPrefix.size()) ||
      !PrepareHook(
          &g_execute_event_patch,
          g_module_base + kExecuteEventOffset,
          kExecuteEventPrefix.size())) {
    return false;
  }
  g_original_add_open_event = reinterpret_cast<AddOpenPlayerEventFn>(
      g_add_open_event_patch.trampoline);
  g_original_uninitialize_open_event =
      reinterpret_cast<OpenPlayerEventUninitializeFn>(
          g_uninitialize_open_event_patch.trampoline);
  g_original_create_situation = reinterpret_cast<CreateSituationFn>(
      g_create_situation_patch.trampoline);
  g_original_destroy_situation = reinterpret_cast<DestroySituationFn>(
      g_destroy_situation_patch.trampoline);
  g_original_update_situation_stage =
      reinterpret_cast<UpdateSituationStageFn>(
          g_update_situation_stage_patch.trampoline);
  g_original_set_situation_approach =
      reinterpret_cast<SetSituationApproachFn>(
          g_set_situation_approach_patch.trampoline);
  g_original_add_situation_delayed_event =
      reinterpret_cast<AddSituationDelayedEventFn>(
          g_add_situation_delayed_event_patch.trampoline);
  g_original_begin_event_chain = reinterpret_cast<BeginEventChainFn>(
      g_begin_event_chain_patch.trampoline);
  g_original_end_event_chain = reinterpret_cast<EndEventChainFn>(
      g_end_event_chain_patch.trampoline);
  g_original_execute_event = reinterpret_cast<ExecuteEventFn>(
      g_execute_event_patch.trampoline);
  return true;
}

bool ApplyHooks() {
  const std::array<std::pair<HookPatch*, void*>, 10> hooks = {{
      {&g_add_open_event_patch, reinterpret_cast<void*>(&AddOpenPlayerEventHook)},
      {&g_uninitialize_open_event_patch,
       reinterpret_cast<void*>(&OpenPlayerEventUninitializeHook)},
      {&g_create_situation_patch, reinterpret_cast<void*>(&CreateSituationHook)},
      {&g_destroy_situation_patch, reinterpret_cast<void*>(&DestroySituationHook)},
      {&g_update_situation_stage_patch,
       reinterpret_cast<void*>(&UpdateSituationStageHook)},
      {&g_set_situation_approach_patch,
       reinterpret_cast<void*>(&SetSituationApproachHook)},
      {&g_add_situation_delayed_event_patch,
       reinterpret_cast<void*>(&AddSituationDelayedEventHook)},
      {&g_begin_event_chain_patch, reinterpret_cast<void*>(&BeginEventChainHook)},
      {&g_end_event_chain_patch, reinterpret_cast<void*>(&EndEventChainHook)},
      {&g_execute_event_patch, reinterpret_cast<void*>(&ExecuteEventHook)},
  }};
  std::size_t applied = 0;
  for (; applied < hooks.size(); ++applied) {
    if (!ApplyHook(hooks[applied].first, hooks[applied].second)) {
      while (applied > 0U) {
        --applied;
        RestoreHook(hooks[applied].first);
      }
      return false;
    }
  }
  return true;
}

__attribute__((constructor)) void InitializeProbe() {
  if (!VerifyExecutable() || !OpenEventStream() || !PrepareHooks() ||
      !ApplyHooks()) {
    return;
  }
  std::snprintf(
      g_probe_status,
      sizeof(g_probe_status),
      "ready:pid=%lu:event=0x%lx:situation=0x%lx:chain=0x%lx",
      static_cast<unsigned long>(::getpid()),
      static_cast<unsigned long>(kExecuteEventOffset),
      static_cast<unsigned long>(kCreateSituationOffset),
      static_cast<unsigned long>(kBeginEventChainOffset));
}

}  // namespace

extern "C" const char* iag_stellaris_event_state_probe_status() {
  return g_probe_status;
}
