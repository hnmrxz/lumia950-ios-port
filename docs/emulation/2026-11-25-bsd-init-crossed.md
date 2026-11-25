# BSD initialisation returns in the emulated boot, 2026-11-25

The kernel stage in QEMU has been stopping at `_skmem_sysctl_init+0x18` for three runs with three ADTs
and three argument sets (`2026-11-24-skmen-sysctl-fault.md`). With the skip from
`ci/skmem-skip.py` compiled into the tree, run
[45587399756](https://github.com/hnmrxz/lumia950-ios-port/actions/runs/45587399756) changes that.

## What the serial log shows

```
[    8.481408]: SK[0]: skmem_region_init   seg_size 16384, md_seg_size 16384, drv_buf_seg_size 65536 [eff 65536], usr_buf_seg_size 16384
[    8.515186]: bsd_autoconf: calling kminit
[   38.682969]: !BSD
[   38.688331]: Waiting on <dict ID="0"><key>IOProviderClass</key><string ID="1">IOMedia</string><key>Content</key><string ID="2">Apple_HFS</string></dict>
[   98.839808]: Still waiting for root device
```

Reading it in order:

1. `skmem_region_init` runs and prints its segment sizes, so the region the old fault lived in is now
   initialised and the sysctl publication is skipped as designed.
2. `bsd_autoconf: calling kminit` is BSD configuration starting.
3. `!BSD` is the fixture's marker that BSD initialisation returned (the guard in the QEMU harness prints it
   when control comes back from `bsd_init`).
4. The kernel then waits for an `IOMedia` provider whose `Content` is `Apple_HFS`, and after a minute
   reports `Still waiting for root device`.

So **BSD initialisation is no longer where this stops**; the boot now reaches the root-device wait, which
is the point where a real root filesystem (or a synthetic one) has to appear.

## What the report says, and why it disagrees

`report.json` records `past_bsd_outcome: panicked` with `fault_elr_symbol: _machine_idle+0xf8` and fault
address `0x0`. That is the idle thread taking a null dereference *while waiting* for the root device,
after the serial log has already printed `!BSD` and the `Apple_HFS` match. The fixture classifies the run
by how the machine stopped, not by how far boot got, so the log is the better evidence here. That
distinction is worth fixing in the fixture: a run that prints `!BSD` and then waits for a root device
should not be reported the same way as one that faults inside BSD.

## What changed in the build

`ci/skmem-skip.py` inserts, as the first statement of `skmem_sysctl_init`:

```c
if (skmem_sysctl_skip_requested()) {
	return;
}
```

with `skmem_sysctl_skip_requested()` parsing the `skmem_sysctl_skip` boot argument (already present in the
job's argument list) and `#include <pexpert/pexpert.h>` added at the top. The job applies the edit after
the source tree exists and re-checks it before compiling, and the compile is clean: the first attempt
failed because the helper was inserted between `__private_extern__ void` and `skmem_sysctl_init(`, and the
patcher now refuses any insertion that is not at file scope.

## Where the next rung is

The boot now wants an `IOMedia` with `Content = Apple_HFS`. In this port that provider can come from two
directions:

- a native storage driver exposing a block device whose media claims HFS content, or
- a synthetic in-memory provider for bring-up, which would let `vfs_mountroot` proceed before the eMMC path
  exists.

Either way the next measurement is `_vfs_mountroot`, which has never been reached.
