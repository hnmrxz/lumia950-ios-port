#!/usr/bin/env python3
"""Tests for scripts/check-bcd-layout.py, using the WOA store's own enumeration as a fixture."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WOA_ENUM = """
Windows 启动管理器
--------------------
标识符                  {bootmgr}
device                  unknown
path                    \\efi\\boot\\bootarm.efi
description             Windows Boot Manager
default                 {default}
bootsequence            {01de5a27-8705-40db-bad6-96fa5187d4a6}
timeout                 0

Windows 启动应用程序(1020000a)
-----------------------------------
标识符                  {default}
device                  unknown
path                    \\windows\\system32\\boot\\bootshim.efi
description             BootShim Application

Windows 启动加载器
-------------------
标识符                  {deadbeef-0000-0000-0000-000000000001}
device                  partition=F:
path                    \\windows\\system32\\boot\\winload.efi
description             Windows Loader
"""

HIJACKED_ENUM = WOA_ENUM.replace(
    "path                    \\windows\\system32\\boot\\bootshim.efi",
    "path                    \\EFI\\boot\\BootShim.efi").replace(
    "device                  unknown\npath                    \\EFI",
    "device                  partition=R:\npath                    \\EFI")


def load():
    spec = importlib.util.spec_from_file_location("check_bcd_layout", ROOT / "scripts" / "check-bcd-layout.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CheckBcdLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def test_reference_layout_passes(self):
        entries = self.module.parse(WOA_ENUM)
        self.assertEqual(self.module.check(entries, "mainos"), [])

    def test_efiesp_path_fails_the_mainos_expectation_with_a_fix(self):
        entries = self.module.parse(HIJACKED_ENUM)
        problems = self.module.check(entries, "mainos")
        self.assertTrue(problems)
        text = "\n".join(problems)
        self.assertIn("bootshim.efi", text.lower())
        commands = "\n".join(self.module.fixes("{default}", "mainos"))
        self.assertIn(r"\windows\system32\boot\bootshim.efi", commands.lower())

    def test_missing_bootmgr_is_reported(self):
        entries = self.module.parse("Windows 启动加载器\n-----------\n标识符 {default}\npath \\windows\\system32\\boot\\winload.efi\n")
        problems = self.module.check(entries, "mainos")
        self.assertTrue(any("bootmgr" in problem for problem in problems))

    def test_windows_expectation_accepts_the_loader(self):
        text = WOA_ENUM.replace(
            "path                    \\windows\\system32\\boot\\bootshim.efi",
            "path                    \\windows\\system32\\boot\\winload.efi")
        entries = self.module.parse(text)
        self.assertEqual(self.module.check(entries, "windows"), [])


if __name__ == "__main__":
    unittest.main()
