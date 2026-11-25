# Post-unlock runbook — deploying the chain to the handset

Every command below is one the repository can run today; the dry-run output in this file came from
`scripts/rehearse-phone-install.py`, which builds a synthetic EFIESP/MainOS tree and executes the installer
against it. Nothing here touches a device until the single `--apply` step.

## 0. What must be true before starting

- the handset is **unlocked** (SJM / 刷机迷 step done after the last FFU flash; the bootloader accepts the
  shim only then);
- the repository is at a revision whose `kernel` job is green (that job builds the payload this runbook
  deploys);
- `out/payload` and the kernel artifacts were downloaded from that run, not rebuilt by hand.

Without the unlock the phone boots Windows; with the wrong PE subsystem it silently falls back to the
`bootsequence` path and resets. That is why step 2 checks the subsystem rather than trusting the file name.

## 1. Confirm the artefacts

```bash
python scripts/phone-install.py --help          # --dry-run and --apply must both be listed
python scripts/check-kernel-link.py --image out/kernel/kernel.macho   # drivers actually linked
```

## 2. Rehearse, then apply

```bash
# rehearsal: builds its own tree, writes nothing, prints the exact report below
python scripts/rehearse-phone-install.py

# on the phone (EFIESP and MainOS mounted, e.g. R: and F:)
python scripts/phone-install.py --efiesp R: --mainos F: \
    --stage out/payload --payload out/kernel --dry-run
python scripts/phone-install.py --efiesp R: --mainos F: \
    --stage out/payload --payload out/kernel --apply
```

Expected dry-run shape (from the rehearsal, paths shortened):

```
BootShim.efi -> MainOS\Windows\System32\Boot
  BootShim.efi                            512 B  sha256 775158ace736f789 subsystem 0x0A
UEFI.elf -> EFIESP root
UniXNU payload -> EFIESP
  UniXNU.efi ... subsystem 0x0A
  unixnu.toml
  DarwinBoot.efi ... subsystem 0x0A
kernel and device tree -> MainOS
  kernel.macho

dry run only; pass --apply to write
```

The `subsystem 0x0A` on the shim line is the check that matters most: the boot manager refuses a `0x0B`
driver silently, and the phone then boots Windows instead.

## 3. Point the boot store at the shim (elevated)

The installer prints these; they are not run for you, because they need elevation and a decision about which
store to edit:

```
bcdedit /store <EFIESP>:\EFI\Microsoft\BOOT\BCD /set {default} device partition=<MainOS>:
bcdedit /store <EFIESP>:\EFI\Microsoft\BOOT\BCD /set {default} path \windows\system32\boot\bootshim.efi
bcdedit /store <EFIESP>:\EFI\Microsoft\BOOT\BCD /set {default} description "BootShim Application"
```

Then verify the layout the way CI does, on the live output:

```bash
bcdedit /store R:\EFI\Microsoft\BOOT\BCD /enum all > out/bcd-after.txt
python scripts/check-bcd-layout.py out/bcd-after.txt --expect mainos
```

## 4. First boot

1. detach USB, power off, power on;
2. the expected sequence is BootShim → `UEFI.elf` → UniXNU menu → DarwinBoot → XNU;
3. `Still waiting for root device` on the serial log is the current known stopping point in emulation; on the
   handset the eMMC path (`NativeSdhci`) is the missing piece, not the boot chain.

## 5. Roll back

- files: `python scripts/phone-snapshot.py --restore <snapshot>` (or the partition images under
  `out/phone-backups/`);
- boot store: restore the `{default}` values captured before step 3;
- full recovery: `scripts/phone-recover.ps1` (FlashFFU → donor AddFFU → Unlock → MSM), which needs the unlock
  again afterwards.

## What this runbook does not claim

`EFI-tested` and beyond are not claimed for this chain until a handset boots it. The rehearsal proves the
installer's file logic and the subsystem check, not the firmware's behaviour.
