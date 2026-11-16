#!/usr/bin/env python3
"""Refuse a comment that points at a README section which no longer exists.

The repository bootstrap replaced an 896-line README with a 72-line one. About a dozen comments in
board.toml, configs/, drivers/ and scripts/ still said `see README.md, "The GPU"` and similar, and
nothing noticed: a comment is not compiled and not tested. They now resolve through the section
index at the end of README.md, and this script keeps it that way — a future README rewrite fails
here instead of quietly orphaning every reference.

    python3 scripts/check-doc-references.py
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# `README.md, "The GPU"` and `README.md, blocker 4` are the two shapes in the tree. The comma is
# required: `shutil.copy2(SOURCES / "README.md", output / ...)` is a path argument, not a section.
REFERENCE = re.compile(r'README\.md,\s*(?:"([^"]+)"|(blocker \d+))')
SCANNED = ("board.toml", "feeds.toml", "configs/**/*", "drivers/**/*.cpp", "drivers/**/*.h",
           "scripts/**/*.py", "scripts/**/*.sh", ".github/workflows/*.yml")


def fail(message: str):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="repository to scan (default: this script's repository)")
    args = parser.parse_args()
    root = args.root.resolve()

    readme = root / "README.md"
    if not readme.is_file():
        fail(f"{readme} is missing")
    text = readme.read_text()

    findings, seen, files = [], set(), 0
    for pattern in SCANNED:
        for path in sorted(root.glob(pattern)):
            if not path.is_file() or "check-doc-references.py" in path.name:
                continue
            files += 1
            for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                for match in REFERENCE.finditer(line):
                    name = match.group(1) or match.group(2)
                    seen.add(name)
                    if name not in text:
                        findings.append(f"{path.relative_to(root)}:{number}: README.md has no "
                                        f"section called {name!r}")
    if findings:
        for finding in findings:
            print(f"error: {finding}", file=sys.stderr)
        print("error: add the section to README.md (or its index) or repoint the comment",
              file=sys.stderr)
        return 1
    print(f"doc references ok: {files} files, {len(seen)} referenced README sections all present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
