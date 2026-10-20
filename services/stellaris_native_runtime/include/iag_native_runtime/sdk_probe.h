#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <span>
#include <vector>

#include "iag_native_runtime/sdk_metadata.h"
#include "iag_native_runtime/state_query.h"

namespace iag::native_runtime {

struct RecoveredConstraintBinding {
  std::string field;
  std::string storage_kind;
  std::string value;
};

// Research inputs are semantic field names and typed values, never offsets or
// pointers. All fields are rechecked against the active generated SDK on Idle.
struct RecoveredConstraintCandidate {
  std::uint64_t expected_world = 0U;
  std::uint32_t expected_date = 0U;
  std::string identity;
  std::string sdk_fingerprint;
  std::vector<RecoveredConstraintBinding> bindings;
  std::uint64_t expected_instance = 0U;
};

[[nodiscard]] std::optional<RecoveredConstraintCandidate> ParseRecoveredConstraintCandidate(
    std::span<const std::string> fields);

struct RecoveredProbeOptions {
  std::optional<std::uint32_t> country_id;
  std::optional<std::uint32_t> leader_id;
  std::uint32_t candidate_index = 0U;
  bool run_game_update = false;
  bool native_domain = false;
  const RecoveredConstraintCandidate* constraint_candidate = nullptr;
};

// Bounded research mapping, not an Action descriptor. Runs on the existing
// CGameIdler request lane and never transfers command ownership to the session.
[[nodiscard]] StateQueryResult ProbeRecoveredCommand(
    const GameApi& game, const RecoveredSdk& sdk, std::string_view command_name,
    const RecoveredProbeOptions& options);
[[nodiscard]] std::string DescribeRecoveredCommands(
    const RecoveredSdk& sdk, std::uint32_t process_id = 0U,
    std::uint64_t instance_id = 0U, const GameApi* game = nullptr);

// Research uses the existing Idle thread without advancing simulation;
// production Prepare/Post/Verify retain their original update gate.
[[nodiscard]] constexpr bool ShouldDispatchPending(
    bool run_game_update, bool recovered_probe) noexcept {
  return run_game_update || recovered_probe;
}

}  // namespace iag::native_runtime
