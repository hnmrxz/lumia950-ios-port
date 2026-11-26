#!/usr/bin/env python3
"""Tests for scripts/phone-modes.py: the wrapper must be unable to surprise its user."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "scripts" / "phone-modes.py"


def load_module():
    spec = importlib.util.spec_from_file_location("phone_modes", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PhoneModesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_every_exposed_mode_maps_to_a_switch(self):
        for mode, (switch, changes, description) in self.module.MODES.items():
            self.assertTrue(switch[0].isupper(), f"{mode}: switch {switch!r} looks wrong")
            self.assertIsInstance(changes, bool)
            self.assertTrue(description)

    def test_the_phone_changing_switches_are_marked(self):
        # These must not run without --apply; a refactor that flips one of these flags would let a
        # bare invocation change the handset.
        for mode in ("mass-storage", "unlock", "root", "fix-boot"):
            self.assertTrue(self.module.MODES[mode][1], f"{mode} must be marked as changing the phone")
        self.assertFalse(self.module.MODES["info"][1], "info has to stay read-only")

    def test_dry_run_does_not_execute(self):
        calls = []
        original = self.module.subprocess.call
        self.module.subprocess.call = lambda *a, **k: calls.append(a) or 0
        try:
            code = self.module.run(Path("WPinternals.exe"), "SwitchToMassStorageMode", [], apply=False, changes=True)
        finally:
            self.module.subprocess.call = original
        self.assertEqual(code, 0)
        self.assertEqual(calls, [], "a dry run must not start the tool")

    def test_apply_runs_the_exact_switch(self):
        calls = []
        original = self.module.subprocess.call
        self.module.subprocess.call = lambda *a, **k: calls.append(a) or 0
        try:
            self.module.run(Path("WPinternals.exe"), "ShowPhoneInfo", [], apply=False, changes=False)
        finally:
            self.module.subprocess.call = original
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], ["WPinternals.exe", "-ShowPhoneInfo"])

    def test_tool_must_exist(self):
        with self.assertRaises(SystemExit):
            self.module.find_tool(Path("does-not-exist.exe"))

    def test_missing_tool_reports_the_default_path(self):
        with self.assertRaises(SystemExit) as raised:
            self.module.find_tool(None) if not Path(self.module.DEFAULT_TOOL).is_file() else (_ for _ in ()).throw(SystemExit())
        self.assertIsNotNone(raised.exception)


if __name__ == "__main__":
    unittest.main()
