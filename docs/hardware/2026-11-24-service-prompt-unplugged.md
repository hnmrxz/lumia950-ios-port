# 2026-11-24 boot with USB detached still lands on the service prompt

With the cable pulled and a normal power press, the panel still shows "press any key to shutdown" and
nothing else.

That is the decisive negative result for this route: the firmware does not run a replaced
`EFI/boot/bootarm.efi`. It either refuses it (signature/validation) and falls back to its service mode,
or it never launches that path at all. Either way, copying an EFI application onto EFIESP is not how this
handset will boot another loader.

## What this rules out

- Replacing `bootarm.efi` on the real EFIESP (done on `R:`, hash-verified) -- no effect.
- Installing the payload beside it and relying on the firmware to look for `BOOTAA64.EFI` -- no effect.

## What the repository already expected

`scripts/install-native-bringup.py` treats `EFI/boot/BootShim.efi` as an expected, hash-pinned file and
states that the install preserves "BCD, BootShim, UEFI, Windows and partitions". The documented chain is
stock loader -> shim -> UniXNU, and the shim is what a locked handset lacks.

## Recovery order

1. Reconnect in mass storage so `R:` is available again.
2. `copy R:\EFI\boot\bootarm.efi.stock R:\EFI\boot\bootarm.efi` -- restores the stock loader.
3. Reboot normally; the handset should return to Windows.

Only after a shim is in place does another install attempt make sense, and installing the shim is the
phone's own unlocking step (WPinternals on this machine), not a file copy over mass storage.
