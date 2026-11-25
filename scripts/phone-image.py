#!/usr/bin/env python3
"""Dump and restore the handset's boot-critical partitions as raw images.

The phone shows up in mass storage mode as volumes, and those volume handles can be read directly, so
the two partitions the unlock patches live on (EFIESP and MainOS) can be captured as raw images. With
them, a bad boot experiment is undone by `-FlashPartition` in flash mode -- no SIM-free re-unlock through
the vendor utility, which is what made every recovery cycle expensive.

    python scripts/phone-image.py dump --volume R: --out out/phone-backups/unlocked-efiesp.img
    python scripts/phone-image.py verify --volume R: --image out/phone-backups/unlocked-efiesp.img
    python scripts/phone-image.py restore --partition EFIESP --image ... --apply

Restore prints the exact WPinternals command; it only runs it with --apply, and it never guesses a
partition name.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

CHUNK = 1 << 20


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def dump(args) -> int:
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = rf"\\.\{args.volume.rstrip(':')}:"
    h = hashlib.sha256()
    total = 0
    try:
        source = open(handle, "rb", buffering=0)
    except OSError as exc:
        print(f"error: cannot open {handle}: {exc}", file=sys.stderr)
        return 2
    with source, target.open("wb") as sink:
        while True:
            block = source.read(CHUNK)
            if not block:
                break
            sink.write(block)
            h.update(block)
            total += len(block)
            if args.progress and total % (64 * CHUNK) == 0:
                print(f"  {total // CHUNK} MiB", file=sys.stderr)
    print(f"{target} {total} bytes sha256 {h.hexdigest()}")
    return 0


def verify(args) -> int:
    image = Path(args.image)
    if not image.is_file():
        print(f"error: {image} is missing", file=sys.stderr)
        return 2
    handle = rf"\\.\{args.volume.rstrip(':')}:"
    expected = digest_file(image)
    h = hashlib.sha256()
    read = 0
    with open(handle, "rb", buffering=0) as source:
        for block in iter(lambda: source.read(CHUNK), b""):
            h.update(block)
            read += len(block)
    actual = h.hexdigest()
    print(f"image {expected[:16]}  device {actual[:16]}  bytes {read}")
    print("match" if expected == actual else "MISMATCH")
    return 0 if expected == actual else 1


def restore(args) -> int:
    image = Path(args.image)
    if not image.is_file():
        print(f"error: {image} is missing", file=sys.stderr)
        return 2
    tool = Path(r"C:\Users\Administrator\Downloads\win-x64\WPinternals.exe")
    ffu = Path(args.ffu)
    command = [str(tool), "-FlashPartition", args.partition, str(image)]
    if ffu.is_file():
        command.append(str(ffu))
    print("$ " + " ".join(f'"{part}"' if " " in part else part for part in command))
    print("run this with the phone in flash mode (Volume Down + power); it writes one partition only")
    if not args.apply:
        print("dry run: pass --apply to run it")
        return 0
    return subprocess.call(command)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_dump = sub.add_parser("dump", help="read a mounted volume into a raw image")
    p_dump.add_argument("--volume", required=True, help="drive letter, for example R:")
    p_dump.add_argument("--out", required=True)
    p_dump.add_argument("--progress", action="store_true")
    p_dump.set_defaults(func=dump)

    p_verify = sub.add_parser("verify", help="compare a mounted volume against an image")
    p_verify.add_argument("--volume", required=True)
    p_verify.add_argument("--image", required=True)
    p_verify.set_defaults(func=verify)

    p_restore = sub.add_parser("restore", help="flash one partition from an image, in flash mode")
    p_restore.add_argument("--partition", required=True)
    p_restore.add_argument("--image", required=True)
    p_restore.add_argument("--ffu", default=r"C:\Users\Administrator\Downloads\RM1105_1078.0053.10586.13169.12716.035044_retail_prod_signed(1).ffu")
    p_restore.add_argument("--apply", action="store_true")
    p_restore.set_defaults(func=restore)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
