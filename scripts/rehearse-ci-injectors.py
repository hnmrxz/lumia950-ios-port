#!/usr/bin/env python3
"""Rehearse both ci/ injectors against the real pinned sources, before spending a CI run.

Fetches osfmk/arm/arm_init.c and iokit/KernelConfigTables.cpp at the pinned tag, lays them out the way the
fetched tree is (osfmk/arm, iokit), runs --apply and --check, and prints the inserted lines with context.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REV = "xnu-8796.141.3"
FILES = {
    "osfmk/arm/arm_init.c": "https://api.github.com/repos/apple-oss-distributions/xnu/contents/osfmk/arm/arm_init.c?ref=" + REV,
    "iokit/KernelConfigTables.cpp": "https://api.github.com/repos/apple-oss-distributions/xnu/contents/iokit/KernelConfigTables.cpp?ref=" + REV,
}


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=90) as response:
        payload = json.load(response)
    return base64.b64decode(payload["content"]).decode("utf-8", "replace")


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        tree = Path(temporary)
        for relative, url in FILES.items():
            destination = tree / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(fetch(url), encoding="utf-8")
            print(f"fetched {relative}: {destination.stat().st_size} B")

        steps = [
            ("boot-progress", ["ci/boot-progress.py", "--root", str(tree), "--apply"]),
            ("boot-progress", ["ci/boot-progress.py", "--root", str(tree), "--check"]),
            ("kernel-personality", ["ci/kernel-personality.py", "--root", str(tree), "--apply"]),
            ("kernel-personality", ["ci/kernel-personality.py", "--root", str(tree), "--check"]),
        ]
        failures = 0
        for name, arguments in steps:
            result = subprocess.run([sys.executable, str(ROOT / arguments[0]), *arguments[1:]],
                                    capture_output=True, text=True)
            print(f"--- {name} {' '.join(arguments[1:])} -> exit {result.returncode}")
            print(result.stdout.rstrip())
            if result.stderr.strip():
                print(result.stderr.rstrip())
            if result.returncode != 0:
                failures += 1

        arm = (tree / "osfmk/arm/arm_init.c").read_text(encoding="utf-8")
        print("--- arm_init.c around the inserted calls")
        for marker in ("native_boot_progress_stage(", "arm_vm_init(xmaxmem, args);"):
            index = arm.find(marker)
            start = max(0, arm.rfind("\n", 0, max(0, index - 240)))
            print(arm[start:index + 260].rstrip())
            print("   ...")

        table = (tree / "iokit/KernelConfigTables.cpp").read_text(encoding="utf-8")
        print("--- KernelConfigTables.cpp tail")
        print(table[table.rfind('"("'):].rstrip())

        return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
