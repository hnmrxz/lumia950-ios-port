#!/usr/bin/env python3
"""Drive WPinternals from this checkout instead of clicking through its window.

The tool exposes a command line (WPinternals/CommandLine.cs upstream). This wrapper only forwards the
switches that this port needs, refuses to run anything destructive without `--apply`, and prints the
exact command so a failure can be reproduced by hand.

    python scripts/phone-modes.py info
    python scripts/phone-modes.py mass-storage --apply
    python scripts/phone-modes.py uefi-dump --out out/uefi
    python scripts/phone-modes.py unlock --apply

Nothing here flashes, unlocks or rewrites a partition on its own: `--apply` is required for every switch
that changes the phone, and `info` is read-only.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_TOOL = Path(r"C:\Users\Administrator\Downloads\win-x64\WPinternals.exe")

# switch -> (does it change the phone, one-line description)
MODES = {
    "info": ("ShowPhoneInfo", False, "read the phone's identity and current mode"),
    "mass-storage": ("SwitchToMassStorageMode", True, "switch the phone to mass storage mode"),
    "unlock": ("UnlockBootloader", True, "unlock the bootloader (the shim route needs this)"),
    "root": ("EnableRootAccess", True, "enable root access"),
    "fix-boot": ("FixBootAfterUnlockingBootloader", True, "repair boot after an unlock"),
}


def find_tool(explicit: Path | None) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise SystemExit(f"error: {explicit} is not a file")
        return explicit
    if DEFAULT_TOOL.is_file():
        return DEFAULT_TOOL
    on_path = shutil.which("WPinternals.exe") or shutil.which("WPinternals")
    if on_path:
        return Path(on_path)
    raise SystemExit(
        "error: WPinternals.exe not found -- pass --tool, or put it on PATH "
        f"(looked at {DEFAULT_TOOL})")


def run(tool: Path, switch: str, extra: list[str], apply: bool, changes: bool) -> int:
    command = [str(tool), "-" + switch, *extra]
    print("$ " + " ".join(command))
    if changes and not apply:
        print("dry run: pass --apply to run it (this switch changes the phone)")
        return 0
    return subprocess.call(command)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=sorted(MODES), help="what to ask the tool to do")
    parser.add_argument("--tool", type=Path, default=None, help=f"WPinternals.exe (default {DEFAULT_TOOL})")
    parser.add_argument("--apply", action="store_true", help="actually change the phone")
    parser.add_argument("--out", type=Path, default=None, help="output directory for dumps")
    args = parser.parse_args(argv)

    tool = find_tool(args.tool)
    switch, changes, description = MODES[args.mode]
    print(f"{args.mode}: {description}")
    extra: list[str] = []
    if args.mode == "uefi-dump":
        if args.out is None:
            raise SystemExit("error: uefi-dump needs --out")
        args.out.mkdir(parents=True, exist_ok=True)
        extra = [str(args.out.resolve())]
    return run(tool, switch, extra, args.apply, changes)


if __name__ == "__main__":
    sys.exit(main())
