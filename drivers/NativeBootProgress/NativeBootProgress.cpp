// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// NativeBootProgress: a framebuffer instrument for the earliest kernel stages.
//
// The handset has no console the kernel can reach, and on 2026-11-26 the panel stayed on DarwinBoot's
// hand-off page with no kernel line after it. Upstream solves this with a boot-progress library drawn into the
// framebuffer (patches/xnu/zzz-boot-progress.patch); this is the smallest useful version of that idea.
//
// It is called from osfmk/arm/arm_init.c while the MMU is still off, so the caller passes the panel
// parameters out of `boot_args.Video` and the stores need no mapping, no lock and no headers. It draws one
// bar per stage and returns; after `arm_vm_init` turns the MMU on there is no call, because a store to the
// framebuffer's physical address then raises a synchronous exception (measured: run 45764900801).

#include <stdint.h>

#include "BootProgressCore.h"

namespace {

inline void
store32(uint64_t address, uint32_t value)
{
    *reinterpret_cast<volatile uint32_t*>(address) = value;
}

}  // namespace

namespace {

bool
contains(const char *haystack, const char *needle)
{
    if (haystack == nullptr || needle == nullptr) {
        return false;
    }
    for (const char *start = haystack; *start != '\0'; ++start) {
        const char *a = start;
        const char *b = needle;
        while (*a != '\0' && *b != '\0' && *a == *b) {
            ++a;
            ++b;
        }
        if (*b == '\0') {
            return true;
        }
    }
    return false;
}

}  // namespace

// The switch that turns the bars on. It is a boot argument because a store to the framebuffer is only safe
// when the address really is the panel: in the emulated run the same call raised a synchronous exception
// before VM setup (runs 45764900801, 45774728401), and the kernel must not be killed by its own instrument.
constexpr const char *kSwitch = "lumia-bars";

extern "C" void
native_boot_progress_stage(void *base, unsigned long stride, unsigned long height,
                           const char *command_line, int stage)
{
    if (!contains(command_line, kSwitch)) {
        return;
    }
    const boot_progress::Rect rect =
        boot_progress::bar_for(stage, static_cast<uint32_t>(stride / boot_progress::kBytesPerPixel),
                               static_cast<uint32_t>(height));
    if (base == nullptr || !boot_progress::drawable(rect, stride, static_cast<uint32_t>(height))) {
        return;
    }

    // Commit before anything else can fault: the same pair upstream's check script requires. On a host build
    // the barriers are not available and not needed -- there the same function writes into a heap buffer so the
    // geometry and the switch can be tested without a kernel.
#if defined(__aarch64__)
    asm volatile("msr DAIFSet, #0xf" ::: "memory");
    asm volatile("dsb sy" ::: "memory");
#endif

    const uintptr_t framebuffer = reinterpret_cast<uintptr_t>(base);
    const uint64_t start = static_cast<uint64_t>(framebuffer) + boot_progress::pixel_offset(rect, stride);
    for (uint32_t row = 0; row < rect.height; ++row) {
        const uint64_t row_base = start + static_cast<uint64_t>(row) * stride;
        for (uint32_t column = 0; column < rect.width; ++column) {
            store32(row_base + static_cast<uint64_t>(column) * boot_progress::kBytesPerPixel, rect.rgb);
        }
    }

#if defined(__aarch64__)
    asm volatile("dsb sy" ::: "memory");
#endif
}
