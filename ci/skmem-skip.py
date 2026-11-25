#!/usr/bin/env python3
"""Make the skmem sysctl publication skippable by boot argument, in the fetched XNU tree.

Why: the emulated boot stops at `_skmem_sysctl_init+0x18` storing through `sysctls->version`, where the
object comes from the static `sk_sys_obj` and the address it points at has no mapping in this port's
layout. Nothing in `skywalk_init()` gates this publication: of the 38 `sk_*` boot arguments none touch
it, which is why the fault survives three ADTs and three argument sets
(docs/emulation/2026-11-24-skmem-sysctl-fault.md).

The change is deliberately small and gated by `skmem_sysctl_skip=1`, so the default build is untouched:

    #include <pexpert/pexpert.h>          (added once, at the top)
    if (skmem_sysctl_skip_requested()) { return; }   (first statement of skmem_sysctl_init)

`skmem_sysctl_skip_requested` parses the argument on each call rather than using a constructor: a
constructor in this file would run at a point this port has not validated, and the call itself is a
one-time initialiser.

    python ci/skmem-skip.py --find            # print the trees where the file exists
    python ci/skmem-skip.py --apply           # edit every tree found
    python ci/skmem-skip.py --check           # exit 1 unless every tree carries the change
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HEADER = "#include <pexpert/pexpert.h>"
HELPER = """
/*
 * Bring-up: publishing the skmem counters is the first thing in this file that writes through a pointer
 * derived from the static sk_sys_obj, and on this port that address is not mapped yet. Gated so a normal
 * build keeps the original behaviour; see docs/emulation/2026-11-24-skmem-sysctl-skip-proposal.md.
 */
static int
skmem_sysctl_skip_requested(void)
{
	int skip = 0;

	if (PE_parse_boot_argn("skmem_sysctl_skip", &skip, sizeof(skip))) {
		return skip != 0;
	}
	return 0;
}
"""

GUARD = "\tif (skmem_sysctl_skip_requested()) {\n\t\treturn;\n\t}\n"
MARKER = "skmem_sysctl_skip_requested"


def candidates(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(sorted(root.rglob("skmem_sysctl.c")))
    return found


def function_span(text: str) -> tuple[int, int] | None:
    match = re.search(r"\nvoid\s*\nskmem_sysctl_init\s*\(\s*void\s*\)\s*\n\{", text)
    if not match:
        match = re.search(r"\nskmem_sysctl_init\s*\(\s*void\s*\)\s*\n\{", text)
    if not match:
        return None
    start = match.end()
    depth = 1
    index = start
    while index < len(text) and depth:
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
        index += 1
    return (match.start(), index)


def apply_to(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        return True, "already carries the change"

    span = function_span(text)
    if span is None:
        return False, "skmem_sysctl_init(void) not found; refusing to guess"
    start, _ = span

    body_open = text.index("{", start) + 1
    patched = text[:body_open] + "\n" + GUARD + text[body_open:]

    if HEADER not in patched:
        # put the include after the last #include at the top, so ordering rules stay intact
        includes = list(re.finditer(r"^#include .*$", patched, re.MULTILINE))
        if not includes:
            return False, "no #include found; refusing to edit"
        last = includes[-1]
        patched = patched[:last.end()] + "\n" + HEADER + patched[last.end():]

    # Insert the helper before the whole declaration, not at the function name: this file declares the
    # function as `__private_extern__ void` on the line above, and splitting that pair is a hard error
    # ("cannot combine with previous '__private_extern__' declaration specifier").
    name_index = patched.index("skmem_sysctl_init(")
    line_start = patched.rfind("\n", 0, name_index) + 1
    previous_start = patched.rfind("\n", 0, max(line_start - 1, 0)) + 1
    previous_line = patched[previous_start:line_start]
    insert_at = line_start
    if previous_line.strip() and not previous_line.rstrip().endswith((";", "}", ")")):
        insert_at = previous_start
    patched = patched[:insert_at] + HELPER.strip("\n") + "\n\n" + patched[insert_at:]

    path.write_text(patched, encoding="utf-8")
    return True, "patched"


def check(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER not in text:
        return False, "missing the boot-argument guard"
    if HEADER not in text:
        return False, "missing the pexpert include"
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", action="append", default=[], type=Path,
                        help="tree to search; repeatable. Defaults to $UNIXNU_OUT and the workspace")
    parser.add_argument("--find", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    roots = args.root or [Path(p) for p in (Path.cwd(),)]
    found = candidates(roots)
    if not found:
        print(f"error: no skmem_sysctl.c under {', '.join(str(root) for root in roots)}", file=sys.stderr)
        return 2

    failures = 0
    for path in found:
        if args.find:
            print(path)
            continue
        if args.apply:
            ok, message = apply_to(path)
        else:
            ok, message = check(path)
        print(f"{'ok  ' if ok else 'FAIL'} {path}: {message}")
        if not ok:
            failures += 1
    if not (args.find or args.apply or args.check):
        print("nothing to do: pass --find, --apply or --check", file=sys.stderr)
        return 2
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
