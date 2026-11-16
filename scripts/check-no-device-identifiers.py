#!/usr/bin/env python3
"""Refuse a raw device identifier in the evidence files.

AGENTS.md rule 8 says not to store private device identifiers in git, and the security boundary in
README.md repeats it. The rule had no execution point: an EFI volume UUID was committed in two
evidence files and used as one of the installer's identity factors.

The scan is deliberately narrow. It looks for UUID-shaped values under keys that name a UUID, in
docs/, and nowhere else: a hardware GUID (the GPU SMMU profile's `guid`) is a SoC constant, not a
device identity, and flagging it would train people to ignore this check.

    python3 scripts/check-no-device-identifiers.py
    python3 scripts/check-no-device-identifiers.py --root .
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

UUID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
# A key that names a device's own identifier. `guid` is not in this list on purpose.
DEVICE_KEY = re.compile(r"(volume_uuid|partition_uuid|disk_uuid|serial|imei|unique_chip_id)",
                        re.IGNORECASE)
# Values that are allowed to look like a UUID because they are hashes of one.
REDACTED = re.compile(r"sha256:[0-9a-f]{8,64}")


def fail(message: str):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def walk(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{path}[{index}]")
    else:
        yield path, node


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="repository to scan (default: this script's repository)")
    args = parser.parse_args()
    root = args.root.resolve()

    findings = []
    files = sorted((root / "docs").rglob("*.json"))
    for path in files:
        try:
            document = json.loads(path.read_text())
        except json.JSONDecodeError as error:
            fail(f"{path} is not JSON: {error}")
        for key, value in walk(document):
            if not DEVICE_KEY.search(key.rsplit(".", 1)[-1]):
                continue
            if not isinstance(value, str) or not UUID.fullmatch(value.strip()):
                continue
            if REDACTED.fullmatch(value.strip()):
                continue
            findings.append(f"{path.relative_to(root)}: {key} holds a raw device identifier")
    if findings:
        for finding in findings:
            print(f"error: {finding}", file=sys.stderr)
        print("error: replace it with sha256:<first 16 hex of the uppercase identifier> and keep "
              "an identifier_redaction note beside it", file=sys.stderr)
        return 1
    print(f"device identifiers ok: {len(files)} evidence files, no raw identifier")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
