#!/usr/bin/env python3
"""Drive Microsoft's thor2 (the emergency/FFU flasher found inside the SJM install).

thor2 is the tool the Chinese flashing utility calls for emergency download (ede/edp) and for FFU
flashing over the emergency transport. This wrapper exposes the two modes this port needs, prints the
exact command, and requires --apply for anything that writes to the phone.

    python scripts/phone-thor2.py devices                 # read-only: does thor2 see the phone?
    python scripts/phone-thor2.py emergency --hex MPRG8992_fh.ede --edp RM1105_fh.edp --apply
    python scripts/phone-thor2.py ffu --file RM1105_....ffu --apply

Paths are resolved by scripts/phone-tools.py; PHONE_TOOL_THOR2 overrides the lookup.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_tools():
    spec = importlib.util.spec_from_file_location("phone_tools", ROOT / "scripts" / "phone-tools.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def thor2(tools, arguments: list[str], apply: bool, writes: bool) -> int:
    path = tools.find("thor2")
    if path is None:
        print("error: thor2 not found; run python scripts/phone-tools.py", file=sys.stderr)
        return 2
    command = [str(path), *arguments]
    print("$ " + " ".join(command))
    if writes and not apply:
        print("dry run: pass --apply to run it (this writes to the phone)")
        return 0
    return subprocess.call(command)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_devices = sub.add_parser("devices", help="read-only: list what thor2 can see")
    p_devices.add_argument("--apply", action="store_true", help="accepted for symmetry; devices is read-only")

    p_emergency = sub.add_parser("emergency", help="emergency download using ede/edp files")
    p_emergency.add_argument("--hex", required=True, type=Path, help="the .ede (hex) file")
    p_emergency.add_argument("--edp", required=True, type=Path, help="the .edp (mbn) file")
    p_emergency.add_argument("--apply", action="store_true")

    p_ffu = sub.add_parser("ffu", help="flash an FFU over the emergency transport")
    p_ffu.add_argument("--file", required=True, type=Path)
    p_ffu.add_argument("--apply", action="store_true")

    args = parser.parse_args(argv)
    tools = load_tools()

    if args.command == "devices":
        return thor2(tools, ["-mode", "list"], apply=True, writes=False)

    if args.command == "emergency":
        for path in (args.hex, args.edp):
            if not path.is_file():
                print(f"error: {path} is missing", file=sys.stderr)
                return 2
        return thor2(tools, ["-mode", "emergency", "-hexfile", str(args.hex), "-edfile", str(args.edp)],
                     apply=args.apply, writes=True)

    if not args.file.is_file():
        print(f"error: {args.file} is missing", file=sys.stderr)
        return 2
    return thor2(tools, ["-mode", "ffureta", "-ffufile", str(args.file)], apply=args.apply, writes=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
