#!/usr/bin/env python3
"""Tests for scripts/embed-blob.py: a blob that cannot be compiled is a build failure at the last moment."""

from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("embed_blob", ROOT / "scripts" / "embed-blob.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class EmbedBlobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def test_the_array_and_its_size_are_emitted(self):
        data = bytes(range(40))
        text = self.module.emit(data, "lumia_blob")
        self.assertIn('extern "C" const unsigned char lumia_blob[] = {', text)
        self.assertIn("extern \"C\" const unsigned long lumia_blob_size = 40UL;", text)
        values = re.findall(r"0x([0-9A-F]{2})", text)
        self.assertEqual([int(value, 16) for value in values], list(data))

    def test_rows_are_sixteen_bytes(self):
        text = self.module.emit(bytes(32), "blob")
        rows = [line for line in text.splitlines() if line.strip().startswith("0x")]
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0].split(",")), 17)  # 16 values and the trailing empty piece

    def test_the_command_line_writes_a_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.bin"
            source.write_bytes(b"\x01\x02\x03")
            output = base / "blob.cpp"
            self.assertEqual(self.module.main(["--input", str(source), "--symbol", "blob",
                                               "--output", str(output)]), 0)
            self.assertIn("blob_size = 3UL", output.read_text(encoding="utf-8"))

    def test_a_bad_symbol_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.bin"
            source.write_bytes(b"\x01")
            self.assertEqual(self.module.main(["--input", str(source), "--symbol", "not a symbol",
                                               "--output", str(base / "out.cpp")]), 2)

    def test_a_missing_input_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.assertEqual(self.module.main(["--input", str(base / "absent"), "--symbol", "blob",
                                               "--output", str(base / "out.cpp")]), 2)


if __name__ == "__main__":
    unittest.main()
