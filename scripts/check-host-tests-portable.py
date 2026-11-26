#!/usr/bin/env python3
"""Fail when a host test assumes Windows-only path semantics.

The `validate` job runs on Linux while the developer machine is Windows. A test that does
`Path(r"C:\\Program Files\\...").is_absolute()` passes locally and fails in CI, because on POSIX that
string is a single relative component. This checker reads every test file and requires that a Windows
absolute path is only ever inspected through `PureWindowsPath`, which is platform independent.

    python scripts/check-host-tests-portable.py
    python scripts/check-host-tests-portable.py --root . --verbose
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

WINDOWS_ABSOLUTE = re.compile(r'(?<![A-Za-z])(?:Path|open|tmp_path)\s*\(\s*[rb]?f?["\']([A-Za-z]:[\\/][^"\']*)["\']')
WINDOWS_LITERAL = re.compile(r'[rb]?f?["\'][A-Za-z]:\\\\?[^"\']*["\']')


# This checker's own test embeds Windows paths on purpose, to prove the detection works.
EXEMPT = {"test-check-host-tests-portable.py"}


def test_files(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        for pattern in ("scripts/test-*.py", "ci/test-*.py", "scripts/**/test-*.py"):
            found.extend(sorted(root.glob(pattern)))
    return sorted(path for path in set(found) if path.name not in EXEMPT)


def check(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    problems: list[str] = []
    has_pure_windows = "PureWindowsPath" in text
    for match in WINDOWS_ABSOLUTE.finditer(text):
        line = text[:match.start()].count("\n") + 1
        problems.append(f"line {line}: Path/open on a Windows absolute path; wrap it in PureWindowsPath")
    if not has_pure_windows:
        for match in WINDOWS_LITERAL.finditer(text):
            line = text[:match.start()].count("\n") + 1
            problems.append(f"line {line}: Windows absolute literal without PureWindowsPath in the file")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", action="append", type=Path, default=[])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    roots = args.root or [Path(__file__).resolve().parent.parent]
    files = test_files(roots)
    if not files:
        print("error: no test files found", file=sys.stderr)
        return 2

    failures = 0
    for path in files:
        problems = check(path)
        if problems:
            failures += 1
            print(f"FAIL {path.relative_to(roots[0]) if path.is_relative_to(roots[0]) else path}")
            for problem in problems:
                print(f"     {problem}")
        elif args.verbose:
            print(f"ok   {path.name}")
    print(f"{len(files)} test files, {failures} with Windows-only assumptions")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
