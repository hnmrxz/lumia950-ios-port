#!/usr/bin/env python3
"""Copy the staged MainOS payload (`EFI/UniXNU/Payloads`) to a connected Lumia 950.

The split this works with is the one `stage-kernel.py --payload-out` produces: the menu, its
configuration and the drivers live on EFIESP (already installed), and the kernel with its sidecars
lives on MainOS, because the prelinked image is about 56 MB while EFIESP is 32 MB. Windows mounts
MainOS as a drive letter (the handset reports it as `MainOS`, NTFS), so `--phone F:\\` addresses it.

Every write is verified by re-reading the file and comparing SHA-256; `--dry-run` is the default and
prints exactly what would be written. `--restore` puts back the copies `--apply` keeps.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

DESTINATION = Path("EFI") / "UniXNU" / "Payloads"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True,
                        help="stage tree holding EFI/UniXNU/Payloads (from stage-kernel.py)")
    parser.add_argument("--phone", type=Path, required=True,
                        help="MainOS root of the connected handset, for example F:\\\\")
    parser.add_argument("--apply", action="store_true",
                        help="write the files; without it only the plan is printed")
    parser.add_argument("--backup", type=Path, default=None,
                        help="directory that keeps the replaced files (default: <phone>/Payloads.previous)")
    args = parser.parse_args(argv)

    source = args.stage / DESTINATION
    if not source.is_dir():
        print(f"error: {source} is missing; stage with --payload-out first", file=sys.stderr)
        return 2
    if not args.phone.is_dir():
        print(f"error: {args.phone} is not a directory", file=sys.stderr)
        return 2

    target = args.phone / DESTINATION
    backup = args.backup or (args.phone / "EFI" / "UniXNU" / "Payloads.previous")
    files = sorted(path for path in source.rglob("*") if path.is_file())
    if not files:
        print(f"error: {source} holds no files", file=sys.stderr)
        return 2

    print(f"source: {source}")
    print(f"target: {target}")
    for path in files:
        relative = path.relative_to(source)
        destination = target / relative
        print(f"  {relative}  {path.stat().st_size} bytes  sha256 {digest(path)[:16]}")
        if not args.apply:
            continue
        if destination.exists():
            keep = backup / relative
            keep.parent.mkdir(parents=True, exist_ok=True)
            if not keep.exists():
                shutil.copy2(destination, keep)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        if digest(destination) != digest(path):
            print(f"error: {destination} did not verify after the write", file=sys.stderr)
            return 1
    if args.apply:
        print(f"installed {len(files)} file(s); replaced copies (if any) are in {backup}")
    else:
        print("dry run only; pass --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
