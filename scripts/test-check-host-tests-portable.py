#!/usr/bin/env python3
"""Tests for scripts/check-host-tests-portable.py."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("portable", ROOT / "scripts" / "check-host-tests-portable.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PortableCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def write(self, text: str) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
        handle.write(text)
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return Path(handle.name)

    def test_windows_absolute_through_plain_path_is_flagged(self):
        path = self.write('from pathlib import Path\np = Path(r"C:\\\\tools\\\\x.exe")\n')
        problems = self.module.check(path)
        self.assertTrue(problems)
        self.assertIn("PureWindowsPath", problems[0])

    def test_pure_windows_path_is_accepted(self):
        path = self.write('from pathlib import PureWindowsPath\np = PureWindowsPath(r"C:\\\\tools\\\\x.exe")\n')
        self.assertEqual(self.module.check(path), [])

    def test_plain_posix_test_is_accepted(self):
        path = self.write('from pathlib import Path\np = Path("/tmp/x")\n')
        self.assertEqual(self.module.check(path), [])

    def test_repository_tests_are_portable(self):
        files = self.module.test_files([ROOT])
        self.assertTrue(files)
        offenders = {path.name: self.module.check(path) for path in files}
        offenders = {name: problems for name, problems in offenders.items() if problems}
        self.assertEqual(offenders, {})


if __name__ == "__main__":
    unittest.main()
