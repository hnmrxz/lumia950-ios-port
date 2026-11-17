#!/usr/bin/env python3
"""Tests for scripts/run-tests.py: the suite cannot lose a test without saying so."""
import importlib.util
import pathlib
import subprocess
import sys
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent
RUNNER = SCRIPTS / "run-tests.py"


def load():
    spec = importlib.util.spec_from_file_location("run_tests", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunnerTests(unittest.TestCase):
    def test_every_test_file_is_classified(self):
        runner = load()
        discovered = set(runner.discover())
        classified = set(runner.SELF_CONTAINED) | set(runner.NEEDS_INPUT)
        self.assertEqual(discovered - classified, set(),
                         "a test file is in neither list, so CI would never run it")
        self.assertEqual(classified - discovered, set(),
                         "a classified test file no longer exists")

    def test_a_skipped_test_says_what_it_needs(self):
        runner = load()
        for name, reason in runner.NEEDS_INPUT.items():
            self.assertTrue(reason.strip(), name)

    def test_the_lists_do_not_overlap(self):
        runner = load()
        self.assertEqual(set(runner.SELF_CONTAINED) & set(runner.NEEDS_INPUT), set())

    def test_list_mode_classifies_without_running_anything(self):
        result = subprocess.run([sys.executable, str(RUNNER), "--list"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run    test-checkpoints.py", result.stdout)
        self.assertIn("skip   test-native-xnu-entry.py", result.stdout)

    def test_an_unclassified_file_is_refused(self):
        # A temporary extra test file makes the runner refuse rather than pass silently.
        # --check-classification exists so this test does not recurse into the runner.
        stray = SCRIPTS / "test-this-file-is-not-classified.py"
        stray.write_text("raise SystemExit(0)\n")
        try:
            result = subprocess.run([sys.executable, str(RUNNER), "--check-classification"],
                                    capture_output=True, text=True)
        finally:
            stray.unlink()
        self.assertEqual(result.returncode, 2)
        self.assertIn("never run", result.stderr)

    def test_a_classified_suite_passes_the_check(self):
        result = subprocess.run([sys.executable, str(RUNNER), "--check-classification"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
