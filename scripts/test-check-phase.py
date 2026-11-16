#!/usr/bin/env python3
"""Tests for scripts/check-phase.py.

The rule worth testing is the one that makes an exit criterion mean something: "met" has to name
the file or the dated command that proves it. Everything else is schema hygiene.

    python3 scripts/test-check-phase.py
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check-phase.py")
ROOT = SCRIPT.parent.parent


def criterion(identity="P0.1", **overrides):
    base = {"id": identity, "requirement": "something that can be judged",
            "evidence": "artifact", "status": "open"}
    base.update(overrides)
    return base


def phase(phase_name="P0", criteria=None, **overrides):
    document = {"schema": "lumia950-phase-exit-v1", "phase": phase_name, "status": "open",
                "criteria": criteria if criteria is not None else [criterion(f"{phase_name}.1")]}
    document.update(overrides)
    return document


class CheckPhaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, document, name="p0-exit.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(document))
        return path

    def check(self, *paths, expect=0):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root),
                                 *[str(path) for path in paths]],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, expect,
                         f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def test_an_honest_all_open_phase_passes(self):
        result = self.check(self.write(phase()))
        self.assertIn("phase exits ok", result.stdout)

    def test_the_committed_phase_files_pass(self):
        result = subprocess.run([sys.executable, str(SCRIPT), str(ROOT / "docs/phases"),
                                 "--root", str(ROOT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("P5 blocked", result.stdout)

    def test_the_phase_must_match_the_file_name(self):
        result = self.check(self.write(phase("P1")), expect=1)
        self.assertIn("the file name says P0", result.stderr)

    def test_a_wrong_schema_is_refused(self):
        result = self.check(self.write(phase(schema="something-else")), expect=1)
        self.assertIn("schema is", result.stderr)

    def test_a_duplicate_criterion_is_refused(self):
        result = self.check(self.write(phase(criteria=[criterion(), criterion()])), expect=1)
        self.assertIn("appears twice", result.stderr)

    def test_a_criterion_from_another_phase_is_refused(self):
        result = self.check(self.write(phase(criteria=[criterion("P1.1")])), expect=1)
        self.assertIn("has to start with P0.", result.stderr)

    def test_met_without_any_evidence_is_refused(self):
        # The finding: a phase was finished because it felt finished.
        result = self.check(self.write(phase(criteria=[criterion(status="met")])), expect=1)
        self.assertIn("names no path and no command", result.stderr)

    def test_met_through_a_file_that_does_not_exist_is_refused(self):
        result = self.check(self.write(phase(criteria=[
            criterion(status="met", path="docs/nothing-here.json")])), expect=1)
        self.assertIn("which does not exist", result.stderr)

    def test_met_through_a_file_that_exists_is_accepted(self):
        evidence = self.root / "proof.json"
        evidence.write_text("{}")
        result = self.check(self.write(phase(criteria=[
            criterion(status="met", path="proof.json")])))
        self.assertIn("met 1", result.stdout)

    def test_met_through_a_command_needs_the_date_it_ran(self):
        result = self.check(self.write(phase(criteria=[
            criterion(status="met", command="python3 scripts/check-phase.py")])), expect=1)
        self.assertIn("no verified_at date", result.stderr)

    def test_met_through_a_dated_command_is_accepted(self):
        result = self.check(self.write(phase(criteria=[
            criterion(status="met", command="python3 -m py_compile x.py",
                      verified_at="2026-11-16")])))
        self.assertIn("met 1", result.stdout)

    def test_verified_by_must_be_a_real_script(self):
        result = self.check(self.write(phase(criteria=[
            criterion(verified_by="scripts/not-a-checker.py")])), expect=1)
        self.assertIn("which does not exist", result.stderr)

    def test_a_phase_cannot_be_met_with_open_criteria(self):
        result = self.check(self.write(phase(status="met")), expect=1)
        self.assertIn("these criteria are not", result.stderr)

    def test_a_later_phase_cannot_be_met_before_an_earlier_one(self):
        first = self.root / "p0-exit.json"
        first.write_text(json.dumps(phase("P0", [criterion("P0.1")])))
        evidence = self.root / "proof.json"
        evidence.write_text("{}")
        second = self.root / "p1-exit.json"
        second.write_text(json.dumps(phase("P1", [criterion("P1.1", status="met",
                                                            path="proof.json")],
                                           status="met")))
        result = self.check(first, second, expect=1)
        self.assertIn("P1 is met but P0 is open", result.stderr)

    def test_blocked_needs_a_reason(self):
        result = self.check(self.write(phase(status="blocked")), expect=1)
        self.assertIn("blocked_by says nothing", result.stderr)

    def test_blocked_with_a_reason_passes(self):
        result = self.check(self.write(phase(status="blocked", blocked_by="no framework ref")))
        self.assertIn("P0 blocked", result.stdout)


if __name__ == "__main__":
    unittest.main()
