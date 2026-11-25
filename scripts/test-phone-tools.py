#!/usr/bin/env python3
"""Tests for scripts/phone-tools.py and scripts/phone-thor2.py -- the tool wrappers stay honest."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PhoneToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools = load("phone_tools", "phone-tools.py")
        cls.thor = load("phone_thor2", "phone-thor2.py")

    def test_candidates_are_absolute_and_named(self):
        for name, paths in self.tools.CANDIDATES.items():
            self.assertTrue(paths, f"{name} has no candidates")
            for path in paths:
                self.assertTrue(path.is_absolute(), f"{name}: {path} is not absolute")
                self.assertTrue(path.name.lower().endswith(".exe"), f"{name}: {path} is not an executable")

    def test_environment_override_wins(self):
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as handle:
            handle.write(b"MZ")
            temporary = handle.name
        try:
            os.environ["PHONE_TOOL_THOR2"] = temporary
            found = self.tools.find("thor2")
            self.assertEqual(str(found), temporary)
        finally:
            os.environ.pop("PHONE_TOOL_THOR2", None)
            Path(temporary).unlink(missing_ok=True)

    def test_missing_tool_is_reported_not_guessed(self):
        self.assertIsNone(self.tools.find("definitely-not-a-tool"))

    def test_thor2_refuses_to_write_without_apply(self):
        calls = []
        original = self.thor.subprocess.call
        fake_find = lambda name: Path("thor2.exe") if name == "thor2" else None

        class FakeTools:
            find = staticmethod(fake_find)

        self.thor.subprocess.call = lambda *a, **k: calls.append(a) or 0
        try:
            code = self.thor.thor2(FakeTools, ["-mode", "ffureta"], apply=False, writes=True)
        finally:
            self.thor.subprocess.call = original
        self.assertEqual(code, 0)
        self.assertEqual(calls, [], "a dry run must not start thor2")

    def test_thor2_read_only_mode_runs_without_apply(self):
        calls = []
        original = self.thor.subprocess.call
        self.thor.subprocess.call = lambda *a, **k: calls.append(a) or 0

        class FakeTools:
            find = staticmethod(lambda name: Path("thor2.exe"))

        try:
            self.thor.thor2(FakeTools, ["-mode", "list"], apply=True, writes=False)
        finally:
            self.thor.subprocess.call = original
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
