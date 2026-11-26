// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// A control mark for the panel, drawn by the loader side.
//
// The kernel-side instrument cannot work before arm_vm_init: osfmk/arm64/start.s turns the MMU on (line 744) and
// maps only the kernel image, so a store to the framebuffer there is a translation fault on every platform. The
// honest pre-MMU witness therefore has to come from something that already owns a mapping -- firmware running
// before ExitBootServices. This application draws the same three bars the kernel instrument would have drawn, in the
// same place, and then returns to firmware.
//
// Reading it: a mark here proves the panel accepts these coordinates, in these colours, from this loader. A later
// boot of the kernel that shows nothing above the mark therefore means the kernel never reached its first draw,
// rather than "the panel does not take our writes".

#include <Uefi.h>
#include <Protocol/GraphicsOutput.h>

#define BAR_HEIGHT 16u
#define FIRST_BAR_Y 120u
#define BAR_STRIDE 20u

// Colours are carried as red, green, blue and composed according to the GOP's pixel format: a panel that reports
// blue-green-red order packs the same colour the other way round, and a bar written without that check is the wrong
// colour (or invisible against the background) on half the machines in the world.
static const UINT8 kBarColors[3][3] = {
    { 0xE0, 0x30, 0x30 },
    { 0xE0, 0xC0, 0x30 },
    { 0x30, 0xC0, 0x60 },
};

static UINT32
ComposeColor(EFI_GRAPHICS_OUTPUT_PROTOCOL *gop, UINT32 stage)
{
    const UINT8 red = kBarColors[stage][0];
    const UINT8 green = kBarColors[stage][1];
    const UINT8 blue = kBarColors[stage][2];
    switch (gop->Mode->Info->PixelFormat) {
    case PixelRedGreenBlueReserved8BitPerColor:
        return ((UINT32)blue << 16) | ((UINT32)green << 8) | red;
    case PixelBlueGreenRedReserved8BitPerColor:
    default:
        return ((UINT32)red << 16) | ((UINT32)green << 8) | blue;
    }
}

static VOID
FillBar(EFI_GRAPHICS_OUTPUT_PROTOCOL *gop, UINT32 stage)
{
    if (stage >= 3u) {
        return;
    }
    const UINT32 width = gop->Mode->Info->HorizontalResolution;
    const UINT32 height = gop->Mode->Info->VerticalResolution;
    const UINT32 stride = gop->Mode->Info->PixelsPerScanLine;
    const UINT32 top = FIRST_BAR_Y + stage * BAR_STRIDE;
    if (top + BAR_HEIGHT > height) {
        return;
    }
    const UINT32 color = ComposeColor(gop, stage);
    UINT32 *panel = (UINT32 *)(UINTN)gop->Mode->FrameBufferBase;
    for (UINT32 row = top; row < top + BAR_HEIGHT; ++row) {
        UINT32 *line = panel + (UINTN)row * stride;
        for (UINT32 column = 0; column < width; ++column) {
            line[column] = color;
        }
    }
    __asm__ volatile("dsb sy" ::: "memory");
}

static VOID
FlushPanel(EFI_GRAPHICS_OUTPUT_PROTOCOL *gop)
{
    // The panel is write-combined memory: clean the lines this application touched so the bars are actually
    // visible before firmware takes the screen back.
    const UINTN base = (UINTN)gop->Mode->FrameBufferBase;
    const UINTN size = (UINTN)gop->Mode->FrameBufferSize;
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

    FillBar(gop, 0);
    FillBar(gop, 1);
    FlushPanel(gop);
    system_table->ConOut->OutputString(system_table->ConOut,
                                       L"control mark drawn: 2 bars\r\n");
#ifdef CONTROL_MARK_HOLD
    // A test build stays on this screen so a screenshot can be taken; the shipped build returns to the menu.
    for (;;) {
        __asm__ volatile("wfe" ::: "memory");
    }
#endif
    return EFI_SUCCESS;
}

// The CI build links with /entry:UefiMain; a Zig cross build of the same file targets a UEFI subsystem image whose
// default entry symbol is EfiMain, so the application offers both names and neither build needs a rename.
EFI_STATUS
EFIAPI
EfiMain(EFI_HANDLE image_handle, EFI_SYSTEM_TABLE *system_table)
{
    return UefiMain(image_handle, system_table);
}
