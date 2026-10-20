#include "rotating_probe_log.h"

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <string>

#include <stdlib.h>

namespace {

bool Require(bool condition, const char* message) {
  if (!condition) {
    std::cerr << message << '\n';
  }
  return condition;
}

std::string ReadFile(const std::filesystem::path& path) {
  std::ifstream stream(path, std::ios::binary);
  return std::string(
      std::istreambuf_iterator<char>(stream),
      std::istreambuf_iterator<char>());
}

}  // namespace

int main() {
  char directory_template[] = "/tmp/iag-rotating-probe-log-XXXXXX";
  const char* directory_value = ::mkdtemp(directory_template);
  if (!Require(directory_value != nullptr, "mkdtemp failed")) {
    return 1;
  }
  const std::filesystem::path directory(directory_value);
  const std::filesystem::path path = directory / "events.jsonl";
  const std::string header = "{\"kind\":\"probe_started\"}\n";
  const std::string event = "{\"kind\":\"command\"}\n";

  {
    iag::stellaris::research::RotatingProbeLog log;
    if (!Require(
            log.Open(
                path.c_str(),
                header,
                "IAG_TEST_ROTATE_BYTES_UNSET",
                "IAG_TEST_ROTATE_SECONDS_UNSET",
                "IAG_TEST_MIN_FREE_UNSET",
                header.size() + event.size(),
                0,
                0),
            "log open failed") ||
        !Require(log.Write(event, 1), "first event write failed") ||
        !Require(log.Write(event, 2), "rotated event write failed")) {
      return 1;
    }
  }

  std::filesystem::path ready;
  for (const auto& entry : std::filesystem::directory_iterator(directory)) {
    if (entry.path().extension() == ".ready") {
      ready = entry.path();
    }
  }
  if (!Require(!ready.empty(), "rotated segment was not published") ||
      !Require(
          ReadFile(ready) == header + event,
          "rotated segment contents differ") ||
      !Require(
          ReadFile(path) == header + event,
          "active segment contents differ")) {
    return 1;
  }

  const std::filesystem::path low_space_path = directory / "low-space.jsonl";
  {
    iag::stellaris::research::RotatingProbeLog log;
    if (!Require(
            log.Open(
                low_space_path.c_str(),
                header,
                "IAG_TEST_ROTATE_BYTES_UNSET",
                "IAG_TEST_ROTATE_SECONDS_UNSET",
                "IAG_TEST_MIN_FREE_UNSET",
                0,
                0,
                std::numeric_limits<std::uint64_t>::max()),
            "low-space log open failed") ||
        !Require(!log.Write(event, 1), "disk reserve did not stop recording")) {
      return 1;
    }
  }

  std::filesystem::remove_all(directory);
  return 0;
}
