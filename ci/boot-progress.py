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
import re
import sys
from pathlib import Path

MARKER = "native_boot_progress_stage"

# The panel parameters come from boot_args.Video, measured in pexpert/pexpert/arm/boot.h of the pinned
# source: `unsigned long v_baseAddr, v_rowBytes, v_height`. Hard-coding them drew into unmapped space
# in QEMU (run 45764900801, synchronous exception before VM setup).
DECLARATION = ("\textern void native_boot_progress_stage(void *base, unsigned long stride, "
               "unsigned long height, const char *command_line, int stage);\n")

BEFORE_VM_INIT = "\tarm_vm_init(xmaxmem, args);\n"
PLATFORM_CALL = "\tPE_init_platform(FALSE, args); /* Get platform expert set up */\n"
# The third stage runs after the platform expert has installed the video console, so pexpert has mapped the
# framebuffer and translated its address: this is the first draw that does not depend on the bootstrap map.
BSD_ANCHOR = "\tthrottle_init();\n"
BSD_DECLARATION = ("\textern void native_boot_progress_stage(void *base, unsigned long stride, "
                   "unsigned long height, const char *command_line, int stage);\n")
BSD_STAGE = ("\n\t/* Bring-up instrument: third bar, drawn once the panel has a mapping. */\n"
             + BSD_DECLARATION
             + "\tnative_boot_progress_stage((void *)PE_state.video.v_baseAddr, PE_state.video.v_rowBytes, "
             + "\t                           PE_state.video.v_height, PE_boot_args()->CommandLine, 2);\n")


STAGE_0 = (
    "\n\t/* Bring-up instrument: one bar per stage reaches the panel before the MMU is on. */\n"
    + DECLARATION
    + "\tnative_boot_progress_stage((void *)args->Video.v_baseAddr, args->Video.v_rowBytes, "
    + "args->Video.v_height, args->CommandLine, 0);\n"
)
STAGE_2 = ("\tnative_boot_progress_stage((void *)args->Video.v_baseAddr, args->Video.v_rowBytes, "
           "args->Video.v_height, args->CommandLine, 1);\n")


def find(root: Path) -> list[Path]:
    found: list[Path] = []
    for candidate in sorted(root.rglob("arm_init.c")):
        if candidate.parent.name == "arm":
            found.append(candidate)
    return found


def find_bsd_init(root: Path) -> list[Path]:
    found: list[Path] = []
    for candidate in sorted(root.rglob("bsd_init.c")):
        if candidate.parent.name == "kern" and candidate.parent.parent.name == "bsd":
            found.append(candidate)
    return found


def arm_init_body(text: str):
    """The index just past the opening brace of the arm_init definition, or None.

    The pinned source writes it as the name on one line and the parameter on the next:

        arm_init(
            boot_args       *args)
        {
    """
    match = re.search(r"\narm_init\s*\([^)]*\)\s*\n?\{", text)
    if not match:
        return None
    return match.end()


def apply_to(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        return True, "already carries the calls"
    if BEFORE_VM_INIT not in text:
        return False, "skipped: no arm_vm_init call in this copy"

    if PLATFORM_CALL not in text:
        return False, "skipped: no PE_init_platform(FALSE, args) call in this copy"

    # Stage 0 goes immediately before the first statement of arm_init, not at the top of the body: the body
    # opens with declarations (`unsigned int maxmem;` ...), and a statement above them would make every later
    # declaration a declaration-after-statement.
    text = text.replace(PLATFORM_CALL, STAGE_0 + PLATFORM_CALL, 1)
    text = text.replace(BEFORE_VM_INIT, STAGE_2 + BEFORE_VM_INIT, 1)
    path.write_text(text, encoding="utf-8")
    return True, "patched"


def apply_bsd(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        return True, "already carries the third stage"
    if BSD_ANCHOR not in text:
        return False, "skipped: no throttle_init() in this copy of bsd_init.c"
    text = text.replace(BSD_ANCHOR, BSD_STAGE + BSD_ANCHOR, 1)
    path.write_text(text, encoding="utf-8")
    return True, "patched"


def check_bsd(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if "PE_boot_args()->CommandLine, 2)" not in text:
        if BSD_ANCHOR not in text:
            return False, "skipped: no throttle_init() in this copy of bsd_init.c"
        return False, "missing the third stage"
    return True, "ok"


def check(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    missing = [str(stage) for stage in (0, 1) if f"args->CommandLine, {stage})" not in text]
    if missing:
        return False, f"missing stage calls: {', '.join(missing)}"
    body = arm_init_body(text)
    if body is not None and text.find("args->CommandLine, 0)") < body:
        return False, "stage 0 is above arm_init instead of inside it"
    platform = text.find("PE_init_platform(FALSE, args);")
    if platform >= 0 and text.find("args->CommandLine, 0)") > platform:
        return False, "stage 0 landed after the platform call"
    if "extern void native_boot_progress_stage(" not in text:
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
    bsd_files = find_bsd_init(roots[0])

    patched = 0
    skipped = 0
    for path in files + bsd_files:
        if path.name == "bsd_init.c":
            ok, message = apply_bsd(path) if args.apply else check_bsd(path)
        else:
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
        print("error: no osfmk/arm/arm_init.c in this tree could be patched", file=sys.stderr)
        return 1
    print(f"ok: {patched} tree(s) patched, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
