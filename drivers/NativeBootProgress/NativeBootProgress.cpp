// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// NativeBootProgress: a framebuffer instrument for the earliest kernel stages.
//
// The handset has no usable serial console, and on 2026-11-26 the panel stayed on DarwinBoot's hand-off
// page with no kernel line after it. Upstream solves the same problem with a boot-progress library drawn
// into the framebuffer (patches/xnu/zzz-boot-progress.patch, scripts/check-boot-progress-code.py): the marks
// are committed with interrupts masked so a fault cannot leave them in flight.
//
// This is the smallest useful version of that idea. It is called from osfmk/arm/arm_init.c, before
// arm_vm_init turns the MMU on, so the framebuffer physical address is still identity-mapped and the writes
// need no mapping, no locks and no headers. Each stage draws one full-width bar; the number of bars on the
// panel is how far the kernel got.
//
// It draws and returns: no allocation, no IOKit, no logging, no state that another CPU depends on.

#include <stdint.h>

#include "BootProgressCore.h"

namespace {

inline void
store32(uint64_t offset, uint32_t value)
{
    *reinterpret_cast<volatile uint32_t*>(boot_progress::kFramebufferBase + offset) = value;
}

void
fill(const boot_progress::Rect& rect)
{
    if (!boot_progress::drawable(rect)) {
        return;
    }
    for (uint32_t row = 0; row < rect.height; ++row) {
        const uint64_t row_base = boot_progress::pixel_offset(rect) + static_cast<uint64_t>(row) * boot_progress::kRowBytes;
        for (uint32_t column = 0; column < rect.width; ++column) {
            store32(row_base + static_cast<uint64_t>(column) * boot_progress::kBytesPerPixel, rect.rgb);
        }
    }
}

void
freeze_and_commit()
{
    // The marks must reach the panel even if the kernel faults immediately afterwards. Upstream's check
    // script requires the same pair (DAIFSet then DSB SY) for its progress library.
    asm volatile("msr DAIFSet, #0xf" ::: "memory");
    asm volatile("dsb sy" ::: "memory");
}

}  // namespace

extern "C" void
native_boot_progress_stage(int stage)
{
    const boot_progress::Rect rect = boot_progress::bar_for(stage);
    if (!boot_progress::drawable(rect)) {
        return;
    }
    freeze_and_commit();
    fill(rect);
    asm volatile("dsb sy" ::: "memory");
}
