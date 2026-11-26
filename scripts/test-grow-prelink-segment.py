#!/usr/bin/env python3
"""Tests for scripts/grow-prelink-segment.py: the blob must land inside a mapped segment, and the file must stay coherent."""

from __future__ import annotations

import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("grow_prelink_segment", ROOT / "scripts" / "grow-prelink-segment.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def image() -> bytes:
    """Two 4K segments; the first carries a section, the second sits after it in the file."""
    first = 72 + 80
    second = 72
    header = 32
    content = 0x1000
    blob = bytearray()
    blob += struct.pack("<IiiIIIII", 0xFEEDFACF, 0x0100000C, 0, 2, 2, first + second, 0, 0)
    blob += struct.pack("<II", 0x19, first)
    blob += b"__PRELINK_TEXT".ljust(16, b"\0")
    blob += struct.pack("<QQQQiiII", 0xFFFFFFF004004000, 0x1000, content, 0x1000, 5, 5, 1, 0)
    blob += b"__text".ljust(16, b"\0")
    blob += b"__TEXT".ljust(16, b"\0")
    blob += struct.pack("<QQI", 0xFFFFFFF004004000, 0x100, content)
    blob += b"\0" * 28  # align/reloff/nreloc/flags/reserved1..3: a section_64 is 80 bytes
    blob += struct.pack("<II", 0x19, second)
    blob += b"__PRELINK_DATA".ljust(16, b"\0")
    blob += struct.pack("<QQQQiiII", 0xFFFFFFF004005000, 0x1000, content + 0x1000, 0x1000, 3, 3, 0, 0)
    blob += b"\0" * (content - len(blob))
    blob += b"\x11" * 0x1000
    blob += b"\x22" * 0x1000
    return bytes(blob)


class GrowPrelinkSegmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def test_the_blob_lands_at_the_segment_end(self):
        original = image()
        grown, detail = self.module.grow(original, b"\xAA" * 16, "__PRELINK_TEXT")
        self.assertEqual(detail["address"], 0xFFFFFFF004004000 + 0x1000)
        self.assertEqual(detail["delta"], 4096)
        self.assertEqual(grown[detail["inserted_at"]: detail["inserted_at"] + 16], b"\xAA" * 16)

    def test_the_segment_and_its_section_grow(self):
        grown, _ = self.module.grow(image(), b"\xAA" * 16, "__PRELINK_TEXT")
        table = self.module.parse(grown)
        segment = next(entry for entry in table["segments"] if entry["name"] == "__PRELINK_TEXT")
        self.assertEqual(segment["vmsize"], 0x2000)
        self.assertEqual(segment["filesize"], 0x2000)
        self.assertEqual(segment["sections"][0]["size"], 0x100 + 4096)

    def test_the_following_segment_moves(self):
        grown, detail = self.module.grow(image(), b"\xAA" * 16, "__PRELINK_TEXT")
        table = self.module.parse(grown)
        following = next(entry for entry in table["segments"] if entry["name"] == "__PRELINK_DATA")
        self.assertEqual(following["fileoff"], 0x2000 + detail["delta"])

    def test_bytes_after_the_insertion_are_preserved(self):
        original = image()
        grown, detail = self.module.grow(original, b"\xAA" * 16, "__PRELINK_TEXT")
        tail = len(original) - (detail["inserted_at"])
        self.assertEqual(grown[-tail:], original[detail["inserted_at"]:])

    def test_an_unknown_segment_is_refused(self):
        with self.assertRaises(ValueError):
            self.module.grow(image(), b"\xAA" * 16, "__NOPE")

    def test_the_command_line_writes_an_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "in.macho"
            source.write_bytes(image())
            blob = base / "blob"
            blob.write_bytes(b"\xAA" * 16)
            output = base / "out.macho"
            self.assertEqual(self.module.main(["--image", str(source), "--blob", str(blob),
                                               "--segment", "__PRELINK_TEXT", "--output", str(output)]), 0)
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
