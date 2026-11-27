#!/usr/bin/env python3
"""Behavioural tests for the early marker in the generated arm_init.c.

The marker draws through the identity map without ever replacing a mapping the kernel relies on: a covered address is used as is, an empty
leaf slot receives the block, and a block entry standing in the way is refused rather than split. The three earlier faults all came from
replacing a block at an intermediate level, which discarded a gigabyte of identity map.
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
        self.assertEqual(self.text.count("lumia_token_at(p, \"lumia-early-map\")"), 1)
        self.assertLess(self.block.index("lumia-early-map"), self.block.index("0x00E03030u"))

    def test_nothing_is_drawn_unless_the_address_is_usable(self):
        first_store = self.block.index("0x00E03030u")
        self.assertLess(self.block.index("if (usable && probe)"), first_store,
                        "the single-word probe is guarded by usable as well")
        self.assertLess(self.block.index("usable = 1"), first_store, "usable is decided before any store")
        self.assertLess(self.block.index("if (usable && !dry_run)"), self.block.index("last-shaped-check") if
                        "last-shaped-check" in self.block else len(self.block))
        self.assertIn("usable = 0", self.block)

    def test_the_mapping_is_read_from_the_identity_registers(self):
        self.assertIn("ttbr0_el1", self.block, "the identity map is TTBR0")
        self.assertNotIn("ttbr1_el1", self.block, "the kernel-VA tables must not be touched")

    def test_a_block_entry_is_never_replaced_by_a_table(self):
        self.assertIn("(l1_entry & 3) == 1", self.block, "a block at the gigabyte level is inspected, not overwritten")
        self.assertIn("? 1 : 9", self.block, "a block that does not cover the framebuffer is refused, not split")
        self.assertIn("l2[l2_index] = ARM_TTE_BOOT_BLOCK", self.block, "only a leaf slot ever receives the block")

    def test_the_dry_run_installs_the_mapping_without_writing(self):
        self.assertIn("lumia-early-map-dry", self.block)
        self.assertIn("if (usable && !dry_run)", self.block, "the store is the part a dry run skips")

    def test_each_drawing_step_can_be_left_out(self):
        self.assertIn("lumia-early-map-noclean", self.block)
        self.assertIn("lumia-early-map-notlbi", self.block)
        self.assertIn("if (!no_tlbi)", self.block, "the TLB invalidate is its own group")
        self.assertIn("if (!no_clean)", self.block, "so is the cache clean")
        self.assertLess(self.block.index("if (!no_tlbi)"), self.block.index("for (row = 120;"), "maintenance before the stores")
        self.assertLess(self.block.index("for (row = 120;"), self.block.index("if (!no_clean)"), "and the clean after them")

    def test_every_table_entry_is_checked_before_it_is_followed(self):
        self.assertIn("(l1_entry & 3) == 3", self.block, "a table at the gigabyte level is followed")
        self.assertIn("(l1_entry & 3) == 1", self.block, "a block is recognised")
        for token in ("l1_index >= entries", "l2_index >= entries"):
            self.assertIn(token, self.block)

    def test_a_leaf_slot_holding_another_block_is_refused(self):
        self.assertIn("(l2[l2_index] & (block - 1)) != block_pa", self.block)

    def test_the_framebuffer_pointer_is_the_identity_address(self):
        self.assertIn("fb = (volatile unsigned int *)pa", self.block)

    def test_the_cache_clean_covers_the_rows_that_were_written(self):
        for token in ("(8 * stride) / 64", "(16 * stride) / 64", "dc civac"):
            self.assertIn(token, self.block)

    def test_the_rows_stay_inside_one_mapped_block(self):
        """The rows used to run past the block the marker maps: a single store worked, the loop did not."""
        self.assertIn("for (row = 8; row < 16; row++)", self.block)
        self.assertNotIn("row < 136", self.block)

    def test_invalid_panel_arguments_skip_the_marker(self):
        for token in ("pa == 0", "v_rowBytes == 0", "v_width == 0", "v_height == 0",
                      "height > 16", "width <= 16384", "stride <= 65536"):
            self.assertIn(token, self.block)

    def test_every_outcome_has_its_own_state_code(self):
        for code, meaning in ((2, "refused"), (3, "bad panel"), (6, "index"),
                              (7, "slot has another block"), (1, "usable"), (0, "drawn")):
            self.assertIn(f"lumia_early_map_state = {code}", self.block, meaning)
        self.assertIn("? 1 : 9", self.block, "the block-in-the-way refusal")

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
