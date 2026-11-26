#!/usr/bin/env python3
"""Tests for ci/kernel-personality.py: the table gains one entry, once, and other copies are tolerated."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TABLE = '''const char * gIOKernelConfigTables =
    "("
    "   {"
    "     'IOClass'         = IOPanicPlatform;"
    "     'IOProviderClass' = IOPlatformExpertDevice;"
    "     'IOProbeScore'    = 0:32;"
    "   }"
    ")";
'''


def load():
    spec = importlib.util.spec_from_file_location("kernel_personality", ROOT / "ci" / "kernel-personality.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class KernelPersonalityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.tree = Path(self.temporary.name) / "iokit"
        self.tree.mkdir(parents=True)
        self.file = self.tree / "KernelConfigTables.cpp"
        self.file.write_text(TABLE, encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_the_entry_lands_inside_the_table(self):
        ok, message = self.module.apply_to(self.file)
        self.assertTrue(ok, message)
        text = self.file.read_text(encoding="utf-8")
        start = text.index('"("')
        end = text.rindex('")";')
        self.assertGreater(text.index("'IOClass'         = NativeSdhci;"), start)
        self.assertLess(text.index("'IOClass'         = NativeSdhci;"), end)
        self.assertIn("'IOProviderClass' = IOPlatformDevice;", text)
        self.assertIn("'IOProbeScore'    = 60000:32;", text)

    def test_apply_is_idempotent(self):
        self.assertTrue(self.module.apply_to(self.file)[0])
        once = self.file.read_text(encoding="utf-8")
        ok, message = self.module.apply_to(self.file)
        self.assertTrue(ok)
        self.assertIn("already", message)
        self.assertEqual(once, self.file.read_text(encoding="utf-8"))

    def test_check_rejects_an_untouched_table(self):
        ok, message = self.module.check(self.file)
        self.assertFalse(ok)
        self.assertIn("missing", message)

    def test_a_copy_with_another_shape_is_skipped(self):
        self.file.write_text("const char * gIOKernelConfigTables = \"()\";\n", encoding="utf-8")
        ok, message = self.module.apply_to(self.file)
        self.assertFalse(ok)
        self.assertTrue(message.startswith("skipped"), message)

    def test_one_patchable_table_is_enough(self):
        other = Path(self.temporary.name) / "feeds" / "iokit"
        other.mkdir(parents=True)
        (other / "KernelConfigTables.cpp").write_text("const char * gIOKernelConfigTables = \"()\";\n",
                                                      encoding="utf-8")
        self.assertEqual(self.module.main(["--root", self.temporary.name, "--apply"]), 0)

    def test_no_patchable_table_is_an_error(self):
        self.file.write_text("const char * gIOKernelConfigTables = \"()\";\n", encoding="utf-8")
        self.assertEqual(self.module.main(["--root", self.temporary.name, "--apply"]), 1)


if __name__ == "__main__":
    unittest.main()
