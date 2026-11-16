# Agent instructions — Lumia 950 UniXNU port

## Mission

Target only Microsoft Lumia 950 (MSM8992 / Snapdragon 808). Build and validate a reversible chain:

`Lumia stock UEFI + Boot Shim → UniXNU EFI menu → DarwinBoot → ARM64 XNU 16.x → iOS 16.7.16 userland`

No local Mac is assumed. GitHub Actions is the canonical Xcode/iPhoneOS SDK build environment.

## Non-negotiable facts

- The current board is P1 research. `board.toml` intentionally has `example = true`; the CI's scratch-copy clear is only for compile/prelink experiments. Never change the committed guard just to make a build command green.
- The verified on-device EFI report is EL1, 1080×1920 BGR GOP at `0x00400000`, 19.2 MHz counter. This is not evidence that XNU takes control or owns the framebuffer after `ExitBootServices`.
- `NativeSdhci` has host tests / ABI compile evidence, not a working XNU eMMC read path on Lumia 950.
- `NativeMdss` and `NativeAdreno418` are early bring-up rungs; do not claim display or GPU support.
- Lumia 950 XL = MSM8994; Xperia Z5 Compact = MSM8994. Their board values are not Lumia 950 MSM8992 values.
- iOS kernel/userland inputs must match the pinned iOS 16.7.16 (20H392) profile and kernelcache ABI. Do not silently switch to another IPSW or XNU tag.

## Engineering rules

1. Read the relevant device source, the upstream UniXNU `AGENTS.md`, and the current board docs before changing build logic.
2. Keep a source/revision for every hardware constant. Prefer WOA firmware sources, device probe logs, stock DTS/ACPI, and measured reports. Unknown values stay unknown.
3. Change one bring-up rung at a time. Add a host test / QEMU fixture / static checker before wiring MMIO into a live driver.
4. For every driver, record: hardware resource, clock/power owner, interrupt, DMA/cache contract, OS ABI, initialization caller, archive recipe, and test evidence.
5. Every driver edit that includes IOKit/XNU headers must be compiled in the macOS `kernel` job against the pinned XNU/iPhoneOS SDK ABI. A host unit test is not an ABI compile.
6. Check archive members, exported symbols, link inclusion and prelink reports. A green generic `validate` job is not proof that a driver was compiled.
7. Preserve rollback paths. No CI workflow may unlock, flash, repartition, edit BCD/EFI variables or write phone storage.
8. Do not store Apple IPSW contents, kernelcache blobs, trust caches, private chip identifiers, or generated proprietary binaries in git. Keep temporary artifacts short-lived and access-restricted.
9. Do not run `git push --force`, rewrite upstream history, or change the upstream remote without explicit instruction.
10. Keep `board.example = true` until the conditions stated at the top of `board.toml` — that comment is the single authority; this file does not restate it. Never manufacture a successful boot report.

## Build policy

- Use the device repository workflow as the execution record.
- Default macOS runner is pinned; the `MACOS_RUNNER` Actions variable may override it for controlled runner comparisons.
- Log `sw_vers`, `uname -m`, Xcode, iPhoneOS SDK, clang, Homebrew tool versions and free disk before the kernel build.
- Use pinned framework and source revisions until a migration to the current UniXNU Format 2 architecture is proven by `unixnu status --json`, `unixnu tree`, and a clean kernel build.

## Completion language

Use only these evidence labels: `source-reviewed`, `host-tested`, `QEMU-tested`, `ABI-compiled`, `kernel-linked`, `prelink-checked`, `EFI-tested`, `XNU-entry-tested`, `hardware-tested`, `userland-booted`. Do not promote a result to a later label without its corresponding evidence.
