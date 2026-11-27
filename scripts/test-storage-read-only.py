#!/usr/bin/env python3
"""The storage driver must be read-only at the driver layer, not by a mount option.

The milestone M2 acceptance says the eMMC is accessed read-only; the objective's owner added the requirement that this be enforced in
the driver rather than relying on `read-only` mount flags. That means three things have to stay true in the source, and this test
holds all three:

  1. the command set the driver actually issues contains no write command (CMD24/CMD25) and no erase (CMD38);
  2. the storage entry point refuses an outbound memory descriptor instead of forwarding it;
  3. the device reports itself write protected, so a filesystem above it has no reason to try.

A host test cannot execute the driver; it can refuse a source change that would create the path in the first place.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

DRIVER = Path(__file__).resolve().parent.parent / "drivers" / "NativeSdhci"
WRITE_COMMANDS = ("kCmd24WriteSingleBlock", "kCmd25WriteMultiple", "kCmd38Erase")
DECLARED_WRITE_COMMANDS = ("kCmd24WriteSingleBlock", "kCmd25WriteMultiple")


class StorageReadOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {path.name: path.read_text(encoding="utf-8", errors="replace") for path in DRIVER.glob("*.cpp")}
        cls.header = (DRIVER / "SdhciRegs.h").read_text(encoding="utf-8", errors="replace")

    def test_no_write_command_is_ever_issued(self):
        offenders = []
        for name, text in self.sources.items():
            for command in WRITE_COMMANDS:
                # an occurrence outside a comment is a call or a case label, i.e. a path that could run
                for line in text.splitlines():
                    stripped = line.strip()
                    if command in stripped and not stripped.startswith("//"):
                        offenders.append(f"{name}: {stripped[:100]}")
        self.assertEqual(offenders, [], "the driver must not issue a write or erase command")

    def test_the_write_commands_exist_only_as_declarations(self):
        for command in DECLARED_WRITE_COMMANDS:
            self.assertIn(command, self.header, f"{command} should stay declared so its absence is deliberate")
        # erase was never declared, which is stronger than declaring and not using it
        self.assertNotIn("kCmd38Erase", self.header, "the header deliberately has no erase command")

    def test_the_entry_point_refuses_outbound_transfers(self):
        text = self.sources["NativeSdhci.cpp"]
        self.assertIn("kIODirectionOut", text, "doAsyncReadWrite must look at the direction")
        match = re.search(r"kIODirectionOut\)[\s\S]{0,400}?return ([A-Za-z0-9_]+);", text)
        self.assertIsNotNone(match, "an outbound transfer must return before any device access")
        self.assertEqual(match.group(1), "kIOReturnUnsupported", "and say so explicitly")

    def test_the_device_reports_write_protection(self):
        text = self.sources["NativeSdhci.cpp"]
        self.assertRegex(text, r"reportWriteProtection\(bool \*value\)[\s\S]{0,400}\*value = true;",
                         "reportWriteProtection has to report the protection that is in force")

    def test_the_polling_host_only_reads(self):
        text = self.sources["PollingHost.cpp"]
        self.assertIn("kCmd17ReadSingleBlock", text, "the read path is the one that exists")
        for command in WRITE_COMMANDS:
            self.assertNotIn(command, text, f"the polling host must not know {command}")


if __name__ == "__main__":
    unittest.main()
