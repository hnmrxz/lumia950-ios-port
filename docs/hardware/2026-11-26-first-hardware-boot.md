# First hardware boot of the chain — 2026-11-26

Measured on the handset (RM-1105, Lumia 950, MSM8992) after the Windows-on-ARM deployment finished. Every
line below is from the phone's own screen or from files read back with checksums; nothing here is inferred
from the emulator.

## What the chain did

```
stock firmware                (secure boot on, untouched)
  -> EFI\boot\bootarm.efi     ARM32 bootmgr, firmware's own, untouched
  -> {default} = \EFI\boot\BootShim.efi
                              ARMNT 0x01C4, subsystem 0x10, 53,744 B, sha256 3b3c7a7f676c297b
                              (written by the deployment tool, kept byte for byte)
  -> \UEFI.elf on EFIESP      AArch64 ELF, 1,114,880 B, sha256 00420de94f7a1ff3 (deployment tool's build)
                              reports itself as: LumiaWoA authors 2.16385, UEFI spec 2.70, git 0e7e24ad (2022-09-14)
  -> EFI\BOOT\BOOTAA64.EFI    this port's loader, 94,208 B, subsystem 0x0A, sha256 9d9311b39a252861
  -> UniXNU 0.1.0 menu        config \EFI\UniXNU\unixnu.toml, "drivers 2 loaded / 0 failed  kits 0  acpi 0"
  -> DarwinBoot hand-off      "inputs validated; exiting boot services" / "hand-off to the kernel"
```

The first attempt at this step failed with `Lumia UEFI Menu / Failed to boot OS. No usable boot entry found`,
because the loader had only been written to `EFI\UniXNU\UniXNU.efi`. The custom UEFI starts
`EFI\BOOT\BOOTAA64.EFI`, which is what `handset-boot-chain.md` had said all along; the install simply had not
put a file there. `phone-install.py --loader-alias` now does, and the second boot reached the menu.

## What DarwinBoot reported on the panel

```
DARWINBOOT: payload from another volume     (the kernel is on MainOS, read through the staged NTFS driver)
DARWINBOOT: ARM64 va=0xFFFFFFF004004000 pa=0x27004000 args=0x2BAE8000 entry=0x2ABEC488 owned=0x20000000
DARWINBOOT: video base=0x400000 display=1 row=4320 width=1080 height=1920 depth=32
DARWINBOOT: inputs validated; exiting boot services
DARWINBOOT: hand-off to the kernel
CurrentEL 1   SCTLR_EL1 0xC01B0D   TCR_EL1 0x280003518
ID_AA64MMFR0_EL1 0x1122   (PARange 2, 4 KiB granule supported)
ID_AA64PFR0_EL1  0x2222
```

Two things worth noting against the emulator run: the panel is the real one (**1080x1920, row 4320 bytes,
32 bpp at 0x400000**, matching the firmware's measured GOP) and the kernel was found on **another volume**,
so the NTFS driver staged at `EFI\UniXNU\Drivers\ntfs.efi` did its job.

## The kernel rung on hardware: silence after the hand-off

The screen stayed exactly on the hand-off page (green bar, the DarwinBoot lines, `Exiting boot services. A green
bar across the top marks the loader before branching to XNU.` and did not change again. That is the same
symptom the merged image showed in QEMU, where the serial console also ended at the hand-off.

Two readings are possible and this boot cannot separate them:

1. XNU ran and printed nothing -- the image deployed at this step was the **prelinked** one
   (56,619,008 B, sha256 17866f70195040e8), whose console may not reach this panel;
2. XNU faulted immediately after the branch, with no console to say so.

The next boot swaps in the **source-built** kernel (15,298,424 B, sha256 0001c3fbc1ecb63e, built by the same
CI run and carrying the `skmem_sysctl_skip` guard) because that image is the one this repository has seen print
`arm_vm_init`-era lines and `Still waiting for root device` -- if the panel shows any of that, the kernel rung
is `XNU-entry-tested` on hardware; if the panel stays silent for both images, the next instrument is a
framebuffer write from a driver that runs before anything else.

## Second hardware boot: the source-built kernel is silent too

The prelinked image was not the explanation. Booting the **source-built** kernel on the handset (15,298,424 B,
sha256 0001c3fbc1ecb63e, the image that prints `arm_vm_init` and `!BSD` in QEMU) produced the identical screen:
the hand-off page, unchanged, with `entry words 140006F5`, `CurrentEL 1`, `SCTLR_EL1 0xC0180D`,
`TCR_EL1 0x280803518`, `ID_AA64MMFR0_EL1 0x1122`, `ID_AA64PFR0_EL1 0x2222`, and nothing after it.

So "the merged image simply has no console" is ruled out: two different kernels, one of which demonstrably prints
in the emulator, both print nothing here. What remains is either that the kernel never executes the branch, or
that this panel is not the console either image reaches -- and those two are exactly what an entry probe
separates.

The next image deployed is the green build 45778628055: the same source kernel with the framebuffer instrument
(15,298,536 B, sha256 f2ebcc450f3250aa) and `args = "-v cpus=1 lumia-bars"`, so the bars draw only when that
argument is present. One bar means `arm_init` ran, two means it reached `arm_vm_init`, none means the kernel never
reached `arm_init` at all.

## Why the instrument faults in the emulator and should not fault on the panel

The local QEMU reproduction (Windows host, QEMU 11.1.0, the same staged ESP) stops exactly where CI stopped, and
the archived registers name the instruction: `x9 = 0xe03030` is the bar colour, `x11`/`x13 = 0x6c7fdc00` is the
address being written, and `x1 = 0x96000005` is ESR_EL1. Decoded: EC `0x25` is a data abort taken at the same
exception level, and the fault status `0b000101` is a translation fault at level 1.

So the store is faulting on translation, which means the MMU is already on when `arm_init` runs: XNU's `start.s`
installs a bootstrap identity map before calling into C. That map covers RAM, and in the emulator the panel sits
at 0x6C7A0000, above RAM, so the write is unmapped. On the handset the panel is reported at 0x400000, which lies
inside the DRAM window the ADT declares (0x0 + 0xaf600000), so the same write should be mapped there.

That is the hypothesis the pending handset boot tests. If the bars appear, `arm_init` ran and the mapping
explanation holds; if they do not, the next instrument must map the framebuffer explicitly (pmap) before drawing,
which the official documentation's "entry probe" also implies -- its stage 3 is a reset rather than a draw.

## What is not claimed

- No kernel output had been observed at the time of writing, so **`XNU-entry-tested` is not claimed** for the
  handset; the run stops at the hand-off line on screen.
- `userland-booted`, display from iOS, and anything about iOS itself remain unclaimed.

## Files on the phone after this step

| volume | path | what |
|---|---|---|
| EFIESP `R:` | `EFI\Boot\BOOTAA64.EFI` | this port's loader (added 2026-11-26) |
| EFIESP `R:` | `EFI\UniXNU\{UniXNU.efi, unixnu.toml, Drivers\{DarwinBoot.efi, ntfs.efi}}` | this port's menu tree |
| MainOS `H:` | `EFI\UniXNU\Payloads\{kernel.macho, kernel.macho.adt}` | the kernel and its ADT |
| EFIESP `R:` | `EFI\boot\{bootarm.efi, BootShim.efi}`, `UEFI.elf`, `EFI\Microsoft\BOOT\BCD` | the deployment tool's files, unmodified |

The EFIESP partition image taken before the first write is `out/phone-backups/unlocked-efiesp.img`
(33,554,432 B, sha256 e72bb27d084bcbe8e9a613d3f218e53e0750590a42608a9a980040b1fad05ab4).
