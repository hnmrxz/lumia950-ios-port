#!/usr/bin/env python3
"""Give a built-in XNU driver a personality, by adding it to iokit/KernelConfigTables.cpp.

Why this file and not the driver's Info.plist: the official driver documentation says built-in XNU drivers
are matched through "built-in personalities in `iokit/KernelConfigTables.cpp`", while a personality in a
bundle's `Info.plist` only applies to a kext the loader stages at run time
(https://unixnu.com/zh/drivers/overview). This port ships four Info.plist files under drivers/ and a build
that never reads any of them, which is why `drivers/NativeSdhci` could exist in the image and never be
probed.

The table is one IOKit matching dictionary string; the framework adds its own entries through
`KernelConfigTables.cpo_CFLAGS_ADD=-DXNU_NATIVE_*` defines, and this adds a board entry the same way it
injects every other edit: a small, idempotent, re-checkable patch.

ORDERING MATTERS: the framework's own xnu patch series edits this same file (run 45774728401:
'error: patch failed: iokit/KernelConfigTables.cpp:56; patch does not apply' when this ran before the build).
So this must run after the series has been applied -- through a `zzz-` late patch in the fetched tree, or as a
post-patch step -- and NOT in the pre-build gate. The script is kept, and its tests, so the mechanism is ready
when that step exists.

The entry matches by provider class only. `NativeSdhci::mapWindows` already refuses a provider without two
`reg` windows of the right sizes and logs why, so a platform device that is not the SDHCI node costs one
probe and one log line rather than a bad mapping. String-valued keys would need escaping inside the C
string, and the escaping is not worth a build round when the driver can say no by itself.

    python ci/kernel-personality.py --root "$UNIXNU_OUT" --apply
    python ci/kernel-personality.py --root "$UNIXNU_OUT" --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MARKER = "NativeSdhci personality"

ANCHOR = '    ")";\n'

BLOCK = (
    '    "   {\\n"\n'
    '    "     \'IOClass\'         = NativeSdhci;\\n"\n'
    '    "     \'IOProviderClass\' = IOPlatformDevice;\\n"\n'
    '    "     \'IOProbeScore\'    = 60000:32;\\n"\n'
    '    "   }"\n'
)


def candidates(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("KernelConfigTables.cpp")):
            if path.parent.name == "iokit":
                found.append(path)
    return found


def comment_block(subject: str) -> str:
    return (
        "    /* " + subject + ": this board's eMMC controller. Matching is by provider class; the\n"
        "     * driver refuses a provider without the two reg windows, so a stranger costs one probe. */\n"
    )


def apply_to(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        return True, "already carries the personality"
    if ANCHOR not in text:
        return False, "skipped: this copy of the table does not end the way the pinned source does"

    head, _, tail = text.rpartition(ANCHOR)
    patched = head + comment_block(MARKER) + BLOCK + ANCHOR + tail
    path.write_text(patched, encoding="utf-8")
    return True, "patched"


def check(path: Path) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER not in text:
        if ANCHOR not in text:
            return False, "skipped: this copy of the table does not end the way the pinned source does"
        return False, "missing the personality"
    if "'IOClass'         = NativeSdhci;" not in text:
        return False, "the NativeSdhci entry is not in the table"
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
        print(f"error: no iokit/KernelConfigTables.cpp under {', '.join(str(r) for r in roots)}", file=sys.stderr)
        return 2

    # The fetched source exists in more than one tree (a pristine feed and the prepared work tree). Only the
    # trees whose table has the expected shape are edited; a tree without it is reported and skipped, and the
    # run fails only when nothing could be patched at all.
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
        print("error: no iokit/KernelConfigTables.cpp in this tree could be patched", file=sys.stderr)
        return 1
    print(f"ok: {patched} table(s) patched, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
