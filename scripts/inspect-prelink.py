#!/usr/bin/env python3
"""Read the prelink information out of a merged kernel image.

The merged image carries a `__PRELINK_INFO` segment whose content is a plist with `_PrelinkInfoDictionary`: one entry per
kext, each naming where its executable was placed and what its kmod record address became. Reading it is the first step of
any attempt to put a kext of ours into that list -- and it is readable without understanding the whole prelinker, so it can
be done and tested before committing to the work ADR-0003 describes.

    python scripts/inspect-prelink.py out/prelinked-test/kernel.macho
    python scripts/inspect-prelink.py <image> --json
"""

from __future__ import annotations

import argparse
import json
import plistlib
import re
import struct
import sys
from pathlib import Path

MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
PRELINK_INFO_SEGMENT = "__PRELINK_INFO"


def segments(blob: bytes) -> list[dict]:
    if len(blob) < 32:
        raise ValueError("shorter than a Mach-O header")
    magic, _cpu, _sub, _filetype, ncmds, _sizeofcmds, _flags, _res = struct.unpack_from("<IiiIIIII", blob, 0)
    if magic != MH_MAGIC_64:
        raise ValueError(f"not a little-endian Mach-O 64 (magic 0x{magic:08X})")

    found: list[dict] = []
    offset = 32
    for _ in range(ncmds):
        command, length = struct.unpack_from("<II", blob, offset)
        if command == LC_SEGMENT_64:
            name = blob[offset + 8: offset + 24].rstrip(b"\0").decode("utf-8", "replace")
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", blob, offset + 24)
            found.append({"name": name, "vmaddr": vmaddr, "vmsize": vmsize,
                          "fileoff": fileoff, "filesize": filesize})
        offset += length
    return found


def prelink_info(blob: bytes) -> tuple[bytes, list[dict]]:
    table = segments(blob)
    segment = next((entry for entry in table if entry["name"] == PRELINK_INFO_SEGMENT), None)
    if segment is None:
        raise ValueError(f"no {PRELINK_INFO_SEGMENT} segment")
    start = segment["fileoff"]
    end = start + segment["filesize"]
    if start >= len(blob) or end > len(blob):
        raise ValueError("the prelink info segment points outside the file")
    return blob[start:end], table


def parse_dictionary(payload: bytes) -> dict:
    """The emitter stores an XML plist *fragment*: it starts at <dict> and has no plist wrapper, and its integers are
    written as hex with a size attribute. Both are normalised here so a standard plist parser can read it."""
    text = payload.rstrip(b"\0").decode("utf-8", "replace")
    if "<?xml" not in text:
        text = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                '<plist version="1.0">' + text + "</plist>")
    # <integer size="64">0xfffffff004004000</integer> is not valid plist; convert to decimal
    def to_decimal(match: "re.Match[str]") -> str:
        return "<integer>" + str(int(match.group(1), 16)) + "</integer>"

    text = re.sub(r'<integer[^>]*>\s*0x([0-9a-fA-F]+)\s*</integer>', to_decimal, text)
    text = re.sub(r'<integer[^>]*>', "<integer>", text)
    parsed = plistlib.loads(text.encode("utf-8"))
    if "_PrelinkInfoDictionary" not in parsed:
        raise ValueError("the plist has no _PrelinkInfoDictionary")
    return parsed


def summarise(parsed: dict) -> list[dict]:
    rows = []
    for entry in parsed["_PrelinkInfoDictionary"]:
        rows.append({
            "id": entry.get("CFBundleIdentifier", "?"),
            "load_addr": entry.get("_PrelinkExecutableLoadAddr"),
            "size": entry.get("_PrelinkExecutableSize"),
            "kmod_info": entry.get("_PrelinkKmodInfo"),
            "path": entry.get("_PrelinkBundlePath"),
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", type=Path)
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args(argv)

    if not args.image.is_file():
        print(f"error: no image at {args.image}", file=sys.stderr)
        return 2
    blob = args.image.read_bytes()
    try:
        payload, table = prelink_info(blob)
        parsed = parse_dictionary(payload)
    except ValueError as error:
        print(f"FAIL {args.image}: {error}")
        return 1

    rows = summarise(parsed)
    if args.json:
        print(json.dumps({"image": str(args.image), "segments": [entry["name"] for entry in table],
                          "kexts": rows}, indent=2))
        return 0

    print(f"{args.image}: {len(rows)} prelinked kexts, prelink info segment {len(payload)} bytes")
    for row in rows:
        load = f"0x{row['load_addr']:x}" if isinstance(row["load_addr"], int) else "?"
        size = f"0x{row['size']:x}" if isinstance(row["size"], int) else "?"
        print(f"  {row['id']:60s} load={load:>18s} size={size:>10s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
