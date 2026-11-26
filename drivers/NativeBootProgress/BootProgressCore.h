// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// The geometry of the boot-progress marks, kept apart from the stores so a host test can check it.
// Nothing here touches memory: NativeBootProgress.cpp does the writes.
//
// The panel parameters are not constants here. The kernel receives them from DarwinBoot in
// `boot_args.Video` (v_baseAddr, v_rowBytes, v_height) and the caller passes them in, because the emulator
// and the handset do not agree on any of them: the handset panel is 1080x1920 at 0x400000, the QEMU run
// reported base 0x6C7A0000. A hard-coded address drew into unmapped space in QEMU and the kernel took a
// synchronous exception before VM setup (run 45764900801).

#ifndef NATIVE_BOOT_PROGRESS_CORE_H
#define NATIVE_BOOT_PROGRESS_CORE_H

#include <stdint.h>

namespace boot_progress {

constexpr uint32_t kBytesPerPixel = 4u;

// Each stage draws one full-width bar, so "how far did it get" is a count from the top of the panel.
constexpr uint32_t kBarHeight = 16u;
constexpr uint32_t kFirstBarY = 120u;
constexpr uint32_t kStageStride = kBarHeight + 4u;

struct Rect {
    uint32_t x;
    uint32_t y;
    uint32_t width;
    uint32_t height;
    uint32_t rgb;  // 0x00RRGGBB
};

// The bar for a stage on a panel of the given width/height, or a zero-sized rect when it cannot be drawn.
constexpr Rect bar_for(int stage, uint32_t width, uint32_t height)
{
    if (stage < 0 || width == 0u || height == 0u) {
        return Rect{0u, 0u, 0u, 0u, 0u};
    }
    const uint32_t y = kFirstBarY + static_cast<uint32_t>(stage) * kStageStride;
    if (y + kBarHeight > height) {
        return Rect{0u, 0u, 0u, 0u, 0u};
    }
    // A colour per stage: red, yellow, green, cyan, magenta, white.
    const uint32_t colours[6] = {0x00E03030u, 0x00E0E030u, 0x0030C030u, 0x0020B0C0u, 0x00C040C0u, 0x00F0F0F0u};
    const uint32_t rgb = colours[static_cast<uint32_t>(stage) % 6u];
    return Rect{0u, y, width, kBarHeight, rgb};
}

// The post-MMU bar goes on the last rows of the panel: the kernel console writes from the top and, at the point this
// bar is drawn, its text already covers roughly the first half of the screen. A bar drawn in that area can be there
// and still be invisible, which is exactly what an instrument must not allow.
constexpr Rect bottom_bar_for(uint32_t width, uint32_t height, uint32_t rgb)
{
    if (width == 0u || height < 2u * kBarHeight) {
        return Rect{0u, 0u, 0u, 0u, 0u};
    }
    return Rect{0u, height - kBarHeight, width, kBarHeight, rgb};
}

// The byte offset of the rect's first pixel, for a panel with the given row stride.
constexpr uint64_t pixel_offset(const Rect& rect, uint64_t stride)
{
    return static_cast<uint64_t>(rect.y) * stride + static_cast<uint64_t>(rect.x) * kBytesPerPixel;
}

constexpr bool drawable(const Rect& rect, uint64_t stride, uint32_t height)
{
    if (rect.width == 0u || rect.height == 0u || stride < static_cast<uint64_t>(rect.width) * kBytesPerPixel) {
        return false;
    }
    return pixel_offset(rect, stride) + static_cast<uint64_t>(rect.height - 1u) * stride +
               static_cast<uint64_t>(rect.width - 1u) * kBytesPerPixel <
           stride * height;
}

}  // namespace boot_progress

#endif  // NATIVE_BOOT_PROGRESS_CORE_H
