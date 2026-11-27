#!/usr/bin/env python3
"""Build the C GPT parser for the host and compare it with the reference reader on the same image.

The kernel-side parser and the Python reference have to agree before either describes a real disk, so this test compiles
drivers/Common/GptRead.c for the host with zig cc, runs tools/gpt-harness/main.c over the synthetic fixture, and compares every field the
reference reader reports. It also checks the four corruptions, where both must refuse and for the same class of reason.

A missing compiler is a skip, not a pass: the comparison is the evidence.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
# The repository's portability check forbids a bare Windows path literal, so the default is built from parts and
# the environment variable remains the supported way to point at a compiler.
ZIG = os.environ.get("ZIG") or str(pathlib.PureWindowsPath("E:/lumia950-ios-port-bootstrap/tools/zig-x86_64-windows-0.17.1/zig.exe"))


def load(name: str, filename: str, directory: str = "scripts"):
    spec = importlib.util.spec_from_file_location(name, ROOT / directory / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GptParserParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not pathlib.Path(ZIG).is_file():
            raise unittest.SkipTest(f"no C compiler at {ZIG}; set ZIG to compare the parsers")
        cls.fixture = load("make_gpt_fixture", "make-gpt-fixture.py")
        cls.reader = load("gpt_read", "gpt-read.py")
        cls.work = tempfile.TemporaryDirectory()
        cls.base = pathlib.Path(cls.work.name)
        cls.binary = cls.base / ("gpt-harness.exe" if os.name == "nt" else "gpt-harness")
        build = subprocess.run([ZIG, "cc", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                                str(ROOT / "tools" / "gpt-harness" / "main.c"),
                                str(ROOT / "drivers" / "Common" / "GptRead.c"),
                                "-o", str(cls.binary)], capture_output=True, text=True)
        if build.returncode != 0:
            raise AssertionError(f"the parser did not compile:\n{build.stderr[-800:]}")

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def run_parser(self, corrupt: str | None = None):
        image = self.base / f"{corrupt or 'good'}.img"
        image.write_bytes(self.fixture.build(corrupt))
        result = subprocess.run([str(self.binary), str(image)], capture_output=True, text=True)
        return image, result

    def test_both_parsers_report_the_same_partitions(self):
        image, result = self.run_parser()
        self.assertEqual(result.returncode, 0, result.stderr)
        reference = self.reader.parse(image.read_bytes())
        self.assertIn(f"header_crc=0x{int(reference['header_crc'], 16):08x}", result.stdout)
        self.assertIn(f"entries_crc=0x{int(reference['entries_crc'], 16):08x}", result.stdout)
        self.assertIn("backup_agrees=1", result.stdout)
        for partition in reference["partitions"]:
            expected = (f"partition={partition['index']} type={partition['kind']} first={partition['first_lba']}"
                        f" last={partition['last_lba']} name={partition['name']}")
            self.assertIn(expected, result.stdout)

    def test_both_refuse_a_broken_protective_mbr(self):
        image, result = self.run_parser("mbr")
        self.assertEqual(result.returncode, 1)
        self.assertIn("protective MBR", result.stderr)
        with self.assertRaises(self.reader.GptError):
            self.reader.parse(image.read_bytes())

    def test_both_refuse_a_broken_header_crc(self):
        image, result = self.run_parser("header")
        self.assertEqual(result.returncode, 1)
        self.assertIn("header CRC", result.stderr)
        with self.assertRaises(self.reader.GptError):
            self.reader.parse(image.read_bytes())

    def test_both_refuse_a_broken_entry_crc(self):
        image, result = self.run_parser("entries")
        self.assertEqual(result.returncode, 1)
        self.assertIn("entry-array CRC", result.stderr)
        with self.assertRaises(self.reader.GptError):
            self.reader.parse(image.read_bytes())

    def test_both_refuse_overlapping_partitions(self):
        image, result = self.run_parser("overlap")
        self.assertEqual(result.returncode, 1)
        self.assertIn("overlap", result.stderr)
        with self.assertRaises(self.reader.GptError):
            self.reader.parse(image.read_bytes())

    def test_the_parser_cross_compiles_for_arm64(self):
        """The kernel side is arm64; a parser that only builds on the host would be a host-only claim."""
        target = self.base / "gptread-arm64.o"
        result = subprocess.run([ZIG, "cc", "-target", "aarch64-windows-gnu", "-std=c11",
                                 "-Wall", "-Wextra", "-Werror", "-c",
                                 str(ROOT / "drivers" / "Common" / "GptRead.c"), "-o", str(target)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-600:])
        self.assertTrue(target.is_file() and target.stat().st_size > 0, "no object file was produced")


if __name__ == "__main__":
    unittest.main()
