#!/usr/bin/env python3
"""Tests for ci/ramblock-hook.py: the call must land inside bsd_init, once, and be checkable."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = '''#include <sys/types.h>
#include <sys/proc.h>

int
some_other_function(void)
{
	return 0;
}

void
bsd_init(void)
{
	proc_init();
	vfs_mountroot();
}
'''


def load():
    spec = importlib.util.spec_from_file_location("ramblock_hook", ROOT / "ci" / "ramblock-hook.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RamBlockHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.tree = Path(self.temporary.name) / "bsd" / "kern"
        self.tree.mkdir(parents=True)
        self.file = self.tree / "bsd_init.c"
        self.file.write_text(SAMPLE, encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_the_call_is_inside_bsd_init_and_before_the_mount(self):
        ok, message = self.module.apply_to(self.file)
        self.assertTrue(ok, message)
        text = self.file.read_text(encoding="utf-8")
        body = text.split("bsd_init(void)")[1]
        self.assertIn("native_ramblock_publish();", body)
        self.assertLess(body.index("native_ramblock_publish()"), body.index("vfs_mountroot"))
        self.assertIn("extern int native_ramblock_publish(void);", text)

    def test_apply_is_idempotent(self):
        self.assertTrue(self.module.apply_to(self.file)[0])
        first = self.file.read_text(encoding="utf-8")
        ok, message = self.module.apply_to(self.file)
        self.assertTrue(ok)
        self.assertIn("already", message)
        self.assertEqual(first, self.file.read_text(encoding="utf-8"))

    def test_check_rejects_an_untouched_file(self):
        ok, message = self.module.check(self.file)
        self.assertFalse(ok)
        self.assertIn("missing", message)

    def test_refuses_when_bsd_init_is_absent(self):
        self.file.write_text("#include <sys/types.h>\nint x(void) { return 0; }\n", encoding="utf-8")
        ok, message = self.module.apply_to(self.file)
        self.assertFalse(ok)
        self.assertIn("refusing", message)

    def test_finds_the_file_under_a_unixnu_tree(self):
        found = self.module.candidates([Path(self.temporary.name)])
        self.assertEqual(found, [self.file])


if __name__ == "__main__":
    unittest.main()
