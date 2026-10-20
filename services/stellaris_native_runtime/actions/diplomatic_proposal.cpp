#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <new>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "iag_native_runtime/action.h"
#include "iag_native_runtime/game_api.h"

namespace iag::native_runtime {
namespace {

enum class ProposalKind {
  kOpenBorders,
  kCloseBorders,
  kMakeRival,
  kDeclareWar,
  kCreateEmbassy,
  kFormCommercialPact,
  kFormDefensivePact,
  kFormResearchAgreement,
  kFormMigrationPact,
  kInviteToFederation,
  kDemandSubjugation,
  kBreakMigrationPact,
  kBreakCommercialPact,
  kInsult,
};

using TwoCountryCtorFn = void (*)(void*, const void*, const void*);
using ProposeCommandCtorFn = void (*)(void*, void**);
using SelectWarGoalFn = const void* (*)(
    const void*, const void*, bool, bool);
using WarGoalCtorFn = void (*)(void*, const void*);
using WarGoalDtorFn = void (*)(void*);
using DeclareWarCtorFn = void (*)(
    void*, const void*, const void*, const void*);
using PeaceOfferCtorFn = void (*)(
    void*, const void*, const void*, const void*);
using OfferPeaceCtorFn = void (*)(void*, const void*);
using InviteFederationCtorFn = void (*)(
    void*, const void*, const void*, const void*);
using DemandSubjugationCtorFn = void (*)(
    void*, const void*, const void*, const void*, int);
using AbstractTradeDealCtorFn = void (*)(
    void*, int, const void*, const void*);
using TradeDealAccessSideFn = void* (*)(void*, const std::uint32_t*);
using TradeDealSetResourceFn = void (*)(
    void*, const void*, const std::int64_t*);
using CStringCtorFn = void (*)(void*, const char*);
using CStringDtorFn = void (*)(void*);
using GetResourceFn = const void* (*)(const void*, const void*);

constexpr std::size_t kSimpleActionSize = 0x50;
constexpr std::size_t kDeclareWarActionSize = 0x90;
constexpr std::size_t kOfferPeaceActionSize = 0x68;
constexpr std::size_t kInviteFederationActionSize = 0xb8;
constexpr std::size_t kDemandSubjugationActionSize = 0x1e0;
constexpr std::size_t kOfferTradeDealActionSize = 0x2a0;
constexpr int kOfferTradeDealTag = 0x304f;
constexpr std::int64_t kFixedPointScale = 100000;

std::string_view ActionType(ProposalKind kind) noexcept {
  switch (kind) {
    case ProposalKind::kOpenBorders:
      return "open_borders";
    case ProposalKind::kCloseBorders:
      return "close_borders";
    case ProposalKind::kMakeRival:
      return "establish_rivalry";
    case ProposalKind::kDeclareWar:
      return "declare_war";
    case ProposalKind::kCreateEmbassy:
      return "establish_embassy";
    case ProposalKind::kFormCommercialPact:
      return "form_commercial_pact";
    case ProposalKind::kFormDefensivePact:
      return "form_defensive_pact";
    case ProposalKind::kFormResearchAgreement:
      return "form_research_agreement";
    case ProposalKind::kFormMigrationPact:
      return "form_migration_pact";
    case ProposalKind::kInviteToFederation:
      return "invite_to_federation";
    case ProposalKind::kDemandSubjugation:
      return "demand_subjugation";
    case ProposalKind::kBreakMigrationPact:
      return "break_migration_pact";
    case ProposalKind::kBreakCommercialPact:
      return "break_commercial_pact";
    case ProposalKind::kInsult:
      return "insult_country";
  }
  return "unknown_diplomatic_proposal";
}

std::uintptr_t SimpleConstructor(
    const DiplomaticActionBindings& bindings,
    ProposalKind kind) noexcept {
  switch (kind) {
    case ProposalKind::kOpenBorders:
      return bindings.construct_open_borders_action;
    case ProposalKind::kCloseBorders:
      return bindings.construct_close_borders_action;
    case ProposalKind::kMakeRival:
      return bindings.construct_make_rival_action;
    case ProposalKind::kCreateEmbassy:
      return bindings.construct_create_embassy_action;
    case ProposalKind::kFormCommercialPact:
      return bindings.construct_form_commercial_pact_action;
    case ProposalKind::kFormDefensivePact:
      return bindings.construct_form_defensive_pact_action;
    case ProposalKind::kFormResearchAgreement:
      return bindings.construct_form_research_agreement_action;
    case ProposalKind::kFormMigrationPact:
      return bindings.construct_form_migration_pact_action;
    case ProposalKind::kBreakMigrationPact:
      return bindings.construct_break_migration_pact_action;
    case ProposalKind::kBreakCommercialPact:
      return bindings.construct_break_commercial_pact_action;
    case ProposalKind::kInsult:
      return bindings.construct_insult_action;
    case ProposalKind::kDeclareWar:
    case ProposalKind::kInviteToFederation:
    case ProposalKind::kDemandSubjugation:
      return 0U;
  }
  return 0U;
}

bool CommonProposalSupported(const BuildProfile& profile) noexcept {
  const auto& bindings = profile.diplomatic_action;
  return bindings.propose_command_size == 0x28U &&
         bindings.construct_propose_command != 0U &&
         bindings.countries.database_instance != 0U &&
         bindings.countries.null_object_instance != 0U;
}

bool TargetOnlySupported(
    const BuildProfile& profile,
    ProposalKind kind) noexcept {
  if (!CommonProposalSupported(profile)) {
    return false;
  }
  const auto& bindings = profile.diplomatic_action;
  if (SimpleConstructor(bindings, kind) != 0U) {
    return true;
  }
  switch (kind) {
    case ProposalKind::kDeclareWar:
      return bindings.select_war_goal_type != 0U &&
             bindings.null_war_goal_type_instance != 0U &&
             bindings.construct_war_goal != 0U &&
             bindings.destroy_war_goal != 0U &&
             bindings.construct_declare_war_action != 0U;
    case ProposalKind::kInviteToFederation:
      return bindings.construct_invite_to_federation_action != 0U;
    case ProposalKind::kDemandSubjugation:
      return bindings.construct_demand_subjugation_action != 0U;
    default:
      return false;
  }
}

const void* ResolveTargetCountry(
    const GameApi& game,
    std::uint32_t target_country_id) noexcept {
  const void* target = game.ResolvePdxObject(
      game.profile().diplomatic_action.countries, target_country_id);
  if (target == nullptr || game.CountryId(target) != target_country_id) {
    return nullptr;
  }
  return target;
}

PrepareResult WrapProposal(
    const GameApi& game,
    std::uint32_t country_id,
    void* action) {
  (void)country_id;
  const auto& bindings = game.profile().diplomatic_action;
  if (action == nullptr) {
    return PrepareResult::Failed("diplomatic_action_allocation_failed");
  }
  void* command = ::operator new(
      bindings.propose_command_size, std::nothrow);
  if (command == nullptr) {
    game.DestroyCommand(action);
    return PrepareResult::Failed("command_allocation_failed");
  }

  // The native scoped-pointer constructor moves the action into command +0x20
  // and clears this source pointer. The command owns destruction thereafter.
  void* moved_action = action;
  game.FunctionAt<ProposeCommandCtorFn>(
      bindings.construct_propose_command)(command, &moved_action);
  if (moved_action != nullptr) {
    game.DestroyCommand(command);
    return PrepareResult::Failed("native_action_ownership_transfer_failed");
  }
  game.ResetCommandSerial(command);
  if (!game.IsCommandValid(command)) {
    game.DestroyCommand(command);
    return PrepareResult::Rejected("native_is_valid_false_before_submit");
  }
  return PrepareResult::Ready(command);
}

void* ConstructTargetOnlyAction(
    const GameApi& game,
    ProposalKind kind,
    const void* actor,
    const void* target,
    std::string& failure_detail) {
  const auto& bindings = game.profile().diplomatic_action;
  const auto simple_constructor = SimpleConstructor(bindings, kind);
  if (simple_constructor != 0U) {
    void* action = ::operator new(kSimpleActionSize, std::nothrow);
    if (action != nullptr) {
      game.FunctionAt<TwoCountryCtorFn>(simple_constructor)(
          action, actor, target);
    }
    return action;
  }

  if (kind == ProposalKind::kInviteToFederation) {
    void* action = ::operator new(
        kInviteFederationActionSize, std::nothrow);
    if (action != nullptr) {
      game.FunctionAt<InviteFederationCtorFn>(
          bindings.construct_invite_to_federation_action)(
          action, actor, target, nullptr);
    }
    return action;
  }

  if (kind == ProposalKind::kDemandSubjugation) {
    void* action = ::operator new(
        kDemandSubjugationActionSize, std::nothrow);
    if (action != nullptr) {
      alignas(std::max_align_t) std::array<std::byte, 0x10> absent_loyalty{};
      game.FunctionAt<DemandSubjugationCtorFn>(
          bindings.construct_demand_subjugation_action)(
          action, actor, target, absent_loyalty.data(), 0);
    }
    return action;
  }

  if (kind == ProposalKind::kDeclareWar) {
    const void* goal_type = game.FunctionAt<SelectWarGoalFn>(
        bindings.select_war_goal_type)(actor, target, false, false);
    const void* null_goal_type = *reinterpret_cast<void* const*>(
        game.Address(bindings.null_war_goal_type_instance));
    if (goal_type == nullptr || goal_type == null_goal_type) {
      failure_detail = "no_legal_native_war_goal";
      return nullptr;
    }
    alignas(std::max_align_t) std::array<std::byte, 0x20> war_goal{};
    game.FunctionAt<WarGoalCtorFn>(bindings.construct_war_goal)(
        war_goal.data(), goal_type);
    void* action = ::operator new(kDeclareWarActionSize, std::nothrow);
    if (action != nullptr) {
      game.FunctionAt<DeclareWarCtorFn>(
          bindings.construct_declare_war_action)(
          action, actor, target, war_goal.data());
    }
    game.FunctionAt<WarGoalDtorFn>(bindings.destroy_war_goal)(
        war_goal.data());
    return action;
  }

  failure_detail = "unsupported_diplomatic_proposal_kind";
  return nullptr;
}

class TargetOnlyProposalInvocation final : public ActionInvocation {
 public:
  TargetOnlyProposalInvocation(
      ProposalKind kind,
      std::uint32_t target_country_id)
      : kind_(kind), target_country_id_(target_country_id) {}

  [[nodiscard]] std::string_view action_type() const noexcept override {
    return ActionType(kind_);
  }

  [[nodiscard]] std::string TargetEcho() const override {
    return std::to_string(target_country_id_);
  }

  [[nodiscard]] PrepareResult Prepare(
      const GameApi& game,
      std::uint32_t country_id,
      const void* local_country) override {
    const void* target = ResolveTargetCountry(game, target_country_id_);
    if (target == nullptr || target == local_country) {
      return PrepareResult::Rejected("invalid_or_stale_target_country");
    }
    std::string failure_detail;
    void* action = ConstructTargetOnlyAction(
        game, kind_, local_country, target, failure_detail);
    if (action == nullptr && !failure_detail.empty()) {
      return PrepareResult::Rejected(std::move(failure_detail));
    }
    return WrapProposal(game, country_id, action);
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
  ProposalKind kind_;
  std::uint32_t target_country_id_;
};

std::unique_ptr<ActionInvocation> ParseTargetOnly(
    std::span<const std::string> fields,
    std::string& error_detail,
    ProposalKind kind) {
  if (fields.size() != 1U) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto target_country_id = ParseUint32(fields[0]);
  if (!target_country_id.has_value() || *target_country_id == UINT32_MAX) {
    error_detail = "invalid_target_country_id";
    return nullptr;
  }
  return std::make_unique<TargetOnlyProposalInvocation>(
      kind, *target_country_id);
}

class OfferPeaceInvocation final : public ActionInvocation {
 public:
  OfferPeaceInvocation(
      std::uint32_t target_country_id,
      std::uint32_t war_id,
      std::string offer_kind,
      int native_status)
      : target_country_id_(target_country_id),
        war_id_(war_id),
        offer_kind_(std::move(offer_kind)),
        native_status_(native_status) {}

  [[nodiscard]] std::string_view action_type() const noexcept override {
    return "offer_peace";
  }

  [[nodiscard]] std::string TargetEcho() const override {
    return std::to_string(target_country_id_) + ":" +
           std::to_string(war_id_) + ":" + offer_kind_;
  }

  [[nodiscard]] PrepareResult Prepare(
      const GameApi& game,
      std::uint32_t country_id,
      const void* local_country) override {
    const auto& bindings = game.profile().diplomatic_action;
    const void* target = ResolveTargetCountry(game, target_country_id_);
    const void* war = game.ResolvePdxObject(bindings.wars, war_id_);
    if (target == nullptr || target == local_country || war == nullptr) {
      return PrepareResult::Rejected("invalid_or_stale_peace_target");
    }

    alignas(std::max_align_t) std::array<std::byte, 0x18> peace_offer{};
    game.FunctionAt<PeaceOfferCtorFn>(bindings.construct_peace_offer)(
        peace_offer.data(), local_country, target, war);
    std::memcpy(
        peace_offer.data() + 0x14,
        &native_status_,
        sizeof(native_status_));

    void* action = ::operator new(kOfferPeaceActionSize, std::nothrow);
    if (action != nullptr) {
      game.FunctionAt<OfferPeaceCtorFn>(
          bindings.construct_offer_peace_action)(action, peace_offer.data());
    }
    return WrapProposal(game, country_id, action);
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
  std::uint32_t target_country_id_;
  std::uint32_t war_id_;
  std::string offer_kind_;
  int native_status_;
};

std::unique_ptr<ActionInvocation> ParseOfferPeace(
    std::span<const std::string> fields,
    std::string& error_detail) {
  if (fields.size() != 3U) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto target_country_id = ParseUint32(fields[0]);
  const auto war_id = ParseUint32(fields[1]);
  int status = -1;
  if (fields[2] == "force_demands") {
    status = 2;
  } else if (fields[2] == "status_quo") {
    status = 0;
  } else if (fields[2] == "surrender") {
    status = 1;
  }
  if (!target_country_id.has_value() || *target_country_id == UINT32_MAX ||
      !war_id.has_value() || *war_id == UINT32_MAX || status < 0) {
    error_detail = "invalid_peace_offer_target";
    return nullptr;
  }
  return std::make_unique<OfferPeaceInvocation>(
      *target_country_id, *war_id, fields[2], status);
}

const void* ResolveResource(
    const GameApi& game,
    std::string_view resource_key) {
  const auto& profile = game.profile();
  std::vector<std::byte> key(profile.c_string.object_size);
  const std::string owned_key(resource_key);
  game.FunctionAt<CStringCtorFn>(profile.c_string.construct)(
      key.data(), owned_key.c_str());
  const void* database = *reinterpret_cast<void* const*>(
      game.Address(profile.market_trade.resource_database_instance));
  const void* resource = nullptr;
  if (database != nullptr) {
    resource = game.FunctionAt<GetResourceFn>(
        profile.market_trade.get_resource)(database, key.data());
  }
  game.FunctionAt<CStringDtorFn>(profile.c_string.destroy)(key.data());
  const void* null_resource = *reinterpret_cast<void* const*>(
      game.Address(profile.market_trade.null_resource_instance));
  return resource == nullptr || resource == null_resource ? nullptr : resource;
}

class OfferTradeDealInvocation final : public ActionInvocation {
 public:
  OfferTradeDealInvocation(
      std::uint32_t target_country_id,
      bool offer,
      std::string resource_key,
      std::uint32_t amount)
      : target_country_id_(target_country_id),
        offer_(offer),
        resource_key_(std::move(resource_key)),
        amount_(amount) {}

  [[nodiscard]] std::string_view action_type() const noexcept override {
    return "offer_trade_deal";
  }

  [[nodiscard]] std::string TargetEcho() const override {
    return std::to_string(target_country_id_) + ":" +
           (offer_ ? "offer:" : "request:") + resource_key_ + ":" +
           std::to_string(amount_);
  }

  [[nodiscard]] PrepareResult Prepare(
      const GameApi& game,
      std::uint32_t country_id,
      const void* local_country) override {
    const void* target = ResolveTargetCountry(game, target_country_id_);
    if (target == nullptr || target == local_country) {
      return PrepareResult::Rejected("invalid_or_stale_target_country");
    }
    const void* resource = ResolveResource(game, resource_key_);
    if (resource == nullptr) {
      return PrepareResult::Rejected("unknown_resource_key");
    }

    const auto& bindings = game.profile().diplomatic_action;
    void* action = ::operator new(kOfferTradeDealActionSize, std::nothrow);
    if (action == nullptr) {
      return PrepareResult::Failed("diplomatic_action_allocation_failed");
    }
    game.FunctionAt<AbstractTradeDealCtorFn>(
        bindings.construct_abstract_trade_deal_action)(
        action, kOfferTradeDealTag, local_country, target);
    const std::uintptr_t vtable = game.Address(
        bindings.offer_trade_deal_vtable);
    std::memcpy(action, &vtable, sizeof(vtable));

    const std::uint32_t side_country_id =
        offer_ ? country_id : target_country_id_;
    void* side = game.FunctionAt<TradeDealAccessSideFn>(
        bindings.trade_deal_access_side)(
        static_cast<std::byte*>(action) + 0x50, &side_country_id);
    if (side == nullptr) {
      game.DestroyCommand(action);
      return PrepareResult::Failed("native_trade_deal_side_not_found");
    }
    const std::int64_t fixed_amount =
        static_cast<std::int64_t>(amount_) * kFixedPointScale;
    game.FunctionAt<TradeDealSetResourceFn>(
        bindings.trade_deal_set_resource)(side, resource, &fixed_amount);
    return WrapProposal(game, country_id, action);
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
  std::uint32_t target_country_id_;
  bool offer_;
  std::string resource_key_;
  std::uint32_t amount_;
};

std::unique_ptr<ActionInvocation> ParseOfferTradeDeal(
    std::span<const std::string> fields,
    std::string& error_detail) {
  if (fields.size() != 4U ||
      (fields[1] != "offer" && fields[1] != "request") ||
      !IsSemanticToken(fields[2], 160U)) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto target_country_id = ParseUint32(fields[0]);
  const auto amount = ParseUint32(fields[3]);
  if (!target_country_id.has_value() || *target_country_id == UINT32_MAX ||
      !amount.has_value() || *amount == 0U || *amount > 1000000U) {
    error_detail = "invalid_trade_deal_target";
    return nullptr;
  }
  return std::make_unique<OfferTradeDealInvocation>(
      *target_country_id, fields[1] == "offer", fields[2], *amount);
}

bool OfferPeaceSupported(const BuildProfile& profile) noexcept {
  const auto& bindings = profile.diplomatic_action;
  return CommonProposalSupported(profile) &&
         bindings.wars.database_instance != 0U &&
         bindings.wars.null_object_instance != 0U &&
         bindings.construct_peace_offer != 0U &&
         bindings.construct_offer_peace_action != 0U;
}

bool OfferTradeDealSupported(const BuildProfile& profile) noexcept {
  const auto& bindings = profile.diplomatic_action;
  return CommonProposalSupported(profile) &&
         bindings.construct_abstract_trade_deal_action != 0U &&
         bindings.offer_trade_deal_vtable != 0U &&
         bindings.trade_deal_access_side != 0U &&
         bindings.trade_deal_set_resource != 0U &&
         profile.market_trade.resource_database_instance != 0U &&
         profile.market_trade.null_resource_instance != 0U &&
         profile.market_trade.get_resource != 0U &&
         profile.c_string.construct != 0U &&
         profile.c_string.destroy != 0U;
}

constexpr std::array<ActionParameterDescriptor, 1> kCountryParameter = {{
    {
        .name = "target_country_id",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Generation-bearing country ID from a current candidate.",
        .minimum = 0,
        .maximum = UINT32_MAX - 1U,
    },
}};

constexpr std::array<ActionParameterDescriptor, 3> kPeaceParameters = {{
    kCountryParameter[0],
    {
        .name = "war_id",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Generation-bearing ID of the current war.",
        .minimum = 0,
        .maximum = UINT32_MAX - 1U,
    },
    {
        .name = "offer_kind",
        .type = ActionParameterType::kString,
        .required = true,
        .description = "One of force_demands, status_quo, or surrender.",
        .maximum_length = 16,
    },
}};

constexpr std::array<ActionParameterDescriptor, 4> kTradeParameters = {{
    kCountryParameter[0],
    {
        .name = "direction",
        .type = ActionParameterType::kString,
        .required = true,
        .description = "offer sends the resource; request asks the recipient.",
        .maximum_length = 7,
    },
    {
        .name = "resource_key",
        .type = ActionParameterType::kString,
        .required = true,
        .description = "Stable resource key from a current trade candidate.",
        .maximum_length = 160,
    },
    {
        .name = "amount",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Positive immediate resource amount in game units.",
        .minimum = 1,
        .maximum = 1000000,
    },
}};

#define IAG_DEFINE_TARGET_PROPOSAL(                                      \
    Symbol, Kind, Name, Description, Risk, Verification)                \
  std::unique_ptr<ActionInvocation> Parse##Symbol(                       \
      std::span<const std::string> fields,                               \
      std::string& error_detail) {                                       \
    return ParseTargetOnly(fields, error_detail, ProposalKind::Kind);     \
  }                                                                      \
  bool Symbol##Supported(const BuildProfile& profile) noexcept {          \
    return TargetOnlySupported(profile, ProposalKind::Kind);              \
  }                                                                      \
  const ActionDescriptor k##Symbol##Descriptor = {                        \
      .action_type = Name,                                                \
      .action_version = 1,                                                \
      .application_id = "etc",                                           \
      .description = Description,                                        \
      .risk_class = Risk,                                                 \
      .verification_state = Verification,                                 \
      .parameters = kCountryParameter,                                   \
      .parse = &Parse##Symbol,                                            \
      .supported = &Symbol##Supported,                                   \
  };                                                                     \
  IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration                \
      k##Symbol##Registration{k##Symbol##Descriptor}

IAG_DEFINE_TARGET_PROPOSAL(
    OpenBorders,
    kOpenBorders,
    "open_borders",
    "Open borders to one validated country.",
    "state_change",
    "live_verified");
IAG_DEFINE_TARGET_PROPOSAL(
    CloseBorders,
    kCloseBorders,
    "close_borders",
    "Close borders to one validated country.",
    "state_change",
    "live_verified");
IAG_DEFINE_TARGET_PROPOSAL(
    EstablishRivalry,
    kMakeRival,
    "establish_rivalry",
    "Declare one validated country a rival.",
    "destructive_state_change",
    "live_verified");
IAG_DEFINE_TARGET_PROPOSAL(
    DeclareWar,
    kDeclareWar,
    "declare_war",
    "Declare war using the native highest-weight currently legal war goal.",
    "destructive_state_change",
    "live_verified");
IAG_DEFINE_TARGET_PROPOSAL(
    EstablishEmbassy,
    kCreateEmbassy,
    "establish_embassy",
    "Establish an embassy with one validated country.",
    "state_change",
    "live_verified");
IAG_DEFINE_TARGET_PROPOSAL(
    FormCommercialPact,
    kFormCommercialPact,
    "form_commercial_pact",
    "Propose a commercial pact to one validated country.",
    "state_change",
    "live_verified");
IAG_DEFINE_TARGET_PROPOSAL(
    FormDefensivePact,
    kFormDefensivePact,
    "form_defensive_pact",
    "Propose a defensive pact to one validated country.",
    "state_change",
    "paired_capture");
IAG_DEFINE_TARGET_PROPOSAL(
    FormResearchAgreement,
    kFormResearchAgreement,
    "form_research_agreement",
    "Propose a research agreement to one validated country.",
    "state_change",
    "live_verified");
IAG_DEFINE_TARGET_PROPOSAL(
    FormMigrationPact,
    kFormMigrationPact,
    "form_migration_pact",
    "Propose a migration treaty to one validated country.",
    "state_change",
    "live_verified");
IAG_DEFINE_TARGET_PROPOSAL(
    InviteToFederation,
    kInviteToFederation,
    "invite_to_federation",
    "Invite one validated country to the actor's federation.",
    "state_change",
    "paired_capture");
IAG_DEFINE_TARGET_PROPOSAL(
    DemandSubjugation,
    kDemandSubjugation,
    "demand_subjugation",
    "Propose the native default subject agreement to one country.",
    "destructive_state_change",
    "paired_capture");
IAG_DEFINE_TARGET_PROPOSAL(
    BreakMigrationPact,
    kBreakMigrationPact,
    "break_migration_pact",
    "End the migration treaty with one validated country.",
    "destructive_state_change",
    "live_verified");
IAG_DEFINE_TARGET_PROPOSAL(
    BreakCommercialPact,
    kBreakCommercialPact,
    "break_commercial_pact",
    "End the commercial pact with one validated country.",
    "destructive_state_change",
    "live_verified");
IAG_DEFINE_TARGET_PROPOSAL(
    InsultCountry,
    kInsult,
    "insult_country",
    "Send a diplomatic insult to one validated country.",
    "destructive_state_change",
    "live_verified");

#undef IAG_DEFINE_TARGET_PROPOSAL

const ActionDescriptor kOfferPeaceDescriptor = {
    .action_type = "offer_peace",
    .action_version = 1,
    .application_id = "etc",
    .description = "Offer force-demands, status-quo, or surrender peace terms.",
    .risk_class = "destructive_state_change",
    .verification_state = "live_verified",
    .parameters = kPeaceParameters,
    .parse = &ParseOfferPeace,
    .supported = &OfferPeaceSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration
    kOfferPeaceRegistration{kOfferPeaceDescriptor};

const ActionDescriptor kOfferTradeDealDescriptor = {
    .action_type = "offer_trade_deal",
    .action_version = 1,
    .application_id = "etc",
    .description = "Offer or request one immediate resource line in a trade deal.",
    .risk_class = "state_change",
    .verification_state = "live_verified",
    .parameters = kTradeParameters,
    .parse = &ParseOfferTradeDeal,
    .supported = &OfferTradeDealSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration
    kOfferTradeDealRegistration{kOfferTradeDealDescriptor};

}  // namespace
}  // namespace iag::native_runtime
