#!/usr/bin/env python3
"""Check a Windows Phone BCD layout against the one the reference WOA image uses.

The store on this handset has no display order; what actually starts is `{bootmgr} default`, and the
reference image points that at `\\windows\\system32\\boot\\bootshim.efi` on MainOS (see
docs/hardware/2026-11-25-woa-ffu-reference.md). Getting this wrong is what produced the reset loop
earlier, so the layout is checked rather than eyeballed.

`bcdedit` needs an elevated token, so this reads its output instead of the store:

    bcdedit /store R:\\EFI\\Microsoft\\BOOT\\BCD /enum all > bcd.txt
    python scripts/check-bcd-layout.py --enum-file bcd.txt --expect mainos
    python scripts/check-bcd-layout.py --enum-file bcd.txt --expect windows

Exit code 0 means the entries match the expectation; 1 means at least one check failed and the exact
`bcdedit` commands to fix it are printed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ENTRY = re.compile(r"标识符\s+(\{[^}]+\})|identifier\s+(\{[^}]+\})", re.IGNORECASE)
FIELD = re.compile(r"^\s*(path|device|description|default)\s+(.+?)\s*$", re.IGNORECASE)

# The reference WOA image points {bootmgr} at this; the firmware loads it before any entry.
BOOTMGR_PATH = r"\efi\boot\bootarm.efi"

EXPECTATIONS = {
    "mainos": "\\windows\\system32\\boot\\bootshim.efi",
    "efiesp": "\\efi\\boot\\bootshim.efi",
    "windows": "\\windows\\system32\\boot\\winload.efi",
}


def parse(text: str) -> dict[str, dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}
    current = None
    for line in text.splitlines():
        match = ENTRY.search(line)
        if match:
            current = (match.group(1) or match.group(2)).lower()
            entries.setdefault(current, {})
            continue
        field = FIELD.match(line)
        if field and current:
            entries[current][field.group(1).lower()] = field.group(2).strip()
    return entries


def decode(raw: bytes) -> str:
    """bcdedit writes in the console code page, and cmd redirection can store UTF-16; try both."""
    for encoding in ("utf-8-sig", "utf-16", "gbk", "cp936", "latin-1"):
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        if "\u6807\u8bc6\u7b26" in text or "identifier" in text.lower():
            return text
    return raw.decode("utf-8", errors="replace")


def check(entries: dict[str, dict[str, str]], expect: str) -> list[str]:
    problems: list[str] = []
    manager = entries.get("{bootmgr}")
    if not manager:
        problems.append("no {bootmgr} entry: this is not the store the firmware reads")
        return problems

    manager_path = manager.get("path", "").strip("\\").lower()
    if manager_path != BOOTMGR_PATH.strip("\\").lower():
        problems.append(
            f"{{bootmgr}} path is '{manager.get('path', '(none)')}', expected '{BOOTMGR_PATH}': "
            "that is the file the firmware loads first")

    target = manager.get("default", "").lower()
    if not target:
        problems.append("{bootmgr} has no default; nothing would start")
        return problems

    entry = entries.get(target)
    if not entry:
        problems.append(f"{target} is named as the default but has no entry")
        return problems

    wanted = EXPECTATIONS[expect]
    path = entry.get("path", "").strip("\\").lower()
    wanted_path = wanted.strip("\\").lower()
    if path != wanted_path:
        problems.append(f"{target} path is '{entry.get('path', '(none)')}', expected '{wanted}'")

    if expect == "mainos":
        device = entry.get("device", "").lower()
        if device and not (device.startswith("partition=f:") or device == "unknown"):
            problems.append(f"{target} device is '{entry.get('device')}', expected partition=F: or unknown")

    description = entry.get("description", "")
    if expect == "mainos" and description and "bootshim" not in description.lower():
        problems.append(f"{target} description is '{description}', expected something naming BootShim")
    return problems


def fixes(target: str, expect: str) -> list[str]:
    wanted = EXPECTATIONS[expect]
    lines = [f"bcdedit /store <EFIESP>:\\EFI\\Microsoft\\BOOT\\BCD /set {target} path {wanted}"]
    if expect == "mainos":
        lines.append(f"bcdedit /store <EFIESP>:\\EFI\\Microsoft\\BOOT\\BCD /set {target} device partition=<MainOS>:")
        lines.append(f'bcdedit /store <EFIESP>:\\EFI\\Microsoft\\BOOT\\BCD /set {target} description "BootShim Application"')
    else:
        lines.append(f"bcdedit /store <EFIESP>:\\EFI\\Microsoft\\BOOT\\BCD /set {target} device partition=<EFIESP>:")
    lines.append("bcdedit /store <EFIESP>:\\EFI\\Microsoft\\BOOT\\BCD /enum {default}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--enum-file", type=Path, required=True,
                        help="output of: bcdedit /store <store> /enum all")
    parser.add_argument("--expect", choices=sorted(EXPECTATIONS), default="mainos")
    args = parser.parse_args(argv)

    if not args.enum_file.is_file():
        print(f"error: {args.enum_file} is missing", file=sys.stderr)
        return 2

    text = decode(args.enum_file.read_bytes())
    entries = parse(text)
    if not entries:
        print("error: no entries parsed; is this bcdedit output?", file=sys.stderr)
        return 2

    problems = check(entries, args.expect)
    manager = entries.get("{bootmgr}", {})
    target = manager.get("default", "{default}")
    print(f"entries: {len(entries)}   default: {target}   expectation: {args.expect}")
    if not problems:
        print("layout ok: the store starts " + EXPECTATIONS[args.expect])
        return 0

    for problem in problems:
        print(f"problem: {problem}")
    print()
    print("fix with these, elevated:")
    for line in fixes(target, args.expect):
        print("  " + line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
