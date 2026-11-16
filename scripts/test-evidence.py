#!/usr/bin/env python3
"""Tests for scripts/check-evidence.py.

The two cases worth writing down: a subject cannot claim a level its own evidence list does not
reach, and the two levels easiest to overclaim (XNU-entry-tested, userland-booted) need the phase
that produces them to be met first.

    python3 scripts/test-evidence.py
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check-evidence.py")
ROOT = SCRIPT.parent.parent
LABELS = ["source-reviewed", "host-tested", "QEMU-tested", "ABI-compiled", "kernel-linked",
          "prelink-checked", "EFI-tested", "XNU-entry-tested", "hardware-tested",
          "userland-booted"]


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "docs").mkdir()
        self.proof = self.root / "proof.json"
        self.proof.write_text("{}")

    def table(self, subjects, labels=None) -> Path:
        path = self.root / "docs/evidence.json"
        path.write_text(json.dumps({"schema": "lumia950-evidence-v1",
                                    "labels": labels or LABELS, "subjects": subjects}))
        return path

    def phases(self, statuses) -> Path:
        directory = self.root / "phases"
        directory.mkdir(exist_ok=True)
        for phase, status in statuses.items():
            (directory / f"{phase.lower()}-exit.json").write_text(json.dumps(
                {"schema": "lumia950-phase-exit-v1", "phase": phase, "status": status,
                 "criteria": []}))
        return directory

    def run_check(self, *arguments, expect=0):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root),
                                 *map(str, arguments)], capture_output=True, text=True)
        self.assertEqual(result.returncode, expect,
                         f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def subject(self, label="source-reviewed", evidence=None, **overrides):
        base = {"id": "thing", "what": "a thing", "label": label,
                "evidence": evidence if evidence is not None else [
                    {"label": "source-reviewed", "path": "proof.json"}]}
        base.update(overrides)
        return base

    def test_the_committed_table_passes(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(ROOT),
                                 "--phases", str(ROOT / "docs/phases")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("evidence ok", result.stdout)

    def test_a_claim_its_own_evidence_does_not_reach_is_refused(self):
        path = self.table([self.subject(label="EFI-tested")])
        result = self.run_check(path, expect=1)
        self.assertIn("lists no evidence at that level", result.stderr)

    def test_citing_stronger_evidence_than_the_claim_is_refused(self):
        path = self.table([self.subject(label="source-reviewed", evidence=[
            {"label": "hardware-tested", "path": "proof.json"}])])
        result = self.run_check(path, expect=1)
        self.assertIn("may not be stronger than the claim", result.stderr)

    def test_an_evidence_file_that_does_not_exist_is_refused(self):
        path = self.table([self.subject(evidence=[{"label": "source-reviewed",
                                                   "path": "nowhere.json"}])])
        result = self.run_check(path, expect=1)
        self.assertIn("which does not exist", result.stderr)

    def test_a_command_without_a_date_is_refused(self):
        path = self.table([self.subject(label="host-tested", evidence=[
            {"label": "host-tested", "command": "bash scripts/test-storage.sh"}])])
        result = self.run_check(path, expect=1)
        self.assertIn("no verified_at date", result.stderr)

    def test_a_dated_command_passes(self):
        path = self.table([self.subject(label="host-tested", evidence=[
            {"label": "host-tested", "command": "bash scripts/test-storage.sh",
             "verified_at": "2026-11-16"}])])
        self.run_check(path)

    def test_an_entry_with_both_path_and_command_is_refused(self):
        path = self.table([self.subject(evidence=[
            {"label": "source-reviewed", "path": "proof.json", "command": "true",
             "verified_at": "2026-11-16"}])])
        result = self.run_check(path, expect=1)
        self.assertIn("exactly one of path or command", result.stderr)

    def test_xnu_entry_tested_needs_p1_met(self):
        # The claim a hopeful person makes first.
        path = self.table([self.subject(label="XNU-entry-tested", evidence=[
            {"label": "source-reviewed", "path": "proof.json"},
            {"label": "XNU-entry-tested", "path": "proof.json"}])])
        result = self.run_check(path, "--phases", self.phases({"P1": "open"}), expect=1)
        self.assertIn("claims XNU-entry-tested but phase P1 is open", result.stderr)
        # ... and the same file passes once the phase is met.
        self.run_check(path, "--phases", self.phases({"P1": "met"}))

    def test_userland_booted_needs_p4_met(self):
        path = self.table([self.subject(label="userland-booted", evidence=[
            {"label": "source-reviewed", "path": "proof.json"},
            {"label": "userland-booted", "path": "proof.json"}])])
        result = self.run_check(path, "--phases", self.phases({"P4": "blocked"}), expect=1)
        self.assertIn("but phase P4 is blocked", result.stderr)

    def test_a_duplicate_subject_is_refused(self):
        path = self.table([self.subject(), self.subject()])
        result = self.run_check(path, expect=1)
        self.assertIn("appears twice", result.stderr)

    def test_an_invented_label_is_refused(self):
        labels = LABELS + ["definitely-works"]
        path = self.table([self.subject()], labels=labels)
        result = self.run_check(path, expect=1)
        self.assertIn("not the ladder from AGENTS.md", result.stderr)

    def test_a_subject_without_evidence_is_refused(self):
        path = self.table([self.subject(evidence=[])])
        result = self.run_check(path, expect=1)
        self.assertIn("has no evidence", result.stderr)


if __name__ == "__main__":
    unittest.main()
