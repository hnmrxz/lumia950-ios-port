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

## What the merged image actually does (measured)

An evidence boot of the merged image was made to run, after waiving three checks that describe the
source-built kernel rather than a merged one (provenance, strip verification, the source crypto contract).
It was staged from the ESP the gated assertion had just used, with only `kernel.macho` swapped, so the menu
the fixture expects is the one it accepted.

Result, run 45693593284:

```
real IOKit initialization did not return: ['_panic']
--- merged image: did a storage media appear? ---
(no media line in the merged boot)
```

So the merged image **does load and execute** -- that was the open question for four rounds -- and it panics
during IOKit initialisation, before `!BSD`. Two consequences:

1. the root-device question cannot even be asked of the merged image as it stands;
2. the synthetic media is not in that image anyway, because the archive is still in
   `[kernel.link_excluded]`.

That closes the "maybe the merged image is the place to run the driver" idea in its current form. The route
the board comment names remains the only coherent one: emit the driver as a kext bundle and let the prelink
step merge it, after which its `Info.plist` personality is actually consulted. Doing that needs the prelink
kit's interface (`kits/NativePrelink` is not checked out in this workspace), so it is the next unit of work
rather than something this round could finish.

## The three routes to a root media, after measuring them

| route | what it needs | measured status |
|---|---|---|
| source link + force-load | the archive in `LD_KERNEL_ARCHIVES` | **closed**: run 45706495971 fails the link with undefined `IOBlockStorageDevice::*`; run 45702387021 shows that without the force-load the member is simply not pulled in |
| prelink closure (`XNU_NATIVE_RAM_BLOCK=1`) | on this pin, `XNU_NATIVE_AES=1`, which in turn requires `CRYPTO_BOOTSTRAP_MODE=prelinked` and `XNU_SOURCE_CORECRYPTO14=1` | **blocked**: `prelinked` means the merged image, and that image panics in IOKit here (run 45693593284) before BSD init |
| **source storage (`XNU_SOURCE_STORAGE=1`)** | upstream's `scripts/build-sheng-source-storage.py`, i.e. the storage stack compiled from source, plus a newer framework pin | **not attempted**: this is the route the current upstream uses to make `drivers/RamBlock` legal without the AES closure |

The third row is the interesting one. Upstream's own check says it plainly:

```bash
if [ "$NATIVE_RAM_BLOCK" = 1 ] && [ "${XNU_SOURCE_STORAGE:-0}" != 1 ]; then
    # ... requires the qualified original storage/AES prelink closure
```

With source storage that requirement disappears, because the storage family is compiled into the kernel the
same way `XNU_SOURCE_CORECRYPTO14` compiles corecrypto in. Our pin (`1a01c2a`) predates that path: its script
has no `XNU_SOURCE_STORAGE`, so on this pin the only way to the media is the merged image, which panics.

### What that makes the next unit of work

1. read `scripts/build-sheng-source-storage.py` and the framework's `components.toml` entry for it, to see
   what it compiles and which headers/ABI it assumes;
2. decide whether to move this port's pin to a framework revision that has `XNU_SOURCE_STORAGE`, or to vendor
   that one builder;
3. only then touch `board.toml` again (source storage on, `XNU_NATIVE_RAM_BLOCK=1`, exclusion still in place
   for the source link, since the media would then come from the storage archive itself).

No workflow change was made for this note: the pin question has to be answered before a build can prove
anything.

## Why a source-only kernel cannot mount a root volume

The last route (upstream's `XNU_SOURCE_STORAGE`) turns out not to compile the storage family either. Its own
header says what it compiles, and it is one file plus a metaclass tweak:

> The original IOStorageFamily and APFS stay in the kernel collection. Only the public
> IOBlockStorageDevice implementation is compiled here; its metaclass is registered late below the original
> class so the original storage driver can match the source-backed device.

and the code matches that description:

```python
base = out / 'IOBlockStorageDevice.cpp'
original = (storage / 'IOStorageFamily/IOBlockStorageDevice.cpp').read_text()
...
OSDefineMetaClassWithInit(IOBlockStorageDevice, IOService, )
IOBlockStorageDevice::MetaClass::MetaClass()
    : OSMetaClass("UniXNUBlockStorageDevice", native_source_storage_parent(), sizeof(IOBlockStorageDevice)) {}
```

Two things follow, and they settle the emulated branch of this rung:

1. `IOBlockStorageDevice` is a **device** base class. It does not publish media by itself: the Apple
   `IOStorageDriver`/`IOMedia` layer does that, and upstream keeps that layer in the kernel collection.
2. The QEMU boot in this repository uses a **source-only kernel** -- no kernel collection. So even with the
   device class compiled in, nothing would appear as an `IOMedia`, and `vfs_mountroot` would keep waiting.

That is why the emulated branch stops where it stops: BSD initialisation returns, the boot waits for an
`Apple_HFS` media, and no source-only arrangement of this tree changes that. The rung can only advance with a
kernel that has the storage layer in it (a merged image that boots here, which currently panics in IOKit) or
on the handset, where a real block device exists.

Recording this is the point of this note: it is a boundary of the emulated setup, not a missing flag.

## There is no filesystem in the source kernel either

An obvious next idea is to skip the block device altogether and mount a root from memory. It does not work on
this tree, and the reason is in the pinned XNU itself. Searching the tree of `xnu-8796.141.3` (GitHub tree
API, 5329 entries, not truncated) for HFS and for the memory-disk driver gives:

- HFS: only `bsd/net/altq/altq_hfsc.h` and `bsd/net/pktsched/pktsched_hfsc.h` -- those are the HFSC packet
  scheduler, not the filesystem. `bsd/hfs` does not exist in this source drop;
- memory disk: no `bsd/dev/md*` file at all.

Both HFS+ and APFS ship as kernel extensions in this generation, and the memory-disk driver is not part of the
open source kernel either. So a source-only kernel has **no mountable filesystem and no way to create a
device to mount one from**, independently of the storage-driver question.

That closes the last "clever workaround" for the emulated branch: reaching userland needs a kernel that has
the Apple extensions in it -- i.e. the merged image, which currently panics in IOKit here -- or the handset.
