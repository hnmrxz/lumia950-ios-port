// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Host test for the boot-progress geometry. The stores themselves are compiled only by the kernel job; this
// checks that the marks land inside the panel and that a stage maps to a distinct bar, for both the handset
// panel and the ones the emulator reports.

#include <cstdio>
#include <cstdlib>

#include "BootProgressCore.h"

using namespace boot_progress;

namespace {

int failures = 0;

void
check(bool condition, const char* what)
{
    if (!condition) {
        std::fprintf(stderr, "FAIL %s\n", what);
        ++failures;
    }
}

}  // namespace

int
main()
{
    // The handset panel, as the firmware probe and DarwinBoot reported it: 1080x1920, row 4320, 32 bpp.
    const uint32_t handset_width = 1080u;
    const uint32_t handset_height = 1920u;
    const uint64_t handset_stride = 4320u;
    check(handset_stride >= static_cast<uint64_t>(handset_width) * kBytesPerPixel,
          "handset stride covers the visible width");

    check(drawable(bar_for(0, handset_width, handset_height), handset_stride, handset_height),
          "stage 0 is drawable on the handset panel");
    check(!drawable(bar_for(-1, handset_width, handset_height), handset_stride, handset_height),
          "a negative stage draws nothing");
    check(!drawable(bar_for(200, handset_width, handset_height), handset_stride, handset_height),
          "a stage past the panel draws nothing");

    for (int stage = 0; stage < 6; ++stage) {
        const Rect rect = bar_for(stage, handset_width, handset_height);
        check(drawable(rect, handset_stride, handset_height), "each early stage is drawable");
        check(rect.y + rect.height <= handset_height, "bar stays inside the panel");
        check(pixel_offset(rect, handset_stride) % 4u == 0u, "pixel offset is 32-bit aligned");
        if (stage > 0) {
            const Rect previous = bar_for(stage - 1, handset_width, handset_height);
            check(rect.y >= previous.y + previous.height, "bars do not overlap");
        }
    }

    check(bar_for(0, handset_width, handset_height).rgb != bar_for(1, handset_width, handset_height).rgb,
          "stage colours differ");

    // A narrower stride than the visible width cannot be drawn into, and an empty panel draws nothing.
    check(!drawable(bar_for(0, handset_width, handset_height), 1000u, handset_height),
          "a stride narrower than the width is refused");
    check(!drawable(bar_for(0, 0u, handset_height), handset_stride, handset_height),
          "a zero-width panel draws nothing");

    if (failures == 0) {
        std::printf("boot progress core: ok\n");
    }
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
