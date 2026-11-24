# 2026-11-24 first handset boot attempt: "press any key to shutdown"

Reported by the owner: after the install, the panel shows **"press any key to shutdown"** and nothing else.

That message belongs to the firmware's **mass-storage mode**, not to the UniXNU loader: the handset
enters it when USB is attached during boot, and in that mode the firmware does not run
`EFI/boot/bootarm.efi` at all. So this attempt says nothing about the loader, positive or negative --
it is the wrong boot path.

The test that answers the question is:

1. press any key to shut the handset down;
2. unplug the USB cable;
3. power it on normally, without holding any volume key;
4. watch the panel for 30 s.

Outcomes and their meaning:

- **UniXNU menu with "iOS 16.7.16" and "Exit to firmware"** -- the EFI chain works; next question is
  DarwinBoot and the kernel.
- **Windows starts** -- the firmware does not launch `EFI/boot/bootarm.efi`; the fallback is a BCD
  entry (back it up before editing).
- **black screen, reset, or a firmware error** -- the loader itself is the problem; recovery is to
  reconnect USB in mass-storage mode and either restore `bootarm.efi.stock` or retry.

Recovery files are in `backups/efiesp-2026-11-24/` and as `EFI/boot/bootarm.efi.stock` on the
partition.
