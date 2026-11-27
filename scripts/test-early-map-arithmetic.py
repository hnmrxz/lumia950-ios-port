#!/usr/bin/env python3
"""The marker's arithmetic, checked for both the handset and the emulator.

The QEMU failure that cost several builds was a row range crossing the end of the single 2 MB block the marker maps. This test makes that
mistake impossible to reintroduce: it computes, for the handset's panel (1080x1920, stride 4320, video base 0x400000) and for the emulator's
(800x600, stride 3200, video base 0xEC7A0000), the block the marker maps, the indices it uses, and whether every store of its row range
lands inside that block.

It reads the row range out of the generated arm_init.c rather than restating it, so a change to the marker is checked against the arithmetic
that made it work.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "build" / "local" / "preflight" / "osfmk" / "arm" / "arm_init.c"

# from osfmk/arm64/proc_reg.h for the 4 KB-page kernel this port builds
BLOCK_BYTES = 2 * 1024 * 1024
ENTRIES = 512

PANELS = {
    "handset": {"base": 0x00400000, "stride": 4320, "width": 1080, "height": 1920},
    "qemu": {"base": 0xEC7A0000, "stride": 3200, "width": 800, "height": 600},
}


def load():
    spec = importlib.util.spec_from_file_location("boot_progress", ROOT / "ci" / "boot-progress.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def generated() -> str:
    module = load()
    source = SOURCE.read_text(encoding="utf-8", errors="replace")
    import tempfile

    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "arm_init.c"
        target.write_text(source, encoding="utf-8")
        ok, message = module.apply_to(target)
        assert ok, message
        return target.read_text(encoding="utf-8")


def row_range(text: str) -> tuple[int, int]:
    """The panel's row range: the loop inside the plain draw branch, not the self-test's own loop."""
    gate = text.index("if (usable && !dry_run && !selftest)")
    match = re.search(r"for \(row = (\d+); row < (\d+); row\+\+\)", text[gate:])
    assert match, "the marker has no panel row loop"
    return int(match.group(1)), int(match.group(2))


class EarlyMapArithmeticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SOURCE.is_file():
            raise unittest.SkipTest(f"{SOURCE} is not cached; run scripts/preflight-injectors.py first")
        cls.text = generated()
        cls.first, cls.end = row_range(cls.text)

    def test_the_rows_stay_inside_the_mapped_block(self):
        for name, panel in PANELS.items():
            with self.subTest(panel=name):
                block_base = panel["base"] & ~(BLOCK_BYTES - 1)
                block_end = block_base + BLOCK_BYTES
                lowest = panel["base"] + self.first * panel["stride"]
                highest = panel["base"] + (self.end - 1) * panel["stride"] + panel["width"] * 4
                self.assertGreaterEqual(lowest, block_base)
                self.assertLess(highest, block_end,
                                f"{name}: the marker's last store is outside the block it maps")

    def test_the_block_indices_are_inside_their_tables(self):
        for name, panel in PANELS.items():
            with self.subTest(panel=name):
                block_base = panel["base"] & ~(BLOCK_BYTES - 1)
                l1_index = (block_base >> 30) & 0x1FF
                l2_index = (block_base >> 21) & 0x1FF
                self.assertLess(l1_index, ENTRIES, f"{name}: L1 index")
                self.assertLess(l2_index, ENTRIES, f"{name}: L2 index")

    def test_the_handset_video_base_shares_the_kernels_gigabyte(self):
        """0x400000 and the kernel's physical base are both below 1 GB, so the identity table's gigabyte entry should already exist on the
        handset and only a leaf entry is needed -- the opposite of the emulator, where the framebuffer sits in an empty gigabyte."""
        handset = PANELS["handset"]
        kernel_phys_base = 0x27004000  # measured earlier for the handset image
        self.assertEqual((handset["base"] & ~(BLOCK_BYTES - 1)) >> 30, (kernel_phys_base & ~(BLOCK_BYTES - 1)) >> 30)
        self.assertNotEqual((PANELS["qemu"]["base"] & ~(BLOCK_BYTES - 1)) >> 30,
                            (0x40000000 & ~(BLOCK_BYTES - 1)) >> 30,
                            "the emulator's framebuffer is in its own gigabyte, which is why it needed a table")

    def test_the_bounds_check_admits_the_rows_it_uses(self):
        self.assertIn(f"height > {self.end}", self.text,
                      "the height bound has to admit the last row the marker draws")
        self.assertLess(self.end, PANELS["handset"]["height"], "and the handset panel is taller than that")

    def test_the_clean_covers_the_same_rows(self):
        for row in (self.first, self.end):
            self.assertIn(f"({row} * stride) / 64", self.text)


if __name__ == "__main__":
    unittest.main()
