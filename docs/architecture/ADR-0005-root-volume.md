# ADR-0005: where the root volume would come from

Status: proposed, must be decided before work that assumes a mounted root
Date: 2026-11-26

## Context

The port's target is an iOS userland on a Lumia 950. `bsd_init` reaches `vfs_mountroot`, which needs a block device
carrying an Apple filesystem, and the device does not have one:

| volume | filesystem | size | owner |
|---|---|---|---|
| MainOS (drive H:) | NTFS | 29.5 GB | Windows on the phone |
| EFIESP (drive R:) | FAT | 32 MB | firmware / deployment tool |

The pinned kernel's source merge includes APFS and HFS+ **code**; code is not a volume. Nothing in this repository
creates an Apple volume today, and the two ways to get one both have a large price:

- **repartition the handset** (shrink or delete MainOS): destroys the Windows installation on the device, which is
  the rollback path this project has used all along;
- **write an FFU that contains such a partition**: the toolchain here cannot generate one (see `docs/state.md`).

A third possibility is untested: mounting an Apple filesystem **from a file or a second device** (for example a
partition on the microSD card, which the 950 supports). That would leave MainOS untouched, and it would be the only
variant that keeps the current rollback contract.

## Decision (proposed)

Prefer the microSD variant if the hardware path allows it, because it is additive: no existing partition changes,
and the rollback stays "restore the EFIESP image and the MainOS files". Before any code depends on a mounted root:

1. confirm the 950's SD controller is reachable from the driver this port can deliver (ADR-0003), or that eMMC
   partitions are addressable without touching MainOS;
2. record the chosen volume's location and geometry in `board.toml` with its source;
3. only then wire `[kernel.prelink]`/`kernel args` to it.

If neither works, the objective's end state changes and that has to be stated rather than assumed away.

## Consequences

- Until this decision, "root volume" work is limited to drivers and buses, not to mounting.
- The rollback image `out/phone-backups/unlocked-efiesp.img` stays the contract; anything that repartitions voids it
  and must be recorded as a new contract.

## Evidence

- `docs/state.md` (the FFU limitation), `board.toml` (`TODO: userdata GPT geometry`)
- The two mounted volumes as listed above, read from the phone during this session
