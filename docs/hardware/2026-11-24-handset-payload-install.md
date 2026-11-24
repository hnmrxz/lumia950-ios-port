# Handset payload install, 2026-11-24

The phone was connected in mass storage mode and its MainOS volume appeared as `F:`. Two things were
installed, each verified by re-reading the file and comparing SHA-256.

## EFIESP: the EFI chain (authorized by the owner)

```
EFI/BOOT/BOOTAA64.EFI          94,208 bytes   (UniXNU payload from out/payload)
EFI/UniXNU/UniXNU.efi          94,208 bytes
EFI/UniXNU/unixnu.toml          2,093 bytes
EFI/UniXNU/Drivers/DarwinBoot.efi
```

The stock loader (`EFI/boot/bootarm.efi`, sha256 `e003475624d4...`) and `EFI/Microsoft/BOOT/BCD`
were **not** touched; copies are in `backups/efiesp-2026-11-24/` beside the checkout.

## MainOS (`F:`): the kernel and its device tree

`F:\EFI\UniXNU\Payloads\` (this is the `--payload-out` split: the kernel is about 15 MB here because
EFIESP is 32 MB):

```
kernel.macho        15,298,424 bytes  sha256 0971d92117b870c9...   run 45316730384, lumia950-kernel-source
kernel.macho.adt        12,716 bytes  sha256 ea230557dd66e375...   make-lumia950-adt.py, dram 0xc0000000 at 0x80000000, 6 CPUs
SHA256SUMS.txt             152 bytes
```

Replaced files, if any, are kept in `F:\EFI\UniXNU\Payloads.previous`.

## What this image is, and is not

It is this repository's own compile of open-source XNU (`mach.development.bcm2837`) from
CI run 45316730384 plus its in-tree drivers. It is **not** the prelinked image: the prelink closure
merges Apple kernelcache kexts and is never uploaded from this repository, so with this payload the
kernel has no Apple kext set to load. The emulated boot of the same source kernel reaches
`dlil_init` after `bsd_init` returns (docs/ci/RUNS.md, run 45314032032), but the handset boot is
unverified and is expected to stop earlier than that.

Rollback: write the copies in `backups/efiesp-2026-11-24/` back to their paths and delete
`EFI/UniXNU/` plus `EFI/BOOT/BOOTAA64.EFI` from EFIESP.
