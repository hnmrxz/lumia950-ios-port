# CI runs of this repository

Every claim of the form "CI produced this" has to be openable. This file is the index; the run ids
below are on `hnmrxz/lumia950-ios-port`.

| Run | Commit | Event | Jobs | Conclusion | Duration |
|---|---|---|---|---|---|
| [43830315484](https://github.com/hnmrxz/lumia950-ios-port/actions/runs/43830315484) | `a2a14e3` | push | validate, efi-preflight, gicv2-emulation, kernel | success | 8m48s |
| [43880379722](https://github.com/hnmrxz/lumia950-ios-port/actions/runs/43880379722) | `220c87d` | push | … + link assertion | failure: the kernel contained none of the four drivers | 7m57s |
| [43882080522](https://github.com/hnmrxz/lumia950-ios-port/actions/runs/43882080522) | `0a28952` | push | … after force-loading all four | failure: `IOBlockStorageDevice` is not in the source kernel | 7m52s |
| [43883767146](https://github.com/hnmrxz/lumia950-ios-port/actions/runs/43883767146) | `0b8f074` | push | … Sdhci excluded | failure: the manifest looked for `unixnu.lock` in the wrong repository | 9m15s |
| [43885772410](https://github.com/hnmrxz/lumia950-ios-port/actions/runs/43885772410) | `1c08cab` | push | validate, efi-preflight, gicv2-emulation, kernel | success | 9m04s |
| [43887531094](https://github.com/hnmrxz/lumia950-ios-port/actions/runs/43887531094) | `1c08cab` | dispatch `target=both` | validate, efi-preflight, gicv2-emulation, payload, kernel, **stage** | success | 11m08s |
| [43890111246](https://github.com/hnmrxz/lumia950-ios-port/actions/runs/43890111246) | `2d6cfda` | push | validate, efi-preflight, gicv2-emulation, kernel | success | 8m20s |
| [43891763434](https://github.com/hnmrxz/lumia950-ios-port/actions/runs/43891763434) | `2d6cfda` | dispatch `target=both` | all six jobs | success | 11m08s |

The last row is the definitive one: the head commit builds validate, efi-preflight, gicv2-emulation,
payload, kernel and stage, so all three artifacts come from one commit and one run.

## What the runs establish

The kernel line (every push to `main`):

- validate passes with the new checkers: the staging-directory guard, the build manifest, the ADT
  profile, the link assertion, the phase exits, the checkpoint contract, the evidence table, the
  device-identifier scan, the doc-reference scan, the action pins and the reproducibility test;
- efi-preflight builds `LumiaGpuProbe` and `LumiaGpuPower` and runs the QEMU refusal cases;
- gicv2-emulation runs the pinned ArmCpu patch preparation and the timer/SGI/SPI fixtures;
- the kernel job compiles XNU on macOS, builds the eight archives, links, prelinks against the
  pinned 16.7.16 kernelcache, **reads the symbol table** and writes `out/build-manifest.json`.

`target=both` adds the two artifacts that were never produced here:

- `lumia950-payload`: `UniXNU.efi`, `DarwinBoot.efi`, `unixnu.toml`;
- `lumia950-stage`: the deployable tree, 7 files — `BOOTAA64.EFI`, `UniXNU.efi`, the menu, the
  loader, `LumiaGpuPower.efi`, the stripped kernel (15,260,776 B) and its ADT (11,352 B) — with
  `native-bringup.json` naming `build_manifest_sha256`, `build_repo_commit`, the pinned framework
  ref, `adt_profile` `bringup` and `secondary_cpu_conduit_qualified` false.

## Artifact hashes

Run 43891763434 on `2d6cfda` (the head commit; this is the set to deploy from):

| Value | SHA-256 |
|---|---|
| `native-bringup.json` → `build_manifest_sha256` | `13dfb9c787c6b956d169790141093d7768d015663be314f4bb65c924f8e6b69c` |
| `native-bringup.json` → `native_kernel_sha256` | `fbdbeac137baf82ebaa90ae02a58550e4fb2d4073b26f477670913d46a11f253` |
| `native-bringup.json` → `stripped_kernel_sha256` (what the phone would read) | `8850ff3fd0764bff3edd89500717dabf7b290a3da8c180af4c85a1c2a461b660` |
| every file in the staged tree | in `native-bringup.json` → `files` |

Run 43887531094 on `1c08cab` produced the same seven-file tree with
`native_kernel_sha256` `f52d20cb…` and `stripped_kernel_sha256` `7897d486…`; the difference is the
same class of non-determinism this page measures below.

The staged tree's `adt_profile` is `bringup`, `adt_dram_size` is `2942304256` (0xAF600000, the
measured 2806 MiB), `secondary_cpu_conduit_qualified` is false and `handset_boot_observed` is
false. It has not been anywhere near a phone.

## Reproducibility between the two kernel runs

Both kernel runs used commit `1c08cab`, and their images differ:

| Artifact | Bytes | Same across runs |
|---|---|---|
| `kernel.macho` (prelinked) | 56,578,048 | no |
| `mach.development.bcm2837.unstripped` | 18,783,720 | no |
| `mach.development.bcm2837` | 15,260,776 | no |
| `kernel.json` (prelink report) | 77,557 leaves | 77,555 identical; the two that differ are `native_sha256` and `candidate_sha256` |

`scripts/check-reproducible.py` classifies every differing byte of the source image: **1,911 of
18,783,720 bytes (0.0102%)** — the 16-byte `LC_UUID`, 6 bytes of the kernel version banner in
`__TEXT,__const` (XNU's `version.c` embeds `__DATE__`/`__TIME__`), and 1,889 bytes of timestamps
inside the debug information and symbol tables, which are not loaded. That is the "named
difference" `docs/phases/p0-exit.json` P0.3 accepts instead of two identical hashes. Making the
banner reproducible would need a pinned build epoch; it is not attempted here.

## How to add a run

```sh
gh run list --repo hnmrxz/lumia950-ios-port --workflow build.yml --limit 5
gh run view <RUN_ID> --repo hnmrxz/lumia950-ios-port
```

Record the id, the commit, the event, the jobs and the conclusion. For a `stage` run also record
the `build-manifest.json` and `native-bringup.json` hashes, since those are what tie the tree to
the run. Note that `gh` resolves this directory's `upstream` remote by default: always pass
`--repo hnmrxz/lumia950-ios-port`.
