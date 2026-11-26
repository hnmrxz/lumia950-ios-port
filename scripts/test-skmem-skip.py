#!/usr/bin/env python3
"""Tests for ci/skmem-skip.py: it must patch the real function shape, be idempotent, and refuse odd input."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = '''#include <sys/types.h>
#include <sys/sysctl.h>

static struct sysctl_oid *sk_sys_obj;

void
skmem_sysctl_init(void)
{
	if (sk_sys_obj == NULL) {
		panic("skmem: no sysctl object");
	}
	sk_sys_obj->version = 1;
}

int other_function(void)
{
	return 0;
}
'''




PRIVATE_SAMPLE = '''#include <sys/types.h>

__private_extern__ void
skmem_sysctl_init(void)
{
	sk_sys_obj->version = 1;
}
'''



def load():
    spec = importlib.util.spec_from_file_location("skmem_skip", ROOT / "ci" / "skmem-skip.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SkmemSkipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.tree = Path(self.temporary.name) / "bsd" / "net"
        self.tree.mkdir(parents=True)
        self.file = self.tree / "skmem_sysctl.c"
        self.file.write_text(SAMPLE, encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_apply_puts_the_guard_first_in_the_function(self):
        ok, message = self.module.apply_to(self.file)
        self.assertTrue(ok, message)
        text = self.file.read_text(encoding="utf-8")
        body = text.split("skmem_sysctl_init(void)")[1]
        self.assertIn("skmem_sysctl_skip_requested()", body)
        self.assertLess(body.index("skmem_sysctl_skip_requested()"), body.index("panic("))
        self.assertIn("#include <pexpert/pexpert.h>", text)

    def test_apply_is_idempotent(self):
        self.assertTrue(self.module.apply_to(self.file)[0])
        first = self.file.read_text(encoding="utf-8")
        ok, message = self.module.apply_to(self.file)
        self.assertTrue(ok)
        self.assertIn("already", message)
        self.assertEqual(first, self.file.read_text(encoding="utf-8"))

    def test_check_rejects_untouched_file(self):
        ok, message = self.module.check(self.file)
        self.assertFalse(ok)
        self.assertIn("guard", message)

    def test_refuses_when_the_function_is_absent(self):
        self.file.write_text("#include <sys/types.h>\nint unrelated(void) { return 0; }\n", encoding="utf-8")
        ok, message = self.module.apply_to(self.file)
        self.assertFalse(ok)
        self.assertIn("refusing", message)


    def test_helper_goes_above_a_private_extern_declaration(self):
        """Splitting `__private_extern__ void` from the name is a hard compile error."""
        path = Path(self.temporary.name) / "private" / "skmem_sysctl.c"
        path.parent.mkdir(parents=True)
        path.write_text(PRIVATE_SAMPLE, encoding="utf-8")
        ok, message = self.module.apply_to(path)
        self.assertTrue(ok, message)
        text = path.read_text(encoding="utf-8")
        helper_at = text.index("skmem_sysctl_skip_requested(")
        private_at = text.index("__private_extern__ void")
        self.assertLess(helper_at, private_at, "the helper must precede the declaration specifiers")
        self.assertIn("__private_extern__ void\nskmem_sysctl_init(void)", text)


    def test_find_locates_the_file(self):
        found = self.module.candidates([Path(self.temporary.name)])
        self.assertEqual(found, [self.file])

    def test_finds_the_file_below_a_unixnu_output_tree(self):
        """The CI step searches $UNIXNU_OUT, where the source sits several directories down."""
        tree = Path(self.temporary.name) / "lumia950" / "tree" / "src" / "xnu" / "bsd" / "net"
        tree.mkdir(parents=True)
        target = tree / "skmem_sysctl.c"
        target.write_text(SAMPLE, encoding="utf-8")
        found = self.module.candidates([Path(self.temporary.name)])
        self.assertIn(target, found)
        ok, message = self.module.apply_to(target)
        self.assertTrue(ok, message)
        self.assertTrue(self.module.check(target)[0])


if __name__ == "__main__":
    unittest.main()

