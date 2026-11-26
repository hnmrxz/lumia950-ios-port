// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// The geometry and colours of the boot-progress marks, kept apart from the stores so a host test can
// check them. Nothing here touches memory: NativeBootProgress.cpp does the writes.
//
// The panel numbers are the Lumia 950's own, as the firmware reported them (1080x1920, row 4320 bytes,
// 32 bpp at 0x400000) and as DarwinBoot printed them on the handset on 2026-11-26:
//
//   DARWINBOOT: video base=0x400000 display=1 row=4320 width=1080 height=1920 depth=32

#ifndef NATIVE_BOOT_PROGRESS_CORE_H
#define NATIVE_BOOT_PROGRESS_CORE_H

#include <stdint.h>

namespace boot_progress {

constexpr uint64_t kFramebufferBase = 0x400000ull;
constexpr uint32_t kRowBytes = 4320u;
constexpr uint32_t kWidth = 1080u;
constexpr uint32_t kHeight = 1920u;
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

// The bar for a stage, or a zero-sized rect when the stage cannot be drawn on this panel.
constexpr Rect bar_for(int stage)
{
    if (stage < 0) {
        return Rect{0u, 0u, 0u, 0u, 0u};
    }
    const uint32_t y = kFirstBarY + static_cast<uint32_t>(stage) * kStageStride;
    if (y + kBarHeight > kHeight) {
        return Rect{0u, 0u, 0u, 0u, 0u};
    }
    // A colour per stage: red, yellow, green, cyan, magenta, white.
    const uint32_t colours[6] = {0x00E03030u, 0x00E0E030u, 0x0030C030u, 0x0020B0C0u, 0x00C040C0u, 0x00F0F0F0u};
    const uint32_t rgb = colours[static_cast<uint32_t>(stage) % 6u];
    return Rect{0u, y, kWidth, kBarHeight, rgb};
}

// The byte offset of the rect's first pixel from the framebuffer base.
constexpr uint64_t pixel_offset(const Rect& rect)
{
    return static_cast<uint64_t>(rect.y) * kRowBytes + static_cast<uint64_t>(rect.x) * kBytesPerPixel;
}

constexpr bool drawable(const Rect& rect)
{
    return rect.width != 0u && rect.height != 0u &&
           pixel_offset(rect) + static_cast<uint64_t>(rect.height - 1u) * kRowBytes +
                   static_cast<uint64_t>(rect.width - 1u) * kBytesPerPixel <
               static_cast<uint64_t>(kRowBytes) * kHeight;
}

}  // namespace boot_progress

#endif  // NATIVE_BOOT_PROGRESS_CORE_H
