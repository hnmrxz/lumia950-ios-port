# What the emulated branch can and cannot reach

This file is the judgement to read before trying another idea in QEMU. Every line below has a run or a source
search behind it; the point is to stop re-measuring the same walls.

## What is established

| fact | evidence |
|---|---|
| BSD initialisation **returns** on the source-built kernel | two runs, `past_bsd_outcome = root-wait`, `docs/emulation/2026-11-25-bsd-init-crossed.md` |
| the boot then waits for an `IOMedia` with `Content = Apple_HFS` | serial: `Still waiting for root device` after `!BSD` |
| `_vfs_mountroot` is never reached | report milestone list + `summarize-xnu-entry.py` |
| the source link has **no storage classes** | force-loading `NativeRamBlock` fails with undefined `IOBlockStorageDevice::*` (run 45706495971); without force-load the member is simply not pulled in (run 45702387021) |
| the source kernel has **no filesystem and no memory disk** | `xnu-8796.141.3` tree search: no `bsd/hfs`, no `bsd/dev/md*`; HFS+/APFS ship as extensions in this generation |
| the merged image **goes silent after the hand-off** | serial of run 45715174239 ends at `hand-off to the kernel`, then the fixture's timeout; no kernel line |

## What follows

1. A **root media cannot exist** in the source-only kernel: the device base class is absent, and even with it,
   the `IOStorageDriver`/`IOMedia` layer that publishes media is an extension, not kernel source.
2. A **root filesystem cannot be synthesised** in the source-only kernel either: there is no HFS in this
   source drop and no memory-disk driver, so a ramdisk has nothing to mount from and nothing to mount.
3. The **merged image is unobservable** here: it reaches the kernel hand-off and prints nothing after it. Any
   claim about how far it gets past that point is a symbol-breakpoint inference, not evidence.

## What would change any of it

- a serial line from the merged image after the hand-off (any console driver inside it, or a debug setting for
  it) would turn row 3 back into a measurable question;
- a framework bump that has `XNU_SOURCE_STORAGE` plus the Sheng source storage would give the source kernel the
  device class -- but not the media layer, so row 1 still stands unless the storage stack comes with it;
- the **handset** has a real block device and a real firmware chain, which is why the deployment route
  (`docs/hardware/post-unlock-runbook.md`) is the live one.

## What is not claimed

`userland-booted`, `hardware-tested`, `EFI-tested` for this chain: none of them. The kernel rung is
`QEMU-tested` up to `bsd_init` returning, and no further.
