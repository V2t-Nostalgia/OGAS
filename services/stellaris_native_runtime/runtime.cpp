#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdarg>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <link.h>
#include <memory>
#include <mutex>
#include <new>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <thread>
#include <unistd.h>
#include <utility>
#include <vector>

#include "iag_native_runtime/action.h"
#include "iag_native_runtime/game_api.h"
#include "iag_native_runtime/sdk_probe.h"
#include "iag_native_runtime/state_query.h"
#include "iag_native_runtime/version_profile.h"

namespace iag::native_runtime {
namespace {

using namespace std::chrono_literals;

constexpr char kDefaultSocketPath[] = "/tmp/iag-stellaris-native.sock";
constexpr char kProtocolVersion[] = "IAG1";
constexpr char kDescribeToolsAction[] = "describe_tools";
constexpr char kInspectOpenEventsAction[] = "inspect_open_events";
constexpr char kInspectPendingDiplomaticActionsAction[] =
    "inspect_pending_diplomatic_actions";
constexpr char kValidateRecoveredCommandAction[] = "validate_recovered_command";
constexpr auto kExecutionTimeout = 15s;
constexpr auto kResponseTimeout = 20s;

using GameIdlerIdleFn = void (*)(void*, bool);

enum class RequestPhase { kPending, kPosted, kDone };
enum class RequestKind {
  kAction,
  kInspectOpenEvents,
  kValidateRecoveredCommand,
  kInspectPendingDiplomaticActions
};

struct RuntimeRequest {
  std::uint64_t generation = 0;
  std::string request_id;
  std::string action_type;
  std::string target_echo;
  std::uint32_t country_id = 0;
  std::optional<std::uint32_t> probe_leader_id;
  std::uint32_t probe_candidate_index = 0;
  bool probe_auto_country = false;
  std::string probe_command_name;
  bool probe_native_domain = false;
  std::optional<RecoveredConstraintCandidate> probe_constraint_candidate;
  std::shared_ptr<ActionInvocation> invocation;
  RequestKind kind = RequestKind::kAction;
  RequestPhase phase = RequestPhase::kPending;
  std::chrono::steady_clock::time_point deadline;
  RuntimeResult result;
};

struct CachedResult {
  std::string request_id;
  std::string payload_fingerprint;
  std::string response;
};

GameIdlerIdleFn g_original_game_idler_idle = nullptr;
std::unique_ptr<GameApi> g_game;
std::mutex g_request_mutex;
std::condition_variable g_request_changed;
std::optional<RuntimeRequest> g_active_request;
std::optional<CachedResult> g_last_result;
std::atomic<std::uint64_t> g_generation{0};
std::mutex g_log_mutex;
char g_runtime_status[256] = "not_initialized";
thread_local bool g_inside_idle_hook = false;

const BuildProfile& Profile() { return ActiveStellarisProfile(); }

void Log(const char* format, ...) {
  std::lock_guard lock(g_log_mutex);
  const int fd = ::open(
      "/tmp/iag-stellaris-native.log", O_CREAT | O_WRONLY | O_APPEND, 0600);
  if (fd < 0) {
    return;
  }
  va_list arguments;
  va_start(arguments, format);
  ::vdprintf(fd, format, arguments);
  va_end(arguments);
  ::close(fd);
}

std::size_t Align4(std::size_t value) {
  return (value + 3U) & ~std::size_t{3U};
}

struct MainModuleIdentity {
  std::uintptr_t base = 0;
  std::string build_id;
};

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
        return 1;
      }
      cursor += name_size + description_size;
    }
  }
  return 1;
}

bool VerifyExecutable() {
  MainModuleIdentity identity;
  ::dl_iterate_phdr(ReadMainModuleIdentity, &identity);
  if (identity.build_id != Profile().build_id) {
    std::snprintf(
        g_runtime_status,
        sizeof(g_runtime_status),
        "build_id_mismatch:%s",
        identity.build_id.c_str());
    return false;
  }
  g_game = std::make_unique<GameApi>(identity.base, Profile());
  if (!g_game->VerifyRequiredAnchors()) {
    std::snprintf(
        g_runtime_status, sizeof(g_runtime_status), "function_signature_mismatch");
    g_game.reset();
    return false;
  }
  return true;
}

void WriteAbsoluteJump(unsigned char* destination, const void* target) {
  destination[0] = 0xff;
  destination[1] = 0x25;
  std::memset(destination + 2, 0, 4);
  const auto value = reinterpret_cast<std::uintptr_t>(target);
  std::memcpy(destination + 6, &value, sizeof(value));
}

bool InstallGameIdlerIdleHook(void* hook) {
  const std::size_t hook_length = Profile().core.hook_length;
  auto* target = reinterpret_cast<unsigned char*>(
      g_game->Address(Profile().core.game_idler_idle));
  void* trampoline = ::mmap(
      nullptr,
      hook_length * 2U,
      PROT_READ | PROT_WRITE | PROT_EXEC,
      MAP_PRIVATE | MAP_ANONYMOUS,
      -1,
      0);
  if (trampoline == MAP_FAILED) {
    std::snprintf(
        g_runtime_status, sizeof(g_runtime_status), "trampoline_mmap_failed");
    return false;
  }
  std::memcpy(trampoline, target, hook_length);
  WriteAbsoluteJump(
      static_cast<unsigned char*>(trampoline) + hook_length,
      target + hook_length);
  __builtin___clear_cache(
      static_cast<char*>(trampoline),
      static_cast<char*>(trampoline) + hook_length * 2U);
  if (::mprotect(trampoline, hook_length * 2U, PROT_READ | PROT_EXEC) != 0) {
    std::snprintf(
        g_runtime_status, sizeof(g_runtime_status), "trampoline_mprotect_failed");
    return false;
  }

  const long page_size = ::sysconf(_SC_PAGESIZE);
  if (page_size <= 0) {
    std::snprintf(g_runtime_status, sizeof(g_runtime_status), "invalid_page_size");
    return false;
  }
  const auto page_mask = static_cast<std::uintptr_t>(page_size - 1);
  const auto page = reinterpret_cast<void*>(
      reinterpret_cast<std::uintptr_t>(target) & ~page_mask);
  if (::mprotect(
          page,
          static_cast<std::size_t>(page_size),
          PROT_READ | PROT_WRITE | PROT_EXEC) != 0) {
    std::snprintf(
        g_runtime_status, sizeof(g_runtime_status), "hook_mprotect_failed");
    return false;
  }
  std::vector<unsigned char> patch(hook_length);
  WriteAbsoluteJump(patch.data(), hook);
  std::memcpy(target, patch.data(), patch.size());
  __builtin___clear_cache(
      reinterpret_cast<char*>(target),
      reinterpret_cast<char*>(target) + patch.size());
  if (::mprotect(
          page,
          static_cast<std::size_t>(page_size),
          PROT_READ | PROT_EXEC) != 0) {
    std::snprintf(
        g_runtime_status,
        sizeof(g_runtime_status),
        "hook_restore_protection_failed");
    return false;
  }
  g_original_game_idler_idle = reinterpret_cast<GameIdlerIdleFn>(trampoline);
  return true;
}

std::vector<std::string> SplitTabs(std::string_view line) {
  std::vector<std::string> fields;
  while (true) {
    const std::size_t separator = line.find('\t');
    fields.emplace_back(line.substr(0, separator));
    if (separator == std::string_view::npos) {
      return fields;
    }
    line.remove_prefix(separator + 1U);
  }
}

std::string SanitizeDetail(std::string detail) {
  for (char& character : detail) {
    if (character == '\t' || character == '\r' || character == '\n') {
      character = ' ';
    }
  }
  if (detail.size() > 240U) {
    detail.resize(240U);
  }
  return detail;
}

std::string RequestFingerprint(const RuntimeRequest& request) {
  if (request.kind != RequestKind::kAction &&
      request.kind != RequestKind::kValidateRecoveredCommand) {
    return request.action_type + '\t' + std::to_string(request.country_id);
  }
  return request.action_type + '\t' + std::to_string(request.country_id) + '\t' +
         request.target_echo;
}

std::string BuildResponse(const RuntimeRequest& request) {
  return std::string(kProtocolVersion) + '\t' + request.request_id + '\t' +
         request.action_type + '\t' + request.result.outcome + '\t' +
         Profile().build_id + '\t' + std::to_string(request.country_id) + '\t' +
         request.target_echo + '\t' +
         SanitizeDetail(request.result.detail) + '\n';
}

std::string ImmediateResponse(
    std::string_view request_id,
    std::string_view action,
    std::string_view outcome,
    std::string_view detail) {
  return std::string(kProtocolVersion) + '\t' + std::string(request_id) + '\t' +
         std::string(action) + '\t' + std::string(outcome) + '\t' +
         Profile().build_id + "\t0\t-\t" +
         SanitizeDetail(std::string(detail)) + '\n';
}

std::string ToolManifestResponse(std::string_view request_id) {
  return std::string(kProtocolVersion) + '\t' + std::string(request_id) + '\t' +
         kDescribeToolsAction + "\tconfirmed\t" + Profile().build_id +
         "\t0\t" + BuildToolManifestJson(Profile()) +
         "\truntime_tool_manifest\n";
}

void FinishRequest(
    std::uint64_t generation,
    std::string outcome,
    std::string detail) {
  std::lock_guard lock(g_request_mutex);
  if (!g_active_request.has_value() ||
      g_active_request->generation != generation) {
    return;
  }
  g_active_request->result = {std::move(outcome), std::move(detail)};
  g_active_request->phase = RequestPhase::kDone;
  g_request_changed.notify_all();
}

void FinishStateQuery(
    std::uint64_t generation,
    StateQueryResult result) {
  std::lock_guard lock(g_request_mutex);
  if (!g_active_request.has_value() ||
      g_active_request->generation != generation) {
    return;
  }
  g_active_request->target_echo = std::move(result.payload);
  g_active_request->result = {
      std::move(result.outcome), std::move(result.detail)};
  g_active_request->phase = RequestPhase::kDone;
  g_request_changed.notify_all();
}

void FailActiveRequest(std::string detail) {
  std::lock_guard lock(g_request_mutex);
  if (!g_active_request.has_value() ||
      g_active_request->phase == RequestPhase::kDone) {
    return;
  }
  g_active_request->result = {"failed", std::move(detail)};
  g_active_request->phase = RequestPhase::kDone;
  g_request_changed.notify_all();
}

void ProcessPendingBeforeUpdate(bool run_game_update) {
  RuntimeRequest request;
  {
    std::lock_guard lock(g_request_mutex);
    if (!g_active_request.has_value() ||
        g_active_request->phase != RequestPhase::kPending) {
      return;
    }
    request = *g_active_request;
  }

  if (!ShouldDispatchPending(
          run_game_update, request.kind == RequestKind::kValidateRecoveredCommand)) {
    return;
  }
  if (request.kind == RequestKind::kInspectOpenEvents) {
    FinishStateQuery(
        request.generation,
        InspectOpenEvents(*g_game, request.country_id));
    return;
  }
  if (request.kind == RequestKind::kInspectPendingDiplomaticActions) {
    FinishStateQuery(
        request.generation,
        InspectPendingDiplomaticActions(*g_game, request.country_id));
    return;
  }
  if (request.kind == RequestKind::kValidateRecoveredCommand) {
    const RecoveredProbeOptions options{
        request.probe_auto_country ? std::nullopt : std::optional{request.country_id},
        request.probe_leader_id, request.probe_candidate_index, run_game_update, request.probe_native_domain,
        request.probe_constraint_candidate ? &*request.probe_constraint_candidate : nullptr};
    FinishStateQuery(request.generation, ProbeRecoveredCommand(
        *g_game, ActiveRecoveredSdk(), request.probe_command_name, options));
    return;
  }

  const void* local_country = g_game->LocalObservedCountry();
  if (local_country == nullptr) {
    FinishRequest(request.generation, "rejected", "no_local_observed_country");
    return;
  }
  if (g_game->CountryId(local_country) != request.country_id) {
    FinishRequest(
        request.generation, "rejected", "authority_country_mismatch");
    return;
  }

  PrepareResult prepared = request.invocation->Prepare(
      *g_game, request.country_id, local_country);
  if (prepared.status != PreparationStatus::kReady) {
    const char* outcome = prepared.status == PreparationStatus::kRejected
                              ? "rejected"
                              : "failed";
    FinishRequest(request.generation, outcome, std::move(prepared.detail));
    return;
  }
  if (prepared.command == nullptr) {
    FinishRequest(request.generation, "failed", "action_returned_null_command");
    return;
  }

  {
    std::lock_guard lock(g_request_mutex);
    if (!g_active_request.has_value() ||
        g_active_request->generation != request.generation) {
      ::operator delete(prepared.command);
      return;
    }
    g_active_request->deadline =
        std::chrono::steady_clock::now() + kExecutionTimeout;
    g_active_request->phase = RequestPhase::kPosted;
  }
  g_game->PostCommand(prepared.command);
  Log(
      "request=%s action=%s country=%u target=%s posted\n",
      request.request_id.c_str(),
      request.action_type.c_str(),
      request.country_id,
      request.target_echo.c_str());
}

void VerifyPostedAfterUpdate() {
  RuntimeRequest request;
  {
    std::lock_guard lock(g_request_mutex);
    if (!g_active_request.has_value() ||
        g_active_request->phase != RequestPhase::kPosted) {
      return;
    }
    request = *g_active_request;
  }

  const void* local_country = g_game->LocalObservedCountry();
  if (local_country != nullptr &&
      g_game->CountryId(local_country) == request.country_id) {
    const auto result = request.invocation->Verify(
        *g_game, request.country_id, local_country);
    if (result.has_value()) {
      FinishRequest(request.generation, result->outcome, result->detail);
      Log(
          "request=%s action=%s country=%u target=%s confirmed detail=%s\n",
          request.request_id.c_str(),
          request.action_type.c_str(),
          request.country_id,
          request.target_echo.c_str(),
          result->detail.c_str());
      return;
    }
  }
  if (std::chrono::steady_clock::now() >= request.deadline) {
    FinishRequest(
        request.generation,
        "pending",
        std::string(request.invocation->TimeoutDetail()));
  }
}

void GameIdlerIdleHook(void* idler, bool run_game_update) {
  if (g_inside_idle_hook || g_original_game_idler_idle == nullptr) {
    if (g_original_game_idler_idle != nullptr) {
      g_original_game_idler_idle(idler, run_game_update);
    }
    return;
  }
  g_inside_idle_hook = true;
  try {
    ProcessPendingBeforeUpdate(run_game_update);
  } catch (...) {
    FailActiveRequest("action_prepare_exception");
  }
  g_original_game_idler_idle(idler, run_game_update);
  if (run_game_update) {
    try {
      VerifyPostedAfterUpdate();
    } catch (...) {
      FailActiveRequest("action_verify_exception");
    }
  }
  g_inside_idle_hook = false;
}

bool SendAll(int socket, std::string_view data) {
  while (!data.empty()) {
    const ssize_t written = ::send(socket, data.data(), data.size(), MSG_NOSIGNAL);
    if (written <= 0) {
      return false;
    }
    data.remove_prefix(static_cast<std::size_t>(written));
  }
  return true;
}

std::optional<std::string> ReceiveLine(int socket) {
  std::string line;
  std::array<char, 256> buffer{};
  while (line.size() <= 65'536U) {
    const ssize_t count = ::recv(socket, buffer.data(), buffer.size(), 0);
    if (count <= 0) {
      return std::nullopt;
    }
    line.append(buffer.data(), static_cast<std::size_t>(count));
    const std::size_t newline = line.find('\n');
    if (newline != std::string::npos) {
      line.resize(newline);
      return line;
    }
  }
  return std::nullopt;
}

std::string HandleRequest(std::string_view line) {
  const auto fields = SplitTabs(line);
  if (fields.size() == 4U && fields[0] == kProtocolVersion &&
      fields[2] == kDescribeToolsAction && fields[3] == "0") {
    if (!IsSemanticToken(fields[1], 96U)) {
      return ImmediateResponse(
          fields[1], fields[2], "rejected", "invalid_request_id");
    }
    return ToolManifestResponse(fields[1]);
  }
  if (fields.size() == 4U && fields[0] == kProtocolVersion &&
      fields[2] == "describe_recovered_commands" && fields[3] == "0") {
    if (!IsSemanticToken(fields[1], 96U)) {
      return ImmediateResponse(fields[1], fields[2], "rejected", "invalid_request_id");
    }
    return std::string(kProtocolVersion) + '\t' + fields[1] + '\t' + fields[2] +
        "\tconfirmed\t" + Profile().build_id + "\t0\t" +
        DescribeRecoveredCommands(ActiveRecoveredSdk(), static_cast<std::uint32_t>(::getpid()),
            reinterpret_cast<std::uintptr_t>(&g_active_request), g_game.get()) +
        "\trecovered_command_catalog\n";
  }
  const bool inspect_open_events =
      fields.size() == 4U && fields[0] == kProtocolVersion &&
      fields[2] == kInspectOpenEventsAction;
  const bool inspect_pending_diplomatic_actions =
      fields.size() == 4U && fields[0] == kProtocolVersion &&
      fields[2] == kInspectPendingDiplomaticActionsAction;
  const bool state_query =
      inspect_open_events || inspect_pending_diplomatic_actions;
  const bool validate_recovered_command =
      (fields.size() == 6U || fields.size() == 7U || fields.size() == 8U || fields.size() == 14U) && fields[0] == kProtocolVersion &&
      fields[2] == kValidateRecoveredCommandAction;
  // Targetless semantic actions still carry the protocol, request, action,
  // and authority fields. Their descriptor receives an empty target span.
  if ((!state_query && fields.size() < 4U) ||
      fields[0] != kProtocolVersion) {
    return ImmediateResponse("invalid", "unknown", "rejected", "bad_request");
  }
  const std::string& request_id = fields[1];
  const std::string& action_type = fields[2];
  if (!IsSemanticToken(request_id, 96U)) {
    return ImmediateResponse(
        request_id, action_type, "rejected", "invalid_semantic_target");
  }
  const bool auto_country = validate_recovered_command &&
      (fields[3] == "auto" || fields[3] == "4294967295");
  const auto country_id = auto_country ? std::optional<std::uint32_t>{UINT32_MAX}
                                       : ParseUint32(fields[3]);
  if (!country_id.has_value()) {
    return ImmediateResponse(
        request_id, action_type, "rejected", "country_id_out_of_range");
  }
  RuntimeRequest parsed_request;
  parsed_request.request_id = request_id;
  parsed_request.action_type = action_type;
  parsed_request.country_id = *country_id;
  if (validate_recovered_command) {
    const auto leader_id = fields[5] == "auto" ? std::optional<std::uint32_t>{}
                                              : ParseUint32(fields[5]);
    const auto candidate_index = fields.size() >= 7U ? ParseUint32(fields[6])
                                                     : std::optional<std::uint32_t>{0U};
    const bool constraint_plan = fields.size() == 14U && fields[7] == "constraint_plan";
    const auto constraint = constraint_plan
        ? ParseRecoveredConstraintCandidate(std::span<const std::string>(fields).subspan(8U))
        : std::optional<RecoveredConstraintCandidate>{};
    if ((fields[5] != "auto" && !leader_id) ||
        !candidate_index || *candidate_index >= 16U || !IsSemanticToken(fields[4], 96U) ||
        (fields.size() == 8U && fields[7] != "native_domain") ||
        (fields.size() == 8U && fields[5] != "auto") ||
        (fields.size() == 14U && (!constraint || fields[5] != "auto" ||
         constraint->expected_instance != reinterpret_cast<std::uintptr_t>(&g_active_request)))) {
      return ImmediateResponse(request_id, action_type, "rejected", "invalid_probe_selector");
    }
    parsed_request.kind = RequestKind::kValidateRecoveredCommand;
    parsed_request.probe_leader_id = leader_id;
    parsed_request.probe_auto_country = auto_country;
    parsed_request.probe_candidate_index = *candidate_index;
    parsed_request.probe_command_name = fields[4];
    parsed_request.probe_native_domain = fields.size() == 8U;
    parsed_request.probe_constraint_candidate = constraint;
    parsed_request.target_echo = fields[4] + ":" + fields[5] + ":" +
                                 std::to_string(*candidate_index);
    if (parsed_request.probe_native_domain) parsed_request.target_echo += ":native_domain";
    if (constraint) {
      for (std::size_t i = 7U; i < fields.size(); ++i) parsed_request.target_echo += ":" + fields[i];
    }
  } else if (inspect_open_events) {
    parsed_request.kind = RequestKind::kInspectOpenEvents;
    parsed_request.target_echo = "open-events";
  } else if (inspect_pending_diplomatic_actions) {
    parsed_request.kind = RequestKind::kInspectPendingDiplomaticActions;
    parsed_request.target_echo = "pending-diplomatic-actions";
  } else {
    const ActionDescriptor* descriptor = FindActionDescriptor(action_type);
    if (descriptor == nullptr || !descriptor->supported(Profile())) {
      return ImmediateResponse(
          request_id, action_type, "rejected", "unsupported_action");
    }

    std::string parse_error;
    const auto target_fields = std::span<const std::string>(fields).subspan(4U);
    std::unique_ptr<ActionInvocation> parsed =
        descriptor->parse(target_fields, parse_error);
    if (parsed == nullptr) {
      return ImmediateResponse(
          request_id,
          action_type,
          "rejected",
          parse_error.empty() ? "invalid_semantic_target" : parse_error);
    }
    const std::string target_echo = parsed->TargetEcho();
    if (parsed->action_type() != descriptor->action_type ||
        !IsSemanticToken(target_echo, 160U)) {
      return ImmediateResponse(
          request_id,
          action_type,
          "failed",
          "action_handler_contract_violation");
    }
    parsed_request.target_echo = target_echo;
    parsed_request.invocation =
        std::shared_ptr<ActionInvocation>(std::move(parsed));
  }
  const std::string fingerprint = RequestFingerprint(parsed_request);

  std::unique_lock lock(g_request_mutex);
  if (g_last_result.has_value() && g_last_result->request_id == request_id) {
    if (g_last_result->payload_fingerprint == fingerprint) {
      return g_last_result->response;
    }
    return ImmediateResponse(
        request_id,
        action_type,
        "conflict",
        "request_id_payload_conflict");
  }
  if (g_active_request.has_value()) {
    if (g_active_request->request_id != request_id) {
      return ImmediateResponse(
          request_id, action_type, "busy", "runtime_request_active");
    }
    if (RequestFingerprint(*g_active_request) != fingerprint) {
      return ImmediateResponse(
          request_id,
          action_type,
          "conflict",
          "request_id_payload_conflict");
    }
  } else {
    parsed_request.generation = ++g_generation;
    g_active_request = std::move(parsed_request);
  }

  const std::uint64_t generation = g_active_request->generation;
  const bool completed = g_request_changed.wait_for(
      lock, kResponseTimeout, [generation] {
        return g_active_request.has_value() &&
               g_active_request->generation == generation &&
               g_active_request->phase == RequestPhase::kDone;
      });
  if (!completed) {
    return ImmediateResponse(
        request_id, action_type, "pending", "runtime_response_timeout");
  }
  const std::string response = BuildResponse(*g_active_request);
  g_last_result = CachedResult{request_id, fingerprint, response};
  g_active_request.reset();
  return response;
}

void SocketServer() {
  const char* configured = std::getenv("IAG_NATIVE_RUNTIME_SOCKET");
  const std::string path = configured != nullptr && configured[0] == '/'
                               ? configured
                               : kDefaultSocketPath;
  sockaddr_un address{};
  if (path.size() >= sizeof(address.sun_path)) {
    Log("socket path too long: %s\n", path.c_str());
    return;
  }
  const int server = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
  if (server < 0) {
    Log("socket creation failed\n");
    return;
  }
  ::unlink(path.c_str());
  address.sun_family = AF_UNIX;
  std::memcpy(address.sun_path, path.c_str(), path.size() + 1U);
  if (::bind(server, reinterpret_cast<sockaddr*>(&address), sizeof(address)) != 0 ||
      ::chmod(path.c_str(), 0600) != 0 || ::listen(server, 4) != 0) {
    Log("socket bind/listen failed: %s\n", path.c_str());
    ::close(server);
    return;
  }
  Log(
      "runtime ready socket=%s build_id=%s hook=CGameIdler::Idle\n",
      path.c_str(),
      Profile().build_id);
  while (true) {
    const int client = ::accept4(server, nullptr, nullptr, SOCK_CLOEXEC);
    if (client < 0) {
      continue;
    }
    const auto line = ReceiveLine(client);
    const std::string response = line.has_value()
                                     ? HandleRequest(*line)
                                     : ImmediateResponse(
                                           "invalid",
                                           "unknown",
                                           "rejected",
                                           "request_read_failed");
    SendAll(client, response);
    ::close(client);
  }
}

void InitializeRuntime() {
  std::string descriptor_error;
  if (!ValidateActionDescriptors(descriptor_error)) {
    std::snprintf(
        g_runtime_status,
        sizeof(g_runtime_status),
        "action_registry_invalid:%s",
        descriptor_error.c_str());
    Log("runtime rejected: %s\n", g_runtime_status);
    return;
  }
  if (!VerifyExecutable()) {
    Log("runtime rejected: %s\n", g_runtime_status);
    return;
  }
  if (!InstallGameIdlerIdleHook(reinterpret_cast<void*>(&GameIdlerIdleHook))) {
    Log("runtime hook failed: %s\n", g_runtime_status);
    return;
  }
  std::snprintf(g_runtime_status, sizeof(g_runtime_status), "ready");
  std::thread(SocketServer).detach();
}

}  // namespace

const char* RuntimeStatus() noexcept { return g_runtime_status; }

void Initialize() { InitializeRuntime(); }

}  // namespace iag::native_runtime

extern "C" __attribute__((visibility("default"))) const char*
iag_native_runtime_status() {
  return iag::native_runtime::RuntimeStatus();
}

__attribute__((constructor)) static void IagNativeRuntimeInitialize() {
  iag::native_runtime::Initialize();
}
