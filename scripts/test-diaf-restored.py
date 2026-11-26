#!/usr/bin/env python3
"""The boot-progress instrument must put DAIF back.

Masking interrupts around the store path is correct -- a fault there would be reported through the console that is not usable
yet -- but returning with them masked is not. Emulated boots said so: right after the LUMIA line, the next allocation in
bsd_init panicked with 'Calling {k,z}alloc from interrupt disabled context isn't allowed'. A host test cannot execute the
inline assembly, so this asserts the invariant on the source itself.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "drivers" / "NativeBootProgress" / "NativeBootProgress.cpp"


class DiafRestoredTests(unittest.TestCase):
    def setUp(self):
        self.text = SOURCE.read_text(encoding="utf-8")

    def test_masking_is_paired_with_a_save(self):
        if "msr DAIFSet, #0xf" not in self.text:
            self.skipTest("the instrument does not mask interrupts")
        self.assertRegex(self.text, r"mrs\s+%0,\s*DAIF",
                         "masks DAIF without saving it first")

    def test_masking_is_paired_with_a_restore(self):
        if "msr DAIFSet, #0xf" not in self.text:
            self.skipTest("the instrument does not mask interrupts")
        self.assertRegex(self.text, r"msr\s+DAIF,\s*%0",
                         "masks DAIF but never restores it")

    def test_the_restore_comes_after_the_mask(self):
        if "msr DAIFSet, #0xf" not in self.text:
            self.skipTest("the instrument does not mask interrupts")
        mask = self.text.index("msr DAIFSet, #0xf")
        restore = self.text.index("msr DAIF, %0")
        self.assertLess(mask, restore, "the restore must follow the mask")

    def test_the_routine_still_returns_early_on_refusal(self):
        # the store path refuses null and undrawable rectangles; that guard must survive the DAIF work
        self.assertIn("boot_progress::drawable(rect", self.text)


if __name__ == "__main__":
    unittest.main()
