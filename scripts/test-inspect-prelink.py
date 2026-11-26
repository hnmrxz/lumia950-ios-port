#!/usr/bin/env python3
"""Tests for scripts/inspect-prelink.py: reading the prelink dictionary is the prerequisite for writing it."""

from __future__ import annotations

import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PAYLOAD = (
    "<dict><key>_PrelinkInfoDictionary</key><array>"
    "<dict><key>CFBundleIdentifier</key><string>com.example.kext</string>"
    '<key>_PrelinkExecutableLoadAddr</key><integer size="64">0xfffffff004004000</integer>'
    '<key>_PrelinkExecutableSize</key><integer size="64">0x1000</integer>'
    "</dict></array></dict>"
)


def load():
    spec = importlib.util.spec_from_file_location("inspect_prelink", ROOT / "scripts" / "inspect-prelink.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def image(payload: bytes, segment_name: str = "__PRELINK_INFO") -> bytes:
    """A Mach-O 64 with one segment whose content is the payload."""
    header_size = 32
    segment_command_size = 72
    fileoff = header_size + segment_command_size
    blob = bytearray()
    blob += struct.pack("<IiiIIIII", 0xFEEDFACF, 0x0100000C, 0, 2, 1, segment_command_size, 0, 0)
    blob += struct.pack("<II", 0x19, segment_command_size)
    blob += segment_name.encode().ljust(16, b"\0")
    blob += struct.pack("<QQQQiiII", 0xFFFFFFF000400000, len(payload), fileoff, len(payload), 7, 7, 1, 0)
    blob += payload
    return bytes(blob)


class InspectPrelinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def test_the_fragment_is_parsed_with_hex_integers(self):
        payload, table = self.module.prelink_info(image(PAYLOAD.encode()))
        self.assertEqual([entry["name"] for entry in table], ["__PRELINK_INFO"])
        parsed = self.module.parse_dictionary(payload)
        rows = self.module.summarise(parsed)
        self.assertEqual(rows[0]["id"], "com.example.kext")
        self.assertEqual(rows[0]["load_addr"], 0xFFFFFFF004004000)
        self.assertEqual(rows[0]["size"], 0x1000)

    def test_an_image_without_the_segment_is_refused(self):
        with self.assertRaises(ValueError):
            self.module.prelink_info(image(PAYLOAD.encode(), segment_name="__TEXT"))

    def test_non_macho_input_is_refused(self):
        with self.assertRaises(ValueError):
            self.module.segments(b"not a mach-o")

    def test_the_command_line_reports_a_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "kernel.macho"
            path.write_bytes(image(PAYLOAD.encode()))
            self.assertEqual(self.module.main([str(path)]), 0)

    def test_the_command_line_can_emit_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "kernel.macho"
            path.write_bytes(image(PAYLOAD.encode()))
            self.assertEqual(self.module.main([str(path), "--json"]), 0)

    def test_a_missing_file_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(self.module.main([str(Path(temporary) / "absent")]), 2)


if __name__ == "__main__":
    unittest.main()
