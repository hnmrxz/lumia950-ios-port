#!/usr/bin/env python3
"""Tests for scripts/check-action-pins.py.

    python3 scripts/test-action-pins.py
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check-action-pins.py")
ROOT = SCRIPT.parent.parent
SHA = "11d5960a326750d5838078e36cf38b85af677262"


class ActionPinTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / ".github/workflows").mkdir(parents=True)

    def workflow(self, body: str, name="build.yml") -> Path:
        path = self.root / ".github/workflows" / name
        path.write_text(body)
        return path

    def run_check(self, expect=0):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, expect,
                         f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def test_the_repository_pins_every_action(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(ROOT)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("action pins ok", result.stdout)

    def test_a_tag_pin_is_refused(self):
        self.workflow("steps:\n  - uses: actions/checkout@v4\n")
        result = self.run_check(expect=1)
        self.assertIn("actions/checkout@v4 is not pinned", result.stderr)

    def test_a_commit_pin_passes(self):
        self.workflow(f"steps:\n  - uses: actions/checkout@{SHA}  # v4\n")
        self.run_check()

    def test_a_local_action_is_not_pinned(self):
        self.workflow("steps:\n  - uses: ./.github/actions/local\n")
        self.run_check()

    def test_a_docker_action_is_not_pinned(self):
        self.workflow("steps:\n  - uses: docker://alpine:3.20\n")
        self.run_check()

    def test_a_branch_is_refused(self):
        self.workflow("steps:\n  - uses: actions/checkout@main\n")
        result = self.run_check(expect=1)
        self.assertIn("@main is not pinned", result.stderr)

    def test_a_short_sha_is_refused(self):
        self.workflow("steps:\n  - uses: actions/checkout@11d5960\n")
        self.run_check(expect=1)

    def test_no_workflows_is_refused(self):
        (self.root / ".github/workflows").rmdir()
        result = self.run_check(expect=1)
        self.assertIn("no workflows under", result.stderr)


if __name__ == "__main__":
    unittest.main()
