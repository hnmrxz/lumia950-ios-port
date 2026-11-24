#!/usr/bin/env python3
"""Insert the skmem sysctl bypass into the xnu work tree the build actually compiles.

docs/emulation/2026-11-24-skmem-sysctl-skip-proposal.md explains why the function is skipped and what
that costs. The tree is `.cache/xnu-work` under the framework's build root; it is cloned and prepared
inside `unixnu build`, so an edit to the fetched feed source does not reach it (run 45325093667 showed
the symbol absent from the image while the boot argument was present).

Usage: ci/skmem-skip.py <xnu work tree>
"""

from __future__ import annotations

import pathlib
import sys

GUARD = (
    "#include <pexpert/pexpert.h>\n"
    "static int skmem_sysctl_skip = 0;\n"
    "static void __attribute__((constructor)) skmem_sysctl_skip_bootarg(void)\n"
    "{\n"
    "\t(void)PE_parse_boot_argn(\"skmem_sysctl_skip\", &skmem_sysctl_skip,\n"
    "\t    sizeof(skmem_sysctl_skip));\n"
    "}\n"
)

HEAD = "skmem_sysctl_init(void)\n{\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: skmem-skip.py <xnu work tree>", file=sys.stderr)
        return 2
    target = pathlib.Path(argv[1]) / "bsd" / "net" / "skmem_sysctl.c"
    if not target.is_file():
        print(f"error: {target} is missing", file=sys.stderr)
        return 2
    text = target.read_text()
    if "skmem_sysctl_skip" in text:
        print(f"already patched: {target}")
        return 0
    if HEAD not in text:
        print(f"error: {HEAD.splitlines()[0]!r} not found in {target}", file=sys.stderr)
        return 2
    target.write_text(text.replace(HEAD, GUARD + HEAD + "\tif (skmem_sysctl_skip) { return; }\n", 1))
    print(f"skmem bypass inserted into {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
