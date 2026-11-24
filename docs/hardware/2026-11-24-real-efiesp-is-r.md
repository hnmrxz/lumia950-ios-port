# 2026-11-24 the real EFIESP is R:, and the earlier install went to the wrong place

`F:\EFIESP` is a junction, and the files written through it in the earlier rounds did not land on the
partition the firmware boots from. With the boot partition mounted as **`R:`** (label `EFIESP`, FAT,
33,275,904 bytes, 22,018,048 free) its contents showed what was missing: `EFI/boot/bootarm.efi` was the
stock 911,304-byte loader and nothing else -- no `BOOTAA64.EFI`, no `EFI/UniXNU`.

That also explains the Windows boot: the loader replacement had never touched this partition.

## What is on R: now

```
EFI/boot/bootarm.efi           94,208   the UniXNU loader (hash-equal to BOOTAA64.EFI)
EFI/boot/bootarm.efi.stock    911,304   the stock loader, kept
EFI/boot/BOOTAA64.EFI          94,208
EFI/UniXNU/UniXNU.efi          94,208
EFI/UniXNU/unixnu.toml          2,352   timeout = 30, fallback_timeout = 30, default = "xnu"
EFI/UniXNU/Drivers/DarwinBoot.efi 26,624
EFI/UniXNU/Drivers/ntfs.efi    61,440   EfiFs v1.13
```

Every file matched the staged tree by SHA-256 except `unixnu.toml`, which was edited after the copy to
raise both waits.

The partition also holds the pieces the firmware uses for its own boot: `EFI/Microsoft/BOOT/BCD`,
`Boot.stl`, `SecureBootPolicy.p7b`, `PlatformManifest/MICROSOFTPHONEFM.pm`, plus `mmos_load_methods.txt`
(contents: `USB`) and `mmo_uefi_start_flag.txt` (contents: `S`).

## The next boot test

Unplug USB, power on, watch the panel for 30 s. If the firmware insists on its own loader, the fallbacks
are, in order: the stock copy on this partition, and a BCD entry (which needs an elevated `bcdedit` this
session cannot run).
