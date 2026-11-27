#!/usr/bin/env python3
"""Build a synthetic GPT image, so the read-only reader can be tested before it ever meets a phone.

The fixture states its own geometry -- 8 MiB, 512-byte sectors, two entries -- and its partition names and LBAs are declared synthetic, not
copied from any device. What it is for is the reader's strictness: protective MBR, header CRC, entry-array CRC, primary/backup agreement, and
overlap checks all get something to be right or wrong about.

    python scripts/make-gpt-fixture.py --out out/gpt-fixture.img [--corrupt header|entries|mbr|overlap]
"""

from __future__ import annotations

import argparse
import binascii
import struct
import sys
from pathlib import Path

SECTOR = 512
SECTORS = 16384  # 8 MiB
ENTRY_SIZE = 128
ENTRY_COUNT = 128

ESP_TYPE = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
DATA_TYPE = "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"
DISK_GUID = "1f8e2b40-9d7a-4c33-8a51-2c6f0b7d9e01"


def guid_bytes(text: str) -> bytes:
    first, second, third, fourth, fifth = text.split("-")
    return (struct.pack("<IHH", int(first, 16), int(second, 16), int(third, 16))
            + bytes.fromhex(fourth) + bytes.fromhex(fifth))


def crc32(data: bytes) -> int:
    return binascii.crc32(data) & 0xFFFFFFFF


def entry(type_text: str, first: int, last: int, name: str) -> bytes:
    raw = bytearray(ENTRY_SIZE)
    raw[0:16] = guid_bytes(type_text)
    raw[16:32] = guid_bytes("00000000-0000-4000-8000-000000000000")
    struct.pack_into("<QQQ", raw, 32, first, last, 0)
    encoded = name.encode("utf-16-le")
    raw[56:56 + len(encoded)] = encoded
    return bytes(raw)


def header(my_lba: int, alt_lba: int, entries_lba: int, entries_crc: int, first_usable: int, last_usable: int) -> bytes:
    raw = bytearray(SECTOR)
    raw[0:8] = b"EFI PART"
    struct.pack_into("<I", raw, 8, 0x00010000)
    struct.pack_into("<I", raw, 12, 92)
    struct.pack_into("<I", raw, 16, 0)  # CRC placeholder
    struct.pack_into("<I", raw, 20, 0)
    struct.pack_into("<QQQQ", raw, 24, my_lba, alt_lba, first_usable, last_usable)
    raw[56:72] = guid_bytes(DISK_GUID)
    struct.pack_into("<Q", raw, 72, entries_lba)
    struct.pack_into("<III", raw, 80, ENTRY_COUNT, ENTRY_SIZE, entries_crc)
    struct.pack_into("<I", raw, 16, crc32(bytes(raw[:92])))
    return bytes(raw)


def build(corrupt: str | None = None) -> bytes:
    image = bytearray(SECTORS * SECTOR)

    mbr = bytearray(SECTOR)
    mbr[0x1BE + 4] = 0xEE
    struct.pack_into("<I", mbr, 0x1BE + 8, 1)
    struct.pack_into("<I", mbr, 0x1BE + 12, SECTORS - 1)
    image[0:SECTOR] = mbr

    first_usable, last_usable = 34, SECTORS - 34
    entries = bytearray(ENTRY_COUNT * ENTRY_SIZE)
    entries[0:ENTRY_SIZE] = entry(ESP_TYPE, 2048, 4095, "EFIESP")
    second_first = 4096
    if corrupt == "overlap":
        second_first = 4095  # one sector inside the first partition
    entries[ENTRY_SIZE:2 * ENTRY_SIZE] = entry(DATA_TYPE, second_first, last_usable, "MainOS")

    entries_crc = crc32(bytes(entries))
    image[SECTOR:2 * SECTOR] = header(1, SECTORS - 1, 2, entries_crc, first_usable, last_usable)
    image[2 * SECTOR:2 * SECTOR + len(entries)] = entries

    backup_entries_lba = SECTORS - 33
    image[backup_entries_lba * SECTOR:backup_entries_lba * SECTOR + len(entries)] = entries
    image[(SECTORS - 1) * SECTOR:SECTORS * SECTOR] = header(SECTORS - 1, 1, backup_entries_lba, entries_crc,
                                                           first_usable, last_usable)

    if corrupt == "mbr":
        image[0x1BE + 4] = 0x83
    elif corrupt == "header":
        image[SECTOR + 40] ^= 0xFF  # inside the CRC-covered area
    elif corrupt == "entries":
        image[SECTOR * 2 + 64] ^= 0xFF  # a name byte, covered by the entry CRC
    return bytes(image)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--corrupt", choices=("mbr", "header", "entries", "overlap"), default=None)
    args = parser.parse_args(argv)

    data = build(args.corrupt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    print(f"wrote {args.out} ({len(data)} bytes, {SECTORS} sectors, {ENTRY_COUNT} entries)"
          + (f", corrupted: {args.corrupt}" if args.corrupt else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
