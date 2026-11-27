#!/usr/bin/env python3
"""Tests for the read-only GPT reader against its own synthetic fixture."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GptReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = load("make_gpt_fixture", "make-gpt-fixture.py")
        cls.reader = load("gpt_read", "gpt-read.py")

    def parse(self, corrupt: str | None = None):
        return self.reader.parse(self.fixture.build(corrupt))

    def test_the_fixture_reads_back_with_both_partitions(self):
        result = self.parse()
        names = [partition["name"] for partition in result["partitions"]]
        self.assertEqual(names, ["EFIESP", "MainOS"])
        self.assertEqual(result["partitions"][0]["first_lba"], 2048)
        self.assertEqual(result["partitions"][0]["last_lba"], 4095)
        self.assertEqual(result["partitions"][0]["sectors"], 2048)
        self.assertEqual(result["partitions"][0]["kind"], "EFI System Partition")
        self.assertEqual(result["partitions"][1]["kind"], "Microsoft basic data")

    def test_the_header_and_entry_crcs_are_verified(self):
        result = self.parse()
        self.assertEqual(result["signature"], "EFI PART")
        self.assertEqual(result["revision"], "1.0")
        self.assertTrue(result["header_crc"].startswith("0x"))
        self.assertTrue(result["entries_crc"].startswith("0x"))

    def test_the_backup_header_agrees(self):
        self.assertTrue(self.parse()["backup"]["agrees"])

    def test_a_broken_protective_mbr_is_refused(self):
        with self.assertRaises(self.reader.GptError):
            self.parse("mbr")

    def test_a_broken_header_crc_is_refused(self):
        with self.assertRaises(self.reader.GptError) as caught:
            self.parse("header")
        self.assertIn("header CRC", str(caught.exception))

    def test_a_broken_entry_crc_is_refused(self):
        with self.assertRaises(self.reader.GptError) as caught:
            self.parse("entries")
        self.assertIn("entry array CRC", str(caught.exception))

    def test_overlapping_partitions_are_refused(self):
        with self.assertRaises(self.reader.GptError) as caught:
            self.parse("overlap")
        self.assertIn("overlaps", str(caught.exception))

    def test_a_truncated_image_is_refused(self):
        with self.assertRaises(self.reader.GptError):
            self.reader.parse(b"\x00" * 512)

    def test_the_cli_exits_non_zero_on_a_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.img"
            path.write_bytes(self.fixture.build("header"))
            self.assertEqual(self.reader.main(["--image", str(path)]), 1)

    def test_the_cli_writes_json_for_a_good_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "good.img"
            report = Path(temporary) / "gpt.json"
            image.write_bytes(self.fixture.build())
            self.assertEqual(self.reader.main(["--image", str(image), "--json", str(report)]), 0)
            self.assertIn("MainOS", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
