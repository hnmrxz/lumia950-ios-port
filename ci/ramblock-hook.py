#!/usr/bin/env python3
"""Call the root-media publish hook from bsd_init, so the synthetic device actually starts.

Source-linked drivers in this port have no kext bundle, so their Info.plist personalities are never
consulted and nothing matches them; `board.toml` says the same about NativeLegacyDisplay, which upstream
calls from `bsd_init.c`. This edits the fetched XNU tree the same way and re-checks the edit, so the call
is a fact in the source rather than an assumption:

    python ci/ramblock-hook.py --root "$UNIXNU_OUT" --apply
    python ci/ramblock-hook.py --root "$UNIXNU_OUT" --check

The inserted call is a no-op unless the driver publishes, and the driver logs whether it did.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DECLARATION = "extern int native_ramblock_publish(void);"
CALL = "\n\t/* Bring-up: publish the synthetic root media before the boot waits for a root device. */\n\tnative_ramblock_publish();\n"
MARKER = "native_ramblock_publish"


def candidates(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(sorted(root.rglob("bsd_init.c")))
    return found


def function_body(text: str) -> tuple[int, int] | None:
    match = re.search(r"\nbsd_init\s*\(\s*void\s*\)\s*\n\{", text)
    if not match:
        match = re.search(r"\nvoid\s*\nbsd_init\s*\(\s*void\s*\)\s*\n\{", text)
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
    return (start, index)


def apply_to(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        return True, "already carries the call"

    span = function_body(text)
    if span is None:
        return False, "bsd_init(void) not found; refusing to guess"
    start, _ = span

    text = text[:start] + CALL + text[start:]
    if DECLARATION not in text:
        # bsd_init.c has includes at the top; put the declaration after them.
        includes = list(re.finditer(r"^#include .*$", text, re.MULTILINE))
        if not includes:
            return False, "no #include found; refusing to edit"
        last = includes[-1]
        text = text[:last.end()] + "\n\n" + DECLARATION + text[last.end():]

    path.write_text(text, encoding="utf-8")
    return True, "patched"


def check(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER not in text:
        return False, "missing the publish call"
    if DECLARATION not in text:
        return False, "missing the declaration"
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", action="append", default=[], type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    roots = args.root or [Path.cwd()]
    found = candidates(roots)
    if not found:
        print(f"error: no bsd_init.c under {', '.join(str(root) for root in roots)}", file=sys.stderr)
        return 2

    failures = 0
    for path in found:
        ok, message = apply_to(path) if args.apply else check(path)
        print(f"{'ok  ' if ok else 'FAIL'} {path}: {message}")
        if not ok:
            failures += 1
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
