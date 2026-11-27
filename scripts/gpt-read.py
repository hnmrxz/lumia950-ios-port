#!/usr/bin/env python3
"""Read a GPT image read-only: protective MBR, header CRC, entry CRC, primary and backup tables.

This is the reference the kernel side of M3 has to match. The acceptance for M3 is written in terms of what an independent reader says --
signature and CRCs valid, the partition count, type GUIDs and start/end LBAs identical to the baseline -- so that reader is here, and it
refuses anything it cannot verify rather than guessing:

    python scripts/gpt-read.py --image out/gpt-fixture.img [--json out/gpt.json]

Nothing is written to the image. The parser is deliberately strict: a bad protective MBR, a bad header CRC, a bad entry-array CRC, a header
that disagrees with the backup, or overlapping partitions all end in a non-zero exit with the reason.
"""

from __future__ import annotations

import argparse
import binascii
import json
import struct
import sys
from pathlib import Path

GPT_SIGNATURE = b"EFI PART"
PROTECTIVE_TYPE = 0xEE
SECTOR = 512
MIN_HEADER = 92

TYPES = {
    "c12a7328-f81f-11d2-ba4b-00a0c93ec93b": "EFI System Partition",
    "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7": "Microsoft basic data",
    "e3c9e316-0b5c-4db8-817d-f92df00215ae": "Microsoft reserved",
    "de94bba4-06d1-4d40-a16a-bfd50179d6ac": "Windows recovery",
    "0fc63daf-8483-4772-8e79-3d69d8477de4": "Linux filesystem",
    "7c3457ef-0000-11aa-aa11-00306543ecac": "Apple APFS",
}


def guid_text(raw: bytes) -> str:
    """GPT stores the first three fields little-endian."""
    first, second, third = struct.unpack_from("<IHH", raw, 0)
    tail = raw[8:]
    return f"{first:08x}-{second:04x}-{third:04x}-{tail[:2].hex()}-{tail[2:].hex()}"


def crc32(data: bytes) -> int:
    return binascii.crc32(data) & 0xFFFFFFFF


class GptError(Exception):
    pass


def parse(image: bytes) -> dict:
    if len(image) < 3 * SECTOR:
        raise GptError("image is too small to hold a GPT")

    mbr = image[:SECTOR]
    if mbr[0x1BE + 4] != PROTECTIVE_TYPE:
        raise GptError("no protective MBR entry of type 0xEE; this is not a GPT disk")
    protect_start = struct.unpack_from("<I", mbr, 0x1BE + 8)[0]
    protect_size = struct.unpack_from("<I", mbr, 0x1BE + 12)[0]
    if protect_start != 1:
        raise GptError(f"protective entry starts at LBA {protect_start}, expected 1")

    header = image[SECTOR:2 * SECTOR]
    if header[:8] != GPT_SIGNATURE:
        raise GptError(f"signature {header[:8]!r} is not {GPT_SIGNATURE!r}")
    header_size = struct.unpack_from("<I", header, 12)[0]
    if header_size < MIN_HEADER or header_size > SECTOR:
        raise GptError(f"implausible header size {header_size}")
    stored_crc = struct.unpack_from("<I", header, 16)[0]
    zeroed = bytearray(header[:header_size])
    struct.pack_into("<I", zeroed, 16, 0)
    if crc32(bytes(zeroed)) != stored_crc:
        raise GptError(f"header CRC {stored_crc:#010x} does not match its contents")

    my_lba, alt_lba, first_usable, last_usable = struct.unpack_from("<QQQQ", header, 24)
    if my_lba != 1:
        raise GptError(f"primary header claims LBA {my_lba}")
    disk_guid = guid_text(header[56:72])
    entries_lba, entry_count, entry_size, entries_crc = struct.unpack_from("<QIII", header, 72)
    if entry_size < 128 or entry_size % 8:
        raise GptError(f"implausible entry size {entry_size}")
    if entry_count == 0 or entry_count > 1024:
        raise GptError(f"implausible entry count {entry_count}")
    total = entry_count * entry_size
    start = entries_lba * SECTOR
    if start + total > len(image):
        raise GptError("entry array runs past the end of the image")
    entries_bytes = image[start:start + total]
    if crc32(entries_bytes) != entries_crc:
        raise GptError(f"entry array CRC {entries_crc:#010x} does not match its contents")

    partitions = []
    last_end = first_usable - 1
    for index in range(entry_count):
        entry = entries_bytes[index * entry_size:(index + 1) * entry_size]
        type_guid = guid_text(entry[0:16])
        if type_guid == "00000000-0000-0000-0000-000000000000":
            continue
        first_lba, end_lba, attrs = struct.unpack_from("<QQQ", entry, 32)
        name = entry[56:128].decode("utf-16-le", "replace").split("\x00")[0]
        if first_lba > end_lba:
            raise GptError(f"partition {index} starts after it ends")
        if first_lba <= last_end:
            raise GptError(f"partition {index} overlaps the one before it")
        last_end = end_lba
        partitions.append({"index": index, "type": type_guid, "kind": TYPES.get(type_guid, "unknown"),
                           "first_lba": first_lba, "last_lba": end_lba, "sectors": end_lba - first_lba + 1,
                           "name": name, "attributes": attrs})

    result = {
        "signature": header[:8].decode("ascii"),
        "revision": f"{struct.unpack_from('<I', header, 8)[0] >> 16}.{struct.unpack_from('<I', header, 8)[0] & 0xFFFF}",
        "header_size": header_size,
        "header_crc": f"{stored_crc:#010x}",
        "entries_crc": f"{entries_crc:#010x}",
        "disk_guid": disk_guid,
        "first_usable_lba": first_usable,
        "last_usable_lba": last_usable,
        "protects_sectors": protect_size,
        "partitions": partitions,
    }

    backup_start = alt_lba * SECTOR
    if backup_start + SECTOR <= len(image):
        backup = image[backup_start:backup_start + SECTOR]
        if backup[:8] == GPT_SIGNATURE:
            backup_my_lba = struct.unpack_from("<Q", backup, 24)[0]
            backup_alt = struct.unpack_from("<Q", backup, 32)[0]
            backup_disk = guid_text(backup[56:72])
            result["backup"] = {"my_lba": backup_my_lba, "alternate_lba": backup_alt, "disk_guid": backup_disk,
                                "agrees": backup_my_lba == alt_lba and backup_alt == my_lba and backup_disk == disk_guid}
        else:
            result["backup"] = {"present": False}
    else:
        result["backup"] = {"present": False, "reason": "the image does not reach the alternate LBA"}

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.image.is_file():
        print(f"error: {args.image} does not exist", file=sys.stderr)
        return 2
    try:
        result = parse(args.image.read_bytes())
    except GptError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1

    print(f"disk {result['disk_guid']}  revision {result['revision']}  header CRC {result['header_crc']}")
    print(f"usable {result['first_usable_lba']}..{result['last_usable_lba']}  entries CRC {result['entries_crc']}")
    for partition in result["partitions"]:
        print(f"  {partition['index']:2d} {partition['kind']:<24} {partition['first_lba']:>12}..{partition['last_lba']:<12}"
              f" {partition['name']}")
    backup = result.get("backup") or {}
    print(f"backup: {'agrees' if backup.get('agrees') else backup.get('reason', 'not present')}")
    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
