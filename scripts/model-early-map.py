#!/usr/bin/env python3
"""The early marker's decision logic as a model, so every branch can be exercised without a build.

The C in ci/boot-progress.py is the authority; this module mirrors its decisions so the branch table can be tested exhaustively in
milliseconds instead of a thirty-minute build. Three of the faults this instrument produced were logic errors in exactly these branches
(an empty gigabyte, a taken leaf slot, a block that was misread), so the cases are worth having on record:

    empty gigabyte            -> create a table, then write the leaf block
    gigabyte already a table  -> write the leaf block (the handset's case)
    gigabyte already a block  -> use it when it covers the target, otherwise refuse
    leaf slot taken           -> refuse when it maps a different block, accept when it maps this one
    index out of range        -> refuse

It also checks the two numeric arrangements that produced real faults: the framebuffer's block boundary on the emulator and the handset's
row range.
"""

from __future__ import annotations

import dataclasses

BLOCK_BYTES = 2 * 1024 * 1024     # ARM_TT_L2_SIZE, 4 KB-page kernel
L1_ENTRIES = 512
L2_ENTRIES = 512

DESCRIPTOR_INVALID = 0
DESCRIPTOR_BLOCK = 1
DESCRIPTOR_TABLE = 3


@dataclasses.dataclass
class Table:
    """A one- or two-level table set, enough to model the identity map for one address."""
    l1: dict[int, int]
    l2: dict[int, dict[int, int]]


@dataclasses.dataclass
class Result:
    state: int
    usable: bool
    created_table: bool
    l1_index: int | None = None
    l2_index: int | None = None


def bit(value: int, low: int, high: int) -> int:
    return (value >> low) & ((1 << (high - low + 1)) - 1)


def install(tables: Table, pa: int) -> Result:
    """Mirror of the C: decide what the marker does for this physical address."""
    if pa == 0:
        return Result(state=3, usable=False, created_table=False)
    block_pa = pa & ~(BLOCK_BYTES - 1)
    l1_index = (block_pa >> 30) & 0x1FF
    if l1_index >= L1_ENTRIES:
        return Result(state=6, usable=False, created_table=False, l1_index=l1_index)
    entry = tables.l1.get(l1_index, DESCRIPTOR_INVALID)
    created = False
    if entry & 3 == DESCRIPTOR_BLOCK:
        covers = (entry & 0x0000FFFFFFFFF000) <= block_pa
        return Result(state=1 if covers else 9, usable=covers, created_table=False, l1_index=l1_index)
    if entry & 3 == DESCRIPTOR_TABLE:
        l2 = tables.l2.setdefault(l1_index, {})
    else:
        l2 = tables.l2.setdefault(l1_index, {})
        created = True
    l2_index = (block_pa >> 21) & 0x1FF
    if l2_index >= L2_ENTRIES:
        return Result(state=6, usable=False, created_table=created, l1_index=l1_index, l2_index=l2_index)
    current = l2.get(l2_index, DESCRIPTOR_INVALID)
    if current and (current & 0x0000FFFFFFFFF000) != block_pa:
        return Result(state=7, usable=False, created_table=created, l1_index=l1_index, l2_index=l2_index)
    l2[l2_index] = DESCRIPTOR_BLOCK | block_pa
    return Result(state=1, usable=True, created_table=created, l1_index=l1_index, l2_index=l2_index)


def covers_one_block(pa: int, first_row: int, last_row: int, stride: int, width: int) -> bool:
    """Whether the marker's rows stay inside the single block it maps."""
    block_base = pa & ~(BLOCK_BYTES - 1)
    lowest = pa + first_row * stride
    highest = pa + (last_row - 1) * stride + width * 4
    return lowest >= block_base and highest < block_base + BLOCK_BYTES


PANELS = {
    "handset": {"base": 0x00400000, "stride": 4320, "width": 1080, "height": 1920},
    "qemu": {"base": 0xEC7A0000, "stride": 3200, "width": 800, "height": 600},
}
