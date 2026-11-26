#!/usr/bin/env python3
"""Pack one kext into an mkext container the kernel can load from memory.

Why this exists: the pinned kernel cannot take a device driver through the source link (there is no IOStorageFamily
there) and its prelink will only merge kexts that are already in Apple's image. What it can do is load a kext from a
buffer, which is what `OSKext::loadFromMkext(OSKextLogSpec, char *, uint32_t, char **, uint32_t *)` is for.

The container is described in the same source tree, `libkern/libkern/mkext.h`: every field is big-endian, the header
carries magic 'MKXT', signature 'MOSX', the whole-file length, an adler32 taken from the `version` field to the end of
the file, version 0x02002001 for the v2 layout, the kext count and the cpu type/subtype, then the offset and sizes of
the combined info-dictionary plist. Version 2 stores files inline as `mkext2_file_entry { compressed_size, full_size,
data }`; a `compressed_size` of zero means the data is stored uncompressed, which is what this writes.

    python scripts/make-mkext.py --bundle-id org.unixnu.NativeSdhci \
        --info-plist drivers/NativeSdhci/Info.plist --executable build/NativeSdhci.kext/NativeSdhci \
        --output out/NativeSdhci.mkext
"""

from __future__ import annotations

import argparse
import plistlib
import struct
import sys
import zlib
from pathlib import Path

MAGIC = 0x4D4B5854  # 'MKXT'
SIGNATURE = 0x4D4F5358  # 'MOSX'
VERSION_2 = 0x02002001
CPU_TYPE_ARM64 = 0x0100000C
CPU_SUBTYPE_ARM64_ALL = 0
HEADER = struct.Struct(">8I3I")  # core (8 words) + plist offset/sizes
PAGE = 4096


def adler32_from_version(blob: bytes) -> int:
    """Checksum from &version to the end of the file, as the format defines it."""
    return zlib.adler32(blob[16:]) & 0xFFFFFFFF


def pack(bundle_id: str, info_plist: dict, executable: bytes,
         cpu_type: int = CPU_TYPE_ARM64, cpu_subtype: int = CPU_SUBTYPE_ARM64_ALL) -> bytes:
    # One inline, uncompressed executable entry.
    entry = struct.pack(">II", 0, len(executable)) + executable

    info = dict(info_plist)
    info["_MKEXTBundlePath"] = f"{bundle_id}.kext"
    info["_MKEXTExecutableRelativePath"] = "Contents/MacOS/" + bundle_id.split(".")[-1]
    info["_MKEXTExecutable"] = HEADER.size  # offset of the file entry from the start of the file
    info["CFBundleIdentifier"] = bundle_id

    plist = plistlib.dumps({"_MKEXTInfoDictionaries": {bundle_id: info}}, fmt=plistlib.FMT_XML)

    # The plist sits on a page boundary so the kernel can unmap it once parsed.
    entries_length = len(entry)
    first_plist_offset = HEADER.size + entries_length
    plist_offset = (first_plist_offset + PAGE - 1) // PAGE * PAGE
    padding = b"\0" * (plist_offset - first_plist_offset)

    total = HEADER.size + entries_length + len(padding) + len(plist)
    header = HEADER.pack(
        MAGIC, SIGNATURE, total, 0, VERSION_2, 1, cpu_type, cpu_subtype,
        plist_offset, 0, len(plist))
    blob = bytearray(header + entry + padding + plist)

    checksum = adler32_from_version(bytes(blob))
    struct.pack_into(">I", blob, 12, checksum)
    return bytes(blob)


def read_header(blob: bytes) -> dict:
    fields = HEADER.unpack_from(blob, 0)
    return {
        "magic": fields[0], "signature": fields[1], "length": fields[2], "adler32": fields[3],
        "version": fields[4], "numkexts": fields[5], "cputype": fields[6], "cpusubtype": fields[7],
        "plist_offset": fields[8], "plist_compressed_size": fields[9], "plist_full_size": fields[10],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--info-plist", required=True, type=Path)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cpu-type", type=lambda value: int(value, 0), default=CPU_TYPE_ARM64)
    parser.add_argument("--cpu-subtype", type=lambda value: int(value, 0), default=CPU_SUBTYPE_ARM64_ALL)
    args = parser.parse_args(argv)

    if not args.info_plist.is_file():
        print(f"error: no Info.plist at {args.info_plist}", file=sys.stderr)
        return 2
    if not args.executable.is_file():
        print(f"error: no executable at {args.executable}", file=sys.stderr)
        return 2

    info = plistlib.loads(args.info_plist.read_bytes())
    blob = pack(args.bundle_id, info, args.executable.read_bytes(), args.cpu_type, args.cpu_subtype)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(blob)

    header = read_header(blob)
    print(f"{args.output}: {len(blob)} bytes, plist at {header['plist_offset']}, "
          f"checksum 0x{header['adler32']:08X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
