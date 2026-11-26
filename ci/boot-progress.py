#!/usr/bin/env python3
"""Call the boot-progress instrument from the earliest kernel stages.

Upstream does this with patches/xnu/zzz-boot-progress.patch, gated behind an audited storage closure this board
cannot satisfy. This inserts the equivalent calls for the Lumia 950:

  * after `PE_init_platform(FALSE, args);` in `osfmk/arm/arm_init.c` -- before `arm_vm_init` turns the MMU on,
    so the framebuffer physical address is still identity-mapped;
  * immediately before `arm_vm_init(xmaxmem, args);`
  * (nothing after it: `arm_vm_init` turns the MMU on, and a store to the framebuffer physical address without
    a mapping raises a synchronous exception -- measured in run 45764900801, which stopped at
    `_sleh_synchronous_sp1` before VM setup when a third call was placed after the call).

One bar per stage reaches the panel, so the number of bars is how far the kernel got. `--apply` is idempotent
and `--check` re-reads the edit, the same contract the other ci/ patches use.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MARKER = "native_boot_progress_stage"

# The panel parameters come from boot_args.Video, measured in pexpert/pexpert/arm/boot.h of the pinned
# source: `unsigned long v_baseAddr, v_rowBytes, v_height`. Hard-coding them drew into unmapped space
# in QEMU (run 45764900801, synchronous exception before VM setup).
DECLARATION = ("\textern void native_boot_progress_stage(unsigned long base, unsigned long stride, "
               "unsigned long height, int stage);\n")

# The real line carries a trailing comment; measured in the pinned xnu-8796.141.3 source.
AFTER_PLATFORM = "\tPE_init_platform(FALSE, args); /* Get platform expert set up */\n"
BEFORE_VM_INIT = "\tarm_vm_init(xmaxmem, args);\n"

STAGE_1 = (
    "\n\t/* Bring-up instrument: one bar per stage reaches the panel before the MMU is on. */\n"
    + DECLARATION
    + "\tnative_boot_progress_stage(args->Video.v_baseAddr, args->Video.v_rowBytes, "
    + "args->Video.v_height, 0);\n"
)
STAGE_2 = ("\tnative_boot_progress_stage(args->Video.v_baseAddr, args->Video.v_rowBytes, "
           "args->Video.v_height, 1);\n")


def find(root: Path) -> list[Path]:
    found: list[Path] = []
    for candidate in sorted(root.rglob("arm_init.c")):
        if candidate.parent.name == "arm":
            found.append(candidate)
    return found


def apply_to(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        return True, "already carries the calls"
    if AFTER_PLATFORM not in text or BEFORE_VM_INIT not in text:
        return False, "the two anchors are not both present; refusing to guess"

    text = text.replace(AFTER_PLATFORM, AFTER_PLATFORM + STAGE_1, 1)
    text = text.replace(BEFORE_VM_INIT, STAGE_2 + BEFORE_VM_INIT, 1)
    path.write_text(text, encoding="utf-8")
    return True, "patched"


def check(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    missing = [str(stage) for stage in (0, 1) if f"args->Video.v_height, {stage})" not in text]
    if missing:
        return False, f"missing stage calls: {', '.join(missing)}"
    if "extern void native_boot_progress_stage(int);" not in text:
        return False, "missing the declaration"
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", action="append", default=[], type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    roots = args.root or [Path.cwd()]
    files = find(roots[0])
    if not files:
        print(f"error: no osfmk/arm/arm_init.c under {roots[0]}", file=sys.stderr)
        return 2

    failures = 0
    for path in files:
        ok, message = apply_to(path) if args.apply else check(path)
        print(f"{'ok  ' if ok else 'FAIL'} {path}: {message}")
        if not ok:
            failures += 1
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
