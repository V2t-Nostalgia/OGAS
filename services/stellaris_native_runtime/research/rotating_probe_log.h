#pragma once

#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <limits>
#include <string>
#include <string_view>
#include <sys/statvfs.h>
#include <time.h>
#include <unistd.h>
#include <utility>

namespace iag::stellaris::research {

class RotatingProbeLog {
 public:
  RotatingProbeLog() = default;
  RotatingProbeLog(const RotatingProbeLog&) = delete;
  RotatingProbeLog& operator=(const RotatingProbeLog&) = delete;

  ~RotatingProbeLog() {
    if (fd_ >= 0) {
      ::close(fd_);
    }
  }

  bool Open(
      const char* path,
      std::string header,
      const char* rotate_bytes_environment,
      const char* rotate_seconds_environment,
      const char* min_free_bytes_environment,
      std::uint64_t default_rotate_bytes,
      std::uint64_t default_rotate_seconds,
      std::uint64_t default_min_free_bytes) {
    base_path_ = path;
    header_ = std::move(header);
    rotate_bytes_ = ReadUnsignedEnvironment(
        rotate_bytes_environment, default_rotate_bytes);
    rotate_ns_ = SecondsToNanoseconds(ReadUnsignedEnvironment(
        rotate_seconds_environment, default_rotate_seconds));
    min_free_bytes_ = ReadUnsignedEnvironment(
        min_free_bytes_environment, default_min_free_bytes);
    struct timespec realtime {};
    (void)::clock_gettime(CLOCK_REALTIME, &realtime);
    char instance[48]{};
    std::snprintf(
        instance,
        sizeof(instance),
        "%llx%08lx",
        static_cast<unsigned long long>(realtime.tv_sec),
        static_cast<unsigned long>(realtime.tv_nsec));
    instance_id_ = instance;
    fd_ = ::open(
        base_path_.c_str(), O_CREAT | O_WRONLY | O_APPEND | O_CLOEXEC, 0600);
    if (fd_ < 0) {
      SetError("log_open_failed");
      return false;
    }
    const off_t end = ::lseek(fd_, 0, SEEK_END);
    bytes_written_ = end > 0 ? static_cast<std::uint64_t>(end) : 0;
    if (!WriteAll(fd_, header_)) {
      SetError("header_write_failed");
      return false;
    }
    bytes_written_ += header_.size();
    return true;
  }

  bool Write(std::string_view line, std::uint64_t monotonic_ns) {
    if (fd_ < 0) {
      return false;
    }
    if (opened_monotonic_ns_ == 0) {
      opened_monotonic_ns_ = monotonic_ns;
    }
    if (!HasCapacity(monotonic_ns)) {
      return false;
    }
    if (ShouldRotate(line.size(), monotonic_ns) &&
        (last_rotation_attempt_ns_ == 0 ||
         monotonic_ns - last_rotation_attempt_ns_ >= kRotationRetryNs)) {
      last_rotation_attempt_ns_ = monotonic_ns;
      (void)Rotate(monotonic_ns);
    }
    if (!WriteAll(fd_, line)) {
      SetError("event_write_failed");
      return false;
    }
    bytes_written_ += line.size();
    return true;
  }

  const char* error() const { return error_; }

 private:
  static constexpr std::uint64_t kSpaceCheckIntervalNs = 5'000'000'000ULL;
  static constexpr std::uint64_t kRotationRetryNs = 5'000'000'000ULL;

  static std::uint64_t ReadUnsignedEnvironment(
      const char* name, std::uint64_t fallback) {
    const char* value = std::getenv(name);
    if (value == nullptr || value[0] == '\0') {
      return fallback;
    }
    errno = 0;
    char* end = nullptr;
    const unsigned long long parsed = std::strtoull(value, &end, 10);
    if (errno != 0 || end == value || *end != '\0') {
      return fallback;
    }
    return static_cast<std::uint64_t>(parsed);
  }

  static std::uint64_t SecondsToNanoseconds(std::uint64_t seconds) {
    constexpr std::uint64_t kNanosecondsPerSecond = 1'000'000'000ULL;
    if (seconds >
        std::numeric_limits<std::uint64_t>::max() / kNanosecondsPerSecond) {
      return std::numeric_limits<std::uint64_t>::max();
    }
    return seconds * kNanosecondsPerSecond;
  }

  static bool WriteAll(int fd, std::string_view value) {
    while (!value.empty()) {
      const ssize_t written = ::write(fd, value.data(), value.size());
      if (written > 0) {
        value.remove_prefix(static_cast<std::size_t>(written));
        continue;
      }
      if (written < 0 && errno == EINTR) {
        continue;
      }
      return false;
    }
    return true;
  }

  bool HasCapacity(std::uint64_t monotonic_ns) {
    if (min_free_bytes_ == 0) {
      return true;
    }
    if (last_space_check_ns_ != 0 &&
        monotonic_ns - last_space_check_ns_ < kSpaceCheckIntervalNs) {
      return capacity_available_;
    }
    last_space_check_ns_ = monotonic_ns;
    struct statvfs status {};
    if (::fstatvfs(fd_, &status) != 0) {
      capacity_available_ = true;
      return true;
    }
    const auto block_size = static_cast<std::uint64_t>(status.f_frsize);
    const auto available_blocks = static_cast<std::uint64_t>(status.f_bavail);
    const std::uint64_t available =
        block_size != 0 &&
                available_blocks >
                    std::numeric_limits<std::uint64_t>::max() / block_size
            ? std::numeric_limits<std::uint64_t>::max()
            : block_size * available_blocks;
    capacity_available_ = available >= min_free_bytes_;
    if (!capacity_available_) {
      SetError("low_disk_space");
    }
    return capacity_available_;
  }

  bool ShouldRotate(std::size_t next_size, std::uint64_t monotonic_ns) const {
    const bool size_due =
        rotate_bytes_ != 0 && bytes_written_ + next_size > rotate_bytes_;
    const bool time_due =
        rotate_ns_ != 0 && opened_monotonic_ns_ != 0 &&
        monotonic_ns - opened_monotonic_ns_ >= rotate_ns_;
    return size_due || time_due;
  }

  bool Rotate(std::uint64_t monotonic_ns) {
    ++segment_index_;
    char suffix[96]{};
    std::snprintf(
        suffix,
        sizeof(suffix),
        ".%lu.%s.%06llu",
        static_cast<unsigned long>(::getpid()),
        instance_id_.c_str(),
        static_cast<unsigned long long>(segment_index_));
    const std::string ready_path = base_path_ + suffix + ".ready";
    const std::string next_path = base_path_ + suffix + ".next";
    const int next_fd = ::open(
        next_path.c_str(),
        O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC,
        0600);
    if (next_fd < 0) {
      SetError("rotation_next_open_failed");
      return false;
    }
    if (!WriteAll(next_fd, header_)) {
      ::close(next_fd);
      ::unlink(next_path.c_str());
      SetError("rotation_header_write_failed");
      return false;
    }
    if (::rename(base_path_.c_str(), ready_path.c_str()) != 0) {
      ::close(next_fd);
      ::unlink(next_path.c_str());
      SetError("rotation_archive_rename_failed");
      return false;
    }
    if (::rename(next_path.c_str(), base_path_.c_str()) != 0) {
      (void)::rename(ready_path.c_str(), base_path_.c_str());
      ::close(next_fd);
      ::unlink(next_path.c_str());
      SetError("rotation_activate_rename_failed");
      return false;
    }
    ::close(fd_);
    fd_ = next_fd;
    bytes_written_ = header_.size();
    opened_monotonic_ns_ = monotonic_ns;
    error_[0] = '\0';
    return true;
  }

  void SetError(const char* value) {
    std::snprintf(error_, sizeof(error_), "%s", value);
  }

  int fd_ = -1;
  std::string base_path_;
  std::string header_;
  std::string instance_id_;
  std::uint64_t rotate_bytes_ = 0;
  std::uint64_t rotate_ns_ = 0;
  std::uint64_t min_free_bytes_ = 0;
  std::uint64_t bytes_written_ = 0;
  std::uint64_t segment_index_ = 0;
  std::uint64_t opened_monotonic_ns_ = 0;
  std::uint64_t last_rotation_attempt_ns_ = 0;
  std::uint64_t last_space_check_ns_ = 0;
  bool capacity_available_ = true;
  char error_[96]{};
};

}  // namespace iag::stellaris::research
