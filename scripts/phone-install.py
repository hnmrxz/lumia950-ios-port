#!/usr/bin/env python3
r"""Install the handset chain from this checkout, and report what still needs a physical action.

Order comes from the upstream projects (Lumia950XLPkg README, postmarketOS wiki): unlock, put
BootShim.efi and give it a boot entry, put UEFI.elf on the EFIESP root, and only then the UniXNU payload
and the kernel. The shim's location is not the obvious one: the Lumia deployment scripts put it at
`\Windows\System32\Boot\bootshim.efi` on MainOS and point the store's `{default}` at it, which is what
the reference WOA image on this machine does (docs/hardware/2026-11-25-woa-ffu-reference.md). `--layout
efiesp` keeps the older placement for comparison. This script does the file parts, verifying every write by SHA-256, and
prints the boot entries and the one action it cannot perform (a power press).

    python scripts/phone-install.py --efiesp R: --mainos F: --stage efiesp --payload mainos --dry-run
    python scripts/phone-install.py --efiesp R: --mainos F: --stage efiesp --payload mainos --apply
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGING = ROOT.parent / "out"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(src: Path, dst: Path, apply: bool) -> bool:
    print(f"  {src.name:32} {src.stat().st_size:>10} B  sha256 {digest(src)[:16]}")
    if not apply:
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if digest(dst) != digest(src):
        print(f"error: {dst} did not verify after the write", file=sys.stderr)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--efiesp", required=True, help="EFIESP mount, for example R:")
    parser.add_argument("--mainos", required=True, help="MainOS mount, for example F:")
    parser.add_argument("--stage", type=Path, default=STAGING / "new-payload",
                        help="payload tree holding EFI/UniXNU")
    parser.add_argument("--payload", type=Path, default=STAGING / "redeploy-mainos",
                        help="staged MainOS tree holding EFI/UniXNU/Payloads")
    parser.add_argument("--bootshim", type=Path, default=STAGING / "bootshim" / "elf-loader-pre3" / "BootShim.efi")
    parser.add_argument("--layout", choices=("mainos", "efiesp"), default="mainos",
                        help="mainos puts the shim at \\Windows\\System32\\Boot\\bootshim.efi as the Lumia "
                             "deployment scripts and the reference WOA image do; efiesp keeps the older "
                             "placement under EFI\\boot")
    parser.add_argument("--refind", type=Path, default=None,
                        help="optional rEFInd tree to copy to EFIESP\\EFI\\REFIND")
    parser.add_argument("--uefi-elf", type=Path,
                        default=STAGING / "xlpkg" / "extracted" / "MSM8992 UEFI (Lumia 950)" / "ELF" / "UEFI.elf")
    parser.add_argument("--apply", action="store_true", help="actually write")
    args = parser.parse_args(argv)

    efiesp = Path(args.efiesp.rstrip("\\/"))
    mainos = Path(args.mainos.rstrip("\\/"))
    for mount, name in ((efiesp, "EFIESP"), (mainos, "MainOS")):
        if not mount.is_dir():
            print(f"error: {name} is not mounted at {mount}", file=sys.stderr)
            return 2

    ok = True
    if args.layout == "mainos":
        shim_destination = mainos / "Windows" / "System32" / "Boot" / "bootshim.efi"
        print(r"BootShim.efi -> MainOS\Windows\System32\Boot")
    else:
        shim_destination = efiesp / "EFI" / "boot" / "BootShim.efi"
        print("BootShim.efi -> EFIESP\\EFI\\boot")
    ok &= install(args.bootshim, shim_destination, args.apply)

    print("UEFI.elf -> EFIESP root")
    ok &= install(args.uefi_elf, efiesp / "UEFI.elf", args.apply)

    print("UniXNU payload -> EFIESP")
    for name in ("UniXNU.efi", "unixnu.toml"):
        source = args.stage / "EFI" / "UniXNU" / name
        if source.is_file():
            ok &= install(source, efiesp / "EFI" / "UniXNU" / name, args.apply)
    drivers = args.stage / "EFI" / "UniXNU" / "Drivers"
    if drivers.is_dir():
        for source in sorted(drivers.iterdir()):
            if source.is_file():
                ok &= install(source, efiesp / "EFI" / "UniXNU" / "Drivers" / source.name, args.apply)

    print("kernel and device tree -> MainOS")
    payloads = args.payload / "EFI" / "UniXNU" / "Payloads"
    if payloads.is_dir():
        for source in sorted(payloads.iterdir()):
            if source.is_file():
                ok &= install(source, mainos / "EFI" / "UniXNU" / "Payloads" / source.name, args.apply)
    else:
        print("  (no staged kernel; run scripts/stage-kernel.py --payload-out first)")

    if args.refind:
        if not args.refind.is_dir():
            print(f"error: --refind {args.refind} is not a directory", file=sys.stderr)
            ok = False
        else:
            print("rEFInd -> EFIESP\\EFI\\REFIND")
            for source in sorted(args.refind.rglob("*")):
                if source.is_file():
                    relative = source.relative_to(args.refind)
                    ok &= install(source, efiesp / "EFI" / "REFIND" / relative, args.apply)

    print()
    if args.apply:
        print("files installed and verified")
    else:
        print("dry run only; pass --apply to write")
    if args.layout == "mainos":
        print()
        print("the shim is on MainOS, so the store has to point at it (run these elevated):")
        print(r"  bcdedit /store <EFIESP>:\\EFI\\Microsoft\\BOOT\\BCD /set {default} device partition=<MainOS>:")
        print(r"  bcdedit /store <EFIESP>:\\EFI\\Microsoft\\BOOT\\BCD /set {default} path \\windows\\system32\\boot\\bootshim.efi")
        print(r"  bcdedit /store <EFIESP>:\\EFI\\Microsoft\\BOOT\\BCD /set {default} description \"BootShim Application\"")
    print("still requires a physical action: detach USB, power off, power on to test the boot result")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
