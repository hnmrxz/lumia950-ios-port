#!/usr/bin/env python3
"""Put bytes inside an existing segment of a merged image, the way the prelink emitter does.

The emitter does not invent mappings: it fills the placeholder segments the native kernel already declares, because those
are the ones the kernel maps at boot. A segment of our own is not mapped, which is what the placement experiment showed
(fault inside _mach_vm_allocate_kernel, fault_far different on every boot).

So this grows a chosen segment instead: the blob goes at the segment's file end, everything after it in the file moves by the
grown amount, and every load command that names a file offset is adjusted. The blob's address is then
`segment.vmaddr + old filesize` -- inside a mapping the kernel already has.

    python scripts/grow-prelink-segment.py --image in.macho --blob kext --segment __PLK_TEXT_EXEC --output out.macho
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

LH_MAGIC = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
# Load commands that carry file offsets and therefore have to move when the file does.
LC_SYMTAB = 0x02
LC_DYSYMTAB = 0x0B
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LC_FUNCTION_STARTS = 0x26
LC_DATA_IN_CODE = 0x29
LC_CODE_SIGNATURE = 0x1D
LC_SEGMENT_SPLIT_INFO = 0x1E
ALIGNMENT = 4096


def align(value: int, boundary: int = ALIGNMENT) -> int:
    return (value + boundary - 1) // boundary * boundary


def parse(blob: bytes) -> dict:
    magic, _cpu, _sub, _filetype, ncmds, sizeofcmds, _flags, _res = struct.unpack_from("<IiiIIIII", blob, 0)
    if magic != LH_MAGIC:
        raise ValueError("not a little-endian Mach-O 64")
    segments = []
    offset = 32
    for _ in range(ncmds):
        command, length = struct.unpack_from("<II", blob, offset)
        if command == LC_SEGMENT_64:
            name = blob[offset + 8: offset + 24].rstrip(b"\0").decode("utf-8", "replace")
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", blob, offset + 24)
            nsects = struct.unpack_from("<I", blob, offset + 64)[0]
            sections = []
            for index in range(nsects):
                base = offset + 72 + index * 80
                _addr, size, section_offset = struct.unpack_from("<QQI", blob, base + 32)
                sections.append({"base": base, "size": size, "offset": section_offset})
            segments.append({"name": name, "command": offset, "vmaddr": vmaddr, "vmsize": vmsize,
                             "fileoff": fileoff, "filesize": filesize, "sections": sections})
        offset += length
    return {"ncmds": ncmds, "sizeofcmds": sizeofcmds, "segments": segments}


def grow(image: bytes, blob: bytes, segment_name: str) -> tuple[bytes, dict]:
    table = parse(image)
    segment = next((entry for entry in table["segments"] if entry["name"] == segment_name), None)
    if segment is None:
        raise ValueError(f"no segment named {segment_name}")
    if segment["filesize"] == 0:
        raise ValueError(f"{segment_name} has no file content to grow")

    insert_at = segment["fileoff"] + segment["filesize"]
    delta = align(len(blob)) - segment["filesize"] % align(len(blob)) if False else align(len(blob))
    # the blob must keep the segment's 4K geometry
    if insert_at % ALIGNMENT:
        raise ValueError(f"{segment_name} does not end on a 4K boundary (0x{insert_at:x})")

    output = bytearray(image[:insert_at]) + bytearray(blob) + bytearray(delta - len(blob)) + bytearray(image[insert_at:])

    # the grown segment and its first section
    struct.pack_into("<Q", output, segment["command"] + 32, segment["vmsize"] + delta)
    struct.pack_into("<Q", output, segment["command"] + 48, segment["filesize"] + delta)
    for section in segment["sections"]:
        struct.pack_into("<Q", output, section["base"] + 40, section["size"] + delta)

    # everything after the insertion point moves
    offset = 32
    for _ in range(table["ncmds"]):
        command, length = struct.unpack_from("<II", output, offset)
        if command == LC_SEGMENT_64:
            fileoff_at = offset + 40
            fileoff = struct.unpack_from("<Q", output, fileoff_at)[0]
            if fileoff >= insert_at:
                struct.pack_into("<Q", output, fileoff_at, fileoff + delta)
            nsects = struct.unpack_from("<I", output, offset + 64)[0]
            for index in range(nsects):
                base = offset + 72 + index * 80
                section_offset = struct.unpack_from("<I", output, base + 48)[0]
                if section_offset >= insert_at:
                    struct.pack_into("<I", output, base + 48, section_offset + delta)
        elif command in (LC_SYMTAB, LC_DYSYMTAB, LC_DYLD_INFO, LC_DYLD_INFO_ONLY, LC_FUNCTION_STARTS,
                         LC_DATA_IN_CODE, LC_CODE_SIGNATURE, LC_SEGMENT_SPLIT_INFO):
            # these carry 32-bit file offsets in the words after the command header
            count = (length - 8) // 4
            for index in range(count):
                at = offset + 8 + index * 4
                value = struct.unpack_from("<I", output, at)[0]
                if value >= insert_at:
                    struct.pack_into("<I", output, at, value + delta)
        offset += length

    return bytes(output), {"address": segment["vmaddr"] + segment["filesize"], "delta": delta,
                           "segment": segment_name, "inserted_at": insert_at}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--blob", required=True, type=Path)
    parser.add_argument("--segment", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    for path in (args.image, args.blob):
        if not path.is_file():
            print(f"error: no file at {path}", file=sys.stderr)
            return 2
    try:
        updated, detail = grow(args.image.read_bytes(), args.blob.read_bytes(), args.segment)
    except ValueError as error:
        print(f"FAIL {args.image}: {error}")
        return 1
    args.output.write_bytes(updated)
    print(f"{args.output}: {args.blob.name} inside {detail['segment']} at 0x{detail['address']:x} "
          f"(grew by {detail['delta']} bytes from offset 0x{detail['inserted_at']:x})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
