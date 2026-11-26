#!/usr/bin/env python3
"""Tests for ci/boot-progress.py: two calls, the first inside arm_init, once, and checkable."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = '''#include <pexpert/pexpert.h>

void arm_init(boot_args * args);

void
arm_init(
	boot_args       *args)
{
	int early = 0;

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

    def test_stage_zero_is_inside_arm_init_and_before_the_platform_call(self):
        ok, message = self.module.apply_to(self.file)
        self.assertTrue(ok, message)
        text = self.file.read_text(encoding="utf-8")
        body = self.module.arm_init_body(text)
        self.assertIsNotNone(body, "the sample has no arm_init to anchor on")
        stage0 = text.index("args->CommandLine, 0)")
        self.assertGreater(stage0, body, "stage 0 must be inside arm_init")
        self.assertLess(stage0, text.index("PE_init_platform"), "stage 0 must come before the platform call")
        declarations = text.index("int early = 0;")
        self.assertLess(declarations, stage0, "stage 0 must not precede the declarations")

    def test_stage_one_sits_before_arm_vm_init(self):
        ok, message = self.module.apply_to(self.file)
        self.assertTrue(ok, message)
        text = self.file.read_text(encoding="utf-8")
        stage1 = text.index("args->CommandLine, 1)")
        self.assertLess(stage1, text.index("arm_vm_init(xmaxmem, args);"))
        self.assertNotIn("CommandLine, 2)", text, "nothing is drawn after the MMU comes on")

    def test_the_panel_comes_from_boot_args(self):
        self.assertTrue(self.module.apply_to(self.file)[0])
        text = self.file.read_text(encoding="utf-8")
        self.assertIn("args->Video.v_baseAddr", text)
        self.assertIn("args->Video.v_rowBytes", text)

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

    def test_a_copy_without_arm_vm_init_is_skipped_not_failed(self):
        self.file.write_text("void arm_init(void)\n{\n}\n", encoding="utf-8")
        ok, message = self.module.apply_to(self.file)
        self.assertFalse(ok)
        self.assertTrue(message.startswith("skipped"), message)

    def test_one_patchable_copy_is_enough(self):
        other = Path(self.temporary.name) / "feeds" / "osfmk" / "arm"
        other.mkdir(parents=True)
        (other / "arm_init.c").write_text("int unrelated;\n", encoding="utf-8")
        code = self.module.main(["--root", self.temporary.name, "--apply"])
        self.assertEqual(code, 0, "a tree without the anchors must not fail the run on its own")


if __name__ == "__main__":
    unittest.main()
