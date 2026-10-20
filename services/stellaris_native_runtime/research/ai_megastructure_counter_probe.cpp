#include <algorithm>
#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <elf.h>
#include <link.h>
#include <limits>
#include <pthread.h>
#include <string>
#include <string_view>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <utility>
#include <vector>

#include "rotating_probe_log.h"

namespace {

constexpr char kExpectedBuildId[] =
    "c6969e60fd81d738948222a94c0b5a0841abbffc";
constexpr char kSchema[] = "iag.stellaris.ai_megastructure_counter.v1";
constexpr char kDefaultLogPath[] =
    "/tmp/iag-stellaris-ai-megastructure-counter.jsonl";
constexpr char kDefaultPausePath[] =
    "/tmp/iag-stellaris-ai-megastructure-counter.pause";

// Stellaris 4.4.6 (fdde), Linux ELF Build ID c6969e60... . Offsets are
// module-relative. Every patched entry is additionally guarded by its exact
// instruction prefix.
constexpr std::uintptr_t kHandleCivilianFleetsOffset = 0x23dfad0;
constexpr std::uintptr_t kFindBestPositionOffset = 0x24017a0;
constexpr std::uintptr_t kCalcAiWeightOffset = 0x26c83a0;
constexpr std::uintptr_t kTriggerEvaluateOffset = 0x1da2a20;
constexpr std::uintptr_t kOwnedFleetActualEvaluateOffset = 0x355c9e0;
constexpr std::uintptr_t kOwnedFleetCalculateCountOffset = 0x355e090;

constexpr std::array<unsigned char, 13> kHandleCivilianFleetsPrefix = {
    0x55, 0x48, 0x89, 0xe5, 0x41, 0x57, 0x41,
    0x56, 0x41, 0x55, 0x41, 0x54, 0x53,
};
constexpr std::array<unsigned char, 13> kFindBestPositionPrefix = {
    0x55, 0x48, 0x89, 0xe5, 0x41, 0x57, 0x41,
    0x56, 0x41, 0x55, 0x41, 0x54, 0x53,
};
constexpr std::array<unsigned char, 14> kCalcAiWeightPrefix = {
    0x41, 0x57, 0x41, 0x56, 0x41, 0x54, 0x53,
    0x48, 0x81, 0xec, 0x48, 0x03, 0x00, 0x00,
};
constexpr std::array<unsigned char, 8> kTriggerEvaluatePrefix = {
    0x41, 0x57, 0x41, 0x56, 0x41, 0x54, 0x53, 0x50,
};
constexpr std::array<unsigned char, 7> kOwnedFleetActualEvaluatePrefix = {
    0x55, 0x41, 0x56, 0x53, 0x48, 0x89, 0xf3,
};
constexpr std::array<unsigned char, 10> kOwnedFleetCalculateCountPrefix = {
    0x55, 0x41, 0x57, 0x41, 0x56,
    0x41, 0x55, 0x41, 0x54, 0x53,
};

constexpr std::size_t kAbsoluteJumpLength = 14;
constexpr std::size_t kRelativeJumpLength = 5;
constexpr std::size_t kIdentityCapacity = 512;
constexpr std::size_t kSignatureCapacity = 1024;
constexpr std::size_t kCalcKeyCapacity = 1024;
constexpr std::size_t kTriggerKeyCapacity = 4096;
constexpr std::size_t kOwnedFleetKeyCapacity = 1024;

using HandleCivilianFleetsFn = void (*)(void*);
// The original returns SMegaStructurePos through a hidden sret pointer in RDI.
// Expressing that pointer explicitly preserves the observed SysV register ABI.
using FindBestPositionFn = void* (*)(
    void*, const void*, const void*, const void*, const char*, int, const void*);
using CalcAiWeightFn = std::int32_t (*)(const void*, const void*, const void*);
using TriggerEvaluateFn = bool (*)(const void*, void*);
using OwnedFleetActualEvaluateFn = bool (*)(const void*, void*);
using OwnedFleetCalculateCountFn = int (*)(const void*, void*, int, int);

struct MainModuleIdentity {
  std::uintptr_t base = 0;
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

struct Counter {
  std::atomic<std::uint64_t> total{0};
  std::atomic<std::uint64_t> path{0};
};

struct TimedCounter : Counter {
  std::atomic<std::uint64_t> thread_cpu_ns{0};
  std::atomic<std::uint64_t> max_thread_cpu_ns{0};
};

struct OpaqueKey {
  std::uintptr_t first = 0;
  std::uintptr_t second = 0;
  std::uintptr_t third = 0;
  std::uintptr_t fourth = 0;

  bool operator==(const OpaqueKey&) const = default;
};

struct LocalKeyEntry {
  OpaqueKey key{};
  std::uint32_t generation = 0;
  std::uint32_t count = 0;
};

template <std::size_t Capacity>
struct LocalKeyTable {
  std::array<LocalKeyEntry, Capacity> entries{};

  bool Observe(
      const OpaqueKey& key,
      std::uint32_t generation,
      std::uint64_t* overflow) noexcept;

  const LocalKeyEntry* MostFrequent(std::uint32_t generation) const noexcept;
};

struct LocalWindow {
  bool active = false;
  std::uint32_t generation = 1;
  std::uintptr_t minister = 0;
  std::uintptr_t country = 0;
  std::uint64_t find_calls = 0;
  std::uint64_t calc_calls = 0;
  std::uint64_t trigger_calls = 0;
  std::uint64_t owned_actual_calls = 0;
  std::uint64_t owned_calculate_calls = 0;
  std::uint64_t calc_duplicates = 0;
  std::uint64_t trigger_duplicates = 0;
  std::uint64_t owned_duplicates = 0;
  std::uint64_t key_overflow = 0;
  LocalKeyTable<kCalcKeyCapacity> calc_keys{};
  LocalKeyTable<kTriggerKeyCapacity> trigger_keys{};
  LocalKeyTable<kOwnedFleetKeyCapacity> owned_keys{};

  void Begin(std::uintptr_t value) noexcept;
};

struct IdentitySlot {
  std::atomic<std::uint64_t> hash{0};
  std::atomic<std::uintptr_t> identity{0};
  std::atomic<std::uint32_t> kind{0};
  std::atomic<std::uint64_t> updates{0};
  std::atomic<std::uint64_t> find_calls{0};
  std::atomic<std::uint64_t> calc_calls{0};
  std::atomic<std::uint64_t> trigger_calls{0};
  std::atomic<std::uint64_t> owned_calculate_calls{0};
  std::atomic<std::uint64_t> duplicate_calc_calls{0};
  std::atomic<std::uint64_t> duplicate_trigger_calls{0};
  std::atomic<std::uint64_t> duplicate_owned_calls{0};
};

enum class SignatureKind : std::uint32_t {
  kCalc = 1,
  kTrigger = 2,
  kOwnedFleet = 3,
};

struct SignatureSlot {
  std::atomic<std::uint64_t> hash{0};
  std::atomic<std::uint32_t> kind{0};
  std::atomic<std::uintptr_t> first{0};
  std::atomic<std::uintptr_t> second{0};
  std::atomic<std::uintptr_t> third{0};
  std::atomic<std::uintptr_t> fourth{0};
  std::atomic<std::uint64_t> windows{0};
  std::atomic<std::uint64_t> calls{0};
  std::atomic<std::uint64_t> duplicates{0};
};

struct IdentitySnapshot {
  std::uint32_t kind = 0;
  std::uintptr_t identity = 0;
  std::uint64_t updates = 0;
  std::uint64_t find_calls = 0;
  std::uint64_t calc_calls = 0;
  std::uint64_t trigger_calls = 0;
  std::uint64_t owned_calculate_calls = 0;
  std::uint64_t duplicate_calc_calls = 0;
  std::uint64_t duplicate_trigger_calls = 0;
  std::uint64_t duplicate_owned_calls = 0;
};

struct SignatureSnapshot {
  std::uint32_t kind = 0;
  OpaqueKey key{};
  std::uint64_t windows = 0;
  std::uint64_t calls = 0;
  std::uint64_t duplicates = 0;
};

std::uintptr_t g_module_base = 0;
bool g_full_detail = false;
std::atomic<bool> g_enabled{false};
std::atomic<std::uint64_t> g_completed_windows{0};
std::atomic<std::uint64_t> g_nested_windows{0};
std::atomic<std::uint64_t> g_key_overflow{0};
std::atomic<std::uint64_t> g_identity_overflow{0};
std::atomic<std::uint64_t> g_signature_overflow{0};
TimedCounter g_find_best;
TimedCounter g_calc_ai_weight;
Counter g_trigger_evaluate;
Counter g_owned_fleet_actual;
Counter g_owned_fleet_calculate;
std::array<IdentitySlot, kIdentityCapacity> g_identities{};
std::array<SignatureSlot, kSignatureCapacity> g_signatures{};

HookPatch g_handle_civilian_patch;
HookPatch g_find_best_patch;
HookPatch g_calc_ai_weight_patch;
HookPatch g_trigger_evaluate_patch;
HookPatch g_owned_actual_patch;
HookPatch g_owned_calculate_patch;
HandleCivilianFleetsFn g_original_handle_civilian = nullptr;
FindBestPositionFn g_original_find_best = nullptr;
CalcAiWeightFn g_original_calc_ai_weight = nullptr;
TriggerEvaluateFn g_original_trigger_evaluate = nullptr;
OwnedFleetActualEvaluateFn g_original_owned_actual = nullptr;
OwnedFleetCalculateCountFn g_original_owned_calculate = nullptr;
iag::stellaris::research::RotatingProbeLog g_log;
std::string g_pause_path = kDefaultPausePath;
std::uint64_t g_interval_seconds = 5;
char g_status[256] = "not_initialized";

thread_local LocalWindow g_window;
thread_local std::uint32_t g_find_depth = 0;
thread_local std::uint32_t g_calc_depth = 0;
thread_local OpaqueKey g_current_calc_key{};

std::uint64_t Mix(std::uint64_t value) noexcept {
  value ^= value >> 30U;
  value *= 0xbf58476d1ce4e5b9ULL;
  value ^= value >> 27U;
  value *= 0x94d049bb133111ebULL;
  value ^= value >> 31U;
  return value;
}

std::uint64_t HashKey(const OpaqueKey& key, std::uint64_t salt = 0) noexcept {
  std::uint64_t value = Mix(static_cast<std::uint64_t>(key.first) ^ salt);
  value ^= Mix(static_cast<std::uint64_t>(key.second) + 0x9e3779b97f4a7c15ULL);
  value ^= Mix(static_cast<std::uint64_t>(key.third) + 0x243f6a8885a308d3ULL);
  value ^= Mix(static_cast<std::uint64_t>(key.fourth) + 0x13198a2e03707344ULL);
  value = Mix(value);
  return value < 2U ? value + 2U : value;
}

template <std::size_t Capacity>
bool LocalKeyTable<Capacity>::Observe(
    const OpaqueKey& key,
    std::uint32_t generation,
    std::uint64_t* overflow) noexcept {
  const std::size_t start = HashKey(key) % Capacity;
  for (std::size_t probe = 0; probe < Capacity; ++probe) {
    LocalKeyEntry& entry = entries[(start + probe) % Capacity];
    if (entry.generation != generation) {
      entry.key = key;
      entry.count = 1;
      entry.generation = generation;
      return false;
    }
    if (entry.key == key) {
      ++entry.count;
      return true;
    }
  }
  ++*overflow;
  return false;
}

template <std::size_t Capacity>
const LocalKeyEntry* LocalKeyTable<Capacity>::MostFrequent(
    std::uint32_t generation) const noexcept {
  const LocalKeyEntry* result = nullptr;
  for (const auto& entry : entries) {
    if (entry.generation == generation &&
        (result == nullptr || entry.count > result->count)) {
      result = &entry;
    }
  }
  return result;
}

void LocalWindow::Begin(std::uintptr_t value) noexcept {
  ++generation;
  if (generation == 0U) {
    calc_keys = {};
    trigger_keys = {};
    owned_keys = {};
    generation = 1U;
  }
  active = true;
  minister = value;
  country = 0;
  find_calls = 0;
  calc_calls = 0;
  trigger_calls = 0;
  owned_actual_calls = 0;
  owned_calculate_calls = 0;
  calc_duplicates = 0;
  trigger_duplicates = 0;
  owned_duplicates = 0;
  key_overflow = 0;
}

std::uint64_t ClockNs(clockid_t clock) noexcept {
  struct timespec value {};
  if (::clock_gettime(clock, &value) != 0) {
    return 0;
  }
  return static_cast<std::uint64_t>(value.tv_sec) * 1'000'000'000ULL +
         static_cast<std::uint64_t>(value.tv_nsec);
}

void UpdateMaximum(
    std::atomic<std::uint64_t>& destination,
    std::uint64_t value) noexcept {
  std::uint64_t observed = destination.load(std::memory_order_relaxed);
  while (observed < value &&
         !destination.compare_exchange_weak(
             observed, value, std::memory_order_relaxed)) {
  }
}

void AddDuration(TimedCounter& counter, std::uint64_t start) noexcept {
  const std::uint64_t end = ClockNs(CLOCK_THREAD_CPUTIME_ID);
  if (start == 0 || end < start) {
    return;
  }
  const std::uint64_t elapsed = end - start;
  counter.thread_cpu_ns.fetch_add(elapsed, std::memory_order_relaxed);
  UpdateMaximum(counter.max_thread_cpu_ns, elapsed);
}

IdentitySlot* FindIdentitySlot(
    std::uint32_t kind,
    std::uintptr_t identity) noexcept {
  const OpaqueKey key{identity, kind, 0, 0};
  const std::uint64_t hash = HashKey(key, 0xa17d4c9eULL);
  const std::size_t start = hash % g_identities.size();
  for (std::size_t probe = 0; probe < g_identities.size(); ++probe) {
    auto& slot = g_identities[(start + probe) % g_identities.size()];
    std::uint64_t observed = slot.hash.load(std::memory_order_acquire);
    if (observed == hash &&
        slot.kind.load(std::memory_order_relaxed) == kind &&
        slot.identity.load(std::memory_order_relaxed) == identity) {
      return &slot;
    }
    if (observed != 0U) {
      continue;
    }
    std::uint64_t empty = 0;
    if (!slot.hash.compare_exchange_strong(
            empty, 1U, std::memory_order_acq_rel)) {
      continue;
    }
    slot.kind.store(kind, std::memory_order_relaxed);
    slot.identity.store(identity, std::memory_order_relaxed);
    slot.hash.store(hash, std::memory_order_release);
    return &slot;
  }
  g_identity_overflow.fetch_add(1, std::memory_order_relaxed);
  return nullptr;
}

void PublishSignature(
    SignatureKind kind,
    const LocalKeyEntry* entry) noexcept {
  if (entry == nullptr || entry->count < 2U) {
    return;
  }
  const std::uint32_t kind_value = static_cast<std::uint32_t>(kind);
  const std::uint64_t hash = HashKey(entry->key, kind_value);
  const std::size_t start = hash % g_signatures.size();
  for (std::size_t probe = 0; probe < g_signatures.size(); ++probe) {
    auto& slot = g_signatures[(start + probe) % g_signatures.size()];
    std::uint64_t observed = slot.hash.load(std::memory_order_acquire);
    if (observed == hash &&
        slot.kind.load(std::memory_order_relaxed) == kind_value &&
        slot.first.load(std::memory_order_relaxed) == entry->key.first &&
        slot.second.load(std::memory_order_relaxed) == entry->key.second &&
        slot.third.load(std::memory_order_relaxed) == entry->key.third &&
        slot.fourth.load(std::memory_order_relaxed) == entry->key.fourth) {
      slot.windows.fetch_add(1, std::memory_order_relaxed);
      slot.calls.fetch_add(entry->count, std::memory_order_relaxed);
      slot.duplicates.fetch_add(entry->count - 1U, std::memory_order_relaxed);
      return;
    }
    if (observed != 0U) {
      continue;
    }
    std::uint64_t empty = 0;
    if (!slot.hash.compare_exchange_strong(
            empty, 1U, std::memory_order_acq_rel)) {
      continue;
    }
    slot.kind.store(kind_value, std::memory_order_relaxed);
    slot.first.store(entry->key.first, std::memory_order_relaxed);
    slot.second.store(entry->key.second, std::memory_order_relaxed);
    slot.third.store(entry->key.third, std::memory_order_relaxed);
    slot.fourth.store(entry->key.fourth, std::memory_order_relaxed);
    slot.windows.store(1, std::memory_order_relaxed);
    slot.calls.store(entry->count, std::memory_order_relaxed);
    slot.duplicates.store(entry->count - 1U, std::memory_order_relaxed);
    slot.hash.store(hash, std::memory_order_release);
    return;
  }
  g_signature_overflow.fetch_add(1, std::memory_order_relaxed);
}

void FinishWindow() noexcept {
  const std::uint32_t identity_kind = g_window.country != 0 ? 1U : 2U;
  const std::uintptr_t identity =
      g_window.country != 0 ? g_window.country : g_window.minister;
  if (IdentitySlot* slot = FindIdentitySlot(identity_kind, identity)) {
    slot->updates.fetch_add(1, std::memory_order_relaxed);
    slot->find_calls.fetch_add(g_window.find_calls, std::memory_order_relaxed);
    slot->calc_calls.fetch_add(g_window.calc_calls, std::memory_order_relaxed);
    slot->trigger_calls.fetch_add(g_window.trigger_calls, std::memory_order_relaxed);
    slot->owned_calculate_calls.fetch_add(
        g_window.owned_calculate_calls, std::memory_order_relaxed);
    slot->duplicate_calc_calls.fetch_add(
        g_window.calc_duplicates, std::memory_order_relaxed);
    slot->duplicate_trigger_calls.fetch_add(
        g_window.trigger_duplicates, std::memory_order_relaxed);
    slot->duplicate_owned_calls.fetch_add(
        g_window.owned_duplicates, std::memory_order_relaxed);
  }
  PublishSignature(
      SignatureKind::kCalc,
      g_window.calc_keys.MostFrequent(g_window.generation));
  PublishSignature(
      SignatureKind::kTrigger,
      g_window.trigger_keys.MostFrequent(g_window.generation));
  PublishSignature(
      SignatureKind::kOwnedFleet,
      g_window.owned_keys.MostFrequent(g_window.generation));
  g_key_overflow.fetch_add(g_window.key_overflow, std::memory_order_relaxed);
  g_completed_windows.fetch_add(1, std::memory_order_relaxed);
  g_window.active = false;
}

void HandleCivilianFleetsHook(void* minister) {
  if (!g_enabled.load(std::memory_order_relaxed)) {
    g_original_handle_civilian(minister);
    return;
  }
  const bool outer = !g_window.active;
  if (outer) {
    g_window.Begin(reinterpret_cast<std::uintptr_t>(minister));
  } else {
    g_nested_windows.fetch_add(1, std::memory_order_relaxed);
  }
  g_original_handle_civilian(minister);
  if (outer) {
    FinishWindow();
  }
}

void* FindBestPositionHook(
    void* result,
    const void* minister,
    const void* megastructure_type,
    const void* fleet,
    const char* context,
    int random_value,
    const void* fixed_point) {
  if (!g_enabled.load(std::memory_order_relaxed)) {
    return g_original_find_best(
        result,
        minister,
        megastructure_type,
        fleet,
        context,
        random_value,
        fixed_point);
  }
  g_find_best.total.fetch_add(1, std::memory_order_relaxed);
  if (g_window.active) {
    ++g_window.find_calls;
    g_find_best.path.fetch_add(1, std::memory_order_relaxed);
  }
  const std::uint64_t start = ClockNs(CLOCK_THREAD_CPUTIME_ID);
  ++g_find_depth;
  void* returned = g_original_find_best(
      result,
      minister,
      megastructure_type,
      fleet,
      context,
      random_value,
      fixed_point);
  --g_find_depth;
  AddDuration(g_find_best, start);
  return returned;
}

std::int32_t CalcAiWeightHook(
    const void* megastructure_type,
    const void* country,
    const void* candidate) {
  if (!g_enabled.load(std::memory_order_relaxed)) {
    return g_original_calc_ai_weight(megastructure_type, country, candidate);
  }
  g_calc_ai_weight.total.fetch_add(1, std::memory_order_relaxed);
  const bool under_find = g_find_depth != 0U;
  const OpaqueKey key{
      reinterpret_cast<std::uintptr_t>(megastructure_type),
      reinterpret_cast<std::uintptr_t>(country),
      reinterpret_cast<std::uintptr_t>(candidate),
      0,
  };
  if (under_find) {
    g_calc_ai_weight.path.fetch_add(1, std::memory_order_relaxed);
    if (g_window.active) {
      ++g_window.calc_calls;
      if (g_window.country == 0) {
        g_window.country = reinterpret_cast<std::uintptr_t>(country);
      }
      if (g_window.calc_keys.Observe(
              key, g_window.generation, &g_window.key_overflow)) {
        ++g_window.calc_duplicates;
      }
    }
  }
  const OpaqueKey previous_key = g_current_calc_key;
  g_current_calc_key = key;
  ++g_calc_depth;
  const std::uint64_t start = ClockNs(CLOCK_THREAD_CPUTIME_ID);
  const std::int32_t result =
      g_original_calc_ai_weight(megastructure_type, country, candidate);
  AddDuration(g_calc_ai_weight, start);
  --g_calc_depth;
  g_current_calc_key = previous_key;
  return result;
}

bool TriggerEvaluateHook(const void* trigger, void* scope) {
  if (!g_enabled.load(std::memory_order_relaxed)) {
    return g_original_trigger_evaluate(trigger, scope);
  }
  g_trigger_evaluate.total.fetch_add(1, std::memory_order_relaxed);
  if (g_calc_depth != 0U) {
    g_trigger_evaluate.path.fetch_add(1, std::memory_order_relaxed);
    if (g_window.active) {
      ++g_window.trigger_calls;
      const OpaqueKey key{
          reinterpret_cast<std::uintptr_t>(trigger),
          g_current_calc_key.first,
          g_current_calc_key.second,
          g_current_calc_key.third,
      };
      if (g_window.trigger_keys.Observe(
              key, g_window.generation, &g_window.key_overflow)) {
        ++g_window.trigger_duplicates;
      }
    }
  }
  return g_original_trigger_evaluate(trigger, scope);
}

bool OwnedFleetActualEvaluateHook(const void* trigger, void* scope) {
  if (!g_enabled.load(std::memory_order_relaxed)) {
    return g_original_owned_actual(trigger, scope);
  }
  g_owned_fleet_actual.total.fetch_add(1, std::memory_order_relaxed);
  if (g_calc_depth != 0U) {
    g_owned_fleet_actual.path.fetch_add(1, std::memory_order_relaxed);
    if (g_window.active) {
      ++g_window.owned_actual_calls;
    }
  }
  return g_original_owned_actual(trigger, scope);
}

int OwnedFleetCalculateCountHook(
    const void* trigger,
    void* scope,
    int threshold,
    int optimization) {
  if (!g_enabled.load(std::memory_order_relaxed)) {
    return g_original_owned_calculate(trigger, scope, threshold, optimization);
  }
  g_owned_fleet_calculate.total.fetch_add(1, std::memory_order_relaxed);
  if (g_calc_depth != 0U) {
    g_owned_fleet_calculate.path.fetch_add(1, std::memory_order_relaxed);
    if (g_window.active) {
      ++g_window.owned_calculate_calls;
      const OpaqueKey key{
          reinterpret_cast<std::uintptr_t>(trigger),
          g_current_calc_key.second,
          static_cast<std::uintptr_t>(static_cast<std::uint32_t>(threshold)),
          static_cast<std::uintptr_t>(static_cast<std::uint32_t>(optimization)),
      };
      if (g_window.owned_keys.Observe(
              key, g_window.generation, &g_window.key_overflow)) {
        ++g_window.owned_duplicates;
      }
    }
  }
  return g_original_owned_calculate(trigger, scope, threshold, optimization);
}

std::size_t Align4(std::size_t value) noexcept {
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
    const std::array<unsigned char, Size>& expected) noexcept {
  return std::memcmp(
             reinterpret_cast<const void*>(address), expected.data(), Size) == 0;
}

void WriteAbsoluteJump(unsigned char* destination, const void* target) noexcept {
  destination[0] = 0xff;
  destination[1] = 0x25;
  std::memset(destination + 2, 0, 4);
  const auto value = reinterpret_cast<std::uintptr_t>(target);
  std::memcpy(destination + 6, &value, sizeof(value));
}

bool SetTargetProtection(const HookPatch& patch, int protection) noexcept {
  const long page_size = ::sysconf(_SC_PAGESIZE);
  if (page_size <= 0) {
    return false;
  }
  const auto mask = static_cast<std::uintptr_t>(page_size - 1);
  const auto first = reinterpret_cast<std::uintptr_t>(patch.target) & ~mask;
  const auto last =
      (reinterpret_cast<std::uintptr_t>(patch.target) + patch.length - 1U) &
      ~mask;
  const auto size = static_cast<std::size_t>(last - first) +
                    static_cast<std::size_t>(page_size);
  return ::mprotect(reinterpret_cast<void*>(first), size, protection) == 0;
}

bool PrepareHook(
    HookPatch* patch,
    std::uintptr_t address,
    std::size_t length) noexcept {
  if (length < kRelativeJumpLength || length > patch->original.size()) {
    std::snprintf(g_status, sizeof(g_status), "invalid_hook_length");
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
    std::snprintf(g_status, sizeof(g_status), "trampoline_mmap_failed");
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
    std::snprintf(g_status, sizeof(g_status), "trampoline_mprotect_failed");
    return false;
  }
  return true;
}

bool ApplyHook(HookPatch* patch, void* hook) noexcept {
  patch->relay = ::mmap(
      nullptr,
      kAbsoluteJumpLength,
      PROT_READ | PROT_WRITE | PROT_EXEC,
      MAP_PRIVATE | MAP_ANONYMOUS | MAP_32BIT,
      -1,
      0);
  if (patch->relay == MAP_FAILED) {
    patch->relay = nullptr;
    std::snprintf(g_status, sizeof(g_status), "relay_mmap_failed");
    return false;
  }
  const auto distance = reinterpret_cast<std::intptr_t>(patch->relay) -
                        (reinterpret_cast<std::intptr_t>(patch->target) +
                         static_cast<std::intptr_t>(kRelativeJumpLength));
  if (distance < std::numeric_limits<std::int32_t>::min() ||
      distance > std::numeric_limits<std::int32_t>::max()) {
    std::snprintf(g_status, sizeof(g_status), "relay_out_of_range");
    return false;
  }
  WriteAbsoluteJump(static_cast<unsigned char*>(patch->relay), hook);
  __builtin___clear_cache(
      static_cast<char*>(patch->relay),
      static_cast<char*>(patch->relay) + kAbsoluteJumpLength);
  if (::mprotect(patch->relay, kAbsoluteJumpLength, PROT_READ | PROT_EXEC) != 0 ||
      !SetTargetProtection(*patch, PROT_READ | PROT_WRITE | PROT_EXEC)) {
    std::snprintf(g_status, sizeof(g_status), "hook_mprotect_failed");
    return false;
  }
  std::array<unsigned char, 32> bytes{};
  bytes.fill(0x90);
  bytes[0] = 0xe9;
  const auto encoded = static_cast<std::int32_t>(distance);
  std::memcpy(bytes.data() + 1, &encoded, sizeof(encoded));
  std::memcpy(patch->target, bytes.data(), patch->length);
  __builtin___clear_cache(
      reinterpret_cast<char*>(patch->target),
      reinterpret_cast<char*>(patch->target) + patch->length);
  patch->applied = true;
  if (!SetTargetProtection(*patch, PROT_READ | PROT_EXEC)) {
    std::snprintf(g_status, sizeof(g_status), "hook_rx_restore_failed");
    return false;
  }
  return true;
}

void RestoreHook(HookPatch* patch) noexcept {
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

void RestoreAllHooks() noexcept {
  RestoreHook(&g_owned_calculate_patch);
  RestoreHook(&g_owned_actual_patch);
  RestoreHook(&g_trigger_evaluate_patch);
  RestoreHook(&g_calc_ai_weight_patch);
  RestoreHook(&g_find_best_patch);
  RestoreHook(&g_handle_civilian_patch);
}

bool VerifyExecutable() noexcept {
  MainModuleIdentity identity;
  ::dl_iterate_phdr(ReadMainModuleIdentity, &identity);
  if (identity.build_id != kExpectedBuildId) {
    std::snprintf(
        g_status,
        sizeof(g_status),
        "build_id_mismatch:%s",
        identity.build_id.c_str());
    return false;
  }
  g_module_base = identity.base;
  const bool outer_valid =
      HasPrefix(
          g_module_base + kHandleCivilianFleetsOffset,
          kHandleCivilianFleetsPrefix) &&
      HasPrefix(
          g_module_base + kFindBestPositionOffset,
          kFindBestPositionPrefix) &&
      HasPrefix(g_module_base + kCalcAiWeightOffset, kCalcAiWeightPrefix);
  const bool full_valid =
      HasPrefix(g_module_base + kTriggerEvaluateOffset, kTriggerEvaluatePrefix) &&
      HasPrefix(
          g_module_base + kOwnedFleetActualEvaluateOffset,
          kOwnedFleetActualEvaluatePrefix) &&
      HasPrefix(
          g_module_base + kOwnedFleetCalculateCountOffset,
          kOwnedFleetCalculateCountPrefix);
  if (!outer_valid || (g_full_detail && !full_valid)) {
    std::snprintf(g_status, sizeof(g_status), "function_signature_mismatch");
    return false;
  }
  return true;
}

bool PrepareHooks() noexcept {
  if (!PrepareHook(
          &g_handle_civilian_patch,
          g_module_base + kHandleCivilianFleetsOffset,
          kHandleCivilianFleetsPrefix.size()) ||
      !PrepareHook(
          &g_find_best_patch,
          g_module_base + kFindBestPositionOffset,
          kFindBestPositionPrefix.size()) ||
      !PrepareHook(
          &g_calc_ai_weight_patch,
          g_module_base + kCalcAiWeightOffset,
          kCalcAiWeightPrefix.size())) {
    return false;
  }
  if (g_full_detail &&
      (!PrepareHook(
           &g_trigger_evaluate_patch,
           g_module_base + kTriggerEvaluateOffset,
           kTriggerEvaluatePrefix.size()) ||
       !PrepareHook(
           &g_owned_actual_patch,
           g_module_base + kOwnedFleetActualEvaluateOffset,
           kOwnedFleetActualEvaluatePrefix.size()) ||
       !PrepareHook(
           &g_owned_calculate_patch,
           g_module_base + kOwnedFleetCalculateCountOffset,
           kOwnedFleetCalculateCountPrefix.size()))) {
    return false;
  }
  g_original_handle_civilian = reinterpret_cast<HandleCivilianFleetsFn>(
      g_handle_civilian_patch.trampoline);
  g_original_find_best =
      reinterpret_cast<FindBestPositionFn>(g_find_best_patch.trampoline);
  g_original_calc_ai_weight =
      reinterpret_cast<CalcAiWeightFn>(g_calc_ai_weight_patch.trampoline);
  if (g_full_detail) {
    g_original_trigger_evaluate = reinterpret_cast<TriggerEvaluateFn>(
        g_trigger_evaluate_patch.trampoline);
    g_original_owned_actual = reinterpret_cast<OwnedFleetActualEvaluateFn>(
        g_owned_actual_patch.trampoline);
    g_original_owned_calculate = reinterpret_cast<OwnedFleetCalculateCountFn>(
        g_owned_calculate_patch.trampoline);
  }
  return true;
}

bool InstallHooks() noexcept {
  if (!ApplyHook(
          &g_handle_civilian_patch,
          reinterpret_cast<void*>(&HandleCivilianFleetsHook)) ||
      !ApplyHook(
          &g_find_best_patch,
          reinterpret_cast<void*>(&FindBestPositionHook)) ||
      !ApplyHook(
          &g_calc_ai_weight_patch,
          reinterpret_cast<void*>(&CalcAiWeightHook))) {
    RestoreAllHooks();
    return false;
  }
  if (g_full_detail &&
      (!ApplyHook(
           &g_trigger_evaluate_patch,
           reinterpret_cast<void*>(&TriggerEvaluateHook)) ||
       !ApplyHook(
           &g_owned_actual_patch,
           reinterpret_cast<void*>(&OwnedFleetActualEvaluateHook)) ||
       !ApplyHook(
           &g_owned_calculate_patch,
           reinterpret_cast<void*>(&OwnedFleetCalculateCountHook)))) {
    RestoreAllHooks();
    return false;
  }
  return true;
}

std::string HexPointer(std::uintptr_t value) {
  char buffer[32]{};
  std::snprintf(
      buffer,
      sizeof(buffer),
      "0x%llx",
      static_cast<unsigned long long>(value));
  return buffer;
}

void AppendCounter(
    std::string* output,
    std::string_view name,
    const Counter& counter,
    bool comma) {
  char buffer[256]{};
  std::snprintf(
      buffer,
      sizeof(buffer),
      "\"%.*s\":{\"total\":%llu,\"path\":%llu}%s",
      static_cast<int>(name.size()),
      name.data(),
      static_cast<unsigned long long>(
          counter.total.load(std::memory_order_relaxed)),
      static_cast<unsigned long long>(
          counter.path.load(std::memory_order_relaxed)),
      comma ? "," : "");
  output->append(buffer);
}

void AppendTimedCounter(
    std::string* output,
    std::string_view name,
    const TimedCounter& counter,
    bool comma) {
  char buffer[384]{};
  std::snprintf(
      buffer,
      sizeof(buffer),
      "\"%.*s\":{\"total\":%llu,\"path\":%llu,"
      "\"thread_cpu_ns\":%llu,\"max_thread_cpu_ns\":%llu}%s",
      static_cast<int>(name.size()),
      name.data(),
      static_cast<unsigned long long>(
          counter.total.load(std::memory_order_relaxed)),
      static_cast<unsigned long long>(
          counter.path.load(std::memory_order_relaxed)),
      static_cast<unsigned long long>(
          counter.thread_cpu_ns.load(std::memory_order_relaxed)),
      static_cast<unsigned long long>(
          counter.max_thread_cpu_ns.load(std::memory_order_relaxed)),
      comma ? "," : "");
  output->append(buffer);
}

std::vector<IdentitySnapshot> IdentitySnapshots() {
  std::vector<IdentitySnapshot> result;
  result.reserve(g_identities.size());
  for (const auto& slot : g_identities) {
    if (slot.hash.load(std::memory_order_acquire) < 2U) {
      continue;
    }
    result.push_back(IdentitySnapshot{
        .kind = slot.kind.load(std::memory_order_relaxed),
        .identity = slot.identity.load(std::memory_order_relaxed),
        .updates = slot.updates.load(std::memory_order_relaxed),
        .find_calls = slot.find_calls.load(std::memory_order_relaxed),
        .calc_calls = slot.calc_calls.load(std::memory_order_relaxed),
        .trigger_calls = slot.trigger_calls.load(std::memory_order_relaxed),
        .owned_calculate_calls =
            slot.owned_calculate_calls.load(std::memory_order_relaxed),
        .duplicate_calc_calls =
            slot.duplicate_calc_calls.load(std::memory_order_relaxed),
        .duplicate_trigger_calls =
            slot.duplicate_trigger_calls.load(std::memory_order_relaxed),
        .duplicate_owned_calls =
            slot.duplicate_owned_calls.load(std::memory_order_relaxed),
    });
  }
  std::sort(
      result.begin(), result.end(), [](const auto& left, const auto& right) {
        return left.calc_calls > right.calc_calls;
      });
  if (result.size() > 32U) {
    result.resize(32U);
  }
  return result;
}

std::vector<SignatureSnapshot> SignatureSnapshots() {
  std::vector<SignatureSnapshot> result;
  result.reserve(g_signatures.size());
  for (const auto& slot : g_signatures) {
    if (slot.hash.load(std::memory_order_acquire) < 2U) {
      continue;
    }
    result.push_back(SignatureSnapshot{
        .kind = slot.kind.load(std::memory_order_relaxed),
        .key = {
            slot.first.load(std::memory_order_relaxed),
            slot.second.load(std::memory_order_relaxed),
            slot.third.load(std::memory_order_relaxed),
            slot.fourth.load(std::memory_order_relaxed),
        },
        .windows = slot.windows.load(std::memory_order_relaxed),
        .calls = slot.calls.load(std::memory_order_relaxed),
        .duplicates = slot.duplicates.load(std::memory_order_relaxed),
    });
  }
  std::sort(
      result.begin(), result.end(), [](const auto& left, const auto& right) {
        return left.duplicates > right.duplicates;
      });
  if (result.size() > 32U) {
    result.resize(32U);
  }
  return result;
}

std::string BuildSnapshot(std::uint64_t monotonic_ns) {
  const std::uint64_t realtime_ns = ClockNs(CLOCK_REALTIME);
  std::string output;
  output.reserve(24'000);
  char header[768]{};
  std::snprintf(
      header,
      sizeof(header),
      "{\"schema\":\"%s\",\"kind\":\"snapshot\","
      "\"monotonic_ns\":%llu,\"realtime_ns\":%llu,"
      "\"enabled\":%s,\"mode\":\"%s\","
      "\"completed_civilian_updates\":%llu,"
      "\"nested_civilian_updates\":%llu,"
      "\"key_table_overflow\":%llu,"
      "\"identity_table_overflow\":%llu,"
      "\"signature_table_overflow\":%llu,\"counters\":{",
      kSchema,
      static_cast<unsigned long long>(monotonic_ns),
      static_cast<unsigned long long>(realtime_ns),
      g_enabled.load(std::memory_order_relaxed) ? "true" : "false",
      g_full_detail ? "full" : "outer",
      static_cast<unsigned long long>(
          g_completed_windows.load(std::memory_order_relaxed)),
      static_cast<unsigned long long>(
          g_nested_windows.load(std::memory_order_relaxed)),
      static_cast<unsigned long long>(
          g_key_overflow.load(std::memory_order_relaxed)),
      static_cast<unsigned long long>(
          g_identity_overflow.load(std::memory_order_relaxed)),
      static_cast<unsigned long long>(
          g_signature_overflow.load(std::memory_order_relaxed)));
  output.append(header);
  AppendTimedCounter(&output, "find_best_position", g_find_best, true);
  AppendTimedCounter(&output, "calc_ai_weight", g_calc_ai_weight, true);
  AppendCounter(&output, "trigger_evaluate", g_trigger_evaluate, true);
  AppendCounter(&output, "owned_fleet_actual_evaluate", g_owned_fleet_actual, true);
  AppendCounter(
      &output, "owned_fleet_calculate_count", g_owned_fleet_calculate, false);
  output.append("},\"identities\":[");
  const auto identities = IdentitySnapshots();
  for (std::size_t index = 0; index < identities.size(); ++index) {
    const auto& item = identities[index];
    if (index != 0U) {
      output.push_back(',');
    }
    char values[768]{};
    const std::string identity = HexPointer(item.identity);
    std::snprintf(
        values,
        sizeof(values),
        "{\"identity_kind\":\"%s\",\"identity\":\"%s\","
        "\"updates\":%llu,\"find_calls\":%llu,\"calc_calls\":%llu,"
        "\"trigger_calls\":%llu,\"owned_calculate_calls\":%llu,"
        "\"duplicate_calc_calls\":%llu,"
        "\"duplicate_trigger_calls\":%llu,"
        "\"duplicate_owned_calls\":%llu}",
        item.kind == 1U ? "country_object" : "minister_object_fallback",
        identity.c_str(),
        static_cast<unsigned long long>(item.updates),
        static_cast<unsigned long long>(item.find_calls),
        static_cast<unsigned long long>(item.calc_calls),
        static_cast<unsigned long long>(item.trigger_calls),
        static_cast<unsigned long long>(item.owned_calculate_calls),
        static_cast<unsigned long long>(item.duplicate_calc_calls),
        static_cast<unsigned long long>(item.duplicate_trigger_calls),
        static_cast<unsigned long long>(item.duplicate_owned_calls));
    output.append(values);
  }
  output.append("],\"repeated_signatures\":[");
  const auto signatures = SignatureSnapshots();
  for (std::size_t index = 0; index < signatures.size(); ++index) {
    const auto& item = signatures[index];
    if (index != 0U) {
      output.push_back(',');
    }
    const char* kind = item.kind == 1U
                           ? "calc_input"
                           : (item.kind == 2U ? "trigger_input"
                                             : "owned_fleet_input");
    char values[1024]{};
    const std::string first = HexPointer(item.key.first);
    const std::string second = HexPointer(item.key.second);
    const std::string third = HexPointer(item.key.third);
    const std::string fourth = HexPointer(item.key.fourth);
    std::snprintf(
        values,
        sizeof(values),
        "{\"kind\":\"%s\",\"opaque_inputs\":[\"%s\",\"%s\","
        "\"%s\",\"%s\"],\"windows\":%llu,\"calls\":%llu,"
        "\"duplicates\":%llu}",
        kind,
        first.c_str(),
        second.c_str(),
        third.c_str(),
        fourth.c_str(),
        static_cast<unsigned long long>(item.windows),
        static_cast<unsigned long long>(item.calls),
        static_cast<unsigned long long>(item.duplicates));
    output.append(values);
  }
  output.append("]}\n");
  return output;
}

void* WriterThread(void*) {
  while (true) {
    const bool paused = ::access(g_pause_path.c_str(), F_OK) == 0;
    g_enabled.store(!paused, std::memory_order_relaxed);
    struct timespec delay {
      .tv_sec = static_cast<time_t>(g_interval_seconds), .tv_nsec = 0
    };
    while (::nanosleep(&delay, &delay) != 0) {
    }
    const std::uint64_t monotonic_ns = ClockNs(CLOCK_MONOTONIC);
    const std::string snapshot = BuildSnapshot(monotonic_ns);
    if (!g_log.Write(snapshot, monotonic_ns)) {
      std::snprintf(g_status, sizeof(g_status), "log_write_failed:%s", g_log.error());
    }
  }
}

std::uint64_t ReadIntervalSeconds() noexcept {
  const char* value = std::getenv("IAG_AI_MEGA_COUNTER_INTERVAL_SECONDS");
  if (value == nullptr || value[0] == '\0') {
    return 5;
  }
  char* end = nullptr;
  const unsigned long long parsed = std::strtoull(value, &end, 10);
  return end != value && *end == '\0' && parsed >= 1U && parsed <= 60U
             ? static_cast<std::uint64_t>(parsed)
             : 5U;
}

bool OpenLog() {
  const char* path = std::getenv("IAG_AI_MEGA_COUNTER_LOG");
  if (path == nullptr || path[0] == '\0') {
    path = kDefaultLogPath;
  }
  std::string header =
      std::string("{\"schema\":\"") + kSchema +
      "\",\"kind\":\"probe_started\",\"build_id\":\"" +
      kExpectedBuildId + "\",\"mode\":\"" +
      (g_full_detail ? "full" : "outer") +
      "\",\"count_semantics\":\"exact function entries while enabled; "
      "path counts are TLS-nested call-path entries\","
      "\"identity_semantics\":\"process-lifetime opaque pointers; no game "
      "objects are dereferenced\",\"fleet_list_size\":\"not_collected\"}\n";
  return g_log.Open(
      path,
      std::move(header),
      "IAG_AI_MEGA_COUNTER_ROTATE_BYTES",
      "IAG_AI_MEGA_COUNTER_ROTATE_SECONDS",
      "IAG_PROBE_MIN_FREE_BYTES",
      64ULL * 1024ULL * 1024ULL,
      3600ULL,
      5ULL * 1024ULL * 1024ULL * 1024ULL);
}

__attribute__((constructor)) void InitializeProbe() {
  const char* armed = std::getenv("IAG_AI_MEGA_COUNTER_ENABLE");
  if (armed == nullptr || std::strcmp(armed, "1") != 0) {
    std::snprintf(g_status, sizeof(g_status), "not_armed");
    return;
  }
  const char* mode = std::getenv("IAG_AI_MEGA_COUNTER_MODE");
  g_full_detail = mode != nullptr && std::strcmp(mode, "full") == 0;
  const char* pause_path = std::getenv("IAG_AI_MEGA_COUNTER_PAUSE_FILE");
  if (pause_path != nullptr && pause_path[0] != '\0') {
    g_pause_path = pause_path;
  }
  g_interval_seconds = ReadIntervalSeconds();
  if (!VerifyExecutable() || !OpenLog() || !PrepareHooks() || !InstallHooks()) {
    RestoreAllHooks();
    return;
  }
  g_enabled.store(::access(g_pause_path.c_str(), F_OK) != 0, std::memory_order_relaxed);
  pthread_t thread{};
  if (::pthread_create(&thread, nullptr, &WriterThread, nullptr) != 0) {
    g_enabled.store(false, std::memory_order_relaxed);
    RestoreAllHooks();
    std::snprintf(g_status, sizeof(g_status), "writer_thread_failed");
    return;
  }
  (void)::pthread_detach(thread);
  std::snprintf(
      g_status,
      sizeof(g_status),
      "ready:mode=%s:pause_file=%s",
      g_full_detail ? "full" : "outer",
      g_pause_path.c_str());
}

}  // namespace

extern "C" const char* iag_stellaris_ai_megastructure_counter_status() {
  return g_status;
}

extern "C" void iag_stellaris_ai_megastructure_counter_set_enabled(int enabled) {
  g_enabled.store(enabled != 0, std::memory_order_relaxed);
}
