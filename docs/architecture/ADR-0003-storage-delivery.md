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

## M4 -- load the driver as a kext from memory (added after reading the pinned kernel)

The pinned kernel carries the kext loader, so the driver does not have to be linked into the image at all:

```c
// libkern/libkern/c++/OSKext.h, xnu-8796.141.3
static OSReturn loadFromMkext(
    OSKextLogSpec   clientLogSpec,
    char          * mkextBuffer,
    uint32_t        mkextBufferLength,
    char         ** logInfoOut,
    uint32_t      * logInfoLengthOut);
```

and the container format is defined in the same tree (`libkern/libkern/mkext.h`):

| field | value |
|---|---|
| magic / signature | `'MKXT'` (`0x4D4B5854`) / `'MOSX'` (`0x4D4F5358`) |
| version 2 | `0x02002001` |
| integrity | adler32 over the image |
| byte order | all header fields big-endian (`OSSwapBigToHostInt32`) |
| info dictionaries key | `_MKEXTInfoDictionaries` |

That turns M1's "someone else must teach the prelink about our kext" into something this repository can do alone:

1. build `NativeSdhci` as a **kext Mach-O** in the macOS kernel job (the archive recipe already compiles the
   sources; the kext link is `ld -kext` with the same objects);
2. pack a one-kext mkext with a small Python tool (pure computation, testable on the host);
3. embed the bytes in the kernel image as a generated C array, force-loaded like any other device archive;
4. call `OSKext::loadFromMkext(...)` at `bsd_init` **before** `vfs_mountroot`, then let the existing personality
   (`IOClass=NativeSdhci`, `IOProviderClass=IOPlatformDevice`, `IONameMatch=qcom,msm8994-sdhci`) match the ADT node.

Why this is the first attempt:

- it is additive -- nothing about the source link, the prelink roots or Apple's kexts changes;
- it is testable without the phone: the packer is host-testable, and the emulator can tell us whether the kext loads
  and matches before any hardware is involved;
- it fails cheaply and visibly (a load failure returns an `OSReturn` and logs).

What has to be checked before trusting it, in this order:

1. does the DEVELOPMENT kernel allow kext loading at all (`kern.kext` restrictions, signature enforcement) in this
   configuration? If not, the boot-arg for kext developer mode decides it, and that is a one-line experiment;
2. does `loadFromMkext` reject unsigned kexts at this pin? The emulator answers this the same way;
3. only then: does the driver find its ADT node and publish a medium.

If any of the three fails in a way we cannot change from this repository, M1 (prelink-side support) becomes the only
path and ADR-0004 (pin migration) has to be decided first.

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

### M4 status: the kext exists and the container is packed

The macOS job now produces both halves on every kernel run:

```
NativeSdhci: arm64 kext bundle, 645 symbols, segments ['__DATA', '__DATA_CONST', '__LINKEDIT',
             '__TEXT', '__TEXT_EXEC']
NativeSdhci.mkext: 95,462 bytes, plist at 94,208, checksum 0x13D34362
```

Four link iterations got there, and each one named its own cause: the step first ran before the XNU build had a compile
record, then linked macOS against iOS objects, then asked `ld` to keep `_kmod_start` (KMOD_EXPLICIT_DECL stores the
start routine as a value inside `kmod_info`, so only `_kmod_info` exists), and finally the record was dropped as dead
code until `-u _kmod_info` held it.

What remains for M4 is the load itself: embed the container in the kernel image, call
`OSKext::loadFromMkext(0, buffer, length, NULL, NULL)` from `bsd_init` behind a switch, and see whether the personality
matches `sdhci@f9824900`.
