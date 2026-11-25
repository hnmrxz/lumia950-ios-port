#!/usr/bin/env python3
"""The rollback rehearsal must keep working: it is the runbook's step-5 evidence."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class RollbackRehearsalTests(unittest.TestCase):
    def test_snapshot_and_restore_round_trip(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "rehearse-phone-rollback.py")],
            capture_output=True, text=True, timeout=120)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("dry run left the store damaged: True", output)
        self.assertIn("store restored: True", output)
        self.assertIn("manifest verified: True", output)


if __name__ == "__main__":
    unittest.main()
