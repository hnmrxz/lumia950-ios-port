#!/usr/bin/env python3
"""Tests for scripts/check-reproducible.py.

The case that matters is the real one: two builds of one commit differ by 1911 bytes, and all of
them are the LC_UUID, the version banner and debug data. A byte outside those classes has to fail.

    python3 scripts/test-reproducible.py
"""
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check-reproducible.py")

BANNER = b"Mon Nov 16 14:35:00 UTC 2026; runner"
SECTION_OFFSET = 208
SECTION_SIZE = 160
TOTAL = SECTION_OFFSET + SECTION_SIZE + 16
UUID_OFFSET = 40


def image(uuid=b"\x11" * 16, banner=BANNER) -> bytes:
    blob = bytearray(b"\0" * TOTAL)
    struct.pack_into("<8I", blob, 0, 0xFEEDFACF, 0x0100000C, 0, 2, 2, 24 + 72 + 80, 0, 0)
    struct.pack_into("<II", blob, 32, 0x1B, 24)
    blob[UUID_OFFSET:UUID_OFFSET + 16] = uuid
    # LC_SEGMENT_64 __TEXT with one section, __const, at SECTION_OFFSET.
    struct.pack_into("<II16sQQQQIIII", blob, 56, 0x19, 152, b"__TEXT", 0, TOTAL,
                     SECTION_OFFSET, SECTION_SIZE, 5, 5, 1, 0)
    struct.pack_into("<16s16sQQIIIIIIII", blob, 128, b"__const", b"__TEXT", 0, SECTION_SIZE,
                     SECTION_OFFSET, 0, 0, 0, 0, 0, 0, 0)
    blob[SECTION_OFFSET:SECTION_OFFSET + len(banner)] = banner
    return bytes(blob)


class ReproTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def compare(self, a: bytes, b: bytes, expect=0):
        left, right = self.root / "a", self.root / "b"
        left.write_bytes(a)
        right.write_bytes(b)
        result = subprocess.run([sys.executable, str(SCRIPT), "--a", str(left), "--b", str(right)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, expect,
                         f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def test_identical_images_are_reproducible(self):
        result = self.compare(image(), image())
        self.assertIn("identical", result.stdout)

    def test_a_different_uuid_is_named_and_accepted(self):
        result = self.compare(image(uuid=b"\x11" * 16), image(uuid=b"\x22" * 16))
        self.assertIn("uuid 16", result.stdout)

    def test_a_different_build_time_in_the_banner_is_named_and_accepted(self):
        later = BANNER.replace(b"14:35:00", b"14:47:03")
        result = self.compare(image(), image(banner=later))
        self.assertIn("version banner", result.stdout)

    def test_a_difference_outside_every_section_is_debug_data(self):
        a, b = bytearray(image()), bytearray(image())
        b[TOTAL - 8] ^= 0xFF
        result = self.compare(bytes(a), bytes(b))
        self.assertIn("debug/metadata", result.stdout)

    def test_a_loadable_difference_away_from_the_banner_is_refused(self):
        a, b = bytearray(image()), bytearray(image())
        # Inside __const, far from the version string.
        b[SECTION_OFFSET + 140] ^= 0xFF
        result = self.compare(bytes(a), bytes(b), expect=1)
        self.assertIn("unexplained difference", result.stderr)

    def test_a_length_change_is_refused(self):
        result = self.compare(image(), image() + b"\0", expect=1)
        self.assertIn("size difference", result.stderr)

    def test_a_non_macho_is_refused(self):
        # Two different buffers, or the script stops at "identical" before it parses anything.
        result = self.compare(b"not a mach-o", b"not a mach-o either", expect=1)
        self.assertIn("size difference", result.stderr)
        result = self.compare(b"not a mach-o", b"NOT a mach-o", expect=1)
        self.assertIn("not a thin Mach-O", result.stderr)


if __name__ == "__main__":
    unittest.main()
