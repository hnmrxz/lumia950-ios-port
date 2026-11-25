# The WOA image on this machine, and what it says about the boot chain

The owner supplied `10.0.21277.1000_CLIENTPRO_TALKMAN_A64FRE_EN-US.ffu` (4.55 GB) and asked what it is.
This note records what was measured, and the one finding that matters for the iOS port.

## It cannot be flashed on this handset as-is

```
WPinternals.log
16:49:09.924: Flashing original FFU...
16:49:10.074: Error: Flash failed!
              Error 0x1106: Security header validation failed
```

The image is a community-built Windows 10 ARM64 (21277) package. Its FFU security header is not signed
with this phone's key, and the flash app (Bootloader Spec B, Secure Boot enabled) rejects it before a
single block is written. The official 10586 FFU flashes fine, so the difference is the signature, not the
transport.

## What the package contains

`-DumpFFU` produced:

| partition | size |
|---|---|
| EFIESP.bin | 32 MB |
| UEFI.bin | 2 MB |
| UEFI_BS_NV.bin | 0.2 MB |
| SYSTEM.bin | 100 MB |
| Data.bin | 29,548 MB |
| IS_UNLOCKED.bin | 0 (empty) |
| PLAT / TZ / TZAPPS / RPM / SBL1 / PMIC / WINSECAPP / HYP / LogFS | small |

`IS_UNLOCKED.bin` being empty is consistent with a package designed for a locked phone.

## The EFIESP contents, read with a small FAT reader

| file | bytes | sha256 (first 16) |
|---|---|---|
| `UEFI.ELF` | 1,114,880 | `68b5ff0ea9ee0487` |
| `EFI\REFIND\refind_aa64.efi` | 202,624 | — |
| `EFI\REFIND\refind.conf` | 217 | `966583e81ec45755` |
| `EFI\MICROS~1\BOOT\BCD` | 28,672 | `670b582ba7a5b9a6` |
| `EFI\BOOT\BOOTARM.EFI` | 870,856 | — |

`UEFI.ELF` here is a **fifth version**, different from every build tried so far (2.24b `00420de9…`,
2.23-b `a90e9521…`, 2.22 `a4b94ecd…`, 2.21-c `ad6f791b…`). All five ELF headers are identical
(`entry=0x200000`, one load segment at `0x200000`, 1 MiB), so the differences are inside the code.

The boot manager is **rEFInd**, configured with `timeout 0`, `enable_touch`, and
`scanfor internal,external,optical,manual`.

## The finding that matters: where the boot chain really puts BootShim

`bcdedit /store <extracted BCD> /enum all` on the package's own store shows:

```
{bootmgr}   path \efi\boot\bootarm.efi        default {default}   bootsequence {01de5a27-…}
{default}   path \windows\system32\boot\bootshim.efi   "BootShim Application"   nointegritychecks Yes
{01de5a27-…} \windows\system32\boot\mobilestartup.efi  "Mobile Startup App"
{0ff5f24a-…} \windows\system32\boot\ffuloader.efi      "FFU Loader (User Invoked)"
{bd8951c4-…} (developer menu related)
```

and the same store carries the strings `\windows\system32\boot\developermenu.efi` and
"Developer Menu Application".

So the working arrangement on this hardware is:

```
firmware -> \efi\boot\bootarm.efi (bootmgr)
         -> {default} = \windows\system32\boot\bootshim.efi     on MainOS, not on EFIESP
         -> bootshim loads UEFI.elf from the EFIESP root
         -> UEFI.elf starts EFI\REFIND\refind_aa64.efi (or EFI\BOOT\bootaa64.efi)
```

Every attempt made before this note put `BootShim.efi` on EFIESP (`\EFI\boot\`) and pointed `{default}`
at an EFIESP device path. The reference image does the opposite: **BootShim lives in
`\Windows\System32\Boot\bootshim.efi` on MainOS**, and `{default}` is an ordinary Windows-style
application entry whose device is the OS partition.

## What is still missing

The `bootshim.efi` and `developermenu.efi` binaries themselves are not in the EFIESP image; a scan of
`SYSTEM.bin` finds `bootmgfw` and `winload.efi` but not `bootshim.efi`, so they live on the Windows
partition (`Data.bin`, 29.5 GB). Extracting them needs either an NTFS mount of that image or an
equivalent copy of the WOAA "UEFI Loader for 8992 and 8994" artifact, which the public Azure DevOps
project does not serve without credentials.

## Consequences for the port

1. The BCD layout to copy is now known exactly; no guessing is needed.
2. `UEFI.ELF` `68b5ff0e…` is a candidate worth testing before any other version.
3. The shim and the developer menu belong on MainOS, which also means a file copy to `F:\Windows\System32\Boot\`
   rather than to EFIESP.
4. `scripts/phone-image.py` can capture MainOS, so this arrangement is reproducible once it works.

## The layout is now checked, not eyeballed

`scripts/check-bcd-layout.py` reads the output of `bcdedit /store <store> /enum all` (it decodes the
console code page, UTF-16 and UTF-8) and decides whether the store starts what it should:

```
python scripts/check-bcd-layout.py --enum-file bcd.txt --expect mainos   # shim on MainOS
python scripts/check-bcd-layout.py --enum-file bcd.txt --expect efiesp   # shim under EFI\boot
python scripts/check-bcd-layout.py --enum-file bcd.txt --expect windows  # plain Windows loader
```

Run against this image's own enumeration it reports
`layout ok: the store starts \windows\system32\boot\bootshim.efi` over 11 parsed entries. Run against the
layout this session actually used (`{default}` pointing at `\EFI\boot\BootShim.efi`) it fails with the
mismatch and prints the three `bcdedit` commands that fix it. Four host tests cover both directions.

## Correction: the 42,976-byte module is a driver, not a boot shim

An earlier attempt placed `8AF09F13-��efi` from the UEFI package at the shim path and the phone rebooted
into the Windows reset flow. Its PE header explains why:

| binary | bytes | subsystem |
|---|---|---|
| `8AF09F13-��efi` (UEFI package) | 42,976 | **0x0B** boot service driver |
| `SJM\Core\Boot\bootaa64.efi` | 1,508,816 | **0x0A** EFI application |
| rEFInd `refind_aa64.efi` | 202,624 | 0x0A |
| GRUB `bootaa64.efi` | 878,544 | 0x0A |

The boot manager only starts EFI applications, so a driver at `{default}` fails and the firmware falls
back to `bootsequence` -> `mobilestartup.efi`, which is the two-gear reset flow seen on the panel.
`phone-install.py` now refuses to place anything but subsystem 0x0A on a boot path, and two host tests
cover the driver refusal and the application acceptance.
