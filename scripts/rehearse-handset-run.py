#!/usr/bin/env python3
"""Rehearse the handset run book against a copy of the staged chain.

The deployment script and the boot arguments have only been tested against temporary volumes built by the unit tests. This runs the whole
procedure -- dry run, apply, token append, backup, runbook -- against a copy of the staged UniXNU tree, which is the same file layout the phone
has. Nothing here touches the phone: the copy is in out/, and the test asserts every artefact the real run would produce.

    python scripts/rehearse-handset-run.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
STAGED = ROOT / "out" / "qemu-phone-esp"
KERNEL = ROOT / "out" / "earlymap" / "mach.development.bcm2837.unstripped"
DEPLOY = ROOT / "scripts" / "deploy-early-map.py"


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if not STAGED.is_dir():
        print(f"skipped: no staged tree at {STAGED}")
        return 0
    if not KERNEL.is_file():
        print(f"skipped: no kernel artifact at {KERNEL}")
        return 0
    with tempfile.TemporaryDirectory() as temporary:
        base = pathlib.Path(temporary)
        volume = base / "EFIESP"
        shutil.copytree(STAGED, volume)
        payload = volume / "EFI" / "UniXNU" / "Payloads" / "kernel.macho"
        config = volume / "EFI" / "UniXNU" / "unixnu.toml"
        before = {"kernel": digest(payload), "config": config.read_text(encoding="utf-8")}

        dry = subprocess.run([sys.executable, str(DEPLOY), "--efiesp", str(volume), "--kernel", str(KERNEL),
                              "--expect-sha256", digest(KERNEL)], capture_output=True, text=True)
        print("== dry-run exit:", dry.returncode)
        print(dry.stdout.strip()[:600])
        untouched = digest(payload) == before["kernel"] and config.read_text(encoding="utf-8") == before["config"]
        print("== the dry run wrote nothing:", untouched)

        backup = base / "backups" / "kernel.before"
        backup.parent.mkdir()
        apply_run = subprocess.run([sys.executable, str(DEPLOY), "--efiesp", str(volume), "--kernel", str(KERNEL),
                                    "--apply", "--backup", str(backup), "--boot-chain-gate", str(KERNEL)],
                                   capture_output=True, text=True)
        print("== apply exit:", apply_run.returncode)
        print(apply_run.stdout.strip()[:800])

        after = digest(payload)
        text = config.read_text(encoding="utf-8")
        runbook = backup.parent / "handset-run.txt"
        checks = {
            "artifact written": after == digest(KERNEL),
            "previous kernel kept": backup.is_file() and digest(backup) == before["kernel"],
            "boot argument added once": text.count("lumia-early-map") == 1,
            "runbook written": runbook.is_file(),
        }
        for name, ok in checks.items():
            print(f"== {name}: {ok}")
        if runbook.is_file():
            print("-- runbook --")
            print(runbook.read_text(encoding="utf-8").strip()[:600])
        return 0 if all(checks.values()) and untouched else 1


if __name__ == "__main__":
    sys.exit(main())
