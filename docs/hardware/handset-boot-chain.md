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

## Where the shim actually goes (from the reference WOA image)

Reading the BCD of the WOA package on this machine settled what had been guessed at for a day
(`docs/hardware/2026-11-25-woa-ffu-reference.md`):

```
{bootmgr}   path \efi\boot\bootarm.efi        default {default}
{default}   path \windows\system32\boot\bootshim.efi   "BootShim Application"   nointegritychecks Yes
{01de5a27-…} \windows\system32\boot\mobilestartup.efi "Mobile Startup App"
```

The shim lives on **MainOS** under `\Windows\System32\Boot`, not on EFIESP, and `{bootmgr} default` is what
starts it. The same store also names `\windows\system32\boot\developermenu.efi`, which is the menu the
owner had seen before.

## The subsystem rule

The boot manager only starts EFI **applications** (PE subsystem `0x0A`) **or the Windows boot applications
(`0x10`) that the deployment tools use** -- measured on this phone: `BootShim.efi` and `mobilestartup.efi` are
ARMNT `0x01C4` / `0x10`, and `bootarm.efi` itself is `0x0A`. A boot service driver (`0x0B`) placed at a boot
path fails and the firmware falls back to its own sequence, which here means the Windows reset flow. Measured on the candidates this machine has:

| binary | bytes | subsystem | usable as a boot entry |
|---|---|---|---|
| `8AF09F13-….efi` (UEFI package) | 42,976 | 0x0B driver | no |
| `SJM\Core\Boot\bootaa64.efi` | 1,508,816 | 0x0A application | yes |
| rEFInd `refind_aa64.efi` | 202,624 | 0x0A | yes |
| GRUB `bootaa64.efi` | 878,544 | 0x0A | yes |

`scripts/phone-install.py` now refuses anything but `0x0A` on a boot path, and
`scripts/check-bcd-layout.py` checks the store afterwards.

## The procedure that matches the evidence

```
1. flash the factory FFU (phone in flash mode)                      -> Windows boots
2. unlock through the vendor utility (it is the only one that completes here)
3. snapshot EFIESP (scripts/phone-snapshot.py save)                -> rollback point
4. F:\Windows\System32\Boot\bootshim.efi <- 0x0A application (1.5 MB candidate)
   R:\UEFI.elf <- the WOA build, sha256 68b5ff0e…
   R:\EFI\REFIND\* <- rEFInd with its long file names (refind.conf, refind_aa64.efi, …)
5. point the store's default at the MainOS shim, then check it with check-bcd-layout.py
6. boot normally (no volume key)                                    -> expect the rEFInd menu
7. only then put the UniXNU loader at EFI\BOOT\bootaa64.efi and add the MainOS kernel
```

Two failures in this period are now explained rather than mysterious: a driver at the boot path (the
subsystem above) and a single-partition restore that left EFIESP stock beside a patched MainOS. Both have
checks now.

The rule that came out of the failures: **one change per boot, with a snapshot before it.** Every loop
in this period came from stacking changes and having no rollback that worked without a reflash.

## Open items on this page

- **The chain has booted on the handset** (2026-11-26): `EFI\BOOT\BOOTAA64.EFI` is what the custom UEFI
  starts, and writing the loader there was the missing step; the first boot without it reported
  `Failed to boot OS. No usable boot entry found`. See `docs/hardware/2026-11-26-first-hardware-boot.md`.
- Still open after that boot: no kernel output was observed past DarwinBoot's hand-off.
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
