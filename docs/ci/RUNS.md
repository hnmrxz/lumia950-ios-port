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
| [43992258242](https://github.com/hnmrxz/lumia950-ios-port/actions/runs/43992258242) | `107a506` | push | validate, efi-preflight, gicv2-emulation, installer-windows, kernel | success | 9m20s |
| [43993637318](https://github.com/hnmrxz/lumia950-ios-port/actions/runs/43993637318) | `107a506` | dispatch `target=both` | all seven jobs, including the installer-precondition step in `stage` | success | 7m10s |
| [44003233713](https://github.com/hnmrxz/lumia950-ios-port/actions/runs/44003233713) | `44930b9` | dispatch `target=both` | all eight jobs, including `xnu-entry-qemu` | success | 10m30s |

The last row is the definitive one. In addition to the three artifacts it is the first run in which
**the linked kernel was executed**: `xnu-entry-qemu` boots the same run's kernel through the
firmware menu and DarwinBoot under QEMU and reads its progress with GDB breakpoints on real
symbols.

## What the emulator run establishes

Gate (`out/xnu-entry/report.json`), all six milestones in order:

```
arm_vm_init_entry, arm_vm_init_return, source_crypto_bootstrap_entry,
source_crypto_bootstrap_return, iokit_entry, iokit_return
```

- the source crypto provider returned with status 0 (KERN_SUCCESS) after VM setup;
- PE_init_iokit was entered and returned;
- the architectural counter is 0x124f800 = 19,200,000 Hz, the Lumia device-tree frequency;
- `wfe_event_index` is 4, as the fixture requires;
- the last PC is `_kernel_bootstrap_thread+0x224`, i.e. the bootstrap thread is running.

Observation (`out/xnu-entry-bsd/report.json`, `continue-on-error`), seven milestones — the six
above plus `kernel_bootstrap_entry` — and then:

```
stop: _fleh_synchronous   pc: _fleh_synchronous+0x0
fault at: ArmCpu::mapGic()+0x444   far: 0xfffffff0b5c2ffe8   esr_el1: 0x96000010
```

ESR 0x96000010 is a synchronous external abort on a data access. The ADT points the GIC at the
Lumia's SoC addresses; QEMU's `virt` machine has no device there, so `ArmCpu::mapGic()` faults as
soon as it programs the interrupt controller. That is a property of the emulation, not a kernel
regression — and it is the next thing worth attacking: an ADT profile that maps QEMU's GIC
(0x08000000) would let the run continue past `mapGic` and expose the next blocker.

The fixture now names the code it stopped in (`pc_symbol`) and the faulting site
(`fault_elr_symbol`) in the report, so a future run explains itself without reading a log.

The last row is the definitive one: the head commit builds validate, efi-preflight, gicv2-emulation,
installer-windows, payload, kernel and stage, so all three artifacts come from one commit and one
run, and the `stage` job also proved that the installer accepts that tree (`install preconditions
ok: 8 files, 15566029 bytes`).

## What the runs establish

The kernel line (every push to `main`):

- validate passes with the new checkers: the staging-directory guard, the build manifest, the ADT
  profile, the link assertion, the phase exits, the checkpoint contract, the evidence table, the
  device-identifier scan, the doc-reference scan, the action pins and the reproducibility test;
- efi-preflight builds `LumiaGpuProbe` and `LumiaGpuPower` and runs the QEMU refusal cases;
- gicv2-emulation runs the pinned ArmCpu patch preparation and the timer/SGI/SPI fixtures;
- installer-windows runs the installer suite on a real Windows filesystem, which is where the
  Windows backend would run for a deployment;
- the kernel job compiles XNU on macOS, builds the eight archives, links, prelinks against the
  pinned 16.7.16 kernelcache, **reads the symbol table** and writes `out/build-manifest.json`.

`target=both` adds the two artifacts that were never produced here:

- `lumia950-payload`: `UniXNU.efi`, `DarwinBoot.efi`, `unixnu.toml`;
- `lumia950-stage`: the deployable tree, 7 files — `BOOTAA64.EFI`, `UniXNU.efi`, the menu, the
  loader, `LumiaGpuPower.efi`, the stripped kernel (15,260,776 B) and its ADT (11,352 B) — with
  `native-bringup.json` naming `build_manifest_sha256`, `build_repo_commit`, the pinned framework
  ref, `adt_profile` `bringup` and `secondary_cpu_conduit_qualified` false. The job then feeds that
  tree to the installer's own `stage_files()` and gets `8 files, 15566029 bytes` back.

No CI job writes to a phone: a hosted runner has no USB path to one. See README, "部署".

## Artifact hashes

Run 43993637318 on `107a506` (the head commit; deploy from this one):

| Value | SHA-256 |
|---|---|
| `native-bringup.json` → `build_manifest_sha256` | `7351a2bb1844fd26d9a4c3b8c784d56bcfc5877be63b0b6cbf359fe58c06e307` |
| `native-bringup.json` → `native_kernel_sha256` | `c3b576a45be802c572fb12efeffd332d37c008b86482b8485caa9f0d68be47e9` |
| `native-bringup.json` → `stripped_kernel_sha256` (what the phone would read) | `c8837797526049f3fd353954f3e1b1ec19b3bdc8c59bf74eb3ab694d9d8cbbfa` |
| every file in the staged tree | in `native-bringup.json` → `files` |

Earlier runs on `2d6cfda` and `1c08cab` produced the same seven-file layout with different hashes;
the difference is the class of non-determinism this page measures below.

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

## 2026-11-17: every job failed before its first step

Three runs, each with zero executed steps and no runner assigned:

| Run | What it was | Result |
|---|---|---|
| 44005104042 | dispatch `target=both` on HEAD `2ac9d47` | every job failed, 0 steps |
| 44005372524 | dispatch `target=payload` (Ubuntu only) on `2ac9d47` | every job failed, 0 steps |
| 44005565141 | dispatch `target=payload` on a probe branch at `e463a61`, the last green commit | every job failed, 0 steps |

The third one is the diagnostic: the last known-good commit fails identically, so neither the
workflow file nor the scripts are the cause — the failure is account-level. The most likely cause
is the Actions quota for this private repository: a macOS minute bills as ten, and roughly a dozen
kernel builds plus stage jobs ran today. Confirm in **Settings → Billing and plans** rather than
guessing further; the REST billing endpoint needs a token scope this session does not have.

Until that is resolved, nothing in this file can be re-verified. The kernel job is now manual-only
(see README), so a later push costs a couple of minutes of Ubuntu time instead of about ninety of
macOS time.

### 2026-11-23: still failing at startup, six days later

One cheap probe (dispatch `target=payload`, Ubuntu only) on `6d90f1a`: every job failed with zero executed steps and no runner assigned (run 45126791279). Nothing in the repository changed in that week, so the condition is unchanged: it is account-level, not a workflow or script problem. The evidence is above; until the account side is resolved, no run can verify anything.

## How to add a run

```sh
gh run list --repo hnmrxz/lumia950-ios-port --workflow build.yml --limit 5
gh run view <RUN_ID> --repo hnmrxz/lumia950-ios-port
```

Record the id, the commit, the event, the jobs and the conclusion. For a `stage` run also record
the `build-manifest.json` and `native-bringup.json` hashes, since those are what tie the tree to
the run. Note that `gh` resolves this directory's `upstream` remote by default: always pass
`--repo hnmrxz/lumia950-ios-port`.
