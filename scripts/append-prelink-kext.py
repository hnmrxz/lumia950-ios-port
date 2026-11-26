#!/usr/bin/env python3
"""Append a kext's bytes to a merged image and describe them with a new segment.

This is the placement half that ADR-0003 sizes in weeks, taken one honest step at a time. What it does:

* appends the kext file at the end of the image;
* adds one `LC_SEGMENT_64` command for it in the header padding that the image already has (320 bytes before the first
  section, enough for one 72-byte command);
* reports the address the prelink entry must carry.

What it does NOT do: bind the kext's dynamic symbols or fix its relocations. Those are what a real prelinker does, and a
kext loaded without them will fault when it runs -- which is exactly what makes the next experiment informative rather
than conclusive.

    python scripts/append-prelink-kext.py --image merged.macho --kext NativeSdhci --vmaddr 0xfffffff009000000 \
        --output merged-placed.macho
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
SEGMENT_COMMAND_SIZE = 72
VM_PROT_READ_EXECUTE = 5


def first_section_offset(blob: bytes) -> int:
    _magic, _cpu, _sub, _filetype, ncmds, _sizeofcmds, _flags, _res = struct.unpack_from("<IiiIIIII", blob, 0)
    lowest = 1 << 62
    offset = 32
    for _ in range(ncmds):
        command, length = struct.unpack_from("<II", blob, offset)
        if command == LC_SEGMENT_64:
            nsects = struct.unpack_from("<I", blob, offset + 64)[0]
            for index in range(nsects):
                base = offset + 72 + index * 80
                _addr, size, file_offset = struct.unpack_from("<QQI", blob, base + 32)
                if size and file_offset and file_offset < lowest:
                    lowest = file_offset
        offset += length
    return lowest


def append(image: bytes, kext: bytes, vmaddr: int) -> tuple[bytes, dict]:
    _magic, _cpu, _sub, _filetype, ncmds, sizeofcmds, _flags, _res = struct.unpack_from("<IiiIIIII", image, 0)
    header_end = 32 + sizeofcmds
    first = first_section_offset(image)
    if first - header_end < SEGMENT_COMMAND_SIZE:
        raise ValueError(f"no room for a segment command: header ends at {header_end}, first section at {first}")

    file_offset = len(image)
    command = bytearray()
    command += struct.pack("<II", LC_SEGMENT_64, SEGMENT_COMMAND_SIZE)
    command += b"__LUMIA_KEXT".ljust(16, b"\0")
    # vmsize is page rounded: the kernel maps segments a page at a time, and a vmsize that is not a whole number of pages is
    # the kind of thing its allocation path trips over (the first attempt faulted inside _mach_vm_allocate_kernel).
    page = 0x4000
    vmsize = (len(kext) + page - 1) // page * page
    command += struct.pack("<QQQQ", vmaddr, vmsize, file_offset, len(kext))
    command += struct.pack("<iiII", VM_PROT_READ_EXECUTE, VM_PROT_READ_EXECUTE, 0, 0)

    out = bytearray(image)
    out[header_end: header_end + SEGMENT_COMMAND_SIZE] = command
    struct.pack_into("<I", out, 16, ncmds + 1)
    struct.pack_into("<I", out, 20, sizeofcmds + SEGMENT_COMMAND_SIZE)
    out += kext
    return bytes(out), {"vmaddr": vmaddr, "size": len(kext), "file_offset": file_offset,
                        "commands_end": header_end + SEGMENT_COMMAND_SIZE}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--kext", required=True, type=Path)
    parser.add_argument("--vmaddr", required=True, type=lambda value: int(value, 0))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    for path in (args.image, args.kext):
        if not path.is_file():
            print(f"error: no file at {path}", file=sys.stderr)
            return 2
    try:
        updated, detail = append(args.image.read_bytes(), args.kext.read_bytes(), args.vmaddr)
    except ValueError as error:
        print(f"FAIL {args.image}: {error}")
        return 1

    args.output.write_bytes(updated)
    print(f"{args.output}: placed {detail['size']} bytes of {args.kext.name} at 0x{detail['vmaddr']:x} "
          f"(file offset 0x{detail['file_offset']:x})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
