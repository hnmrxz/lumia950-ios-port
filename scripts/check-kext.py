#!/usr/bin/env python3
"""Check that a Mach-O file can serve as a kext executable, before it is packed into an mkext.

The kernel's mkext reader hands each executable to the kext loader, which expects a kext bundle executable: a 64-bit
Mach-O for arm64 whose file type is MH_KEXT_BUNDLE, carrying the kmod info/start entry points. Building that on a macOS
runner and only discovering at load time that the file type was MH_OBJECT would cost a phone round trip, so this is a
cheap check that can run on the host.

    python scripts/check-kext.py build/NativeSdhci.kext/Contents/MacOS/NativeSdhci
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

MH_MAGIC_64 = 0xFEEDFACF
MH_KEXT_BUNDLE = 0xB
CPU_TYPE_ARM64 = 0x0100000C
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
SECT_KMOD = {"__kmod_info", "__kmod_start", "__kmod_stop"}
SEG_KMOD = {"__kmod"}


def read_macho(blob: bytes) -> dict:
    if len(blob) < 32:
        raise ValueError("too short to be a Mach-O 64 file")
    magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved = struct.unpack_from(
        "<IiiIIIII", blob, 0)
    if magic != MH_MAGIC_64:
        raise ValueError(f"not a little-endian Mach-O 64 file (magic 0x{magic:08X})")

    sections: set[str] = set()
    segments: set[str] = set()
    symtab: tuple[int, int] | None = None
    offset = 32
    for _ in range(ncmds):
        command, length = struct.unpack_from("<II", blob, offset)
        if command == LC_SEGMENT_64:
            name = blob[offset + 8: offset + 24].rstrip(b"\0").decode("utf-8", "replace")
            segments.add(name)
            nsects = struct.unpack_from("<I", blob, offset + 64)[0]
            for index in range(nsects):
                section = offset + 72 + index * 80
                section_name = blob[section: section + 16].rstrip(b"\0").decode("utf-8", "replace")
                sections.add(section_name)
        elif command == LC_SYMTAB:
            symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", blob, offset + 8)
            # a nlist_64 string index is relative to the string table, not to the start of the file
            symtab = (symoff, nsyms, stroff)
        offset += length

    symbols: list[str] = []
    if symtab:
        symoff, nsyms, stroff = symtab
        for index in range(nsyms):
            entry = symoff + index * 16
            if entry + 16 > len(blob):
                break
            string_index = struct.unpack_from("<I", blob, entry)[0]
            start = stroff + string_index
            end = start
            while end < len(blob) and blob[end] != 0:
                end += 1
            symbols.append(blob[start:end].decode("utf-8", "replace"))

    return {
        "cputype": cputype, "cpusubtype": cpusubtype, "filetype": filetype,
        "ncmds": ncmds, "sections": sections, "segments": segments, "symbols": symbols,
    }


KMOD_SYMBOLS = ("_kmod_info", "__kmod_info", "_kmod_start", "__kmod_start")


def problems(info: dict) -> list[str]:
    found: list[str] = []
    if info["cputype"] != CPU_TYPE_ARM64:
        found.append(f"cpu type is 0x{info['cputype']:08X}, not arm64")
    if info["filetype"] != MH_KEXT_BUNDLE:
        found.append(f"file type is {info['filetype']}, not MH_KEXT_BUNDLE (0xb)")
    # KMOD_EXPLICIT_DECL() in osfmk/mach/kmod.h declares KMOD_INFO_NAME = kmod_info with no section attribute,
    # so the record is an ordinary C symbol; the __kmod_* sections are a convention of Apple's build, not a
    # requirement of the format. Either shape proves the bundle carries its entry points.
    has_section = bool(SEG_KMOD & info["segments"]) or bool(SECT_KMOD & info["sections"])
    has_symbol = any(name in info["symbols"] for name in KMOD_SYMBOLS)
    if not has_section and not has_symbol:
        found.append("no __kmod segment/section and no kmod_info symbol, so the loader has no entry points")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)

    if not args.path.is_file():
        print(f"error: no file at {args.path}", file=sys.stderr)
        return 2
    try:
        info = read_macho(args.path.read_bytes())
    except ValueError as error:
        print(f"FAIL {args.path}: {error}")
        return 1

    found = problems(info)
    if found:
        for problem in found:
            print(f"FAIL {args.path}: {problem}")
        return 1
    print(f"ok   {args.path}: arm64 kext bundle, {len(info['symbols'])} symbols, "
          f"segments {sorted(info['segments'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
