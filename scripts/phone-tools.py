#!/usr/bin/env python3
"""Locate the flashing tools this port uses, without committing any of them.

The binaries belong to other projects (WPinternals, Microsoft's thor2/ffutool, Qualcomm's emmcdl) and
none of them may live in this repository, so the checkout keeps the *knowledge of where they are* and
prints a hash for each one it finds. Two sources are searched:

  1. explicit overrides: --tool-name PATH, or the environment variable PHONE_TOOL_<NAME>
  2. the usual install locations on this machine (the WPinternals download folder and the SJM install)

    python scripts/phone-tools.py            # table of what was found and its SHA-256
    python scripts/phone-tools.py --json     # same, machine readable
    python scripts/phone-tools.py --require thor2 ffutool   # exit 1 if either is missing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

# name -> candidate locations, in the order they are tried
CANDIDATES = {
    "wpinternals": [
        Path(r"C:\Program Files\chengcong\SJM\WPI\WPinternals.exe"),
        Path(r"C:\Program Files\chengcong\SJM\WPI\SJMWPinternals.exe"),
        Path(r"C:\Users\Administrator\Downloads\win-x64\WPinternals.exe"),
    ],
    "thor2": [
        Path(r"C:\Program Files\chengcong\SJM\WPI\thor2.exe"),
        Path(r"C:\Program Files (x86)\Microsoft Care Suite\Windows Device Recovery Tool\thor2.exe"),
    ],
    "ffutool": [
        Path(r"C:\Program Files\chengcong\SJM\WPI\ffutool.exe"),
    ],
    "emmcdl": [
        Path(r"C:\Program Files\chengcong\SJM\WPI\Qualcomm\emmcdl.exe"),
    ],
    "img2ffu": [
        Path(r"C:\Program Files\chengcong\SJM\Img2Ffu.exe"),
    ],
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find(name: str) -> Path | None:
    override = os.environ.get("PHONE_TOOL_" + name.upper())
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None
    for candidate in CANDIDATES.get(name, []):
        if candidate.is_file():
            return candidate
    return shutil.which(name + ".exe") and Path(shutil.which(name + ".exe"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require", nargs="*", default=[], metavar="NAME",
                        help="exit non-zero unless every named tool is found")
    args = parser.parse_args(argv)

    found = {}
    for name in sorted(CANDIDATES):
        path = find(name)
        if path is None:
            found[name] = None
            continue
        found[name] = {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}

    if args.json:
        print(json.dumps(found, indent=2))
    else:
        for name in sorted(found):
            record = found[name]
            if record is None:
                print(f"{name:12} MISSING  (set PHONE_TOOL_{name.upper()} or install it)")
            else:
                print(f"{name:12} {record['bytes']:>10} B  sha256 {record['sha256'][:16]}  {record['path']}")

    missing = [name for name in args.require if found.get(name) is None]
    if missing:
        print(f"error: required tool(s) not found: {', '.join(missing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
