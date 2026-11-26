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
is_separator(char character)
{
    return character == '\0' || character == ' ' || character == '\t';
}

// A boot argument is a token: 'lumia-bars2' must not satisfy 'lumia-bars', which is what plain substring matching did
// -- and that made the post-MMU run enable the two bootstrap bars, which fault before VM setup.
bool
contains(const char *haystack, const char *needle)
{
    if (haystack == nullptr || needle == nullptr || *needle == '\0') {
        return false;
    }
    for (const char *start = haystack; *start != '\0'; ++start) {
        if (start != haystack && !is_separator(start[-1])) {
            continue;
        }
        const char *a = start;
        const char *b = needle;
        while (*a != '\0' && *b != '\0' && *a == *b) {
            ++a;
            ++b;
        }
        if (*b == '\0' && is_separator(*a)) {
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

// The post-MMU bar needs its own switch: the two bootstrap bars fault on every platform (the panel is not mapped when
// arm_init runs), so enabling them to see the third bar would kill the kernel before it ever got there.
constexpr const char *kMappedSwitch = "lumia-bars2";

namespace {

// What arm_init learned from boot_args, kept for the later stage. Nothing here is an ABI guess: arm_init passes
// the values straight through, and the later call only needs them again after the MMU has been configured.
struct Remembered {
    void *base;
    unsigned long stride;
    unsigned long height;
    const char *command_line;
};

Remembered remembered = {nullptr, 0ul, 0ul, nullptr};

extern "C" void native_boot_progress_stage(void *base, unsigned long stride, unsigned long height,
                                       const char *command_line, int stage);

}  // namespace

extern "C" void
native_boot_progress_remember(void *base, unsigned long stride, unsigned long height, const char *command_line)
{
    remembered.base = base;
    remembered.stride = stride;
    remembered.height = height;
    remembered.command_line = command_line;
}

// The post-MMU caller has the console's mapped panel but not the command line as a C string (PE_boot_args() returns
// the boot_args block itself), so the switch is evaluated against what arm_init remembered.
extern "C" void
native_boot_progress_stage_remembered(void *base, unsigned long stride, unsigned long height, int stage)
{
    native_boot_progress_stage(base, stride, height, remembered.command_line, stage);
}

// The storage driver reaches the kernel as an mkext: the source link has no IOStorageFamily and the prelink takes only
// Apple's kexts, while OSKext::loadFromMkext() is in the kernel. The container is embedded in this archive by
// scripts/embed-blob.py, and the call is behind its own switch so a boot that does not ask for it never loads anything.
extern "C" const unsigned char lumia_sdhci_mkext[];
extern "C" const unsigned long lumia_sdhci_mkext_size;

extern "C" int
native_boot_progress_switch(const char *command_line, const char *want)
{
    return contains(command_line, want) ? 1 : 0;
}

extern "C" void
native_boot_progress_stage(void *base, unsigned long stride, unsigned long height,
                           const char *command_line, int stage)
{
    if (!contains(command_line, stage >= 2 ? kMappedSwitch : kSwitch)) {
        return;
    }
    // Stage 2 runs after the kernel console has filled the upper half of the panel, so that bar goes on the last
    // rows instead: an instrument that draws where the console overwrites it cannot be read.
    const boot_progress::Rect rect =
        stage >= 2
            ? boot_progress::bottom_bar_for(static_cast<uint32_t>(stride / boot_progress::kBytesPerPixel),
                                            static_cast<uint32_t>(height),
                                            boot_progress::bar_for(stage, static_cast<uint32_t>(stride / boot_progress::kBytesPerPixel), static_cast<uint32_t>(height)).rgb)
            : boot_progress::bar_for(stage, static_cast<uint32_t>(stride / boot_progress::kBytesPerPixel),
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
