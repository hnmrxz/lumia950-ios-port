// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Load the storage driver's container from the image this kernel carries.
//
// The source link cannot take NativeSdhci (no IOStorageFamily there) and the prelink merges only Apple's kexts, so the
// one route left is the kernel's own kext loader: the container is embedded in this archive by scripts/embed-blob.py
// and OSKext::loadFromMkext() is called from bsd_init, before vfs_mountroot, behind its own boot argument.
//
// This lives in its own translation unit because it is the only file in the component that includes an XNU C++ header;
// the host preflight compiles NativeBootProgress.cpp with nothing but the repository on the include path, and it should
// stay that way.

#include <libkern/c++/OSKext.h>

extern "C" const unsigned char lumia_sdhci_mkext[];
extern "C" const unsigned long lumia_sdhci_mkext_size;

namespace {

bool
has_token(const char *haystack, const char *needle)
{
    if (haystack == nullptr || needle == nullptr || *needle == '\0') {
        return false;
    }
    for (const char *start = haystack; *start != '\0'; ++start) {
        if (start != haystack && start[-1] != ' ' && start[-1] != '\t') {
            continue;
        }
        const char *a = start;
        const char *b = needle;
        while (*a != '\0' && *b != '\0' && *a == *b) {
            ++a;
            ++b;
        }
        if (*b == '\0' && (*a == '\0' || *a == ' ' || *a == '\t')) {
            return true;
        }
    }
    return false;
}

}  // namespace

extern "C" int
lumia_kext_load(const char *command_line)
{
    if (!has_token(command_line, "lumia-kext")) {
        return 0;
    }
    char *log = nullptr;
    uint32_t log_length = 0;
    const OSReturn result = OSKext::loadFromMkext(
        0, const_cast<char *>(reinterpret_cast<const char *>(lumia_sdhci_mkext)),
        static_cast<uint32_t>(lumia_sdhci_mkext_size), &log, &log_length);
    IOLog("lumia: OSKext::loadFromMkext returned %d (%lu bytes, %u bytes of log)\n",
          static_cast<int>(result), lumia_sdhci_mkext_size, log_length);
    if (log != nullptr && log_length > 0) {
        IOLog("lumia: %.*s\n", static_cast<int>(log_length), log);
    }
    return static_cast<int>(result);
}
