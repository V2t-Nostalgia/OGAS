#pragma once

#include <cstdint>
#include <string>

namespace iag::native_runtime {

class GameApi;
struct BuildProfile;

struct StateQueryResult {
  std::string outcome;
  std::string payload;
  std::string detail;
};

[[nodiscard]] bool OpenEventStateSupported(
    const BuildProfile& profile) noexcept;
[[nodiscard]] StateQueryResult InspectOpenEvents(
    const GameApi& game,
    std::uint32_t country_id);
[[nodiscard]] bool PendingDiplomaticActionStateSupported(
    const BuildProfile& profile) noexcept;
[[nodiscard]] StateQueryResult InspectPendingDiplomaticActions(
    const GameApi& game,
    std::uint32_t country_id);

}  // namespace iag::native_runtime
