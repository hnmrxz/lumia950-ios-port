# 2026-11-24 redeploy after the first boot test

The phone was reconnected and the latest green build was installed again, from run 45329355613.

## EFIESP

```
EFI/boot/BOOTAA64.EFI            94,208   (also copied over bootarm.efi)
EFI/boot/bootarm.efi.stock      911,304   (the stock loader, kept)
EFI/UniXNU/UniXNU.efi            94,208
EFI/UniXNU/unixnu.toml            2,352   timeout = 30, fallback_timeout = 30, default = "xnu"
EFI/UniXNU/Drivers/DarwinBoot.efi 26,624
EFI/UniXNU/Drivers/ntfs.efi       61,440  EfiFs v1.13, read-only NTFS for MainOS
```

Every file matched the staged tree by SHA-256 except `unixnu.toml`, which was deliberately edited after
the copy to raise both waits to 30 s; the entries themselves are the staged ones (`xnu` titled
"iOS 16.7.16", `exit`, `reset`, `shutdown`).

## MainOS (`F:`)

```
EFI/UniXNU/Payloads/kernel.macho      56,619,008   sha256 6a461ef5ae49f830...
EFI/UniXNU/Payloads/kernel.macho.adt      11,360   sha256 ef582c52590cd720...
EFI/UniXNU/Payloads/SHA256SUMS.txt           296
```

Replaced files are in `F:\EFI\UniXNU\Payloads.previous`.

## The chip identifier is still a placeholder

`stage-kernel.py` requires `--unique-chip-id`; this repository does not record the handset's value, so
the ADT was generated with zeros. The menu, the loader and the kernel stage correctly, but the device
tree carries a wrong identifier, so a boot that stops early may be stopping because of that rather than
because of the kernel.

## What the next boot test must do

The first attempt showed "press any key to shutdown", which is the firmware's mass-storage prompt: with
USB attached at boot the loader never runs. This time: **unplug the cable, power on normally**, and
watch the panel for 30 s.
