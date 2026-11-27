#!/usr/bin/env python3
"""Map one block containing the framebuffer from the kernel's own bootstrap page tables.

Measured facts behind this patch (see docs/hardware/m1-observability.md):

  * `vinfo` is all zeros when PE_init_platform() returns, and the console that maps the framebuffer is created by
    PE_create_console() after arm_vm_init -- so no kernel code can write the panel before the VM work;
  * start.s builds the only mapping that exists that early, with the macro
    `create_bootstrap_mapping(vbase, pbase, entries, L1 table, free pointer, scratch x5)`;
  * the block size is ARM_TT_L2_SIZE -- 32 MB on the 16 KB-page kernel -- and the block template is write-back normal memory,
    so the marker has to clean its cache lines (`dc civac`) for the panel to see them.

The patch adds one more call after the two existing ones, mapping the 32 MB block that contains the video physical base (read from the
boot arguments at run time, so it works on the handset where video is at 0x400000 and under QEMU where it is at 0xEC7A0000) at a spare
KVA. It runs on every boot: a single block mapping of unused KVA is the cheapest thing that can be wrong, and gating it would need a
boot-argument parse that does not exist that early.

    python ci/framebuffer-map.py --root "$UNIXNU_OUT" --apply
    python ci/framebuffer-map.py --root "$UNIXNU_OUT" --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MARKER = "LUMIA_EARLY_MAP"
MAP_BASE = 0xFFFFFFF0E0000000
ANCHOR = "\t/* Ensure TTEs are visible */\n\tdsb\t\tish\n"


def patch_text() -> str:
    """The call, in the register discipline of the two existing ones.

    On entry: x1 = V=P L1 page, x3 = KVA L1 page, x2 = free pointer (already advanced by the earlier calls), x20 = PA of boot args.
    The macro takes (vbase, pbase, entries, L1 table, freeptr, scratch x5) = ($0, $1, $2, $3, $4, $5..$9), so the free pointer has
    to move out of x2 before x2 carries the entry count.
    """
    words = [
        "",
        f"\t/* {MARKER}: one block that contains the framebuffer, so early code can report progress on the panel. */",
        "\tldr\tx0, [x20, #24]\t\t\t// boot_args.Video.v_baseAddr (physical)",
        "\tmov\tx9, #(ARM_TT_L2_SIZE)",
        "\tsub\tx9, x9, #1",
        "\tbic\tx1, x0, x9\t\t\t// block-align the physical base",
        "\tmov\tx0, #(0x%04x)\t\t\t// 0x%016x & 0xffff" % (MAP_BASE & 0xFFFF, MAP_BASE),
        "\tmovk\tx0, #(0x%04x), lsl #16\t// bits 16..31" % ((MAP_BASE >> 16) & 0xFFFF),
        "\tmovk\tx0, #(0x%04x), lsl #32\t// bits 32..47" % ((MAP_BASE >> 32) & 0xFFFF),
        "\tmovk\tx0, #(0x%04x), lsl #48\t// bits 48..63" % ((MAP_BASE >> 48) & 0xFFFF),
        "\tmov\tx4, x2\t\t\t// free page pointer",
        "\tmov\tx2, #1\t\t\t\t// one block",
        "\tcreate_bootstrap_mapping x0, x1, x2, x3, x4, x5, x6, x7, x8, x9",
        "",
    ]
    return "\n".join(words)


def candidates(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(sorted(path for path in root.rglob("start.s") if path.parent.name == "arm64"))
    return found


def apply_to(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        return True, "already maps the framebuffer"
    anchor = ANCHOR
    if anchor not in text:
        # tolerate a copy whose mnemonic spacing differs: locate the comment and insert before the following dsb
        comment = "\t/* Ensure TTEs are visible */"
        at = text.find(comment)
        if at < 0:
            return False, "skipped: no 'Ensure TTEs are visible' anchor in this copy"
        anchor = text[at:text.find("\n", at) + 1]
        return False, f"skipped: anchor found at 0x{at:x} but the expected spacing differs"
    text = text.replace(ANCHOR, patch_text() + ANCHOR, 1)
    path.write_text(text, encoding="utf-8")
    return True, "patched"


def check(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER not in text:
        return False, "does not map the framebuffer"
    if "create_bootstrap_mapping x0, x1, x2, x3, x4" not in text:
        return False, "the marker is present but the call is not"
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", action="append", default=[], type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    roots = args.root or [Path.cwd()]
    files = candidates(roots)
    if not files:
        print(f"error: no osfmk/arm64/start.s under {', '.join(str(root) for root in roots)}", file=sys.stderr)
        return 2

    patched = 0
    skipped = 0
    for path in files:
        ok, message = apply_to(path) if args.apply else check(path)
        if ok:
            print(f"ok   {path}: {message}")
            patched += 1
        elif message.startswith("skipped"):
            print(f"skip {path}: {message}")
            skipped += 1
        else:
            print(f"FAIL {path}: {message}")
    if patched == 0:
        print("error: no copy of start.s could be patched", file=sys.stderr)
        return 1
    print(f"ok: {patched} file(s) patched, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
