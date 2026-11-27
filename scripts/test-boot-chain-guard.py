#!/usr/bin/env python3
"""Tests for scripts/boot-chain-guard.py: six classes protected, one gate, no bypass by deletion or by editing hashes."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("boot_chain_guard", ROOT / "scripts" / "boot-chain-guard.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BootChainGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def test_all_six_classes_are_protected(self):
        for path in ("EFI/boot/bootarm.efi", "EFI/boot/BootShim.efi", "UEFI.elf",
                     "EFI/Microsoft/BOOT/BCD", "EFI/BOOT/BOOTAA64.EFI", "EFI/UniXNU/unixnu.toml"):
            protected, why = self.module.classify(path)
            self.assertTrue(protected, f"{path} must be protected ({why})")

    def test_path_spelling_does_not_matter(self):
        for spelling in ("EFI\\boot\\bootarm.efi", "efi/boot/BOOTARM.EFI", "EFI/Boot/Bootarm.efi"):
            self.assertTrue(self.module.classify(spelling)[0], spelling)

    def test_the_whole_unixnu_tree_is_protected(self):
        for path in ("EFI/UniXNU/UniXNU.efi", "EFI/UniXNU/Drivers/DarwinBoot.efi",
                     "EFI/UniXNU/Payloads/kernel.macho"):
            self.assertTrue(self.module.classify(path)[0], path)

    def test_ordinary_files_are_allowed(self):
        for path in ("EFI/Boot/notes.txt", "readme.txt", "EFI/UniXNULib/x.efi"):
            self.assertFalse(self.module.classify(path)[0], path)

    def test_a_protected_write_needs_both_the_flag_and_a_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            backup = Path(temporary) / "before.efi"
            backup.write_bytes(b"backup")
            self.assertEqual(self.module.main(["check", "--path", "EFI/BOOT/BOOTAA64.EFI"]), 1)
            self.assertEqual(self.module.main(["check", "--path", "EFI/BOOT/BOOTAA64.EFI",
                                               "--replace-protected"]), 1)
            self.assertEqual(self.module.main(["check", "--path", "EFI/BOOT/BOOTAA64.EFI",
                                               "--replace-protected", "--backup", str(backup)]), 0)
            self.assertEqual(self.module.main(["check", "--path", "EFI/BOOT/notes.txt"]), 0)

    def test_a_missing_backup_does_not_count(self):
        self.assertEqual(self.module.main(["check", "--path", "UEFI.elf", "--replace-protected",
                                           "--backup", "does-not-exist.efi"]), 1)

    def test_inventory_records_the_tree_with_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            volume = Path(temporary)
            (volume / "EFI" / "boot").mkdir(parents=True)
            (volume / "EFI" / "boot" / "bootarm.efi").write_bytes(b"arm")
            (volume / "EFI" / "UniXNU" / "Drivers").mkdir(parents=True)
            (volume / "EFI" / "UniXNU" / "Drivers" / "DarwinBoot.efi").write_bytes(b"darwin")
            report = self.module.inventory(volume)
            names = {self.module.normalise(name) for name in report["files"]}
            self.assertIn("efi/boot/bootarm.efi", names)
            self.assertIn("efi/unixnu/drivers/darwinboot.efi", names)
            recorded = next(value for key, value in report["files"].items()
                            if self.module.normalise(key) == "efi/boot/bootarm.efi")
            self.assertEqual(recorded["sha256"], hashlib.sha256(b"arm").hexdigest())

    def test_the_inventory_command_writes_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            volume = Path(temporary) / "vol"
            (volume / "EFI" / "UniXNU").mkdir(parents=True)
            (volume / "EFI" / "UniXNU" / "unixnu.toml").write_bytes(b"version = 1\n")
            out = Path(temporary) / "out" / "inventory.json"
            self.assertEqual(self.module.main(["inventory", "--root", str(volume), "--out", str(out)]), 0)
            parsed = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("EFI/UniXNU/unixnu.toml", parsed["files"])


if __name__ == "__main__":
    unittest.main()
