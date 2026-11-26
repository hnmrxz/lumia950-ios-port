#!/usr/bin/env python3
"""Swap the file the firmware boots for the control mark, with a verified backup.

The control mark answers one question the kernel cannot answer about itself: is this panel writable at these
coordinates by our own code? To ask it on the handset, the firmware has to start our application instead of the
loader, so this replaces EFI/BOOT/BOOTAA64.EFI -- a file this port wrote, never the deployment tool's BootShim or
UEFI.elf -- and keeps the previous file next to it as BOOTAA64.EFI.before-control-mark.

    python scripts/swap-loader.py --efiesp R: --show
    python scripts/swap-loader.py --efiesp R: --control-mark out/control-mark-deploy/BOOTAA64.EFI --apply
    python scripts/swap-loader.py --efiesp R: --restore

Every step verifies SHA-256 in both directions, and --restore puts the backed-up loader back.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

LOADER = Path("EFI") / "BOOT" / "BOOTAA64.EFI"
BACKUP = Path("EFI") / "BOOT" / "BOOTAA64.EFI.before-control-mark"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def describe(path: Path) -> str:
    if not path.is_file():
        return f"{path}: absent"
    return f"{path}: {path.stat().st_size} B  sha256 {digest(path)[:16]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--efiesp", default="R:", help="the EFIESP volume, for example R:")
    parser.add_argument("--control-mark", type=Path, help="the application to install as the boot option")
    parser.add_argument("--apply", action="store_true", help="install the control mark (needs --control-mark)")
    parser.add_argument("--restore", action="store_true", help="put the backed-up loader back")
    parser.add_argument("--show", action="store_true", help="report the current state and do nothing else")
    args = parser.parse_args(argv)

    volume = Path(args.efiesp.rstrip("\\/") + "\\")
    if not volume.is_dir():
        print(f"error: EFIESP is not mounted at {volume}", file=sys.stderr)
        return 2
    loader = volume / LOADER
    backup = volume / BACKUP

    print(describe(loader))
    print(describe(backup))

    if args.show or (not args.apply and not args.restore):
        return 0

    if args.restore:
        if not backup.is_file():
            print("error: no backup to restore", file=sys.stderr)
            return 1
        wanted = digest(backup)
        shutil.copy2(backup, loader)
        if digest(loader) != wanted:
            print("error: the restored file does not hash to the backup", file=sys.stderr)
            return 1
        print(f"restored: {loader}  sha256 {wanted[:16]}")
        return 0

    if not args.control_mark or not args.control_mark.is_file():
        print("error: --apply needs --control-mark pointing at an existing .efi", file=sys.stderr)
        return 2
    if not backup.is_file():
        shutil.copy2(loader, backup)
        if digest(backup) != digest(loader):
            print("error: the backup does not match the loader it copied", file=sys.stderr)
            return 1
        print(f"backed up: {backup}  sha256 {digest(backup)[:16]}")

    wanted = digest(args.control_mark)
    shutil.copy2(args.control_mark, loader)
    if digest(loader) != wanted:
        print("error: the installed file does not match the control mark", file=sys.stderr)
        return 1
    print(f"installed: {loader}  sha256 {wanted[:16]}")
    print("boot the phone: two bars near the top mean the panel takes our writes; power-cycle afterwards, the")
    print("control mark holds the screen on purpose. Restore with --restore.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
