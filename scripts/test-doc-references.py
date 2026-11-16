#!/usr/bin/env python3
"""Tests for scripts/check-doc-references.py.

The regression: the bootstrap replaced a 896-line README and left a dozen comments pointing at
sections that no longer existed. Nothing failed, because nothing looked.

    python3 scripts/test-doc-references.py
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check-doc-references.py")
ROOT = SCRIPT.parent.parent


class DocReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "scripts").mkdir()
        self.write("README.md", "# readme\n\nThe GPU is here.\n")

    def write(self, name, text) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def run_check(self, expect=0):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, expect,
                         f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def test_the_repository_has_no_dangling_reference(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(ROOT)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("doc references ok", result.stdout)

    def test_a_reference_to_a_missing_section_is_refused(self):
        self.write("scripts/thing.py", '# see README.md, "The boot route"\nx = 1\n')
        result = self.run_check(expect=1)
        self.assertIn("no section called 'The boot route'", result.stderr)

    def test_a_reference_to_a_present_section_passes(self):
        self.write("scripts/thing.py", '# see README.md, "The GPU"\nx = 1\n')
        self.run_check()

    def test_a_path_argument_is_not_a_section_reference(self):
        # shutil.copy2(SOURCES / "README.md", output / "README.txt") must not be scanned as one.
        self.write("scripts/thing.py", 'copy2(SOURCES / "README.md", output / "README.txt")\n')
        self.run_check()

    def test_the_blocker_form_is_checked_too(self):
        self.write("scripts/thing.py", "# See README.md, blocker 4.\n")
        self.run_check(expect=1)
        self.write("README.md", "# readme\n\nblocker 4: no SYSTEM_OFF.\n")
        self.run_check()

    def test_a_missing_readme_is_refused(self):
        (self.root / "README.md").unlink()
        result = self.run_check(expect=1)
        self.assertIn("README.md is missing", result.stderr)


if __name__ == "__main__":
    unittest.main()
