#!/usr/bin/env python3
"""Tests for scripts/make-mkext.py: the container has to be readable by the kernel's own checks."""

from __future__ import annotations

import importlib.util
import plistlib
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("make_mkext", ROOT / "scripts" / "make-mkext.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MakeMkextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def build(self):
        info = {"IOKitPersonalities": {"Lumia 950 eMMC": {"IOClass": "NativeSdhci"}}}
        executable = b"\xcf\xfa\xed\xfe" + b"kext-text" * 64
        blob = self.module.pack("org.unixnu.NativeSdhci", info, executable)
        return blob, executable

    def test_header_fields_follow_the_format(self):
        blob, _ = self.build()
        header = self.module.read_header(blob)
        self.assertEqual(header["magic"], 0x4D4B5854)
        self.assertEqual(header["signature"], 0x4D4F5358)
        self.assertEqual(header["length"], len(blob))
        self.assertEqual(header["version"], 0x02002001)
        self.assertEqual(header["numkexts"], 1)
        self.assertEqual(header["cputype"], 0x0100000C)

    def test_checksum_covers_version_to_end(self):
        blob, _ = self.build()
        stored = self.module.read_header(blob)["adler32"]
        self.assertEqual(stored, zlib.adler32(blob[16:]) & 0xFFFFFFFF)

    def test_file_entry_points_at_the_executable(self):
        blob, executable = self.build()
        offset = self.module.read_header(blob)["length"]  # sanity, overwritten below
        del offset
        entry = self.module.HEADER.size
        compressed, full = struct.unpack_from(">II", blob, entry)
        self.assertEqual(compressed, 0, "the entry is stored uncompressed")
        self.assertEqual(full, len(executable))
        self.assertEqual(blob[entry + 8: entry + 8 + len(executable)], executable)

    def test_plist_is_page_aligned_and_parses(self):
        blob, _ = self.build()
        header = self.module.read_header(blob)
        self.assertEqual(header["plist_offset"] % 4096, 0)
        plist = blob[header["plist_offset"]: header["plist_offset"] + header["plist_full_size"]]
        parsed = plistlib.loads(plist)
        dictionaries = parsed["_MKEXTInfoDictionaries"]
        self.assertIn("org.unixnu.NativeSdhci", dictionaries)
        entry = dictionaries["org.unixnu.NativeSdhci"]
        self.assertEqual(entry["_MKEXTExecutable"], self.module.HEADER.size)
        self.assertEqual(entry["CFBundleIdentifier"], "org.unixnu.NativeSdhci")

    def test_command_line_writes_the_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            plist_path = base / "Info.plist"
            plist_path.write_bytes(plistlib.dumps({"CFBundleIdentifier": "org.unixnu.NativeSdhci"}))
            executable = base / "NativeSdhci"
            executable.write_bytes(b"\xcf\xfa\xed\xfe" + b"x" * 100)
            output = base / "NativeSdhci.mkext"
            code = self.module.main(["--bundle-id", "org.unixnu.NativeSdhci",
                                     "--info-plist", str(plist_path),
                                     "--executable", str(executable),
                                     "--output", str(output)])
            self.assertEqual(code, 0)
            blob = output.read_bytes()
            self.assertEqual(self.module.read_header(blob)["length"], len(blob))

    def test_missing_inputs_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            code = self.module.main(["--bundle-id", "x", "--info-plist", str(base / "absent.plist"),
                                     "--executable", str(base / "absent"), "--output", str(base / "out.mkext")])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
