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
