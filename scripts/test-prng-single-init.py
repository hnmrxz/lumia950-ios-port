#!/usr/bin/env python3
"""Tests for ci/prng-single-init.py: the guard has to land on the assertion and nowhere else."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = '''void
register_and_init_prng(struct cckprng_ctx *ctx, const struct cckprng_funcs *funcs)
{
\tassert(cpu_number() == master_cpu);
\tassert(!prng_ready);

\tentropy_init();

\tprng_ctx = ctx;
\tprng_ready = 1;
}
'''


def load():
    spec = importlib.util.spec_from_file_location("prng_single_init", ROOT / "ci" / "prng-single-init.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PrngSingleInitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.tree = Path(self.temporary.name) / "osfmk" / "prng"
        self.tree.mkdir(parents=True)
        self.file = self.tree / "prng_random.c"
        self.file.write_text(SAMPLE, encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_the_assertion_becomes_a_guard(self):
        ok, message = self.module.apply_to(self.file)
        self.assertTrue(ok, message)
        text = self.file.read_text(encoding="utf-8")
        self.assertNotIn("assert(!prng_ready);", text)
        self.assertIn("if (prng_ready) {", text)
        self.assertIn("return;", text)
        # the master-cpu assertion is not ours to touch
        self.assertIn("assert(cpu_number() == master_cpu);", text)

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

    def test_a_copy_without_the_assertion_is_skipped(self):
        self.file.write_text("int unrelated;\n", encoding="utf-8")
        ok, message = self.module.apply_to(self.file)
        self.assertFalse(ok)
        self.assertTrue(message.startswith("skipped"), message)

    def test_one_patchable_copy_is_enough(self):
        other = Path(self.temporary.name) / "feeds" / "osfmk" / "prng"
        other.mkdir(parents=True)
        (other / "prng_random.c").write_text("int unrelated;\n", encoding="utf-8")
        self.assertEqual(self.module.main(["--root", self.temporary.name, "--apply"]), 0)

    def test_nothing_patchable_is_an_error(self):
        self.file.write_text("int unrelated;\n", encoding="utf-8")
        self.assertEqual(self.module.main(["--root", self.temporary.name, "--apply"]), 1)


if __name__ == "__main__":
    unittest.main()
