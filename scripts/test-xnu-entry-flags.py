#!/usr/bin/env python3
"""Check the flag chain of scripts/test-native-xnu-entry.py without running QEMU.

The fixture's real work needs an emulator, a staged tree and a linked kernel. What can be tested
here is the part that decides what it will assert: `--finish-bsd` has to imply `--finish-iokit`,
which has to imply `--crypto-post`, or the strongest checks would be silently skipped.

    python3 scripts/test-xnu-entry-flags.py
"""
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("test-native-xnu-entry.py")
SPEC = importlib.util.spec_from_file_location("xnu_entry", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

BASE = ["test-native-xnu-entry.py", "--kernel", "k", "--esp", "e", "--firmware", "f",
        "--output", "o"]


class FlagChainTests(unittest.TestCase):
    def parse(self, *extra):
        captured = {}

        def run(args):
            captured.update(vars(args))

        original_run, original_argv = MODULE.run, sys.argv
        MODULE.run = run
        sys.argv = BASE + list(extra)
        try:
            MODULE.main()
        finally:
            MODULE.run, sys.argv = original_run, original_argv
        return captured

    def test_the_default_run_asserts_only_the_early_vm_step(self):
        args = self.parse()
        self.assertFalse(args["crypto_post"])
        self.assertFalse(args["finish_vm"])
        self.assertFalse(args["finish_iokit"])
        self.assertFalse(args["finish_bsd"])

    def test_crypto_post_requires_the_vm_return(self):
        args = self.parse("--crypto-post")
        self.assertTrue(args["crypto_post"])
        self.assertTrue(args["finish_vm"])

    def test_finish_iokit_requires_the_crypto_post(self):
        args = self.parse("--finish-iokit")
        self.assertTrue(args["finish_iokit"])
        self.assertTrue(args["crypto_post"])
        self.assertTrue(args["finish_vm"])

    def test_finish_bsd_requires_iokit_and_therefore_crypto(self):
        args = self.parse("--finish-bsd")
        self.assertTrue(args["finish_bsd"])
        self.assertTrue(args["finish_iokit"])
        self.assertTrue(args["crypto_post"])

    def test_a_timeout_outside_the_bound_is_refused(self):
        with self.assertRaises(SystemExit) as caught:
            self.parse("--timeout", "1000")
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
