#!/usr/bin/env python3
"""Tests for scripts/check-kext.py: a kext that cannot load has to be refused on the host, not on the phone."""

from __future__ import annotations

import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("check_kext", ROOT / "scripts" / "check-kext.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def macho(filetype: int, cputype: int = 0x0100000C, segment: str = "__kmod",
          symbols: tuple[str, ...] = ("_kmod_info", "_kmod_start")) -> bytes:
    """A minimal little-endian Mach-O 64 with one segment and a symbol table."""
    string_table = b"\0" + b"\0".join(name.encode() for name in symbols) + b"\0"
    header_size = 32
    segment_command_size = 72
    size_of_commands = segment_command_size + 24
    symbols_offset = header_size + size_of_commands      # the nlist array starts right after the commands
    strings_offset = symbols_offset + len(symbols) * 16   # and the strings follow it

    blob = bytearray()
    blob += struct.pack("<IiiIIIII", 0xFEEDFACF, cputype, 0, filetype, 2, size_of_commands, 0, 0)
    blob += struct.pack("<II", 0x19, segment_command_size)
    blob += segment.encode().ljust(16, b"\0")
    blob += struct.pack("<QQQQiiII", 0, 0, 0, 0, 7, 7, 1, 0)
    blob += struct.pack("<II", 0x2, 24)
    blob += struct.pack("<IIII", symbols_offset, len(symbols), strings_offset, len(string_table))

    index = 1
    for name in symbols:
        blob += struct.pack("<IBBHQ", index, 0x0F, 0x01, 0, 0)
        index += len(name) + 1
    blob += string_table
    return bytes(blob)


class CheckKextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def parse(self, blob: bytes):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "NativeSdhci"
            path.write_bytes(blob)
            info = self.module.read_macho(blob)
            return info, self.module.problems(info)

    def test_a_kext_bundle_passes(self):
        _, found = self.parse(macho(self.module.MH_KEXT_BUNDLE))
        self.assertEqual(found, [])

    def test_an_object_file_is_refused(self):
        _, found = self.parse(macho(0x1))  # MH_OBJECT
        self.assertTrue(any("MH_KEXT_BUNDLE" in problem for problem in found), found)

    def test_a_wrong_cpu_is_refused(self):
        _, found = self.parse(macho(self.module.MH_KEXT_BUNDLE, cputype=0x01000007))
        self.assertTrue(any("arm64" in problem for problem in found), found)

    def test_a_missing_kmod_section_is_refused(self):
        _, found = self.parse(macho(self.module.MH_KEXT_BUNDLE, segment="__TEXT", symbols=("_main",)))
        self.assertTrue(any("__kmod" in problem for problem in found), found)

    def test_a_missing_kmod_symbols_are_refused(self):
        _, found = self.parse(macho(self.module.MH_KEXT_BUNDLE, symbols=("_other",)))
        self.assertTrue(any("_kmod_info" in problem for problem in found), found)

    def test_not_a_macho_is_refused(self):
        with self.assertRaises(ValueError):
            self.module.read_macho(b"not a mach-o file at all, definitely not")

    def test_the_command_line_reports_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "NativeSdhci"
            path.write_bytes(macho(self.module.MH_KEXT_BUNDLE))
            self.assertEqual(self.module.main([str(path)]), 0)

    def test_the_command_line_reports_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "NativeSdhci"
            path.write_bytes(macho(0x1))
            self.assertEqual(self.module.main([str(path)]), 1)


if __name__ == "__main__":
    unittest.main()
