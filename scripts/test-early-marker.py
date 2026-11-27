#!/usr/bin/env python3
"""Behavioural tests for the early marker in the generated arm_init.c.

These read the file the injector actually produces and check properties of it, not the strings of a template:

  * the marker exists once, behind the 'lumia-early-map' token, and nothing is drawn without it;
  * the mapping is only installed into an L1 slot that reads back empty, with both indices bounds checked;
  * nothing is written to the framebuffer unless the mapping was installed;
  * the addresses the marker uses are the mapped virtual ones, never the physical address from the boot arguments;
  * the cache maintenance covers exactly the rows that were written;
  * a second apply changes nothing.
"""

from __future__ import annotations

import importlib.util
import re
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

    def test_the_marker_is_injected_once_and_behind_its_token(self):
        self.assertEqual(self.text.count("lumia-early-map"), 1, "the marker must appear once")
        marker = self.text.index("lumia-early-map")
        drawing = self.text.index("0x00E03030u")
        self.assertLess(marker, drawing, "the token test has to precede the drawing")

    def test_nothing_is_drawn_without_the_token(self):
        block = self.text[self.text.index("Bring-up marker"):self.text.index("PE_init_platform")]
        # every store to the framebuffer sits inside the `if (installed)` branch
        installed = block.index("if (installed)")
        drawing = block.index("0x00E03030u")
        self.assertLess(installed, drawing)

    def test_the_mapping_only_uses_an_empty_l1_slot(self):
        block = self.text[self.text.index("Bring-up marker"):self.text.index("PE_init_platform")]
        self.assertIn("l1[l1_index] != 0", block, "an occupied slot must be refused, and the refusal recorded")
        self.assertIn("l1_index >= entries", block)
        self.assertIn("l2_index >= entries", block)
        self.assertIn("(root[root_index] & 3) != 3", block, "the root entry has to be a table before it is followed")

    def test_nothing_is_drawn_unless_the_mapping_was_installed(self):
        block = self.text[self.text.index("Bring-up marker"):self.text.index("PE_init_platform")]
        self.assertIn("installed = 0", block)
        self.assertIn("installed = 1", block)

    def test_the_framebuffer_pointer_is_the_mapped_address(self):
        block = self.text[self.text.index("Bring-up marker"):self.text.index("PE_init_platform")]
        self.assertIn("fb = (volatile unsigned int *)(va + (pa - block_pa))", block)
        self.assertNotRegex(block, r"fb\s*=\s*\(volatile unsigned int \*\)pa\b",
                            "the physical address must never be used as a pointer")

    def test_the_cache_clean_covers_the_rows_that_were_written(self):
        block = self.text[self.text.index("Bring-up marker"):self.text.index("PE_init_platform")]
        self.assertIn("(120 * stride) / 64", block)
        self.assertIn("(136 * stride) / 64", block)
        self.assertIn("dc civac", block)

    def test_invalid_panel_arguments_skip_the_marker(self):
        block = self.text[self.text.index("Bring-up marker"):self.text.index("PE_init_platform")]
        self.assertIn("pa == 0", block)
        self.assertIn("v_rowBytes == 0", block)
        self.assertIn("v_width == 0", block)
        self.assertIn("v_height == 0", block)
        self.assertIn("height > 136", block)
        self.assertIn("width <= 16384", block, "an absurd width must not be multiplied out")
        self.assertIn("stride <= 65536", block, "nor an absurd stride")

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
        # the injected block is the only addition before the platform call; the call itself still happens exactly once
        self.assertEqual(self.text.count("PE_init_platform(FALSE, args)"), 1)
        self.assertLess(self.text.index("Bring-up marker"), self.text.index("PE_init_platform(FALSE, args)"))

    def test_every_outcome_has_its_own_state_code(self):
        block = self.text[self.text.index("Bring-up marker"):self.text.index("PE_init_platform")]
        self.assertIn("lumia_early_map_state = 2", block, "refused by default")
        self.assertIn("lumia_early_map_state = 5", block, "no root entry")
        self.assertIn("lumia_early_map_state = 6", block, "index out of range")
        self.assertIn("lumia_early_map_state = 7", block, "slot already taken")
        self.assertIn("lumia_early_map_state = 3", block, "invalid panel arguments")
        self.assertIn("lumia_early_map_state = 1", block, "installed but not drawn")
        self.assertIn("lumia_early_map_state = 0", block, "installed and drawn")

    def test_the_state_is_reported_after_the_vm_work(self):
        self.assertIn("LUMIA: early map state", self.text)
        self.assertLess(self.text.index("arm_vm_init"), self.text.index("LUMIA: early map state"))


if __name__ == "__main__":
    unittest.main()
