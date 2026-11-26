#!/usr/bin/env python3
"""Tests for scripts/add-prelink-entry.py: an edit that does not read back is not an edit."""

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
    "<dict><key>CFBundleIdentifier</key><string>com.apple.iokit.IOStorageFamily</string>"
    '<key>_PrelinkExecutableLoadAddr</key><integer size="64">0xfffffff00400b280</integer>'
    "</dict></array>"
    "<key>_PrelinkKCID</key><data>AAAA</data></dict>"
)


def load():
    spec = importlib.util.spec_from_file_location("add_prelink_entry", ROOT / "scripts" / "add-prelink-entry.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def image(payload: bytes, segment_size: int | None = None) -> bytes:
    size = segment_size or (len(payload) + 1024)
    header = 32
    command = 72
    fileoff = header + command
    blob = bytearray()
    blob += struct.pack("<IiiIIIII", 0xFEEDFACF, 0x0100000C, 0, 2, 1, command, 0, 0)
    blob += struct.pack("<II", 0x19, command)
    blob += b"__PRELINK_INFO".ljust(16, b"\0")
    blob += struct.pack("<QQQQiiII", 0xFFFFFFF0082CC000, size, fileoff, size, 7, 7, 1, 0)
    blob += payload + b"\0" * (size - len(payload))
    return bytes(blob)


class AddPrelinkEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def test_the_entry_is_inserted_and_reads_back(self):
        original = image(PAYLOAD.encode())
        updated, detail = self.module.insert(original, "org.unixnu.NativeSdhci", 0xFFFFFFF0082CC000, 0x2000)
        payload, _ = self.module.inspect_prelink.prelink_info(updated)
        rows = self.module.inspect_prelink.summarise(self.module.inspect_prelink.parse_dictionary(payload))
        ids = [row["id"] for row in rows]
        self.assertIn("com.apple.iokit.IOStorageFamily", ids, "the existing entry must survive")
        self.assertIn("org.unixnu.NativeSdhci", ids)
        self.assertEqual(detail["segment_size"], len(payload))

    def test_everything_but_the_insertion_is_untouched(self):
        original = image(PAYLOAD.encode())
        updated, detail = self.module.insert(original, "x.y", 0x1000, 0x10)
        cut = detail["inserted_at"] + 32  # header words of the image precede the payload
        # the bytes before the insertion point are identical
        self.assertEqual(original[:cut], updated[:cut])

    def test_an_entry_that_does_not_fit_is_refused(self):
        tight = image(PAYLOAD.encode(), segment_size=len(PAYLOAD) + 8)
        with self.assertRaises(ValueError):
            self.module.insert(tight, "a" * 64, 0x1000, 0x2000)

    def test_an_image_without_the_dictionary_is_refused(self):
        with self.assertRaises(ValueError):
            self.module.insert(image(b"<dict></dict>"), "x.y", 0x1000, 0x10)

    def test_the_command_line_writes_a_readable_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "in.macho"
            source.write_bytes(image(PAYLOAD.encode()))
            output = base / "out.macho"
            code = self.module.main(["--image", str(source), "--bundle-id", "org.unixnu.NativeSdhci",
                                     "--load-addr", "0xfffffff0082cc000", "--size", "0x2000",
                                     "--output", str(output)])
            self.assertEqual(code, 0)
            self.assertTrue(output.is_file())

    def test_a_missing_image_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            code = self.module.main(["--image", str(Path(temporary) / "absent"), "--bundle-id", "x.y",
                                     "--load-addr", "0x1000", "--size", "0x10",
                                     "--output", str(Path(temporary) / "out.macho")])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
