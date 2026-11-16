#!/usr/bin/env python3
"""Refuse a workflow action pinned to a tag or a branch.

`build.yml` ran `actions/checkout@v4` and three neighbours. A tag is a mutable pointer: whoever
owns the action repository can move it, and the next run executes different code with this
repository's `GITHUB_TOKEN` in its environment. Pinning the commit makes the move a visible commit
in this repository instead. `.github/dependabot.yml` keeps the pins current.

    python3 scripts/check-action-pins.py
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

USES = re.compile(r"^\s*(?:- )?uses:\s*(\S+)(?:\s+#.*)?\s*$")
SHA = re.compile(r"[0-9a-f]{40}")


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

    workflows = sorted((root / ".github/workflows").glob("*.yml"))
    if not workflows:
        fail(f"no workflows under {root / '.github/workflows'}")

    findings, pinned = [], 0
    for path in workflows:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            match = USES.match(line)
            if not match:
                continue
            target = match.group(1)
            if target.startswith(("./", "docker://")):
                continue
            reference = target.rsplit("@", 1)
            if len(reference) != 2 or not SHA.fullmatch(reference[1]):
                findings.append(f"{path.relative_to(root)}:{number}: {target} is not pinned to a "
                                f"commit; a tag or branch can move under the run")
            else:
                pinned += 1
    if findings:
        for finding in findings:
            print(f"error: {finding}", file=sys.stderr)
        print("error: pin to the commit the tag points at (git ls-remote --tags) and keep the tag "
              "in a trailing comment", file=sys.stderr)
        return 1
    print(f"action pins ok: {pinned} references pinned to a commit across {len(workflows)} workflows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
