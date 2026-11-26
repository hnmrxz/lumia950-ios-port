#!/usr/bin/env python3
"""Tests for scripts/deploy-kernel.py: the manifest is the only record of which kernel the phone is running."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("deploy_kernel", ROOT / "scripts" / "deploy-kernel.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DeployKernelTests(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.mainos = base / "MainOS"
        self.mainos.mkdir()
        self.staged = base / "staged" / "EFI" / "UniXNU" / "Payloads"
        self.staged.mkdir(parents=True)
        self.kernel_bytes = b"\xcf\xfa\xed\xfe" + b"kernel-A" * 64
        (self.staged / "kernel.macho").write_bytes(self.kernel_bytes)
        (self.staged / "kernel.macho.adt").write_bytes(b"adt-A")

    def tearDown(self):
        self.temporary.cleanup()

    def run_deploy(self, staged=None, apply=True):
        arguments = ["--efiesp", "R:", "--mainos", str(self.mainos),
                     "--kernel", str(staged or self.staged)]
        arguments.append("--apply" if apply else "--dry-run")
        return self.module.main(arguments)

    def payload(self):
        return self.mainos / "EFI" / "UniXNU" / "Payloads"

    def test_dry_run_writes_nothing(self):
        self.assertEqual(self.run_deploy(apply=False), 0)
        self.assertFalse(self.payload().exists())

    def test_apply_writes_the_kernel_and_a_manifest(self):
        self.assertEqual(self.run_deploy(), 0)
        written = self.payload() / "kernel.macho"
        self.assertEqual(written.read_bytes(), self.kernel_bytes)
        manifest = (self.payload() / "DEPLOYED.txt").read_text(encoding="utf-8")
        self.assertIn(hashlib.sha256(self.kernel_bytes).hexdigest(), manifest)
        self.assertIn("previous   (none)", manifest)

    def test_a_second_deploy_keeps_the_previous_kernel(self):
        self.assertEqual(self.run_deploy(), 0)
        other = Path(self.temporary.name) / "other" / "EFI" / "UniXNU" / "Payloads"
        other.mkdir(parents=True)
        (other / "kernel.macho").write_bytes(b"kernel-B" * 32)
        (other / "kernel.macho.adt").write_bytes(b"adt-B")
        self.assertEqual(self.run_deploy(staged=other), 0)
        previous = self.payload() / "kernel.macho.prev"
        self.assertTrue(previous.is_file())
        self.assertEqual(previous.read_bytes(), self.kernel_bytes)
        manifest = (self.payload() / "DEPLOYED.txt").read_text(encoding="utf-8")
        self.assertIn("kernel.macho.prev", manifest)

    def test_deploying_the_same_kernel_does_not_copy_a_previous(self):
        self.assertEqual(self.run_deploy(), 0)
        self.assertEqual(self.run_deploy(), 0)
        self.assertFalse((self.payload() / "kernel.macho.prev").exists())

    def test_a_missing_kernel_is_refused(self):
        empty = Path(self.temporary.name) / "empty"
        empty.mkdir()
        self.assertEqual(self.run_deploy(staged=empty), 2)

    def test_apply_and_dry_run_together_are_refused(self):
        with self.assertRaises(SystemExit):
            self.module.main(["--efiesp", "R:", "--mainos", str(self.mainos),
                              "--kernel", str(self.staged), "--apply", "--dry-run"])


if __name__ == "__main__":
    unittest.main()
