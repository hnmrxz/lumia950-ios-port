#!/usr/bin/env python3
"""Tests for scripts/phone-install.py -- the shim must land where the reference image keeps it."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("phone_install", ROOT / "scripts" / "phone-install.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PhoneInstallLayoutTests(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.efiesp = base / "EFIESP"
        self.mainos = base / "MainOS"
        self.efiesp.mkdir()
        self.mainos.mkdir()
        self.bootshim = base / "BootShim.efi"
        self.bootshim.write_bytes(b"MZ" + b"\x00" * 64)
        self.uefi = base / "UEFI.elf"
        self.uefi.write_bytes(b"\x7fELF" + b"\x00" * 64)
        self.payload = base / "payload"

    def tearDown(self):
        self.temporary.cleanup()

    def run_installer(self, *extra):
        return self.module.main([
            "--efiesp", str(self.efiesp),
            "--mainos", str(self.mainos),
            "--bootshim", str(self.bootshim),
            "--uefi-elf", str(self.uefi),
            "--payload", str(self.payload),
            "--stage", str(self.payload),
            "--apply",
            *extra,
        ])

    def test_default_layout_puts_the_shim_on_mainos(self):
        self.assertEqual(self.run_installer(), 0)
        self.assertTrue((self.mainos / "Windows" / "System32" / "Boot" / "bootshim.efi").is_file())
        self.assertFalse((self.efiesp / "EFI" / "boot" / "BootShim.efi").exists())
        self.assertTrue((self.efiesp / "UEFI.elf").is_file())

    def test_efiesp_layout_is_still_available(self):
        self.assertEqual(self.run_installer("--layout", "efiesp"), 0)
        self.assertTrue((self.efiesp / "EFI" / "boot" / "BootShim.efi").is_file())
        self.assertFalse((self.mainos / "Windows" / "System32" / "Boot" / "bootshim.efi").exists())

    def test_refind_tree_is_copied_when_given(self):
        tree = Path(self.temporary.name) / "refind"
        (tree / "icons").mkdir(parents=True)
        (tree / "refind.conf").write_text("timeout 0\n", encoding="utf-8")
        (tree / "icons" / "os_win.png").write_bytes(b"\x89PNG")
        self.assertEqual(self.run_installer("--refind", str(tree)), 0)
        copied = self.efiesp / "EFI" / "REFIND"
        self.assertTrue((copied / "refind.conf").is_file())
        self.assertTrue((copied / "icons" / "os_win.png").is_file())


if __name__ == "__main__":
    unittest.main()
