#include "iag_native_runtime/sdk_metadata.h"

#if defined(IAG_NATIVE_RUNTIME_RECOVERED_SDK_HEADER)
#include IAG_NATIVE_RUNTIME_RECOVERED_SDK_HEADER
#elif defined(_WIN32)
#include "versions/generated/stellaris_4_5_2_windows_sdk.hpp"
#else
#include "versions/generated/stellaris_4_5_2_linux_sdk.hpp"
#endif

namespace iag::native_runtime {

const RecoveredSdk& ActiveRecoveredSdk() noexcept {
  return generated::kRecoveredSdk;
}

}  // namespace iag::native_runtime
