#include <array>
#include <cstddef>
#include <cstring>
#include <new>
#include <string>
#include <utility>
#include <vector>

#include "iag_native_runtime/action.h"
#include "iag_native_runtime/game_api.h"

namespace iag::native_runtime {
namespace {

using CStringCtorFn = void (*)(void*, const char*);
using CStringDtorFn = void (*)(void*);
using GetResourceFn = const void* (*)(const void*, const void*);
using MarketCommandCtorFn = void (*)(void*, const void*, int);
using MarketCommandIsValidFn = bool (*)(const void*, void*);

template <typename Value>
void WriteField(void* object, std::size_t offset, Value value) {
  std::memcpy(static_cast<std::byte*>(object) + offset, &value, sizeof(value));
}

class MarketTradeInvocation final : public ActionInvocation {
 public:
  MarketTradeInvocation(std::string resource_key, int lots, bool buy)
      : resource_key_(std::move(resource_key)), lots_(lots), buy_(buy) {}

  [[nodiscard]] std::string_view action_type() const noexcept override {
    return buy_ ? "market_buy_resource" : "market_sell_resource";
  }

  [[nodiscard]] std::string TargetEcho() const override {
    return resource_key_ + ":" + std::to_string(lots_);
  }

  [[nodiscard]] PrepareResult Prepare(
      const GameApi& game,
      std::uint32_t country_id,
      const void*) override {
    const auto& profile = game.profile();
    std::vector<std::byte> key(profile.c_string.object_size);
    game.FunctionAt<CStringCtorFn>(profile.c_string.construct)(
        key.data(), resource_key_.c_str());
    const void* database = *reinterpret_cast<void* const*>(
        game.Address(profile.market_trade.resource_database_instance));
    const void* resource = nullptr;
    if (database != nullptr) {
      resource = game.FunctionAt<GetResourceFn>(profile.market_trade.get_resource)(
          database, key.data());
    }
    game.FunctionAt<CStringDtorFn>(profile.c_string.destroy)(key.data());
    const void* null_resource = *reinterpret_cast<void* const*>(
        game.Address(profile.market_trade.null_resource_instance));
    if (resource == nullptr || resource == null_resource) {
      return PrepareResult::Rejected("unknown_resource_key");
    }

    std::array<std::byte, 0x18> trade_data{};
    WriteField(trade_data.data(), 0x08, resource);
    WriteField(trade_data.data(), 0x10, buy_ ? 0 : 1);
    WriteField(trade_data.data(), 0x14, country_id);

    const auto construct = game.FunctionAt<MarketCommandCtorFn>(
        buy_ ? profile.market_trade.construct_buy_command
             : profile.market_trade.construct_sell_command);
    const auto validate = game.FunctionAt<MarketCommandIsValidFn>(
        buy_ ? profile.market_trade.validate_buy_command
             : profile.market_trade.validate_sell_command);
    std::vector<std::byte> validation(profile.market_trade.command_size);
    construct(validation.data(), trade_data.data(), lots_);
    if (!validate(validation.data(), nullptr)) {
      return PrepareResult::Rejected("native_is_valid_false_before_submit");
    }

    void* command =
        ::operator new(profile.market_trade.command_size, std::nothrow);
    if (command == nullptr) {
      return PrepareResult::Failed("command_allocation_failed");
    }
    construct(command, trade_data.data(), lots_);
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
  std::string resource_key_;
  int lots_;
  bool buy_;
};

std::unique_ptr<ActionInvocation> ParseMarketTrade(
    std::span<const std::string> fields,
    std::string& error_detail,
    bool buy) {
  if (fields.size() != 2U || !IsSemanticToken(fields[0], 160U)) {
    error_detail = "invalid_semantic_target";
    return nullptr;
  }
  const auto lots = ParseUint32(fields[1]);
  if (!lots.has_value() || *lots == 0U || *lots > 0x7fffffffU) {
    error_detail = "invalid_market_lot_count";
    return nullptr;
  }
  return std::make_unique<MarketTradeInvocation>(
      fields[0], static_cast<int>(*lots), buy);
}

std::unique_ptr<ActionInvocation> ParseMarketBuy(
    std::span<const std::string> fields,
    std::string& error_detail) {
  return ParseMarketTrade(fields, error_detail, true);
}

std::unique_ptr<ActionInvocation> ParseMarketSell(
    std::span<const std::string> fields,
    std::string& error_detail) {
  return ParseMarketTrade(fields, error_detail, false);
}

bool MarketTradeSupported(const BuildProfile& profile) noexcept {
  return profile.market_trade.command_size != 0U &&
         profile.market_trade.construct_buy_command != 0U &&
         profile.market_trade.construct_sell_command != 0U &&
         profile.market_trade.validate_buy_command != 0U &&
         profile.market_trade.validate_sell_command != 0U &&
         profile.market_trade.resource_database_instance != 0U &&
         profile.market_trade.null_resource_instance != 0U &&
         profile.market_trade.get_resource != 0U &&
         profile.c_string.construct != 0U && profile.c_string.destroy != 0U;
}

constexpr std::array<ActionParameterDescriptor, 2> kParameters = {{
    {
        .name = "resource_key",
        .type = ActionParameterType::kString,
        .required = true,
        .description = "Stable strategic-resource key from a current market candidate.",
        .maximum_length = 160,
    },
    {
        .name = "lots",
        .type = ActionParameterType::kUint32,
        .required = true,
        .description = "Positive number of game-defined immediate-trade lots.",
        .minimum = 1,
        .maximum = 0x7fffffffU,
    },
}};

const ActionDescriptor kBuyDescriptor = {
    .action_type = "market_buy_resource",
    .action_version = 1,
    .application_id = "economy_governance",
    .description = "Buy a validated number of lots of one market resource.",
    .risk_class = "state_change",
    .verification_state = "live_verified",
    .parameters = kParameters,
    .parse = &ParseMarketBuy,
    .supported = &MarketTradeSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kBuyRegistration{
    kBuyDescriptor};

const ActionDescriptor kSellDescriptor = {
    .action_type = "market_sell_resource",
    .action_version = 1,
    .application_id = "economy_governance",
    .description = "Sell a validated number of lots of one market resource.",
    .risk_class = "state_change",
    .verification_state = "live_verified",
    .parameters = kParameters,
    .parse = &ParseMarketSell,
    .supported = &MarketTradeSupported,
};
IAG_NATIVE_ACTION_REGISTRATION const ActionRegistration kSellRegistration{
    kSellDescriptor};

}  // namespace
}  // namespace iag::native_runtime
