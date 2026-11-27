#!/usr/bin/env python3
"""No script may write a protected boot-chain object without saying so.

The handset's chain works today; the protection rule is that replacing any of its six object classes requires an explicit
acknowledgement in the calling script. This test reads the scripts that can write to the phone and asserts the gate is called on
every write path, and that the guard's own rule keeps its two halves: creation on a blank volume is allowed, replacement is not.

It is a source-level test on purpose: the alternative is trusting each installer to remember.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def load_guard():
    spec = importlib.util.spec_from_file_location("boot_chain_guard", SCRIPTS / "boot-chain-guard.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProtectionIsWiredTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = load_guard()

    def test_every_installer_asks_the_guard(self):
        installer = (SCRIPTS / "phone-install.py").read_text(encoding="utf-8")
        self.assertIn("refuse_protected", installer, "phone-install.py must consult the guard")
        self.assertIn("--replace-protected", installer, "and offer the acknowledgement flag")
        self.assertIn("replace_protected=args.replace_protected", installer,
                      "every install() call has to carry the acknowledgement")

    def test_the_handoff_installer_keeps_its_own_refusal(self):
        installer = (SCRIPTS / "install-native-bringup.py").read_text(encoding="utf-8")
        self.assertIn("existing boot state changed", installer,
                      "install-native-bringup.py must keep refusing when a CRITICAL hash differs")
        self.assertIn("EFI/UniXNU already exists", installer,
                      "and must keep refusing to overwrite an earlier installation")

    def test_the_loader_swap_keeps_a_backup(self):
        swap = (SCRIPTS / "swap-loader.py").read_text(encoding="utf-8")
        self.assertIn("before-control-mark", swap, "swap-loader.py keeps the file it replaced")
        self.assertIn("--restore", swap, "and offers the restore")

    def test_the_guard_requires_a_backup_for_a_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            volume = Path(temporary)
            (volume / "EFI" / "BOOT").mkdir(parents=True)
            (volume / "EFI" / "BOOT" / "BOOTAA64.EFI").write_bytes(b"loader")
            self.assertEqual(self.guard.main(["check", "--root", str(volume),
                                              "--path", "EFI/BOOT/BOOTAA64.EFI"]), 1)
            backup = volume / "backup.efi"
            backup.write_bytes(b"loader")
            self.assertEqual(self.guard.main(["check", "--root", str(volume),
                                              "--path", "EFI/BOOT/BOOTAA64.EFI",
                                              "--replace-protected", "--backup", str(backup)]), 0)

    def test_creating_a_missing_object_is_not_a_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            volume = Path(temporary)
            (volume / "EFI").mkdir()
            self.assertEqual(self.guard.main(["check", "--root", str(volume), "--path", "UEFI.elf"]), 0)

    def test_the_updater_only_touches_its_own_files(self):
        updater = (SCRIPTS / "update-native-bringup.py").read_text(encoding="utf-8")
        self.assertIn("UPDATABLE", updater, "update-native-bringup.py declares what it may write")
        self.assertIn("EFI/UniXNU/Payloads/kernel.macho", updater)
        # the loader itself, the store and the boot managers are not in the updatable set
        for protected in ("BOOTAA64.EFI", "BootShim.efi", "bootarm.efi", "UEFI.elf", "BCD"):
            self.assertNotIn(f'"{protected}"', updater,
                             f"{protected} must not be something the updater writes")

    def test_the_snapshot_restore_takes_a_manifest_and_a_name(self):
        snapshot = (SCRIPTS / "phone-snapshot.py").read_text(encoding="utf-8")
        self.assertIn("manifest", snapshot, "a restore must be driven by a manifest")
        self.assertIn("--name", snapshot, "and by an explicit snapshot name, never by 'the newest'")


if __name__ == "__main__":
    unittest.main()
