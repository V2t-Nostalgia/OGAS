#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <string_view>
#include <span>
#include <vector>

#include "iag_native_runtime/sdk_metadata.h"

namespace iag::native_runtime {

class GameApi;

// Shared by reviewed Action::Prepare implementations and bounded research
// probes. Owns the engine-created object until ReleaseForSubmission(); never
// posts or executes a command. Call only on the CGameIdler game thread.
class NativeCommandBuilder final {
 public:
  [[nodiscard]] static bool Preflight(
      const GameApi& game, const RecoveredSdk& sdk,
      std::string_view command_name, std::string& error);
  [[nodiscard]] static std::unique_ptr<NativeCommandBuilder> Create(
      const GameApi& game,
      const RecoveredSdk& sdk,
      std::string_view command_name,
      std::string& error);
  ~NativeCommandBuilder();
  NativeCommandBuilder(const NativeCommandBuilder&) = delete;
  NativeCommandBuilder& operator=(const NativeCommandBuilder&) = delete;

  [[nodiscard]] bool SetObjectId(
      std::string_view field_name, std::string_view object_class,
      std::uint32_t id, std::string& error);
  [[nodiscard]] bool SetUnsigned(
      std::string_view field_name, std::uint64_t value, std::string& error);
  [[nodiscard]] bool SetSigned(
      std::string_view field_name, std::int64_t value, std::string& error);
  [[nodiscard]] bool SetText(
      std::string_view field_name, std::string_view value, std::string& error);
  [[nodiscard]] bool SetDefinitionKey(
      std::string_view field_name, std::string_view type,
      std::string_view key, std::string& error);
  [[nodiscard]] bool SetReferenceList(
      std::string_view field_name, std::string_view type,
      std::span<const std::uint32_t> ids, std::string& error);
  [[nodiscard]] static std::vector<std::string> DefinitionCandidates(
      const GameApi& game, const RecoveredSdk& sdk, std::string_view type,
      std::size_t limit);
  [[nodiscard]] static std::string DefinitionKeyForObject(
      const GameApi& game, const RecoveredSdk& sdk, std::string_view type,
      const void* object);
  // End the factory's initial value, then construct an engine return value in
  // the same engine allocation. No memcpy/clone of owning members. A throwing
  // native constructor quarantines the allocation and must stop the batch.
  [[nodiscard]] bool ReconstructFromProducer(
      std::uintptr_t value_destructor_rva,
      const std::function<void(void*)>& construct, std::string& error);
  [[nodiscard]] bool owns_command() const noexcept { return command_ != nullptr; }
  [[nodiscard]] bool IsValid(std::string* reason = nullptr);
  [[nodiscard]] void* ReleaseForSubmission() noexcept;
  [[nodiscard]] const RecoveredCommand& metadata() const noexcept;

 private:
  NativeCommandBuilder(
      const GameApi& game, const RecoveredSdk& sdk,
      const RecoveredCommand& metadata, void* command);
  [[nodiscard]] const RecoveredField* FindField(
      std::string_view name, std::string& error) const;
  const GameApi& game_;
  const RecoveredSdk& sdk_;
  const RecoveredCommand& metadata_;
  void* command_;
  bool native_validated_ = false;
};

}  // namespace iag::native_runtime
