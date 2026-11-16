# CI runs of this repository

Every claim of the form "CI produced this" has to be openable. This file is the index; the run ids
below are on `hnmrxz/lumia950-ios-port`. Nothing here is a substitute for the run itself.

| Run | Commit | Event | Jobs | Conclusion | Duration |
|---|---|---|---|---|---|
| [43830315484](https://github.com/hnmrxz/lumia950-ios-port/actions/runs/43830315484) | `a2a14e3` | push to `main` | validate, efi-preflight, gicv2-emulation, kernel | success | 8m48s |

## What that run does and does not establish

It is the baseline commit: the documentation, the existing workflows and the board as they stood
before the review. It establishes:

- `validate` passes on the committed tree (host tests, ADT/payload checks, the board guard);
- `efi-preflight` builds `LumiaGpuProbe` and `LumiaGpuPower` and runs the QEMU refusal cases;
- `gicv2-emulation` runs the pinned ArmCpu patch preparation and the timer/SGI/SPI fixtures;
- the `kernel` job compiles the XNU line, builds the device archives, links and produces the
  prelinked candidate on macOS.

It does **not** establish the newer gates, because it predates them: the build manifest, the
`llvm-nm` link assertion, the ADT-profile check and the `stage` job were added afterwards. A run
after those changes is what closes `docs/phases/p0-exit.json` P0.2 and P0.4.

## How to add a run

```sh
gh run list --repo hnmrxz/lumia950-ios-port --limit 5
gh run view <RUN_ID> --repo hnmrxz/lumia950-ios-port
```

Record the id, the commit, the jobs and the conclusion. For a `stage` run also record the
`build-manifest.json` and `native-bringup.json` hashes from the artifacts, since those are what
tie the tree to the run.
