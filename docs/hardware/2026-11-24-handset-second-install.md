# 2026-11-24 second install: menu with a kernel entry, and the prelinked image

The first attempt installed the payload beside the stock loader, so the firmware never ran it
(docs/hardware/2026-11-24-handset-boot-entry.md). This attempt used `scripts/stage-kernel.py` against
the **prelinked** image from CI run 45318161131 (`lumia950-prelinked`, 56,619,008 B) with the NTFS
driver from `scripts/get-ntfs-driver.py` (EfiFs v1.13, 61,440 B), so the configuration really has an
`xnu` entry:

```
default = "xnu"
id = "xnu"      title = "iOS 16.7.16"   path = "Payloads/kernel.macho"
id = "exit"     title = "Exit to firmware"
id = "reset" / "shutdown"
timeout = 30    fallback_timeout = 30
```

Deployed, every file verified by SHA-256 against the staged tree:

| partition | path | bytes | sha256 |
|---|---|---|---|
| EFIESP | `EFI/boot/bootarm.efi` (+`BOOTAA64.EFI`) | 94,208 | UniXNU loader |
| EFIESP | `EFI/UniXNU/unixnu.toml` | 2,352 | kernel entry above |
| EFIESP | `EFI/UniXNU/Drivers/DarwinBoot.efi` | 26,624 | from the payload |
| EFIESP | `EFI/UniXNU/Drivers/ntfs.efi` | 61,440 | EfiFs v1.13 |
| MainOS | `EFI/UniXNU/Payloads/kernel.macho` | 56,619,008 | `8e523907ef052dce...` |
| MainOS | `EFI/UniXNU/Payloads/kernel.macho.adt` | 11,360 | `78b402e82d15f365...` |

The stock loader is preserved as `EFI/boot/bootarm.efi.stock`.

## One value in this install is a placeholder

`stage-kernel.py` requires `--unique-chip-id`, a per-handset value that is not recorded in this
repository. The ADT above was therefore generated with `0000000000000000`. The tree is otherwise what
the stager produces, but the chip identifier inside the ADT is wrong and must be replaced with the
handset's own value before any result from this boot is treated as a kernel finding.

Rollback: `EFI/boot/bootarm.efi.stock` back over `EFI/boot/bootarm.efi`, and the copies in
`backups/efiesp-2026-11-24/`.
