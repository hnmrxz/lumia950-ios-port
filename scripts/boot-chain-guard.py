#!/usr/bin/env python3
"""The boot chain's protected objects, and one place that decides what may write them.

The handset's chain runs today and the whole point of the protection rules is that nothing in this repository can quietly break it.
Six classes of object are protected:

    EFI\\boot\\bootarm.efi            the firmware's own ARM32 boot manager (also what provides mass storage mode)
    EFI\\boot\\BootShim.efi           the ARM32 shim the deployment tools install
    UEFI.elf                          the LumiaWoA AArch64 UEFI at the EFIESP root
    EFI\\Microsoft\\BOOT\\BCD         the unlocked boot store
    EFI\\BOOT\\BOOTAA64.EFI           what the custom UEFI starts: this port's loader
    EFI\\UniXNU\\**                   the loader's own tree (menu, config, drivers, payloads)

The rule is deliberately narrow and mechanical, because a rule with exceptions is the thing that gets bypassed:

  * creating a protected path on a blank volume is allowed -- there is nothing to destroy;
  * *replacing* one requires `--replace-protected` *and* a backup that exists, and the caller has to have read the value it is
    replacing;
  * nothing may lower that bar by deleting a file first, emptying a directory, or editing the recorded hashes;
  * `EFI\\UniXNU` is protected as a whole, because replacing one file in it invalidates the hand-off evidence for all of it.

    python scripts/boot-chain-guard.py check --root R: --path EFI/BOOT/BOOTAA64.EFI
    python scripts/boot-chain-guard.py inventory --root R: --out out/phone-backups/chain-inventory.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# path (case-folded, forward slashes) -> why it is protected
PROTECTED = {
    "efi/boot/bootarm.efi": "the firmware's ARM32 boot manager; replacing it stops mass storage mode too",
    "efi/boot/bootshim.efi": "the ARM32 shim the deployment tools install and the store points at",
    "uefi.elf": "the LumiaWoA AArch64 UEFI the shim chainloads",
    "efi/microsoft/boot/bcd": "the unlocked boot store; editing it has produced the Windows reset loop",
    "efi/boot/bootaa64.efi": "what the custom UEFI starts; the entry point of this port's loader",
}
PROTECTED_TREE = "efi/unixnu"


def normalise(path: str) -> str:
    return path.replace("\\", "/").strip("/").casefold()


def classify(relative: str) -> tuple[bool, str]:
    """Is this path protected, and why?"""
    name = normalise(relative)
    if name in PROTECTED:
        return True, PROTECTED[name]
    if name == PROTECTED_TREE or name.startswith(PROTECTED_TREE + "/"):
        return True, "the loader's own tree; replacing one file invalidates the hand-off evidence for all of it"
    return False, "not a protected boot-chain object"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root: Path) -> dict:
    """Read-only: what the six classes look like on this volume right now."""
    files = {}

    def record(path: Path) -> None:
        # the key keeps the casing the volume uses; callers compare through normalise() when case matters
        key = path.relative_to(root).as_posix()
        files[key] = {"bytes": path.stat().st_size, "sha256": digest(path)}

    for name in PROTECTED:
        found = None
        for candidate in root.rglob("*"):
            if candidate.is_file() and normalise(candidate.relative_to(root).as_posix()) == name:
                found = candidate
                break
        if found is not None:
            record(found)
    tree = next((entry for entry in root.iterdir() if entry.is_dir() and entry.name.casefold() == "efi"))
    unixnu = tree / "UniXNU" if tree else None
    if unixnu is not None and unixnu.is_dir():
        for path in sorted(unixnu.rglob("*")):
            if path.is_file():
                files[path.relative_to(root).as_posix()] = {
                    "bytes": path.stat().st_size,
                    "sha256": digest(path),
                }
    return {"root": str(root), "files": files}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("check", "inventory", "list"))
    parser.add_argument("--root", type=Path, help="the mounted EFIESP volume")
    parser.add_argument("--path", help="a path relative to the volume, for 'check'")
    parser.add_argument("--out", type=Path, help="where 'inventory' writes its JSON")
    parser.add_argument("--backup", type=Path, help="a verified backup that makes a protected write acceptable")
    parser.add_argument("--replace-protected", action="store_true",
                        help="acknowledge that a protected object is being replaced; still requires --backup")
    args = parser.parse_args(argv)

    if args.action == "list":
        for name, why in sorted(PROTECTED.items()):
            print(f"protected  {name:32s} {why}")
        print(f"protected  {PROTECTED_TREE + '/**':32s} the loader's own tree")
        return 0

    if args.action == "check":
        if not args.path:
            print("error: --path is required for check", file=sys.stderr)
            return 2
        protected, why = classify(args.path)
        if not protected:
            print(f"allowed: {args.path} is {why}")
            return 0
        exists = args.root is not None and (args.root / args.path).exists()
        if not exists and args.root is not None:
            print(f"allowed: {args.path} is protected, but it does not exist on this volume -- nothing to replace")
            return 0
        if args.replace_protected and args.backup and args.backup.is_file():
            print(f"allowed (with backup {args.backup}): {args.path} is protected -- {why}")
            return 0
        print(f"refused: {args.path} is protected -- {why}")
        print("         a protected object may only be written with --replace-protected and a backup that verifies")
        return 1

    if not args.root or not args.root.is_dir():
        print("error: --root must be a mounted EFIESP volume", file=sys.stderr)
        return 2
    report = inventory(args.root)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"{args.out}: {len(report['files'])} protected files recorded")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
