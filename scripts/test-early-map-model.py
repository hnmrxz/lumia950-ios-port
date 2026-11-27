#!/usr/bin/env python3
"""Exhaustive branch tests for the early marker's decision logic (scripts/model-early-map.py)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("model_early_map", ROOT / "scripts" / "model-early-map.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class EarlyMapModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load()

    def tables(self):
        return self.model.Table(l1={}, l2={})

    def test_an_empty_gigabyte_gets_a_table_then_the_leaf(self):
        tables = self.tables()
        result = self.model.install(tables, 0xEC7A0000)
        self.assertTrue(result.usable)
        self.assertTrue(result.created_table, "the emulator's gigabyte was empty")
        self.assertEqual(result.l1_index, 3)
        self.assertIsNotNone(result.l2_index)
        self.assertEqual(tables.l2[3][result.l2_index] & 3, self.model.DESCRIPTOR_BLOCK)

    def test_an_existing_table_is_used_without_creating_one(self):
        """The handset's case: the framebuffer shares the kernel image's gigabyte, whose entry is already a table."""
        tables = self.tables()
        tables.l1[0] = self.model.DESCRIPTOR_TABLE | 0x48B5C000
        tables.l2[0] = {}
        result = self.model.install(tables, 0x00400000)
        self.assertTrue(result.usable)
        self.assertFalse(result.created_table, "the handset branch must not create a table")
        self.assertEqual(result.l2_index, 2, "0x400000 is the third 2 MB block of gigabyte 0")

    def test_a_block_that_covers_the_target_is_used(self):
        tables = self.tables()
        tables.l1[0] = self.model.DESCRIPTOR_BLOCK | 0x00000000  # a 1 GB block at 0 covers 0x400000
        result = self.model.install(tables, 0x00400000)
        self.assertTrue(result.usable)

    def test_a_block_that_does_not_cover_the_target_is_refused(self):
        tables = self.tables()
        tables.l1[3] = self.model.DESCRIPTOR_BLOCK | 0xF0000000  # a block starting past the framebuffer's block
        result = self.model.install(tables, 0xEC7A0000)
        self.assertFalse(result.usable)
        self.assertEqual(result.state, 9, "a block in the way is refused, never split")

    def test_a_leaf_slot_holding_another_block_is_refused(self):
        tables = self.tables()
        tables.l1[3] = self.model.DESCRIPTOR_TABLE | 0x48B5C000
        tables.l2[3] = {}
        index = (0xEC600000 >> 21) & 0x1FF
        tables.l2[3][index] = self.model.DESCRIPTOR_BLOCK | 0xEA000000
        result = self.model.install(tables, 0xEC7A0000)
        self.assertFalse(result.usable)
        self.assertEqual(result.state, 7)

    def test_a_leaf_slot_holding_the_same_block_is_accepted(self):
        tables = self.tables()
        tables.l1[3] = self.model.DESCRIPTOR_TABLE | 0x48B5C000
        tables.l2[3] = {}
        index = (0xEC600000 >> 21) & 0x1FF
        tables.l2[3][index] = self.model.DESCRIPTOR_BLOCK | 0xEC600000
        result = self.model.install(tables, 0xEC7A0000)
        self.assertTrue(result.usable)

    def test_a_zero_address_is_refused(self):
        self.assertEqual(self.model.install(self.tables(), 0).state, 3)

    def test_the_emulator_block_index_and_the_handset_index_differ(self):
        self.assertEqual(self.model.bit(0xEC600000, 30, 30 + 8), 3, "the emulator's framebuffer is in gigabyte 3")
        self.assertEqual(self.model.bit(0x00400000, 30, 30 + 8), 0, "the handset's is in gigabyte 0")

    def test_the_row_ranges_fit_inside_one_block(self):
        """The emulator's rows used to cross into the next 2 MB block; that is what faulted for several builds."""
        self.assertFalse(self.model.covers_one_block(0xEC7A0000, 120, 136, 3200, 800),
                         "the old range 120..135 crossed the block boundary")
        self.assertTrue(self.model.covers_one_block(0xEC7A0000, 8, 16, 3200, 800), "the range in use stays inside")
        self.assertTrue(self.model.covers_one_block(0x00400000, 8, 16, 4320, 1080), "and so does the handset's")


if __name__ == "__main__":
    unittest.main()
