#!/usr/bin/env python3
"""Tests for scripts/deploy-early-map.py.

The chain has two volumes -- the configuration on EFIESP, the kernel and its adt on MainOS -- so these tests build both, and they check the
parts that made an earlier version unsafe: the kernel is written where the loader reads it, the backup is a copy of the object being replaced
and the gate is asked to verify that, and the configuration gets its own backup and its own decision.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CONFIG = """[[entry]]
name = "xnu"
args = "-v lumia-bars2"
"""


def load():
    spec = importlib.util.spec_from_file_location("deploy_early_map", ROOT / "scripts" / "deploy-early-map.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DeployEarlyMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.efiesp = base / "EFIESP"
        self.mainos = base / "MainOS"
        self.config = self.efiesp / "EFI" / "UniXNU" / "unixnu.toml"
        self.kernel = self.mainos / "EFI" / "UniXNU" / "Payloads" / "kernel.macho"
        self.adt = self.mainos / "EFI" / "UniXNU" / "Payloads" / "kernel.macho.adt"
        for path in (self.config, self.kernel, self.adt):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text(CONFIG, encoding="utf-8")
        self.kernel.write_bytes(b"the kernel that is deployed")
        self.adt.write_bytes(b"the adt that is deployed")
        self.new = base / "artifact" / "kernel.macho"
        self.new.parent.mkdir()
        self.new.write_bytes(b"the early-map kernel")
        self.new_adt = base / "artifact" / "kernel.macho.adt"
        self.new_adt.write_bytes(b"the early-map adt")
        self.backups = base / "backups"

    def tearDown(self):
        self.temporary.cleanup()

    def run_deploy(self, *extra: str):
        return self.module.main(["--efiesp", str(self.efiesp), "--mainos", str(self.mainos),
                                 "--kernel", str(self.new), "--adt", str(self.new_adt), *extra])

    def test_a_dry_run_writes_nothing_anywhere(self):
        before = {path: path.read_bytes() for path in (self.config, self.kernel, self.adt)}
        self.assertEqual(self.run_deploy(), 0)
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertFalse(self.backups.exists())

    def test_apply_needs_a_backup_directory(self):
        code = self.run_deploy("--apply")
        self.assertEqual(code, 1)
        self.assertEqual(self.kernel.read_bytes(), b"the kernel that is deployed")

    def test_the_kernel_is_written_on_the_mainos_volume(self):
        code = self.run_deploy("--apply", "--backup-dir", str(self.backups))
        self.assertEqual(code, 0)
        self.assertEqual(digest(self.kernel), digest(self.new), "MainOS must carry the new kernel")
        self.assertFalse((self.efiesp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho").exists(),
                         "nothing may be written into the efiesp payload path")
        self.assertEqual(digest(self.adt), digest(self.new_adt))

    def test_the_backup_is_the_object_that_was_replaced(self):
        previous = self.kernel.read_bytes()
        self.assertEqual(self.run_deploy("--apply", "--backup-dir", str(self.backups)), 0)
        kept = self.backups / "kernel.macho.before-m1"
        self.assertTrue(kept.is_file())
        self.assertEqual(kept.read_bytes(), previous, "the backup has to be the old kernel, byte for byte")
        kept_config = self.backups / "unixnu.toml.before-m1"
        self.assertEqual(kept_config.read_text(encoding="utf-8"), CONFIG)

    def test_the_gate_is_asked_about_the_object_with_a_matching_backup(self):
        """A backup that is a copy of something else must not authorise the replacement."""
        gate = self.module.gate()
        other = Path(self.kernel).parent / "something.else"
        other.write_bytes(b"not the kernel")
        decision = gate.authorise(self.kernel, replace=True, backup=other, backup_matches=self.kernel,
                                  reason="test", verify="test")
        self.assertFalse(decision.allowed)
        self.assertIn("not a copy of it", decision.message)

    def test_the_token_is_added_once_and_the_config_is_backed_up(self):
        self.assertEqual(self.run_deploy("--apply", "--backup-dir", str(self.backups)), 0)
        text = self.config.read_text(encoding="utf-8")
        self.assertEqual(text.count("lumia-early-map"), 1)
        first = text
        self.assertEqual(self.run_deploy("--apply", "--backup-dir", str(self.backups)), 0)
        self.assertEqual(self.config.read_text(encoding="utf-8").count("lumia-early-map"), 1,
                         "a second run must not add the token again")
        restored = self.config.read_text(encoding="utf-8").replace(" lumia-early-map", "").strip()
        self.assertEqual(restored, CONFIG.strip(), "removing the token restores the previous configuration")
        self.assertTrue(first.endswith("\n"))

    def test_a_wrong_expected_hash_is_refused(self):
        code = self.run_deploy("--apply", "--backup-dir", str(self.backups), "--expect-sha256", "0" * 64)
        self.assertEqual(code, 1)
        self.assertEqual(self.kernel.read_bytes(), b"the kernel that is deployed")

    def test_an_efiesp_without_the_configuration_is_refused(self):
        self.config.unlink()
        self.assertEqual(self.run_deploy("--apply", "--backup-dir", str(self.backups)), 2)

    def test_a_missing_mainos_volume_is_refused(self):
        for path in (self.kernel, self.adt):
            path.unlink()
        import shutil
        shutil.rmtree(self.mainos)
        self.assertEqual(self.run_deploy("--apply", "--backup-dir", str(self.backups)), 2)

    def test_the_phone_adt_must_be_replaced_with_the_kernel(self):
        """Leaving the old adt beside a new kernel is a silent mismatch, so the run stops instead."""
        code = self.module.main(["--efiesp", str(self.efiesp), "--mainos", str(self.mainos),
                                 "--kernel", str(self.new), "--apply", "--backup-dir", str(self.backups)])
        self.assertEqual(code, 2)
        self.assertEqual(self.kernel.read_bytes(), b"the kernel that is deployed")


if __name__ == "__main__":
    unittest.main()
