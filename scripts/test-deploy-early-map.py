#!/usr/bin/env python3
"""Tests for scripts/deploy-early-map.py: dry run writes nothing, the guards refuse, and the token is added once."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("deploy_early_map", ROOT / "scripts" / "deploy-early-map.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CONFIG = """[[entry]]
name = "xnu"
args = "-v lumia-bars2"
"""


class DeployEarlyMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.efiesp = base / "EFIESP"
        self.payloads = self.efiesp / "EFI" / "UniXNU" / "Payloads"
        self.payloads.mkdir(parents=True)
        self.config = self.efiesp / "EFI" / "UniXNU" / "unixnu.toml"
        self.config.write_text(CONFIG, encoding="utf-8")
        self.current = self.payloads / "kernel.macho"
        self.current.write_bytes(b"the kernel that is deployed")
        self.new = base / "artifact" / "kernel.macho"
        self.new.parent.mkdir()
        self.new.write_bytes(b"the early-map kernel")
        self.backup = base / "backups" / "kernel.before"
        self.backup.parent.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_a_dry_run_writes_nothing(self):
        before = (self.current.read_bytes(), self.config.read_text(encoding="utf-8"))
        code = self.module.main(["--efiesp", str(self.efiesp), "--kernel", str(self.new)])
        self.assertEqual(code, 0)
        self.assertEqual((self.current.read_bytes(), self.config.read_text(encoding="utf-8")), before)

    def test_apply_requires_a_backup(self):
        code = self.module.main(["--efiesp", str(self.efiesp), "--kernel", str(self.new), "--apply"])
        self.assertEqual(code, 1)
        self.assertEqual(self.current.read_bytes(), b"the kernel that is deployed")

    def test_apply_refuses_without_the_boot_chain_acknowledgement(self):
        code = self.module.main(["--efiesp", str(self.efiesp), "--kernel", str(self.new), "--apply",
                                 "--backup", str(self.backup)])
        self.assertEqual(code, 1, "an existing kernel is a protected object; the gate has to refuse")
        self.assertEqual(self.current.read_bytes(), b"the kernel that is deployed")

    def test_apply_with_a_backup_and_the_gate_writes_both(self):
        code = self.module.main(["--efiesp", str(self.efiesp), "--kernel", str(self.new), "--apply",
                                 "--backup", str(self.backup),
                                 "--boot-chain-gate", str(self.new)])
        self.assertEqual(code, 0)
        self.assertEqual(self.current.read_bytes(), b"the early-map kernel")
        self.assertIn("lumia-early-map", self.config.read_text(encoding="utf-8"))
        self.assertEqual(self.backup.read_bytes(), b"the kernel that is deployed")

    def test_the_token_is_added_once(self):
        first = self.module.add_token(CONFIG, "lumia-early-map")
        second = self.module.add_token(first, "lumia-early-map")
        self.assertEqual(first, second)
        self.assertEqual(first.count("lumia-early-map"), 1)

    def test_a_wrong_expected_hash_is_refused(self):
        code = self.module.main(["--efiesp", str(self.efiesp), "--kernel", str(self.new),
                                 "--expect-sha256", "0" * 64])
        self.assertEqual(code, 1)

    def test_a_phone_without_the_chain_is_refused(self):
        empty = Path(self.temporary.name) / "EMPTY"
        empty.mkdir()
        code = self.module.main(["--efiesp", str(empty), "--kernel", str(self.new)])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
