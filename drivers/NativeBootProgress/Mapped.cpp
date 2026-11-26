// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// Is the framebuffer the platform expert reported actually mapped?
//
// The instrument stores into `vinfo.v_baseaddr` from bsd_init. In emulation that page is always mapped, so a store either works
// or the run is broken for a different reason. On the handset it need not be: a store to an unmapped address is a synchronous
// exception, and the kernel would die *because of the instrument*, which would read as "the kernel did not start".
//
// The check uses the kernel's own page tables, so it answers the question the store would answer -- without the store. When the
// page is not mapped the instrument says so and draws nothing, which turns a possible panic into a log line.
//
// This lives in its own unit because it is the only file here that includes an arm pmap header; the host preflight compiles
// NativeBootProgress.cpp with nothing but the repository on its include path, and the host tests link it without this file (the
// declaration there is weak, so it is null on a host build).

#include <arm/pmap.h>

extern "C" bool
native_boot_progress_ready(const void *base, unsigned long stride, unsigned long height)
{
    if (base == nullptr || stride == 0 || height == 0) {
        return false;
    }
    const addr64_t first = reinterpret_cast<addr64_t>(base);
    const addr64_t last = first + static_cast<addr64_t>(stride) * (static_cast<addr64_t>(height) - 1);
    if (pmap_find_phys(pmap_kernel(), first) == 0) {
        kprintf("lumia: the panel base %p is not mapped; not drawing\n", base);
        return false;
    }
    if (pmap_find_phys(pmap_kernel(), last) == 0) {
        kprintf("lumia: the panel's last row (%p) is not mapped; not drawing\n", reinterpret_cast<const void *>(last));
        return false;
    }
    return true;
}
