#!/usr/bin/env python3
"""The recovery scripts must at least parse: a syntax error there fails when the phone is already broken."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class PowerShellParseTests(unittest.TestCase):
    def test_recovery_scripts_parse(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check-powershell-parses.py")],
            capture_output=True, text=True, timeout=300)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn('"failures": 0', output)


if __name__ == "__main__":
    unittest.main()
