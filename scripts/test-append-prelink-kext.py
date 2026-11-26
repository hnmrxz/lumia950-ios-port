#!/usr/bin/env python3
"""Tests for scripts/append-prelink-kext.py: one new segment in the header padding, bytes appended at the tail."""

from __future__ import annotations

import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("append_prelink_kext", ROOT / "scripts" / "append-prelink-kext.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def image(padding: int = 256) -> bytes:
    """A Mach-O 64 with one segment and one section, with `padding` bytes between commands and content."""
    command = 72
    section_command = 72 + 80
    header = 32
    content = header + section_command + padding
    blob = bytearray()
    blob += struct.pack("<IiiIIIII", 0xFEEDFACF, 0x0100000C, 0, 2, 1, section_command, 0, 0)
    blob += struct.pack("<II", 0x19, section_command)
    blob += b"__TEXT".ljust(16, b"\0")
    blob += struct.pack("<QQQQiiII", 0x1000, 0x1000, 0, 0x1000, 7, 5, 1, 0)
    blob += b"__text".ljust(16, b"\0")
    blob += b"__TEXT".ljust(16, b"\0")
    blob += struct.pack("<QQI", 0x1000, 0x100, content)
    blob += b"\0" * (content - len(blob))
    blob += b"\xAA" * 0x100
    return bytes(blob)


class AppendPrelinkKextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def test_a_segment_command_is_added_and_the_kext_appended(self):
        original = image()
        updated, detail = self.module.append(original, b"\xCF\xFA\xED\xFEkext", 0xFFFFFFF009000000)
        ncmds = struct.unpack_from("<I", updated, 16)[0]
        sizeofcmds = struct.unpack_from("<I", updated, 20)[0]
        self.assertEqual(ncmds, 2)
        self.assertEqual(sizeofcmds, 72 + 80 + 72)
        self.assertEqual(updated[-8:], b"\xCF\xFA\xED\xFEkext")
        self.assertEqual(detail["size"], 8)

    def test_the_new_segment_points_at_the_appended_bytes(self):
        original = image()
        kext = b"K" * 32
        updated, detail = self.module.append(original, kext, 0xFFFFFFF009000000)
        base = 32 + 72 + 80  # the command lands right after the existing commands
        command, length = struct.unpack_from("<II", updated, base)
        self.assertEqual(command, 0x19)
        self.assertEqual(length, 72)
        name = updated[base + 8: base + 24].rstrip(b"\0")
        self.assertEqual(name, b"__LUMIA_KEXT")
        vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", updated, base + 24)
        self.assertEqual(vmaddr, 0xFFFFFFF009000000)
        self.assertEqual(filesize, 32)
        self.assertEqual(fileoff, len(original))

    def test_no_room_is_refused(self):
        tight = image(padding=8)
        with self.assertRaises(ValueError):
            self.module.append(tight, b"x" * 4, 0x1000)

    def test_the_command_line_writes_the_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "in.macho"
            source.write_bytes(image())
            kext = base / "NativeSdhci"
            kext.write_bytes(b"k" * 16)
            output = base / "out.macho"
            code = self.module.main(["--image", str(source), "--kext", str(kext),
                                     "--vmaddr", "0xfffffff009000000", "--output", str(output)])
            self.assertEqual(code, 0)
            self.assertTrue(output.is_file())

    def test_a_missing_file_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            code = self.module.main(["--image", str(base / "absent"), "--kext", str(base / "absent2"),
                                     "--vmaddr", "0x1000", "--output", str(base / "out")])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
