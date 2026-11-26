#!/usr/bin/env python3
"""Tests for scripts/swap-loader.py: the boot option can always be put back."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("swap_loader", ROOT / "scripts" / "swap-loader.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SwapLoaderTests(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.temporary = tempfile.TemporaryDirectory()
        self.volume = Path(self.temporary.name)
        (self.volume / "EFI" / "BOOT").mkdir(parents=True)
        self.loader = self.volume / "EFI" / "BOOT" / "BOOTAA64.EFI"
        self.loader_bytes = b"loader" * 40
        self.loader.write_bytes(self.loader_bytes)
        self.mark = Path(self.temporary.name) / "LumiaControlMark.efi"
        self.mark_bytes = b"control-mark" * 8
        self.mark.write_bytes(self.mark_bytes)

    def tearDown(self):
        self.temporary.cleanup()

    def run_script(self, *arguments):
        return self.module.main(["--efiesp", str(self.volume), *arguments])

    def test_show_changes_nothing(self):
        self.assertEqual(self.run_script("--show"), 0)
        self.assertEqual(self.loader.read_bytes(), self.loader_bytes)

    def test_install_backs_up_the_loader_and_installs_the_mark(self):
        self.assertEqual(self.run_script("--control-mark", str(self.mark), "--apply"), 0)
        backup = self.volume / "EFI" / "BOOT" / "BOOTAA64.EFI.before-control-mark"
        self.assertEqual(backup.read_bytes(), self.loader_bytes)
        self.assertEqual(self.loader.read_bytes(), self.mark_bytes)

    def test_restore_puts_the_loader_back(self):
        self.assertEqual(self.run_script("--control-mark", str(self.mark), "--apply"), 0)
        self.assertEqual(self.run_script("--restore"), 0)
        self.assertEqual(self.loader.read_bytes(), self.loader_bytes)

    def test_restore_without_a_backup_is_refused(self):
        self.assertEqual(self.run_script("--restore"), 1)

    def test_apply_without_a_mark_is_refused(self):
        self.assertEqual(self.run_script("--apply"), 2)

    def test_missing_volume_is_refused(self):
        self.assertEqual(self.module.main(["--efiesp", str(Path(self.temporary.name) / "absent"), "--show"]), 2)

    def test_the_backup_is_not_overwritten_on_a_second_install(self):
        self.assertEqual(self.run_script("--control-mark", str(self.mark), "--apply"), 0)
        first = hashlib.sha256((self.volume / "EFI" / "BOOT" / "BOOTAA64.EFI.before-control-mark").read_bytes()).hexdigest()
        self.assertEqual(self.run_script("--control-mark", str(self.mark), "--apply"), 0)
        second = hashlib.sha256((self.volume / "EFI" / "BOOT" / "BOOTAA64.EFI.before-control-mark").read_bytes()).hexdigest()
        self.assertEqual(first, second, "the backup must stay the original loader")


if __name__ == "__main__":
    unittest.main()
