#!/usr/bin/env python3
"""Every evidence citation must resolve inside the repository.

The CI checker runs in a clean checkout, where nothing under out/ exists; the same check on this machine passes
because out/ is full of measurements. That difference turned a green local run into three red ones, so this test
enforces the rule locally: evidence paths must be repository-relative files that are committed, never build output.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class EvidencePathTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "docs" / "evidence.json").read_text(encoding="utf-8"))

    def test_no_evidence_points_at_build_output(self):
        offenders = []
        for subject in self.data["subjects"]:
            for item in subject.get("evidence", []):
                path = item.get("path", "")
                if path.startswith("out/") or path.startswith("./out/"):
                    offenders.append(f"{subject.get('id')}: {path}")
        self.assertEqual(offenders, [], "evidence must cite committed files, not build output")

    def test_every_citation_exists(self):
        missing = []
        for subject in self.data["subjects"]:
            for item in subject.get("evidence", []):
                path = item.get("path", "")
                # a subject may cite a directory of sources, and the CI checker accepts that too
                if path and not (ROOT / path).exists():
                    missing.append(f"{subject.get('id')}: {path}")
        self.assertEqual(missing, [], "every cited path has to exist in the tree")


if __name__ == "__main__":
    unittest.main()
