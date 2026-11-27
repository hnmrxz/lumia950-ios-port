#!/usr/bin/env python3
"""Behavioural tests for the early marker in the generated arm_init.c.

The marker completes the identity (V=P) map for the block holding the framebuffer and writes through the physical address, which is the
virtual one there. Each level it adds gets its own page: pointing the added level at the page that then receives the block entry is what
made build 45978469173 fault on the first store.
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
        self.assertEqual(self.text.count("lumia-early-map"), 1)
        self.assertLess(self.block.index("lumia-early-map"), self.block.index("0x00E03030u"))

    def test_nothing_is_drawn_without_the_token(self):
        self.assertLess(self.block.index("if (installed)"), self.block.index("0x00E03030u"))

    def test_the_mapping_goes_into_the_identity_tables(self):
        self.assertIn("ttbr0_el1", self.block)
        self.assertNotIn("ttbr1_el1", self.block, "the kernel-VA tables must not be touched")

    def test_each_added_level_has_its_own_page(self):
        self.assertIn("static uint64_t lumia_l2[", self.block)
        self.assertIn("static uint64_t lumia_l1[", self.block)
        self.assertIn("root[root_index] = ARM_TTE_BOOT_TABLE | (l1_pa & ARM_TTE_TABLE_MASK)", self.block)
        self.assertIn("l1[l1_index] = ARM_TTE_BOOT_TABLE | (l2_pa & ARM_TTE_TABLE_MASK)", self.block)
        self.assertIn("l2[l2_index] = ARM_TTE_BOOT_BLOCK", self.block)

    def test_every_table_entry_is_checked_before_it_is_followed(self):
        self.assertIn("(root_entry & 3) == 3", self.block)
        self.assertIn("(l1_entry & 3) == 3", self.block)
        self.assertIn("root_index >= entries", self.block)
        self.assertIn("l1_index >= entries", self.block)
        self.assertIn("l2_index >= entries", self.block)

    def test_an_occupied_slot_is_refused_when_it_holds_another_block(self):
        self.assertIn("(l2[l2_index] & (block - 1)) != block_pa", self.block)

    def test_the_levels_coincide_on_a_large_granule(self):
        self.assertIn("ARM_TT_ROOT_SHIFT == ARM_TT_L1_SHIFT", self.block)

    def test_nothing_is_drawn_unless_the_mapping_was_installed(self):
        self.assertIn("installed = 0", self.block)
        self.assertIn("installed = 1", self.block)

    def test_the_framebuffer_pointer_is_the_identity_address(self):
        self.assertIn("fb = (volatile unsigned int *)pa", self.block)

    def test_the_cache_clean_covers_the_rows_that_were_written(self):
        self.assertIn("(120 * stride) / 64", self.block)
        self.assertIn("(136 * stride) / 64", self.block)
        self.assertIn("dc civac", self.block)

    def test_invalid_panel_arguments_skip_the_marker(self):
        for token in ("pa == 0", "v_rowBytes == 0", "v_width == 0", "v_height == 0",
                      "height > 136", "width <= 16384", "stride <= 65536"):
            self.assertIn(token, self.block)

    def test_every_outcome_has_its_own_state_code(self):
        for code, meaning in ((2, "refused"), (3, "bad panel"), (6, "index"),
                              (7, "slot has another block"), (1, "installed"), (0, "drawn")):
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
