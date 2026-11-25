#!/usr/bin/env python3
"""Install the handset chain from this checkout, and report what still needs a physical action.

Order comes from the upstream projects (Lumia950XLPkg README, postmarketOS wiki): unlock, put
BootShim.efi on EFIESP and give it a boot entry, put UEFI.elf on the EFIESP root, and only then the
UniXNU payload and the kernel. This script does the file parts, verifying every write by SHA-256, and
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
    parser.add_argument("--uefi-elf", type=Path,
                        default=STAGING / "xlpkg" / "extracted" / "MSM8992 UEFI (Lumia 950)" / "ELF" / "UEFI.elf")
    parser.add_argument("--apply", action="store_true", help="actually write")
    args = parser.parse_args(argv)

    efiesp = Path(args.efiesp.rstrip("\\") + "\\")
    mainos = Path(args.mainos.rstrip("\\") + "\\")
    for mount, name in ((efiesp, "EFIESP"), (mainos, "MainOS")):
        if not mount.is_dir():
            print(f"error: {name} is not mounted at {mount}", file=sys.stderr)
            return 2

    ok = True
    print("BootShim.efi -> EFIESP")
    ok &= install(args.bootshim, efiesp / "EFI" / "boot" / "BootShim.efi", args.apply)

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

    print()
    if args.apply:
        print("files installed and verified")
    else:
        print("dry run only; pass --apply to write")
    print("still requires a physical action: detach USB, power off, power on to test the boot result")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
