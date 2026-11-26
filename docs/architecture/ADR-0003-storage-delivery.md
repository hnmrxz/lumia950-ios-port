# ADR-0003: how a storage driver can reach this kernel at the pinned framework revision

Status: proposed, with the evidence that makes it decidable
Date: 2026-11-26

## Context

The objective needs `bsd_init` to finish, and that needs a root volume. A root volume needs a block device. This
port has a block-device driver (`drivers/NativeSdhci`, host-tested, ABI-compiled) that cannot be linked into the
kernel, and `board.toml` records why:

```toml
[kernel.link_excluded]
NativeSdhci     = "subclasses IOBlockStorageDevice from IOStorageFamily, which only exists after the prelink merge"
NativeRamBlock  = "subclasses IOBlockStorageDevice from IOStorageFamily, which only exists after the prelink merge"
```

Two facts decided the question of whether a kext bundle can fix that at this revision:

1. `[kernel.prelink] roots` lists **Apple bundle identifiers** (`com.apple.iokit.IOStorageFamily`, ...), not paths.
2. The prelink tool at the pinned submodule (`UniXNU/NativePrelink@2b6ffb50`, `emit_prelink.py`) takes `--kernel`,
   `--prelinked`, repeated `--root`, `--slide`, `--output` and `--early-security-init`. There is **no option that
   adds a kext of our own**; roots are looked up in the original image's `_PrelinkInfoDictionary`
   (`entries = {e['CFBundleIdentifier']: e for e in metadata['_PrelinkInfoDictionary']}`).

So a driver built in this repository can only reach the image through the **source link**, and the source link has
no IOStorageFamily. That is the wall, and it is not a matter of finishing the driver.

## Options

**M1 -- kext bundle merged by the prelink step.** The strategic answer: our driver becomes a bundle with an
`Info.plist` personality, and the prelink merges it next to Apple's kexts.
Cost: the pinned prelink cannot do it, so this needs either a newer framework with third-party kext support or a
patch to `emit_prelink.py` in this repository. Neither is a device-port change, and both need the framework owner.

**M2 -- stop subclassing IOStorageFamily.** Provide our own minimal block-device surface and publish it without
Apple's superclass, calling it from `bsd_init` the way `ramblock-hook.py` already calls
`native_ramblock_publish`. Cost: `vfs_mountroot` expects the IOKit media chain (`IOMedia` -> `IOBlockStorageDevice`
-> driver); replacing it means reimplementing the contract the VFS mounts through, which is a filesystem-adjacent
project, not a driver.

**M3 -- move the pin to a framework where the prelink accepts device kexts.** Cost: every paid baseline
(45314032032, 45587399756, 45706495971) becomes unusable, and the pin's XNU patch set has to be re-derived. It buys
one thing: a supported path for our kext.

## Decision (proposed)

Try M1 first, because it is the only option that keeps the driver and the OS contract as they are, and it fails
loudly and cheaply (the prelink either accepts a bundle path or does not). Concretely:

1. Add a `--kext` path to `emit_prelink.py` **in this repository** as a wrapper, or ask the framework for it: the
   tool already builds a `_PrelinkInfoDictionary`; appending one entry plus its Mach-O is mechanical.
2. Build `NativeSdhci` as a bundle: `NativeSdhci` binary + `Info.plist` with the personality already written
   (`IOClass=NativeSdhci`, `IOProviderClass=IOPlatformDevice`, `IONameMatch=qcom,msm8994-sdhci`).
3. Verify with `check-kernel-link.py --check-personalities` and the existing prelink assertions.

Do **not** start M2 and M1 together: they solve the same problem in incompatible ways.

## Consequence that outlives this decision

Even with a working block device there is **no Apple-format root volume on the device**: MainOS is NTFS (29.5 GB)
and EFIESP is FAT (32 MB). APFS/HFS support arrives as *code* in the kernel image, not as a *volume*. Creating one
means repartitioning (destroys Windows on the device) or writing an FFU this toolchain cannot generate. That is
ADR-0005, and it changes the rollback contract, so it must be decided before any work that assumes a mounted root.

## Evidence

- `board.toml` `[kernel.link_excluded]`, `[kernel.prelink] roots`
- `UniXNU/NativePrelink@2b6ffb50 emit_prelink.py` argument list and `_PrelinkInfoDictionary` lookup
- `docs/emulation/emulated-branch-limits.md` (why the emulator cannot reach userland either)
- `ci/ramblock-hook.py` (the hook pattern M2 would have to extend)
