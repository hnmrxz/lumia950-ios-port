# Top-level documentation audit, 2026-11-25

Follow-up to `docs/validation/2026-11-25-documentation-audit.md`, done after the hardware notes were
folded into `docs/hardware/handset-boot-chain.md`.

## Done in this pass

- `docs/status-2026-11-24.md` was a snapshot whose handset section still said the UniXNU loader sits on
  EFIESP as `bootarm.efi` (it does not) and whose check counts were stale. It was replaced by
  `docs/state.md`, which keeps only what a run or a file supports and points at the boot-chain page for
  everything device-side. Nothing references the old name any more (checked across `.md`, `.py`, `.json`,
  `.toml`, `.yml`).

## Overlaps found, not merged

These groups describe the same work at different times. Merging them would mean rewriting 50+ KB of
measured bring-up notes, which is riskier than leaving them with a clear entry point.

| group | files | size | recommendation |
|---|---|---|---|
| GPU bring-up | `native-bringup.md` (34.7 KB), `gpu-bringup.md` (13.9 KB), `native-gpu-batch.md` (10.8 KB), `native-gpu-power.md` (20 KB) | ~79 KB | keep as the chronological record; add a one-paragraph index at the top of `native-bringup.md` naming what each covers and which is current |
| platform bits | `native-gicv2.md`, `storage-bringup.md` | 9 KB | fine as they are; both are narrow and uncited elsewhere |
| navigation | `PORTING-ROADMAP.md`, `HARDWARE-INVENTORY.md`, `BUILD-VERIFICATION.md`, `docs/phases/*` | ~19 KB | roadmap and phases overlap conceptually; a single "how this port is organised" page would help, but the roadmaps are dated material |
| data | `evidence.json`, `native-checkpoints.json` | 13 KB | machine-read by the checkers; never merge |

## What the checks say now

```
check-doc-references : 161 files, 11 referenced README sections all present
check-evidence       : 16 subjects (source-reviewed 6, QEMU-tested 7, kernel-linked 1, EFI-tested 2)
run-tests            : 25/25 passed, 7 skipped
```

## Suggested next step, if more consolidation is wanted

The only group where a merge would reduce real duplication without touching measured content is the GPU
set, and even there the honest move is an index paragraph rather than a rewrite: those files record
different bring-up stages, and their values are cited by `board.toml` and the driver archives.
