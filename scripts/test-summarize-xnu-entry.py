#!/usr/bin/env python3
"""Tests for scripts/summarize-xnu-entry.py against the two shapes of archived report."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STOPPED = {
    "past_bsd_outcome": "stopped",
    "fault_elr_symbol": "_skmem_sysctl_init+0x18",
    "fault_far": "0xfffffff0c6a15000",
    "milestones": ["arm_vm_init_entry", "iokit_entry", "bsd_init_entry"],
    "watched": {"_vfs_mountroot": False},
}

PANICKED = {
    "past_bsd_outcome": "panicked",
    "fault_elr_symbol": None,
    "fault_far": "0x0",
    "milestones": ["bsd_init_entry"],
    "watched": {"_vfs_mountroot": False},
}


def load():
    spec = importlib.util.spec_from_file_location(
        "summarize_xnu_entry", ROOT / "scripts" / "summarize-xnu-entry.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SummarizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load()

    def test_stopped_report_names_the_faulting_symbol(self):
        summary = self.module.summarize(STOPPED)
        self.assertEqual(summary["past_bsd_outcome"], "stopped")
        self.assertEqual(summary["fault_elr_symbol"], "_skmem_sysctl_init+0x18")
        self.assertEqual(summary["last_milestone"], "bsd_init_entry")
        self.assertFalse(summary["vfs_mountroot"])

    def test_panicked_report_still_summarises(self):
        summary = self.module.summarize(PANICKED)
        self.assertEqual(summary["past_bsd_outcome"], "panicked")
        self.assertIsNone(summary["fault_elr_symbol"])
        self.assertEqual(summary["milestones"], 1)

    def test_report_without_flag_uses_the_sibling_dmesg(self):
        """Older reports predate the flag; the dmesg beside them carries the same evidence."""
        import json as _json
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "report.json").write_text(_json.dumps(STOPPED), encoding="utf-8")
            (root / "dmesg.txt").write_text(
                "[   38.688331]: Waiting on <dict ID=\"0\"><key>IOProviderClass</key>\n"
                "[   98.839808]: Still waiting for root device\n", encoding="utf-8")
            code = self.module.main([str(root / "report.json")])
        self.assertEqual(code, 0)

    def test_summarize_reports_the_wait_flag_when_present(self):
        report = dict(STOPPED)
        report["root_device_wait_observed"] = True
        summary = self.module.summarize(report)
        self.assertTrue(summary["root_device_wait"])

    def test_missing_watched_entries_are_listed_not_invented(self):
        summary = self.module.summarize({"watched": {"_vfs_mountroot": False, "irq_init": True}})
        self.assertEqual(summary["watched_reached"], ["irq_init"])
        self.assertEqual(summary["watched_missing"], ["_vfs_mountroot"])

    def test_empty_report_does_not_raise(self):
        summary = self.module.summarize({})
        self.assertIsNone(summary["past_bsd_outcome"])
        self.assertEqual(summary["milestones"], 0)


if __name__ == "__main__":
    unittest.main()
