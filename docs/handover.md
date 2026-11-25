# Handover — Lumia 950 (MSM8992) iOS 16.7.16 port, 2026-11-26

What this page is for: someone picking this branch up (including me in a month) needs to know where the work
actually stands, which claims are paid for and which are not, and what the next action is. Everything here is
backed by a run number, a script or a document in this repository.

## Where the work stands

| rung | state | paid for by |
|---|---|---|
| boot chain files (shim, `UEFI.elf`, rEFInd, payload) | installable and rehearsed offline, never booted on hardware | `scripts/rehearse-phone-install.py` |
| boot store (BCD) | checked in three layers, verifiable in the install command | `scripts/check-bcd-layout.py`, `--verify-bcd` |
| rollback | snapshot/restore and FFU recovery rehearsed offline | `scripts/rehearse-phone-rollback.py` |
| kernel build | green, pthread linked, skmem guarded | kernel job, `docs/state.md` |
| kernel boot in QEMU | **returns from BSD initialisation**, then waits for an Apple_HFS media | run 45587399756, `docs/emulation/2026-11-25-bsd-init-crossed.md` |
| root volume | **not reachable in this setup**, with three separate reasons | `docs/emulation/emulated-branch-limits.md` |
| iOS userland, display, desktop | **not started**; nothing here claims them | — |

Evidence labels in use, exactly: `source-reviewed`, `QEMU-tested`, `kernel-linked`, `EFI-tested` (for the
firmware pieces that were probed earlier). `hardware-tested`, `XNU-entry-tested` and `userland-booted` are
**not** claimed for the chain on the handset.

## Why the root volume is the wall, in three sentences

The source link has no storage classes (force-loading the driver fails on undefined `IOBlockStorageDevice::*`,
run 45706495971); the pinned XNU contains no HFS and no memory-disk driver, so a ramdisk root has nothing to
mount; and the merged image, which does contain those extensions, goes silent immediately after the kernel
hand-off in this emulator (serial of run 45715174239), so any claim past that point would be inference.

## The next action, in order

1. **Unlock the handset.** Everything else waits on this; the last attempt stalled switching to mass storage
   and the phone was flashed back to factory.
2. **Snapshot before touching anything**: `python scripts/phone-snapshot.py save --efiesp R: --out out/phone-backups`,
   then `python scripts/phone-image.py dump --volume R: --out out/phone-backups/unlocked-efiesp.img` (and the
   same for MainOS). The partition images are what make a bad experiment cheap.
3. **Install and verify in one command** (see `docs/hardware/post-unlock-runbook.md` step 2/3), then run
   `python scripts/check-bcd-layout.py` on the captured store and require exit 0.
4. **Install the shim on MainOS**, not EFIESP: `\Windows\System32\Boot\bootshim.efi`, subsystem `0x0A`. A `0x0B`
   driver on that path fails silently and the phone falls back to the Windows reset flow.
5. **Boot and read the serial/display**: the first thing to learn on hardware is whether the chain reaches
   DarwinBoot at all. That single fact decides whether the next work is the chain or the kernel.

## What would most likely unblock the emulated branch

Not more driver work: a source of console output from the merged image, or a framework pin with
`XNU_SOURCE_STORAGE` **plus** the media layer. Both are recorded with their reasons in
`docs/emulation/emulated-branch-limits.md`; do not re-measure them without reading that page first.

## House rules that cost rounds to learn

- CI's `validate` job runs on Linux: a path helper that only understands `R:` breaks there (run 45711382502).
- The workflow's concurrency group cancels a second dispatch on the same branch: one kernel run at a time.
- A failing experiment is worth recording next to the configuration it invalidated (`board.toml`,
  `configs/lumia950_defconfig`) so the next person does not repeat it.
- Do not promote a result to a later evidence label without the corresponding run.
