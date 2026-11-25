#!/usr/bin/env python3
"""Rehearse the rollback path offline: snapshot, damage, restore.

Builds a synthetic EFIESP tree with a BCD store, saves a snapshot into a temp directory, damages the store,
proves the dry run writes nothing, then proves --apply puts the bytes back and verifies them. No device and no
outside writes.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "phone-snapshot.py"), *arguments],
                          capture_output=True, text=True)


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        efiesp = base / "EFIESP"
        store = efiesp / "EFI" / "Microsoft" / "BOOT"
        store.mkdir(parents=True)
        bcd = store / "BCD"
        bcd.write_text("synthetic-bcd", encoding="utf-8")
        (efiesp / "UEFI.elf").write_bytes(b"\x7fELF" + b"\x00" * 32)
        backups = base / "backups"

        save = run("save", "--efiesp", str(efiesp), "--out", str(backups))
        print("== save exit:", save.returncode)
        print(save.stdout.rstrip())
        if save.returncode != 0:
            return 1

        names = [entry.name for entry in backups.iterdir() if entry.is_dir()]
        if not names:
            print("error: save produced no snapshot directory")
            return 1
        name = sorted(names)[0]

        bcd.write_text("damaged", encoding="utf-8")

        dry = run("restore", "--efiesp", str(efiesp), "--out", str(backups), "--name", name)
        print("== restore dry exit:", dry.returncode)
        print(dry.stdout.rstrip())
        untouched = bcd.read_text(encoding="utf-8") == "damaged"
        print("== dry run left the store damaged:", untouched)

        apply = run("restore", "--efiesp", str(efiesp), "--out", str(backups), "--name", name, "--apply")
        print("== restore apply exit:", apply.returncode)
        print(apply.stdout.rstrip())
        repaired = bcd.read_text(encoding="utf-8") == "synthetic-bcd"
        print("== store restored:", repaired)
        print("== manifest verified:", "restored and verified" in apply.stdout)

        return 0 if dry.returncode == 0 and untouched and apply.returncode == 0 and repaired else 1


if __name__ == "__main__":
    sys.exit(main())
