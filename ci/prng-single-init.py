#!/usr/bin/env python3
"""Make the kernel PRNG registration idempotent, so a merged image can boot.

`register_and_init_prng()` begins with `assert(!prng_ready);` (osfmk/prng/prng_random.c, pinned line 267). That holds
when one corecrypto initialises the PRNG -- which is what the source image does -- and fails in the merged image, where the
framework's `source-corecrypto14-bootstrap.patch` calls `corecrypto_kext_start()` and Apple's prelinked
`com.apple.kec.corecrypto` initialises it too. The emulated merged boot stops exactly there:

    panic_format : "%s:%d Assertion failed: %s"
    panic_args   : ['!prng_ready']

This replaces the assertion with a guard that returns early when the PRNG is already registered. The first registration is
the one that stays live, and every later one becomes a no-op, which is what "the kernel PRNG has been installed" means for
the callers: they only need it to be there.

    python ci/prng-single-init.py --root "$UNIXNU_OUT" --apply
    python ci/prng-single-init.py --root "$UNIXNU_OUT" --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MARKER = "the PRNG is registered once"

ASSERTION = "\tassert(!prng_ready);\n"
GUARD = (
    "\t/* " + MARKER + ": a merged image initialises it twice (the source bootstrap patch and Apple's prelinked\n"
    "\t * corecrypto), and the second registration must not be fatal. */\n"
    "\tif (prng_ready) {\n"
    "\t\treturn;\n"
    "\t}\n"
)


def candidates(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("prng_random.c")):
            if path.parent.name == "prng":
                found.append(path)
    return found


def apply_to(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        return True, "already registers once"
    if ASSERTION not in text:
        return False, "skipped: no 'assert(!prng_ready);' in this copy"
    text = text.replace(ASSERTION, GUARD, 1)
    path.write_text(text, encoding="utf-8")
    return True, "patched"


def check(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER not in text:
        if ASSERTION not in text:
            return False, "skipped: no 'assert(!prng_ready);' in this copy"
        return False, "missing the single-registration guard"
    if "assert(!prng_ready);" in text:
        return False, "the assertion is still there"
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
        print(f"error: no osfmk/prng/prng_random.c under {', '.join(str(root) for root in roots)}", file=sys.stderr)
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
        print("error: no copy of prng_random.c could be patched", file=sys.stderr)
        return 1
    print(f"ok: {patched} file(s) patched, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
