#!/usr/bin/env python3
"""Tests for scripts/check-no-device-identifiers.py.

The case that matters is the one that already happened: an EFI volume UUID committed in an
evidence file, where the installer reads a UUID as an identity factor.

    python3 scripts/test-no-device-identifiers.py
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check-no-device-identifiers.py")
ROOT = SCRIPT.parent.parent
RAW = "455FB1CB-F473-3654-A26A-8E96BB80B44C"


class IdentifierTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "docs/hardware").mkdir(parents=True)

    def write(self, document, name="probe.json") -> Path:
        path = self.root / "docs/hardware" / name
        path.write_text(json.dumps(document))
        return path

    def run_check(self, expect=0):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, expect,
                         f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def test_the_repository_has_no_raw_identifier(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(ROOT)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no raw identifier", result.stdout)

    def test_a_raw_volume_uuid_is_refused(self):
        self.write({"disk": {"volume_uuid": RAW}})
        result = self.run_check(expect=1)
        self.assertIn("volume_uuid holds a raw device identifier", result.stderr)

    def test_a_redacted_value_is_accepted(self):
        self.write({"disk": {"volume_uuid": "sha256:49d22a0759873eb5",
                             "identifier_redaction": "withheld"}})
        self.run_check()

    def test_the_blocked_device_name_is_not_a_volume_uuid(self):
        # `device` is prose, not an identifier key.
        self.write({"device": "Microsoft Lumia 950"})
        self.run_check()

    def test_a_hardware_guid_is_not_a_device_identity(self):
        # The GPU SMMU profile carries a SoC GUID; flagging it would train people to ignore this.
        self.write({"smmu": {"guid": "9833c712-3292-4ffb-b0f4-2bd20e1f7f66"}})
        self.run_check()

    def test_a_nested_identifier_is_found(self):
        self.write({"a": [{"b": {"partition_uuid": RAW}}]})
        result = self.run_check(expect=1)
        self.assertIn("partition_uuid", result.stderr)

    def test_a_non_uuid_value_under_an_identifier_key_is_ignored(self):
        self.write({"disk": {"volume_uuid": "not-a-uuid"}})
        self.run_check()

    def test_invalid_json_is_reported_rather_than_skipped(self):
        path = self.root / "docs/hardware/broken.json"
        path.write_text("{not json")
        result = self.run_check(expect=1)
        self.assertIn("is not JSON", result.stderr)


if __name__ == "__main__":
    unittest.main()
