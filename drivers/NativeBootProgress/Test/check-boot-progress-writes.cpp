// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Host test for the store path, not just the geometry: the same NativeBootProgress.cpp is compiled for this
// machine and asked to draw into a heap buffer that looks like the handset panel. That answers two questions
// without a phone or a kernel build --
//
//   * does a command line carrying "lumia-bars" actually put pixels on the rows the core says, and
//   * does a command line without it leave the buffer untouched (the QEMU gate depends on that).

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "BootProgressCore.h"

extern "C" void native_boot_progress_stage(void *base, unsigned long stride, unsigned long height,
                                           const char *command_line, int stage);

namespace {

int failures = 0;

void *
panel_buffer(std::vector<uint32_t> &panel)
{
    return panel.data();
}

void
check(bool condition, const char *what)
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
    const uint32_t width = 1080u;
    const uint32_t height = 1920u;
    const unsigned long stride = 4320u;
    std::vector<uint32_t> panel(static_cast<size_t>(stride / 4u) * height, 0u);
    const uint32_t *pixels = panel.data();

    // The switch is absent: nothing may be written. The QEMU gate boots with '-v cpus=1' and relies on this.
    native_boot_progress_stage(panel_buffer(panel), stride, height, "-v cpus=1", 0);
    bool untouched = true;
    for (uint32_t value : panel) {
        if (value != 0u) {
            untouched = false;
            break;
        }
    }
    check(untouched, "no bars without the switch");

    // The switch is present: stage 0 draws the first bar where the core says, and nothing above it.
    native_boot_progress_stage(panel_buffer(panel), stride, height,
                               "-v cpus=1 lumia-bars", 0);
    const boot_progress::Rect bar = boot_progress::bar_for(0, width, height);
    bool bar_filled = true;
    for (uint32_t row = bar.y; row < bar.y + bar.height; ++row) {
        const uint32_t *line = reinterpret_cast<const uint32_t *>(reinterpret_cast<const uint8_t *>(pixels) +
                                                                   static_cast<size_t>(row) * stride);
        for (uint32_t column = 0; column < width; ++column) {
            if (line[column] != bar.rgb) {
                bar_filled = false;
            }
        }
    }
    check(bar_filled, "stage 0 fills the bar the core describes");

    const uint32_t *first_row =
        reinterpret_cast<const uint32_t *>(reinterpret_cast<const uint8_t *>(pixels) + 0u);
    bool nothing_above = true;
    for (uint32_t column = 0; column < width; ++column) {
        if (first_row[column] == bar.rgb) {
            nothing_above = false;
        }
    }
    check(nothing_above, "nothing is drawn above the first bar");

    // Stage 1 must land on the next bar and keep stage 0's colour, so a photo can count them.
    native_boot_progress_stage(panel_buffer(panel), stride, height,
                               "lumia-bars", 1);
    const boot_progress::Rect second = boot_progress::bar_for(1, width, height);
    const uint32_t *second_row =
        reinterpret_cast<const uint32_t *>(reinterpret_cast<const uint8_t *>(pixels) +
                                           static_cast<size_t>(second.y) * stride);
    check(second_row[0] == second.rgb, "stage 1 draws its own bar");
    check(second.rgb != bar.rgb, "the two bars are different colours");

    // A zero base must be refused rather than written through.
    native_boot_progress_stage(nullptr, stride, height, "lumia-bars", 0);
    check(true, "a zero base is ignored");

    if (failures == 0) {
        std::printf("boot progress writes: ok\n");
    }
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
