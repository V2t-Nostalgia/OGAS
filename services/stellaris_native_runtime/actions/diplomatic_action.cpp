#include <array>
#include <new>
#include <string>

#include "iag_native_runtime/action.h"
#include "iag_native_runtime/game_api.h"

namespace iag::native_runtime {
namespace {

using RespondCtorFn = void (*)(void*, std::uint64_t, bool);
using VoteCtorFn = void (*)(void*, std::uint64_t, const void*, bool);

class DiplomaticActionInvocation final : public ActionInvocation {
 public:
  DiplomaticActionInvocation(
      std::uint64_t pending_action_id,
      bool decision,
      bool vote)
      : pending_action_id_(pending_action_id),
        decision_(decision),
        vote_(vote) {}

  [[nodiscard]] std::string_view action_type() const noexcept override {
    return vote_ ? "vote_on_diplomatic_action"
                 : "respond_to_diplomatic_action";
  }

  [[nodiscard]] std::string TargetEcho() const override {
    return std::to_string(pending_action_id_) + ":" +
           (decision_ ? "1" : "0");
  }

  [[nodiscard]] PrepareResult Prepare(
      const GameApi& game,
      std::uint32_t country_id,
      const void* local_country) override {
    (void)country_id;
    const auto& bindings = game.profile().diplomatic_action;
    const std::size_t command_size = vote_ ? bindings.vote_command_size
                                           : bindings.respond_command_size;
    void* command = ::operator new(command_size, std::nothrow);
    if (command == nullptr) {
      return PrepareResult::Failed("command_allocation_failed");
    }
    if (vote_) {
      game.FunctionAt<VoteCtorFn>(bindings.construct_vote_command)(
          command, pending_action_id_, local_country, decision_);
    } else {
      game.FunctionAt<RespondCtorFn>(bindings.construct_respond_command)(
          command, pending_action_id_, decision_);
    }
    game.ResetCommandSerial(command);
    if (!game.IsCommandValid(command)) {
      game.DestroyCommand(command);
      return PrepareResult::Rejected("native_is_valid_false_before_submit");
    }
    return PrepareResult::Ready(command);
  }

  [[nodiscard]] std::optional<RuntimeResult> Verify(
      const GameApi&,
      std::uint32_t,
      const void*) override {
    return RuntimeResult{
        "pending", "native_posted_awaiting_save_verification"};
  }

  [[nodiscard]] std::string_view TimeoutDetail() const noexcept override {
    return "native_posted_awaiting_save_verification";
  }

 private:
  std::uint64_t pending_action_id_;
  bool decision_;
  bool vote_;
};

std::unique_ptr<ActionInvocation> ParseDiplomaticAction(
    std::span<const std::string> fields,
    std::string& error_detail,
    bool vote) {
  if (fields.size() != 2U) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto pending_action_id = ParseUint64(fields[0]);
  if (!pending_action_id.has_value() || *pending_action_id == 0U ||
      (fields[1] != "0" && fields[1] != "1")) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  return std::make_unique<DiplomaticActionInvocation>(
      *pending_action_id, fields[1] == "1", vote);
}

std::unique_ptr<ActionInvocation> ParseResponse(
    std::span<const std::string> fields,
    std::string& error_detail) {
  return ParseDiplomaticAction(fields, error_detail, false);
}

std::unique_ptr<ActionInvocation> ParseVote(
    std::span<const std::string> fields,
    std::string& error_detail) {
  return ParseDiplomaticAction(fields, error_detail, true);
}

bool ResponseSupported(const BuildProfile& profile) noexcept {
  return profile.diplomatic_action.respond_command_size != 0U &&
         profile.diplomatic_action.construct_respond_command != 0U;
}

bool VoteSupported(const BuildProfile& profile) noexcept {
  return profile.diplomatic_action.vote_command_size != 0U &&
         profile.diplomatic_action.construct_vote_command != 0U;
}

constexpr std::array<ActionParameterDescriptor, 2> kResponseParameters = {{
    {
        .name = "pending_action_id",
        .type = ActionParameterType::kUint64,
        .required = true,
        .description = "Current pending diplomatic-action identifier.",
        .minimum = 1,
        .maximum = UINT64_MAX,
    },
    {
        .name = "accept",
        .type = ActionParameterType::kBoolean,
        .required = true,
        .description = "Whether to accept rather than reject the pending action.",
    },
}};

constexpr std::array<ActionParameterDescriptor, 2> kVoteParameters = {{
    {
        .name = "pending_action_id",
        .type = ActionParameterType::kUint64,
        .required = true,
        .description = "Current pending diplomatic-action identifier.",
        .minimum = 1,
        .maximum = UINT64_MAX,
    },
    {
        .name = "support",
        .type = ActionParameterType::kBoolean,
        .required = true,
        .description = "Whether this authority country supports the action.",
    },
}};

const ActionDescriptor kResponseDescriptor = {
    .action_type = "respond_to_diplomatic_action",
    .action_version = 1,
    .application_id = "etc",
    .description = "Accept or reject one currently pending diplomatic action.",
    .risk_class = "destructive_state_change",
    .verification_state = "live_verified",
    .parameters = kResponseParameters,
    .parse = &ParseResponse,
    .supported = &ResponseSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kResponseRegistration{
    kResponseDescriptor};

const ActionDescriptor kVoteDescriptor = {
    .action_type = "vote_on_diplomatic_action",
    .action_version = 1,
    .application_id = "etc",
    .description = "Vote for or against one currently pending diplomatic action.",
    .risk_class = "state_change",
    .verification_state = "live_verified",
    .parameters = kVoteParameters,
    .parse = &ParseVote,
    .supported = &VoteSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kVoteRegistration{
    kVoteDescriptor};

}  // namespace
}  // namespace iag::native_runtime
