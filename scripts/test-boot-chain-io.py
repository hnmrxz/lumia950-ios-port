#!/usr/bin/env python3
"""Tests for scripts/boot-chain-io.py: one gate, complete requests only, and deletion covered by the same rule."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("boot_chain_io", ROOT / "scripts" / "boot-chain-io.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BootChainIoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.io = load()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.backup = self.base / "before.efi"
        self.backup.write_bytes(b"backup")
        self.target = self.base / "EFI" / "UniXNU" / "unixnu.toml"
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"version = 1\n")

    def tearDown(self):
        self.temporary.cleanup()

    def test_creating_a_protected_object_needs_nothing(self):
        fresh = self.base / "EFI" / "BOOT" / "BOOTAA64.EFI"
        decision = self.io.authorise(fresh)
        self.assertTrue(decision.allowed, decision.message)

    def test_replacing_without_the_flag_is_refused(self):
        decision = self.io.authorise(self.target)
        self.assertFalse(decision.allowed)
        self.assertIn("refused", decision.message)

    def test_the_flag_alone_is_not_enough(self):
        decision = self.io.authorise(self.target, replace=True)
        self.assertFalse(decision.allowed)
        self.assertIn("--backup", decision.message)

    def test_a_missing_backup_file_does_not_count(self):
        decision = self.io.authorise(self.target, replace=True, backup=self.base / "absent.efi",
                                     reason="test", verify="test")
        self.assertFalse(decision.allowed)

    def test_a_complete_request_is_allowed_and_recorded(self):
        decision = self.io.authorise(self.target, replace=True, backup=self.backup,
                                     reason="swap the menu config for the microSD experiment",
                                     verify="photograph the menu and the hand-off page")
        self.assertTrue(decision.allowed, decision.message)
        self.assertIn("reason=", decision.message)
        self.assertIn("verify=", decision.message)

    def test_deleting_a_protected_object_needs_the_same_evidence(self):
        self.assertFalse(self.io.authorise(self.target, delete=True).allowed)
        allowed = self.io.authorise(self.target, delete=True, backup=self.backup,
                                    reason="remove a broken config", verify="menu still boots")
        self.assertTrue(allowed.allowed, allowed.message)

    def test_every_protected_class_is_recognised(self):
        for relative in ("EFI/boot/bootarm.efi", "EFI/boot/BootShim.efi", "UEFI.elf",
                         "EFI/Microsoft/BOOT/BCD", "EFI/BOOT/BOOTAA64.EFI", "EFI/UniXNU/Drivers/DarwinBoot.efi"):
            self.assertIsNotNone(self.io.protected_object(Path(relative)), relative)

    def test_an_ordinary_file_is_not_protected(self):
        self.assertIsNone(self.io.protected_object(Path("EFI/BOOT/notes.txt")))

    def test_the_command_line_reports_the_same_decision(self):
        self.assertEqual(self.io.main([str(self.target)]), 1)
        self.assertEqual(self.io.main([str(self.target), "--replace-protected"]), 1)
        self.assertEqual(self.io.main([str(self.target), "--replace-protected", "--backup", str(self.backup),
                                       "--reason", "r", "--verify", "v"]), 0)


if __name__ == "__main__":
    unittest.main()
