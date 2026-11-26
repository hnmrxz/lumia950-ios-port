// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Host test for the boot-progress geometry. The stores themselves are compiled only by the kernel job;
// this checks that the marks land inside the panel and that a stage maps to a distinct bar.

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
    // The panel numbers match what the firmware probe and DarwinBoot reported on the handset.
    check(kWidth == 1080u && kHeight == 1920u && kRowBytes == 4320u && kBytesPerPixel == 4u,
          "panel geometry matches the measured Lumia 950 GOP");
    check(kRowBytes >= kWidth * kBytesPerPixel, "row stride covers the visible width");

    // Stage 0 must be drawable and land on the panel; a negative stage must not.
    check(drawable(bar_for(0)), "stage 0 is drawable");
    check(!drawable(bar_for(-1)), "a negative stage draws nothing");
    check(!drawable(bar_for(200)), "a stage past the panel draws nothing");

    // Bars must not overlap and must stay inside the panel.
    for (int stage = 0; stage < 6; ++stage) {
        const Rect rect = bar_for(stage);
        check(drawable(rect), "each early stage is drawable");
        check(rect.y + rect.height <= kHeight, "bar stays inside the panel");
        check(pixel_offset(rect) % 4u == 0u, "pixel offset is 32-bit aligned");
        if (stage > 0) {
            const Rect previous = bar_for(stage - 1);
            check(rect.y >= previous.y + previous.height, "bars do not overlap");
        }
    }

    // Distinct stages must be visually distinct.
    check(bar_for(0).rgb != bar_for(1).rgb, "stage colours differ");

    if (failures == 0) {
        std::printf("boot progress core: ok\n");
    }
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
