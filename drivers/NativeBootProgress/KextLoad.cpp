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

#include <pexpert/pexpert.h>

// The kernel cannot load an mkext from here.
//
// OSKext::loadFromMkext() exists in the pinned kernel, but it is a **private** member (OSKext.h, line 509), as is
// withBooterData(); the compiler refuses the call outright:
//
//   error: 'loadFromMkext' is a private member of 'OSKext'
//
// The public entry, loadKextWithIdentifier(), looks a bundle up on disk, and this port has no filesystem at bsd_init --
// that is the very thing the driver would provide. So the container stays embedded and unused until one of these is
// built:
//
//   * a kernel-side request through kmod_control()/OSKext::handleRequest(), whose request format is user-space shaped;
//   * an entry in the kernel's own __PRELINK_INFO, so the boot path loads the kext the way it loads Apple's;
//   * a public (or upstreamed) memory-loading entry point.
//
// What this file does keep is the diagnostic: it reports that a boot asked for the kext and that the route is not
// wired yet, so the log says which of the two is missing instead of looking like a silent failure.

extern "C" const unsigned long lumia_sdhci_mkext_size;

extern "C" int
lumia_kext_load(const char *command_line)
{
    if (command_line == nullptr || lumia_sdhci_mkext_size == 0UL) {
        return 0;
    }
    // "lumia-kext" is a token check, matching the other switches.
    bool wanted = false;
    for (const char *start = command_line; *start != '\0'; ++start) {
        if (start != command_line && start[-1] != ' ' && start[-1] != '\t') {
            continue;
        }
        const char *candidate = "lumia-kext";
        const char *a = start;
        const char *b = candidate;
        while (*a != '\0' && *b != '\0' && *a == *b) {
            ++a;
            ++b;
        }
        if (*b == '\0' && (*a == '\0' || *a == ' ' || *a == '\t')) {
            wanted = true;
            break;
        }
    }
    if (!wanted) {
        return 0;
    }
    kprintf("lumia: %lu bytes of kext container are embedded, but OSKext::loadFromMkext() is private in this kernel; "
            "the load is not wired yet\n", lumia_sdhci_mkext_size);
    return 0;
}
