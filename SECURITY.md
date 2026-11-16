# Security policy

## What this repository is

A research port of an Apple kernel to a Microsoft Lumia 950 (MSM8992). It is **P1 research**, not
a supported system: there is no working iOS userland, no firmware signing chain, and none of the
trust capabilities an iPhone has. Do not put data on a device built from it, do not connect one to
a network, and do not sign in to an Apple ID from it.

The device's trust boundary is written down as a phase criterion
(`docs/phases/p4-exit.json`, P4.3) precisely because it is currently absent rather than pending.

## Reporting a problem

Open a private security advisory on this repository (Security -> Advisories) rather than a public
issue. If that is unavailable, contact the repository owner through the account that owns it.

Relevant reports include:

- a workflow or script that can write to the phone, a boot partition or an EFI variable;
- an artifact path that would publish Apple-derived binaries from a public repository;
- a device identifier, kernelcache, IPSW content or trust cache committed to the tree;
- a checker that accepts the thing it exists to refuse.

## What is deliberately out of scope

- **The Apple binaries.** The kernel job fetches a pinned kernelcache from Apple's public CDN and
  merges kernel extensions out of it. This project does not redistribute them: the artifact is
  gated on `github.event.repository.private` and expires in one day by default. Licensing and
  distribution are not security questions this file can answer.
- **A rooted or unlocked phone.** The port runs on a handset whose boot chain the owner already
  modified. Physical access and firmware integrity are the owner's responsibility.
- **Memory safety of the inherited driver code.** `drivers/NativeAdreno418` and
  `drivers/NativeSdhci` were not written here and have not been audited; they have host tests and
  an ABI compile, nothing more.

## How the invariants are enforced

| Invariant | Enforcement |
|---|---|
| The repository stays private for Apple-derived artifacts | `build.yml`, the `kernel` artifact's `if:` |
| No raw device identifier in git | `scripts/check-no-device-identifiers.py`, run by `validate` |
| Nothing in CI writes to the phone | no workflow runs an installer; `install-native-bringup.py` is dry-run by default |
| A staging directory is a build product | `scripts/stage-kernel.py --out` guard, `scripts/test-stage-kernel.py` |
| A stage's kernel is the one CI built | `--manifest` in `scripts/stage-native-bringup.py` |
| A third-party action cannot move under a run | `scripts/check-action-pins.py` (every `uses:` is a commit); `.github/dependabot.yml` keeps the pins current |
