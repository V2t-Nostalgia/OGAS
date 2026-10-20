#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "iag_native_runtime/sdk_metadata.h"

namespace iag::native_runtime {

class GameApi;
class NativeCommandBuilder;

// Game-thread-local correlated inputs. Native pointers never leave this scope
// or become model-facing targets. These providers do not score AI decisions.
struct NativeProducerCandidate {
  std::string source;
  std::string identity;
  std::string definition_key;
  std::string reason;
  std::uint32_t country_id = UINT32_MAX;
  std::uint32_t colony_id = UINT32_MAX;
  std::uint32_t zone_id = UINT32_MAX;
  std::size_t candidate_count = 0;
  std::size_t query_calls = 0;
  bool truncated = false;
  std::optional<bool> native_rule_valid;
  const void* definition = nullptr;
  const void* colony = nullptr;
  const void* zone = nullptr;
};

[[nodiscard]] std::vector<std::string_view> NativeProducerCommands(
    const GameApi& game, const RecoveredSdk& sdk);
// Observes the exact-build native pause state; unknown never authorizes a probe.
[[nodiscard]] std::optional<bool> NativeProducerFixturePaused(const GameApi& game);
[[nodiscard]] NativeProducerCandidate ResolveNativeProducerCandidate(
    const GameApi& game, const RecoveredSdk& sdk, const RecoveredCommand& command,
    std::uint32_t country_id, std::uint32_t candidate_index);
[[nodiscard]] bool PopulateNativeProducerCandidate(
    const GameApi& game, const RecoveredSdk& sdk,
    const NativeProducerCandidate& candidate, NativeCommandBuilder& builder,
    std::string& error);

}  // namespace iag::native_runtime
