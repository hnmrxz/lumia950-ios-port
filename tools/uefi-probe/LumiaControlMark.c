// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// A control mark for the panel, drawn by the loader side, that also writes the mode it found onto the screen.
//
// The kernel-side instrument cannot work before arm_vm_init: osfmk/arm64/start.s turns the MMU on (line 744) and
// maps only the kernel image, so a store to the framebuffer there is a translation fault on every platform. The
// honest pre-MMU witness therefore has to come from something that already owns a mapping -- firmware running before
// ExitBootServices.
//
// Two bars prove the panel accepts these coordinates and colours from this loader. The text says which mode the
// firmware actually reported, so a failure is diagnosable without a second trip: if the bars are missing but the
// text is there, the coordinates or the pixel format are wrong; if nothing at all is visible, the panel is not being
// written at all.

#include <Uefi.h>
#include <Protocol/GraphicsOutput.h>

#include "FramebufferCore.h"
#include "ProbeCore.h"

#define BAR_HEIGHT 16u
#define FIRST_BAR_Y 120u
#define BAR_STRIDE 20u

static const UINT8 kBarColors[3][3] = {
    { 0xE0, 0x30, 0x30 },
    { 0xE0, 0xC0, 0x30 },
    { 0x30, 0xC0, 0x60 },
};

static void
Describe(struct ProbeFramebuffer *framebuffer, EFI_GRAPHICS_OUTPUT_PROTOCOL *gop)
{
    framebuffer->base = gop->Mode->FrameBufferBase;
    framebuffer->byte_size = gop->Mode->FrameBufferSize;
    framebuffer->width = gop->Mode->Info->HorizontalResolution;
    framebuffer->height = gop->Mode->Info->VerticalResolution;
    framebuffer->stride = gop->Mode->Info->PixelsPerScanLine;
    framebuffer->pixel_format = (uint32_t)gop->Mode->Info->PixelFormat;
}

static UINT32
ComposeColor(uint32_t pixel_format, UINT32 stage)
{
    return ProbeFramebufferColor(pixel_format, kBarColors[stage][0], kBarColors[stage][1], kBarColors[stage][2]);
}

static VOID
FlushPanel(const struct ProbeFramebuffer *framebuffer)
{
    // The panel is write-combined memory: clean the lines this application touched so the bars are actually
    // visible before firmware takes the screen back.
    const UINTN base = (UINTN)framebuffer->base;
    const UINTN size = (UINTN)framebuffer->byte_size;
    UINT64 cache_type = 0;
    __asm__ volatile("mrs %0, ctr_el0" : "=r"(cache_type));
    const UINTN line = 4u << ((cache_type >> 16) & 15u);
    for (UINTN address = base & ~(line - 1u); address < base + size; address += line) {
        __asm__ volatile("dc cvac, %0" ::"r"(address) : "memory");
    }
    __asm__ volatile("dsb sy" ::: "memory");
}

EFI_STATUS
EFIAPI
UefiMain(EFI_HANDLE image_handle, EFI_SYSTEM_TABLE *system_table)
{
    (void)image_handle;
    EFI_GRAPHICS_OUTPUT_PROTOCOL *gop = NULL;
    EFI_GUID gop_guid = EFI_GRAPHICS_OUTPUT_PROTOCOL_GUID;
    EFI_STATUS status = system_table->BootServices->LocateProtocol(&gop_guid, NULL, (VOID **)&gop);
    if (EFI_ERROR(status) || gop == NULL || gop->Mode == NULL) {
        return EFI_NOT_FOUND;
    }

    struct ProbeFramebuffer framebuffer;
    Describe(&framebuffer, gop);
    if (!ProbeFramebufferValid(&framebuffer)) {
        return EFI_DEVICE_ERROR;
    }

    for (UINT32 stage = 0; stage < 2; ++stage) {
        const UINT32 top = FIRST_BAR_Y + stage * BAR_STRIDE;
        if (top + BAR_HEIGHT <= framebuffer.height) {
            ProbeFillRectangle(&framebuffer, 0, top, framebuffer.width, BAR_HEIGHT,
                               ComposeColor(framebuffer.pixel_format, stage));
        }
    }

    // The mode, written on the panel itself so a photograph carries it even when nothing else works.
    char line[64];
    const UINT32 text_color = ProbeFramebufferColor(framebuffer.pixel_format, 0xFF, 0xFF, 0xFF);
    if (ProbeFormatUnsigned(framebuffer.width, 10, 1, line, sizeof(line))) {
        ProbeDrawText(&framebuffer, 24, 200, 3, line, text_color);
    }
    if (ProbeFormatUnsigned(framebuffer.height, 10, 1, line, sizeof(line))) {
        ProbeDrawText(&framebuffer, 24, 236, 3, line, text_color);
    }
    if (ProbeFormatUnsigned(framebuffer.stride, 10, 1, line, sizeof(line))) {
        ProbeDrawText(&framebuffer, 24, 272, 3, line, text_color);
    }
    if (ProbeFormatUnsigned(framebuffer.pixel_format, 10, 1, line, sizeof(line))) {
        ProbeDrawText(&framebuffer, 24, 308, 3, line, text_color);
    }
    if (ProbeFormatUnsigned(framebuffer.base, 16, 1, line, sizeof(line))) {
        ProbeDrawText(&framebuffer, 24, 344, 3, line, text_color);
    }

    // The registers the kernel's early boot depends on, read here at EL1 where they are readable. A hang before the kernel can
    // print is otherwise invisible: this panel is the only place these values can be seen. CNTFRQ_EL0 matters most -- a firmware
    // that leaves it zero would give the kernel a zero timebase, and the handset's own value has never been recorded here.
    {
        UINT64 cntfrq = 0, midr = 0, mpidr = 0, currentel = 0, sctlr = 0, tcr = 0, ttbr0 = 0, ttbr1 = 0;
        __asm__ volatile("mrs %0, CNTFRQ_EL0" : "=r"(cntfrq));
        __asm__ volatile("mrs %0, MIDR_EL1" : "=r"(midr));
        __asm__ volatile("mrs %0, MPIDR_EL1" : "=r"(mpidr));
        __asm__ volatile("mrs %0, CurrentEL" : "=r"(currentel));
        __asm__ volatile("mrs %0, SCTLR_EL1" : "=r"(sctlr));
        __asm__ volatile("mrs %0, TCR_EL1" : "=r"(tcr));
        __asm__ volatile("mrs %0, TTBR0_EL1" : "=r"(ttbr0));
        __asm__ volatile("mrs %0, TTBR1_EL1" : "=r"(ttbr1));

        UINT32 y = 380;
        ProbeDrawText(&framebuffer, 24, y, 2, "CNTFRQ", text_color);
        if (ProbeFormatUnsigned(cntfrq, 16, 1, line, sizeof(line))) {
            ProbeDrawText(&framebuffer, 24 + 7 * 24, y, 2, line, text_color);
        }
        y += 32;
        ProbeDrawText(&framebuffer, 24, y, 2, "MIDR", text_color);
        if (ProbeFormatUnsigned(midr, 16, 1, line, sizeof(line))) {
            ProbeDrawText(&framebuffer, 24 + 7 * 24, y, 2, line, text_color);
        }
        y += 32;
        ProbeDrawText(&framebuffer, 24, y, 2, "MPIDR", text_color);
        if (ProbeFormatUnsigned(mpidr, 16, 1, line, sizeof(line))) {
            ProbeDrawText(&framebuffer, 24 + 7 * 24, y, 2, line, text_color);
        }
        y += 32;
        ProbeDrawText(&framebuffer, 24, y, 2, "CURRL", text_color);
        if (ProbeFormatUnsigned(currentel, 16, 1, line, sizeof(line))) {
            ProbeDrawText(&framebuffer, 24 + 7 * 24, y, 2, line, text_color);
        }
        y += 32;
        ProbeDrawText(&framebuffer, 24, y, 2, "SCTLR", text_color);
        if (ProbeFormatUnsigned(sctlr, 16, 1, line, sizeof(line))) {
            ProbeDrawText(&framebuffer, 24 + 7 * 24, y, 2, line, text_color);
        }
        y += 32;
        ProbeDrawText(&framebuffer, 24, y, 2, "TCR", text_color);
        if (ProbeFormatUnsigned(tcr, 16, 1, line, sizeof(line))) {
            ProbeDrawText(&framebuffer, 24 + 7 * 24, y, 2, line, text_color);
        }
        y += 32;
        ProbeDrawText(&framebuffer, 24, y, 2, "TTBR0", text_color);
        if (ProbeFormatUnsigned(ttbr0, 16, 1, line, sizeof(line))) {
            ProbeDrawText(&framebuffer, 24 + 7 * 24, y, 2, line, text_color);
        }
        y += 32;
        ProbeDrawText(&framebuffer, 24, y, 2, "TTBR1", text_color);
        if (ProbeFormatUnsigned(ttbr1, 16, 1, line, sizeof(line))) {
            ProbeDrawText(&framebuffer, 24 + 7 * 24, y, 2, line, text_color);
        }
    }

    FlushPanel(&framebuffer);
    system_table->ConOut->OutputString(system_table->ConOut,
                                       L"control mark drawn\r\n");
#ifdef CONTROL_MARK_HOLD
    for (;;) {
        __asm__ volatile("wfe" ::: "memory");
    }
#endif
    return EFI_SUCCESS;
}

EFI_STATUS
EFIAPI
EfiMain(EFI_HANDLE image_handle, EFI_SYSTEM_TABLE *system_table)
{
    return UefiMain(image_handle, system_table);
}
