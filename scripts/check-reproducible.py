#!/usr/bin/env python3
"""Compare two builds of the same commit and name every difference.

Two runs of one commit (43885772410 and 43887531094) produced kernels with different SHA-256s.
This script is the judge for docs/phases/p0-exit.json P0.3, which accepts a named difference
instead of two identical hashes -- but only a named one.

Measured on that pair, every differing byte falls into one of three classes:

* the 16-byte Mach-O LC_UUID, which the linker randomises per link;
* the kernel's own version banner in __TEXT,__const, which carries the build time
  ("... Mon Nov 16 14:35:00 UTC 2026; runner@..." -- XNU's version.c uses __DATE__/__TIME__);
* timestamps inside the debug information and the symbol tables, which are not loaded.

Anything else fails, so the next source of non-determinism shows up as a failure instead of as
"the hashes just differ".

    python3 scripts/check-reproducible.py --a out/a/mach.development.bcm2837.unstripped \
                                         --b out/b/mach.development.bcm2837.unstripped
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

LC_UUID = 0x1B
LC_SEGMENT_64 = 0x19
# Segments that are mapped into the running kernel. A difference in one of these has to be the
# version banner, or it is a real behavioural difference between the two builds.
LOADABLE_SEGMENTS = ("__TEXT", "__DATA", "__DATA_CONST", "__LINKEDIT_RESERVED")
TIME_NEEDLES = (b"UTC ", b" GMT")


def fail(message: str):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def layout(blob: bytes) -> tuple[list[tuple[int, int]], list[tuple[int, int, str]]]:
    if len(blob) < 32:
        fail(f"not a thin Mach-O ({len(blob)} bytes); pass a built kernel image")
    magic, _, _, _, ncmds, _, _, _ = struct.unpack_from("<8I", blob, 0)
    if magic not in (0xFEEDFACF, 0xFEEDFACE):
        fail(f"not a thin Mach-O (magic {magic:#x}); pass one architecture's image")
    uuids, sections = [], []
    offset = 32
    for _ in range(ncmds):
        command, size = struct.unpack_from("<II", blob, offset)
        if command == LC_UUID:
            uuids.append((offset + 8, offset + 8 + 16))
        elif command == LC_SEGMENT_64:
            segment = blob[offset + 8:offset + 24].split(b"\0")[0].decode("ascii", "replace")
            count = struct.unpack_from("<I", blob, offset + 64)[0]
            section_offset = offset + 72
            for _ in range(count):
                name = blob[section_offset:section_offset + 16].split(b"\0")[0].decode("ascii", "replace")
                section_size = struct.unpack_from("<Q", blob, section_offset + 40)[0]
                file_offset = struct.unpack_from("<I", blob, section_offset + 48)[0]
                sections.append((file_offset, file_offset + section_size, f"{segment},{name}"))
                section_offset += 80
        offset += size
    return uuids, sections


def differing_ranges(a: bytes, b: bytes) -> list[tuple[int, int]]:
    ranges, start = [], None
    for index in range(min(len(a), len(b))):
        if a[index] != b[index]:
            if start is None:
                start = index
        elif start is not None:
            ranges.append((start, index))
            start = None
    if start is not None:
        ranges.append((start, min(len(a), len(b))))
    return ranges


def containing(range_: tuple[int, int], sections) -> str | None:
    start, end = range_
    for section_start, section_end, name in sections:
        if start >= section_start and end <= section_end:
            return name
    return None


def near_time_string(blob: bytes, range_: tuple[int, int], window: int = 64) -> bool:
    start, end = range_
    context = blob[max(0, start - window):min(len(blob), end + window)]
    return any(needle in context for needle in TIME_NEEDLES)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--a", type=Path, required=True, help="first image")
    parser.add_argument("--b", type=Path, required=True, help="second image")
    args = parser.parse_args()

    a, b = args.a.read_bytes(), args.b.read_bytes()
    if len(a) != len(b):
        fail(f"{args.a} is {len(a)} bytes and {args.b} is {len(b)}; two builds of one commit have "
             "the same layout, so a size difference is not a rebuild")
    if a == b:
        print(f"reproducible: {args.a} and {args.b} are identical")
        return 0

    uuids, sections = layout(a)
    if not uuids:
        fail(f"{args.a} has no LC_UUID; there is nothing to attribute a UUID difference to")
    counts = {"uuid": 0, "banner": 0, "debug": 0}
    unexplained = []
    for range_ in differing_ranges(a, b):
        length = range_[1] - range_[0]
        if any(range_[0] >= start and range_[1] <= end for start, end in uuids):
            counts["uuid"] += length
            continue
        name = containing(range_, sections)
        if name is None or not name.startswith(LOADABLE_SEGMENTS):
            counts["debug"] += length
            continue
        if near_time_string(a, range_):
            counts["banner"] += length
            continue
        unexplained.append((range_, name))
    if unexplained:
        for (start, end), name in unexplained[:10]:
            print(f"error: unexplained difference at [{start:#x}, {end:#x}) in {name}", file=sys.stderr)
        print(f"error: {len(unexplained)} difference(s) are not the LC_UUID, the version banner or "
             "debug data; something new is non-deterministic", file=sys.stderr)
        return 1
    total = sum(counts.values())
    print(f"reproducible modulo named differences: {total} of {len(a)} bytes ({total / len(a):.4%}) "
          f"-- uuid {counts['uuid']}, version banner {counts['banner']}, debug/metadata "
          f"{counts['debug']}")
    if counts["banner"]:
        print("note: the version banner is loadable data, so the running kernel would report a "
              "different build time; making it reproducible needs a pinned build epoch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
