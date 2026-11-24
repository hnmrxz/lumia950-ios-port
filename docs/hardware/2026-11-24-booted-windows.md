# 2026-11-24 the handset booted Windows: the loader replacement does not take effect

Reported: with USB detached the phone boots Windows normally. WPinternals, connected in flash mode,
reports `Microsoft.MSM8992.P6218_ATT.1.0`, variant RM-1105, product code 059X4D5, "Lumia Bootloader
Spec B".

So replacing `EFI/boot/bootarm.efi` with the UniXNU loader changed nothing: the firmware either does not
launch that file or refuses it. The stock loader has been written back from `bootarm.efi.stock`, so the
phone is left in the state it arrived in apart from `EFI/UniXNU/` and the MainOS payload.

## Why this was predictable from this repository

`scripts/install-native-bringup.py` lists an existing **`EFI/boot/BootShim.efi`** among the files it
expects to find (with a pinned hash) and states plainly that it preserves "BCD, BootShim, UEFI, Windows
and partitions". In other words the install route this project documents assumes a shim is already in
place and the chain runs `stock loader -> shim -> UniXNU`; it never replaces the Microsoft loader. That
file is not on this phone, which is the gap.

## What has to happen before another install attempt

1. The bootloader has to accept a non-Microsoft EFI application: on this platform that is the
   unlock/shim step, done with the phone's own tooling (WPinternals is the tool at hand), not by copying
   files over mass storage.
2. Once `EFI/boot/BootShim.efi` exists and the chain reaches it, the same payload already staged on
   EFIESP and MainOS becomes reachable -- no rework of the kernel side.

Until then, copying loaders onto EFIESP will keep producing a phone that boots Windows.
