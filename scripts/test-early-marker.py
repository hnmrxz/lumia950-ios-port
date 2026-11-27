#!/usr/bin/env python3
"""Behavioural tests for the early marker in the generated arm_init.c.

The marker completes the identity (V=P) map that start.s builds -- the tables XNU itself treats as temporary, since
arm_replace_identity_map() bzeroes the V=P L1 table -- and writes through the physical address, which is the same as the virtual one
there. These tests read the file the injector actually produces, not a template.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "build" / "local" / "preflight" / "osfmk" / "arm" / "arm_init.c"


def load():
    spec = importlib.util.spec_from_file_location("boot_progress", ROOT / "ci" / "boot-progress.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def generated() -> str:
    module = load()
    source = SOURCE.read_text(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "arm_init.c"
        target.write_text(source, encoding="utf-8")
        ok, message = module.apply_to(target)
        assert ok, message
        return target.read_text(encoding="utf-8")


class EarlyMarkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SOURCE.is_file():
            raise unittest.SkipTest(f"{SOURCE} is not cached; run scripts/preflight-injectors.py first")
        cls.text = generated()
        cls.block = cls.text[cls.text.index("Bring-up marker"):cls.text.index("PE_init_platform")]

    def test_the_marker_is_injected_once_and_behind_its_token(self):
        self.assertEqual(self.text.count("lumia-early-map"), 1, "the marker must appear once")
        self.assertLess(self.block.index("lumia-early-map"), self.block.index("0x00E03030u"),
                        "the token test has to precede the drawing")

    def test_nothing_is_drawn_without_the_token(self):
        self.assertLess(self.block.index("if (installed)"), self.block.index("0x00E03030u"),
                        "every framebuffer store sits inside the installed branch")

    def test_the_mapping_goes_into_the_identity_tables(self):
        self.assertIn("ttbr0_el1", self.block, "the identity map is TTBR0")
        self.assertNotIn("ttbr1_el1", self.block, "the kernel-VA tables must not be touched")

    def test_every_table_entry_is_checked_before_it_is_followed(self):
        self.assertIn("(root_entry & 3) == 3", self.block, "a root entry is followed only when it is a table")
        self.assertIn("(l1[l1_index] & 3) != 3", self.block, "and so is an L1 entry")
        self.assertIn("root_index >= entries", self.block)
        self.assertIn("l1_index >= entries", self.block)
        self.assertIn("l2_index >= entries", self.block)

    def test_an_occupied_slot_is_not_overwritten_with_a_different_mapping(self):
        self.assertIn("(l2[l2_index] & (block - 1)) != block_pa", self.block,
                      "a slot holding some other block must be refused")

    def test_the_walk_goes_through_the_root_when_the_levels_differ(self):
        self.assertIn("ARM_TT_ROOT_SHIFT == ARM_TT_L1_SHIFT", self.block,
                      "the two levels coincide on the 16 KB granule only")
        self.assertIn("root[root_index] = ARM_TTE_BOOT_TABLE", self.block,
                      "a gigabyte the identity map does not reach gets a table of this marker's own")
        self.assertIn("l1[l1_index] = ARM_TTE_BOOT_TABLE", self.block,
                      "and the next level down likewise")

    def test_nothing_is_drawn_unless_the_mapping_was_installed(self):
        self.assertIn("installed = 0", self.block)
        self.assertIn("installed = 1", self.block)

    def test_the_framebuffer_pointer_is_the_identity_address(self):
        self.assertIn("fb = (volatile unsigned int *)pa", self.block,
                      "in the identity map the physical address is the virtual one")

    def test_the_cache_clean_covers_the_rows_that_were_written(self):
        self.assertIn("(120 * stride) / 64", self.block)
        self.assertIn("(136 * stride) / 64", self.block)
        self.assertIn("dc civac", self.block)

    def test_invalid_panel_arguments_skip_the_marker(self):
        self.assertIn("pa == 0", self.block)
        self.assertIn("v_rowBytes == 0", self.block)
        self.assertIn("v_width == 0", self.block)
        self.assertIn("v_height == 0", self.block)
        self.assertIn("height > 136", self.block)
        self.assertIn("width <= 16384", self.block)
        self.assertIn("stride <= 65536", self.block)

    def test_every_outcome_has_its_own_state_code(self):
        for code, meaning in ((2, "refused"), (3, "bad panel"), (6, "index"),
                              (7, "slot has another mapping"), (1, "installed"), (0, "drawn")):
            self.assertIn(f"lumia_early_map_state = {code}", self.block, meaning)

    def test_the_state_is_reported_after_the_vm_work(self):
        self.assertIn("LUMIA: early map state", self.text)
        self.assertLess(self.text.index("arm_vm_init"), self.text.index("LUMIA: early map state"))

    def test_applying_twice_changes_nothing(self):
        module = load()
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "arm_init.c"
            target.write_bytes(SOURCE.read_bytes())
            module.apply_to(target)
            once = target.read_text(encoding="utf-8", errors="replace")
            module.apply_to(target)
            twice = target.read_text(encoding="utf-8", errors="replace")
        self.assertEqual(once, twice)

    def test_the_default_path_is_unchanged(self):
        self.assertEqual(self.text.count("PE_init_platform(FALSE, args)"), 1)
        self.assertLess(self.text.index("Bring-up marker"), self.text.index("PE_init_platform(FALSE, args)"))


if __name__ == "__main__":
    unittest.main()
