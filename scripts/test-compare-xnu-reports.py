#!/usr/bin/env python3
"""Tests for scripts/compare-xnu-reports.py."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "compare-xnu-reports.py"


def report(milestones, **fields):
    document = {"schema": "lumia950-xnu-entry-emulation-v1", "emulator_only": True,
                "handset_boot_observed": False, "milestones": list(milestones)}
    document.update(fields)
    return document


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)

    def write(self, name, document):
        path = self.root / name
        path.write_text(json.dumps(document))
        return path

    def run_compare(self, before, after, *extra):
        return subprocess.run([sys.executable, str(SCRIPT), str(before), str(after), *extra],
                              capture_output=True, text=True)

    def test_two_identical_reports_say_so(self):
        document = report(["arm_vm_init_entry", "iokit_return"], stop_symbols=[])
        result = self.run_compare(self.write("a.json", document), self.write("b.json", document))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("identical", result.stdout)

    def test_a_new_milestone_is_reported_as_gained(self):
        before = self.write("a.json", report(["arm_vm_init_entry"]))
        after = self.write("b.json", report(["arm_vm_init_entry", "bsd_init_entry"],
                                            stop_symbols=["_bsd_init"]))
        result = self.run_compare(before, after)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("+ bsd_init_entry", result.stdout)

    def test_a_lost_milestone_is_a_regression(self):
        before = self.write("a.json", report(["iokit_return", "bsd_init_entry"]))
        after = self.write("b.json", report(["iokit_return"], panic_format="something failed"))
        result = self.run_compare(before, after)
        self.assertEqual(result.returncode, 3)
        self.assertIn("- bsd_init_entry", result.stdout)
        self.assertIn("regressed", result.stderr)

    def test_a_changed_panic_format_is_shown(self):
        before = self.write("a.json", report([], panic_format="first panic"))
        after = self.write("b.json", report([], stop_symbols=["_bsd_init"]))
        result = self.run_compare(before, after)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("panic_format", result.stdout)

    def test_required_milestones_are_enforced(self):
        before = self.write("a.json", report(["iokit_return"]))
        after = self.write("b.json", report(["iokit_return"]))
        result = self.run_compare(before, after, "--require-milestones", "iokit_return,bsd_init_entry")
        self.assertEqual(result.returncode, 3)
        self.assertIn("bsd_init_entry", result.stderr)

    def test_a_missing_report_is_refused(self):
        result = self.run_compare(self.root / "nope.json", self.write("b.json", report([])))
        self.assertEqual(result.returncode, 1)
        self.assertIn("is missing", result.stderr)

    def test_a_file_that_is_not_a_report_is_refused(self):
        other = self.root / "other.json"
        other.write_text(json.dumps({"hello": "world"}))
        result = self.run_compare(other, self.write("b.json", report([])))
        self.assertEqual(result.returncode, 1)
        self.assertIn("not an XNU emulation report", result.stderr)


if __name__ == "__main__":
    unittest.main()
