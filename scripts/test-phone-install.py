#!/usr/bin/env python3
"""Tests for scripts/phone-install.py -- the shim must land where the reference image keeps it."""

from __future__ import annotations

import importlib.util
import sys
import struct
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



def make_pe(path, subsystem, machine=0xAA64):
    """A minimal PE header stub with a chosen machine and subsystem."""
    data = bytearray(0x200)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<H", data, 0x84, machine)
    data[0xDC] = subsystem
    path.write_bytes(bytes(data))


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
        make_pe(self.bootshim, subsystem=0x0A)
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

    def test_dry_run_writes_nothing(self):
        argv = ["--efiesp", str(self.efiesp), "--mainos", str(self.mainos),
                "--bootshim", str(self.bootshim), "--uefi-elf", str(self.uefi),
                "--payload", str(self.payload), "--stage", str(self.payload),
                "--dry-run"]
        self.assertEqual(self.module.main(argv), 0)
        self.assertFalse((self.mainos / "Windows").exists())
        self.assertFalse((self.efiesp / "EFI").exists())

    def test_apply_and_dry_run_together_are_refused(self):
        with self.assertRaises(SystemExit):
            self.run_installer("--dry-run")

    def test_default_layout_puts_the_shim_on_mainos(self):
        self.assertEqual(self.run_installer(), 0)
        self.assertTrue((self.mainos / "Windows" / "System32" / "Boot" / "bootshim.efi").is_file())
        self.assertFalse((self.efiesp / "EFI" / "boot" / "BootShim.efi").exists())
        self.assertTrue((self.efiesp / "UEFI.elf").is_file())

    def test_efiesp_layout_is_still_available(self):
        self.assertEqual(self.run_installer("--layout", "efiesp"), 0)
        self.assertTrue((self.efiesp / "EFI" / "boot" / "BootShim.efi").is_file())
        self.assertFalse((self.mainos / "Windows" / "System32" / "Boot" / "bootshim.efi").exists())


    def test_default_shim_resolution_prefers_a_real_application(self):
        """With no --bootshim the resolver must not silently pick the ARM32 driver in staging."""
        resolved = self.module.resolve_bootshim(None)
        self.assertTrue(str(resolved).endswith(("bootaa64.efi", "BootShim.efi")))
        # If the SJM application is present on this machine, it must be what gets chosen.
        if self.module.SJM_SHIM.is_file():
            self.assertEqual(resolved, self.module.SJM_SHIM)

    def test_explicit_shim_is_respected(self):
        self.assertEqual(self.module.resolve_bootshim(self.bootshim), self.bootshim)

    def test_a_driver_on_the_boot_path_is_refused(self):
        """A boot service driver (0x0B) at the shim path is the failure this check exists for."""
        make_pe(self.bootshim, subsystem=0x0B)
        self.assertEqual(self.run_installer(), 1)
        self.assertFalse((self.mainos / "Windows" / "System32" / "Boot" / "bootshim.efi").exists())

    def test_an_application_on_the_boot_path_is_accepted(self):
        make_pe(self.bootshim, subsystem=0x0A)
        self.assertEqual(self.run_installer(), 0)
        self.assertTrue((self.mainos / "Windows" / "System32" / "Boot" / "bootshim.efi").is_file())



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
