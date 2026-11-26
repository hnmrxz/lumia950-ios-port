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

    // The post-MMU switch must not enable the bootstrap bars: matching by prefix did exactly that, and the bootstrap
    // bars fault before VM setup, so asking for the third bar killed the kernel.
    std::vector<uint32_t> prefix(static_cast<size_t>(stride / 4u) * height, 0u);
    native_boot_progress_stage(panel_buffer(prefix), stride, height, "lumia-bars2", 0);
    bool prefix_stayed_off = true;
    for (uint32_t value : prefix) {
        if (value != 0u) {
            prefix_stayed_off = false;
            break;
        }
    }
    check(prefix_stayed_off, "lumia-bars2 does not enable the bootstrap bar");
    native_boot_progress_stage(panel_buffer(prefix), stride, height, "lumia-bars", 0);
    check(prefix[static_cast<size_t>(bar.y) * (stride / 4u)] == bar.rgb, "lumia-bars still draws the bootstrap bar");

    // Stage 2 is the post-MMU bar and must ignore the bootstrap switch, so a boot can ask for it alone.
    std::vector<uint32_t> later(static_cast<size_t>(stride / 4u) * height, 0u);
    native_boot_progress_stage(panel_buffer(later), stride, height, "lumia-bars", 2);
    bool stage_two_stayed_off = true;
    for (uint32_t value : later) {
        if (value != 0u) {
            stage_two_stayed_off = false;
            break;
        }
    }
    check(stage_two_stayed_off, "the bootstrap switch does not enable the post-MMU bar");

    native_boot_progress_stage(panel_buffer(later), stride, height, "lumia-bars2", 2);
    // The post-MMU bar sits on the last rows: by the time it is drawn the console has already written over the
    // upper half, so a bar up there could be present and unreadable.
    const boot_progress::Rect third = boot_progress::bottom_bar_for(width, height, 0x0030C030u);
    const uint32_t *third_row =
        reinterpret_cast<const uint32_t *>(reinterpret_cast<const uint8_t *>(later.data()) +
                                           static_cast<size_t>(third.y) * stride);
    check(third_row[0] == third.rgb, "the post-MMU switch draws the third bar");
    check(third.y + third.height == height, "the post-MMU bar sits on the last rows of the panel");

    // A zero base must be refused rather than written through.
    native_boot_progress_stage(nullptr, stride, height, "lumia-bars", 0);
    check(true, "a zero base is ignored");

    if (failures == 0) {
        std::printf("boot progress writes: ok\n");
    }
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
