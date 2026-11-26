#!/usr/bin/env python3
"""The offline deployment rehearsal must keep working: it is the runbook's dry-run evidence."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class RehearsalTests(unittest.TestCase):
    def test_the_rehearsal_reports_success_and_writes_nothing(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "rehearse-phone-install.py")],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("dry-run exit: 0", result.stdout)
        self.assertIn("the dry run wrote nothing: True", result.stdout)
        self.assertIn("bcdedit /store", result.stdout)
        # the runbook's one command, against a reference store and against a drifted one
        self.assertIn("install + verify (reference store) exit: 0", result.stdout)
        self.assertIn("store matches the layout: True", result.stdout)
        self.assertIn("install + verify (loader-path store) exit: 1", result.stdout)


if __name__ == "__main__":
    unittest.main()
