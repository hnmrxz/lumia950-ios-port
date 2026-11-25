# Root device for the emulated boot: design before code

The guarded run returns from BSD initialisation and then waits:

```
[   38.682969]: !BSD
[   38.688331]: Waiting on <dict ID="0"><key>IOProviderClass</key><string ID="1">IOMedia</string><key>Content</key><string ID="2">Apple_HFS</string></dict>
[   98.839808]: Still waiting for root device
```

`docs/emulation/2026-11-25-bsd-init-crossed.md` records that. This page decides what to build so the next
rung — `_vfs_mountroot` — can be measured at all.

## What the kernel is actually asking for

`vfs_mountroot()` has no root spec, so BSD asks the IORegistry for an `IOMedia` whose `Content` is
`Apple_HFS`, then reads block 0 through the `IOStorage` interface that media exposes. Two things must
therefore exist:

1. an object in the registry of class `IOMedia` with the content hint set, and
2. an implementation of `read` reachable from that object.

`board.toml` has a commented line naming `NativeRamBlock` ("Data volume; also needs the virtio bindings
builder"), but `drivers/` has no such directory: the driver does not exist yet.

## Option A — synthetic media inside the kernel (chosen for the next rung)

Subclass `IOMedia`, keep a caller-provided buffer, implement `read`/`write` (and the `IOStorage`
completion forms) against that buffer, and publish `kIOMediaContentKey = "Apple_HFS"` plus a block size and
block count. Attach it under the platform expert so it is in the registry before `vfs_mountroot` runs.

Why this first:

- it removes the storage stack from the experiment, so a failure is about VFS and not about eMMC;
- it needs no device tree, clock, power or interrupt resources, which is exactly the list this repository
  requires a driver to record and prove;
- the same object becomes the test double for the native path later.

Costs and honesty about them:

- the buffer must contain something HFS-shaped for `mount` to succeed; a zero buffer gets `vfs_mountroot`
  *called*, which is itself the measurement, but then fails in `hfs_mountfs`;
- an in-kernel image is memory we cannot spare on the handset (the UEFI environment reports far less free
  memory than QEMU's 768 MB), so this is a bring-up device, not a shipping one;
- subclassing `IOMedia` means linking against IOStorageFamily, which `board.toml` already documents as
  resolvable only after the prelink merge — the same constraint `NativeSdhci` has.

## Option B — virtio-blk in QEMU

Attach an HFS+ image to QEMU and let a virtio driver provide the media. Attractive because the image is a
real filesystem, and QEMU's `virt` machine already has the transport. Blocked by the same fact as
`NativeRamBlock`: this port has no virtio bindings and no driver; the comment in `board.toml` says as much.

## Option C — NativeSdhci read path

The honest long-term answer, and the one that also serves the handset. Today `NativeSdhci` has host tests
and an ABI compile, not a working eMMC read on this device (`docs/state.md`). Nothing in the root-device
work should pretend otherwise.

## What the next change will contain

| item | value |
|---|---|
| file | `drivers/NativeRamBlock/NativeRamBlock.cpp` (+ `.h`, `Info.plist`) |
| superclass | `IOMedia`, IOStorageFamily |
| matching | published by the driver's own `start()` under the platform expert; no `IOPlatformDevice` match |
| resources | none: no MMIO, no clock, no power domain, no interrupt |
| buffer | `IOMallocContiguous`, size from a boot argument (`ramblock_bytes`), so QEMU and handset differ only in the argument |
| content | `Apple_HFS`, block size 512, block count = bytes / 512 |
| archive | `build-arm-driver.py NativeRamBlock`, listed in `board.toml` only after it compiles |
| tests | host test for the geometry and content-hint logic; ABI compile in the `kernel` job; registry presence from the QEMU serial log |
| evidence label | `ABI-compiled` then `QEMU-tested` when the log shows the media matching |

## The measurement that decides whether this worked

`_vfs_mountroot` is watched by the fixture already (`watched: {"_vfs_mountroot": …}`). Success for this
rung is that the report shows `root_device_wait_observed` false and `_vfs_mountroot` true, or that the
serial log moves from `Still waiting for root device` to an HFS mount attempt.

## Deliberately out of scope

- a real HFS+ volume with anything in it (userland needs one later, not this rung);
- persistence, write-back, or power management;
- claiming display or userland progress from a mount attempt.

## Status: the IOKit half is written, not yet compiled

`drivers/NativeRamBlock/` now holds `RamBlockCore` (host tested in CI, 16 assertions), `NativeRamBlock.h`
and `NativeRamBlock.cpp` (an `IOMedia` subclass that allocates a contiguous buffer sized by
`ramblock_bytes`, sets `kIOMediaContentKey` to `Apple_HFS`, publishes itself, and serves read/write from
the buffer through the IOStorage completion interface), plus `Info.plist`.

It is deliberately **not** in `board.toml`'s driver list yet, so the kernel job does not compile it. The
next step is to add it there and accept a red kernel job as the price of finding out what the IOStorageFamily
ABI actually requires -- the same loop NativeSdhci went through. Anything claimed about the media appearing
in QEMU is premature until that compile is green.

## Correction: personalities do not start anything here

Two personalities were tried (`IOPlatformExpertDevice` named "platform", then `IOResources`) and neither
produced a single `NativeRamBlock` log line in the emulated boot. The reason is in this repository's own
arrangement: drivers are **link inputs to the kernel**, not loadable kexts. `board.toml` says as much about
`NativeLegacyDisplay` -- "Link input, not a driver: upstream calls `native_legacy_display_probe()` from
`bsd_init.c`". A source-linked class has no kext bundle, so its `Info.plist` personalities are never
consulted and nothing matches it.

What the next rung therefore needs is an explicit start hook, the same pattern the display probe already
uses: an `extern "C"` entry point that creates the instance, attaches it to a provider that exists in the
boot, and publishes it, called from a place in XNU that runs before `vfs_mountroot` waits. That is a source
patch of the kind `ci/skmem-skip.py` already demonstrates, and it must be verified by the log line rather
than assumed.

## The two boot images, and which one can carry a root media

The kernel job produces two images and they are not interchangeable for this rung:

| image | what it is | can it carry a storage device |
|---|---|---|
| `build/xnu/ios-obj/.../mach.development.bcm2837.unstripped` | this repository's own compile of the open-source XNU plus the in-tree drivers | **no**: `board.toml` excludes archives that subclass `IOStorageFamily`, because that family only exists after the merge |
| `*/kernel/kernel.macho` | the prelinked image, with the pinned 16.7.16 kernelcache's extensions merged in | **possibly**: the families those drivers need are present there |

The QEMU assertion boots the first. Three experiments established what that implies: a
`bsd_init`-time call to the synthetic media cannot link there (`_native_ramblock_publish` unresolved, and
this `ld` rejects weak undefined references too), so the media rung cannot be measured on the source
kernel at all. The job therefore boots the merged image a second time as **evidence only**, staged by the
project's own stager, and prints whether any media line appears. Whether the merged image is even loadable
by the current QEMU setup is itself part of what that boot reports.

## What the prelink roots already say

`board.toml`'s `[kernel.prelink] roots` list contains `com.apple.iokit.IOStorageFamily`. So the merged image
does carry the family that a storage driver needs -- the source kernel does not, which is why the archive is
excluded from it.

That changes the shape of the fix. The board's own comment next to `[kernel.link_excluded]` states it:

> Until the driver is emitted as a kext bundle and merged by the prelink step, it is built and checked but
> not in the image.

So the path to a root media is not "call the driver from `bsd_init`" (impossible in the source link, as three
experiments showed) and not "another personality in the source build" (personalities are never read there).
It is: **emit `NativeRamBlock` as a kext bundle, let the prelink step merge it, and let the framework match
it there** -- in that arrangement the personality *is* consulted, because a merged kext is a real kext.

What that requires, in order:

1. a bundle layout the prelink step accepts for an in-tree driver (executable + `Info.plist`);
2. an entry in the board/prelink configuration that merges it into the image;
3. the personality to name the class and a provider that exists in that image;
4. the serial log to show `NativeRamBlock: starting`, then an `Apple_HFS` media.
