# The handset boot chain, as measured on this phone

One page, replacing six overlapping notes from 2026-11-24. Every claim here was measured on the handset
or read out of the tools; where a note was wrong, the correction is stated rather than silently dropped.

## The chain

```
firmware (stock UEFI, secure boot on)
  -> EFI\boot\bootarm.efi        (Windows Phone boot manager; left alone)
  -> unlocked boot manager looks for \UEFI.elf on EFIESP
  -> UEFI.elf                    (Lumia950XLPkg 2.24b, ELF, loaded with the AArch64 shim)
  -> EFI\Boot\bootaa64.efi       (what the custom UEFI starts; our UniXNU loader)
  -> EFI\UniXNU\UniXNU.efi + unixnu.toml + Drivers\DarwinBoot.efi
  -> EFI\UniXNU\Payloads\kernel.macho (+ .adt) on MainOS
```

## The four corrections that took the longest

1. **Do not replace `bootarm.efi`.** The firmware runs it; it is also the boot manager that starts
   everything else, and it is what provides mass-storage mode. Replacing it made the phone stop showing
   mass storage at all.
2. **The EFIESP the firmware boots is a partition, not the junction.** `F:\EFIESP` is a junction whose
   writes never reached the boot partition; the real one appeared as `R:` and showed a stock
   `bootarm.efi` and nothing else. Anyone repeating this work should mount the partition and look at
   `EFI\boot` before believing anything about the install.
3. **A shim fetched from `imbushuo/boot-shim` is ARM32.** Both releases are `PE machine 0x01C4` and
   cannot run on this AArch64 handset. The AArch64 shim is the 42,976-byte `8AF09F13-…` module inside
   the Lumia950XLPkg package.
4. **`{default}` is not how this BCD store starts an entry.** The store has no display order, and
   pointing `{default}` at a loader makes the manager fall back to its boot sequence and the Windows
   reset flow (the two gears). The sequence start entry is `{01de5a27-…}` (`mobilestartup.efi`), and the
   boot menu itself is reached by **holding Volume Down while powering on**.

## What the phone reported about itself

`WPinternals` reads: `RM-1105`, product code `059X4D5`, platform
`Microsoft.MSM8992.P6218_ATT.1.0`, `Lumia Bootloader Spec B`. The owner's flashing tool additionally
records that **every Lumia, regardless of model, needs the 950 XL image** for the unlock patch to resolve
its reference versions — the same mechanism as WPinternals' `-AddFFU` donor
.

## The procedure that matches the evidence

```
1. flash the factory FFU (phone in flash mode)          -> Windows boots
2. unlock with WPinternals (donor 950 XL FFU present)   -> Windows still boots, mass storage works
3. snapshot EFIESP (scripts/phone-snapshot.py save)     -> rollback point, seconds to restore
4. copy \UEFI.elf and EFI\Boot\bootaa64.efi             -> one change, then test
5. boot holding Volume Down, pick the entry             -> custom UEFI or Windows, never a loop
6. only then add EFI\UniXNU\* and the MainOS kernel
```

The rule that came out of the failures: **one change per boot, with a snapshot before it.** Every loop
in this period came from stacking changes and having no rollback that worked without a reflash.

## Open items on this page

- The unlock on this specific phone has not yet been completed by a tool that can patch the boot chain
  from flash mode; WPinternals' command line stalls switching to mass storage before it can patch.
- `--unique-chip-id` in the handset ADT is still a zero placeholder.
- The kernel stage is proven in QEMU only (`docs/ci/RUNS.md`), never on the handset.

## Cleanup note

Eight overlapping notes from 2026-11-24 were folded into this page and removed:
`booted-windows`, `real-efiesp-is-r`, `service-prompt-unplugged`, `handset-boot-entry`,
`first-boot-attempt`, `handset-payload-install`, `handset-redeploy`, `handset-second-install`. What
survives separately is what this page does not cover: the device identity and the chip-id caveat
(`2026-11-24-device-identity.md`), the WPinternals wrapper
(`2026-11-24-wpinternals-integration.md`), and the flashing toolchain with its hashes
(`2026-11-25-flashing-toolchain.md`).
