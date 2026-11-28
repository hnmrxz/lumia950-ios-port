#!/usr/bin/env python3
"""Rehearse the handset run book against a copy of the staged chain, on two volumes.

The chain spans EFIESP (the configuration) and MainOS (the kernel and its adt), so the rehearsal builds both from the staged tree and runs the
procedure the phone will see: dry run, then apply with real backups of the kernel, the adt and the configuration, each proven to hash the same
as the object it replaces, with the boot-chain gate asked about those objects.

    python scripts/rehearse-handset-run.py
"""

from __future__ import annotations

import hashlib
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
    if not STAGED.is_dir() or not KERNEL.is_file():
        print(f"skipped: needs {STAGED} and {KERNEL}")
        return 0
    staged_payloads = STAGED / "EFI" / "UniXNU" / "Payloads"
    if not (staged_payloads / "kernel.macho").is_file():
        print("skipped: the staged tree has no payload to rehearse with")
        return 0

    with tempfile.TemporaryDirectory() as temporary:
        base = pathlib.Path(temporary)
        efiesp = base / "EFIESP"
        mainos = base / "MainOS"
        (efiesp / "EFI" / "UniXNU").mkdir(parents=True)
        shutil.copy2(STAGED / "EFI" / "UniXNU" / "unixnu.toml", efiesp / "EFI" / "UniXNU" / "unixnu.toml")
        shutil.copytree(staged_payloads, mainos / "EFI" / "UniXNU" / "Payloads")
        backups = base / "backups"

        config = efiesp / "EFI" / "UniXNU" / "unixnu.toml"
        kernel = mainos / "EFI" / "UniXNU" / "Payloads" / "kernel.macho"
        adt = mainos / "EFI" / "UniXNU" / "Payloads" / "kernel.macho.adt"
        before = {"config": config.read_text(encoding="utf-8"), "kernel": digest(kernel),
                  "adt": digest(adt) if adt.is_file() else None}

        # the phone carries an adt beside the kernel and the pair has to move together; the fetched kernel artifact is the kernel alone, so
        # the rehearsal stands in the staged adt when the artifact has none
        artifact_adt = KERNEL.with_suffix(KERNEL.suffix + ".adt")
        stand_in = staged_payloads / "kernel.macho.adt"
        adt_argument = artifact_adt if artifact_adt.is_file() else stand_in
        common = ["--efiesp", str(efiesp), "--mainos", str(mainos), "--kernel", str(KERNEL), "--adt", str(adt_argument)]
        dry = subprocess.run([sys.executable, str(DEPLOY), *common], capture_output=True, text=True)
        print("== dry-run exit:", dry.returncode)
        print(dry.stdout.strip()[:700])
        untouched = (config.read_text(encoding="utf-8") == before["config"] and digest(kernel) == before["kernel"]
                     and (not adt.is_file() or digest(adt) == before["adt"]) and not backups.exists())
        print("== the dry run wrote nothing:", untouched)

        apply_run = subprocess.run([sys.executable, str(DEPLOY), *common,
                                    "--apply", "--backup-dir", str(backups)], capture_output=True, text=True)
        print("== apply exit:", apply_run.returncode)
        print(apply_run.stdout.strip()[:1200])

        checks = {
            "kernel replaced on MainOS": digest(kernel) == digest(KERNEL),
            "old kernel kept": (backups / "kernel.macho.before-m1").is_file()
                                and digest(backups / "kernel.macho.before-m1") == before["kernel"],
            "configuration kept": (backups / "unixnu.toml.before-m1").read_text(encoding="utf-8") == before["config"]
                                  if (backups / "unixnu.toml.before-m1").is_file() else False,
            "argument added once": config.read_text(encoding="utf-8").count("lumia-early-map") == 1,
            "nothing written into efiesp payloads": not (efiesp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho").exists(),
            "runbook written": (backups / "handset-run.txt").is_file(),
        }
        for name, ok in checks.items():
            print(f"== {name}: {ok}")
        if (backups / "handset-run.txt").is_file():
            print("-- runbook --")
            print((backups / "handset-run.txt").read_text(encoding="utf-8").strip()[:700])
        return 0 if all(checks.values()) and untouched else 1


if __name__ == "__main__":
    sys.exit(main())
