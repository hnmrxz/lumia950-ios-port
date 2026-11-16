#!/usr/bin/env python3
"""Tests for scripts/check-checkpoints.py.

Two things have to hold: the contract itself is well formed, and a log that skips a checkpoint
cannot pass by reaching a later one.

    python3 scripts/test-checkpoints.py
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check-checkpoints.py")
ROOT = SCRIPT.parent.parent
CONTRACT = ROOT / "docs/native-checkpoints.json"


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def contract(self, checkpoints=None, transport="ram-mailbox") -> Path:
        path = self.root / "contract.json"
        path.write_text(json.dumps({"schema": "lumia950-xnu-checkpoint-v1",
                                    "transport": transport,
                                    "checkpoints": checkpoints if checkpoints is not None else [
                                        {"id": "a", "marker": "xnu:a", "proves": "a happened"},
                                        {"id": "b", "marker": "xnu:b", "proves": "b happened"},
                                    ]}))
        return path

    def log(self, text: str) -> Path:
        path = self.root / "bringup.log"
        path.write_text(text)
        return path

    def run_check(self, *arguments, expect=0):
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, arguments)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, expect,
                         f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def test_the_committed_contract_passes(self):
        result = self.run_check(CONTRACT)
        self.assertIn("checkpoint contract ok", result.stdout)
        self.assertIn("undecided", result.stderr)

    def test_a_duplicate_marker_is_refused(self):
        result = self.run_check(self.contract([
            {"id": "a", "marker": "xnu:a", "proves": "a"},
            {"id": "b", "marker": "xnu:a", "proves": "b"}]), expect=1)
        self.assertIn("used by two checkpoints", result.stderr)

    def test_a_checkpoint_without_a_marker_is_refused(self):
        result = self.run_check(self.contract([{"id": "a", "proves": "a"}]), expect=1)
        self.assertIn("has no marker", result.stderr)

    def test_a_checkpoint_must_say_what_it_proves(self):
        result = self.run_check(self.contract([{"id": "a", "marker": "xnu:a"}]), expect=1)
        self.assertIn("does not say what it proves", result.stderr)

    def test_an_unknown_transport_is_refused(self):
        result = self.run_check(self.contract(transport="serial-over-usb"), expect=1)
        self.assertIn("transport is", result.stderr)

    def test_a_complete_log_passes(self):
        log = self.log("[1.0] xnu:handoff\r\n[1.2] xnu:a\r\n[1.4] xnu:b\r\n")
        result = self.run_check(self.contract(), "--log", log)
        self.assertIn("bring-up log ok", result.stdout)

    def test_a_log_that_stops_early_is_refused_by_default(self):
        log = self.log("[1.0] xnu:a\r\n")
        result = self.run_check(self.contract(), "--log", log, expect=1)
        self.assertIn("does not reach b", result.stderr)

    def test_a_log_that_stops_early_passes_with_a_require_through_that_it_reaches(self):
        log = self.log("[1.0] xnu:a\r\n")
        result = self.run_check(self.contract(), "--log", log, "--require-through", "a")
        self.assertIn("reaches 1 checkpoint(s)", result.stdout)

    def test_an_out_of_order_log_is_refused(self):
        # b before a means this is not the sequence the fixture asserts.
        log = self.log("[1.0] xnu:b\r\n[1.2] xnu:a\r\n")
        result = self.run_check(self.contract(), "--log", log, expect=1)
        self.assertIn("does not reach", result.stderr)

    def test_a_log_with_none_of_the_markers_is_refused(self):
        log = self.log("nothing here\r\n")
        result = self.run_check(self.contract(), "--log", log, expect=1)
        self.assertIn("reached nothing", result.stderr)

    def test_an_unknown_require_through_is_refused(self):
        result = self.run_check(self.contract(), "--log", self.log("xnu:a\n"),
                                "--require-through", "z", expect=1)
        self.assertIn("is not one of", result.stderr)

    def test_a_missing_log_is_refused(self):
        result = self.run_check(self.contract(), "--log", self.root / "absent.log", expect=1)
        self.assertIn("is missing", result.stderr)


if __name__ == "__main__":
    unittest.main()
