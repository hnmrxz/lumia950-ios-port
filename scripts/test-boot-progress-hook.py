#!/usr/bin/env python3
"""Tests for ci/boot-progress.py: the three calls must land in order, once, and be checkable."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = '''#include <pexpert/pexpert.h>

void
arm_init(void)
{
	PE_init_platform(FALSE, args); /* Get platform expert set up */

	configure_timer_apple_regs();

	arm_vm_init(xmaxmem, args);

	if (debug_boot_arg) {
		patch_low_glo();
	}
}
'''


def load():
    spec = importlib.util.spec_from_file_location("boot_progress_hook", ROOT / "ci" / "boot-progress.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BootProgressHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.tree = Path(self.temporary.name) / "osfmk" / "arm"
        self.tree.mkdir(parents=True)
        self.file = self.tree / "arm_init.c"
        self.file.write_text(SAMPLE, encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_the_two_calls_land_in_order(self):
        ok, message = self.module.apply_to(self.file)
        self.assertTrue(ok, message)
        text = self.file.read_text(encoding="utf-8")
        first = text.index("args->Video.v_height, 0);")
        second = text.index("args->Video.v_height, 1);")
        vm = text.index("arm_vm_init(xmaxmem, args);")
        self.assertLess(text.index("PE_init_platform"), first, "stage 0 follows PE_init_platform")
        self.assertLess(first, vm)
        self.assertLess(second, vm, "stage 1 is before arm_vm_init")
        self.assertNotIn("v_height, 2);", text, "nothing is drawn after the MMU comes on")
        self.assertIn("extern void native_boot_progress_stage(", text)
        self.assertIn("args->Video.v_baseAddr", text, "the panel comes from boot_args, not a constant")

    def test_apply_is_idempotent(self):
        self.assertTrue(self.module.apply_to(self.file)[0])
        once = self.file.read_text(encoding="utf-8")
        ok, message = self.module.apply_to(self.file)
        self.assertTrue(ok)
        self.assertIn("already", message)
        self.assertEqual(once, self.file.read_text(encoding="utf-8"))

    def test_check_rejects_an_untouched_file(self):
        ok, message = self.module.check(self.file)
        self.assertFalse(ok)
        self.assertIn("missing", message)

    def test_refuses_when_an_anchor_is_absent(self):
        self.file.write_text("void arm_init(void) { }\n", encoding="utf-8")
        ok, message = self.module.apply_to(self.file)
        self.assertFalse(ok)
        self.assertIn("refusing", message)

    def test_finds_only_the_arm_init(self):
        (self.tree / "other.c").write_text("int x;\n", encoding="utf-8")
        self.assertEqual(self.module.find(Path(self.temporary.name)), [self.file])


if __name__ == "__main__":
    unittest.main()
