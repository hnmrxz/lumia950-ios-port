#!/usr/bin/env python3
"""Rehearse the handset deployment offline: build a synthetic EFIESP/MainOS tree and dry-run the installer.

Writes nothing outside a temp directory and never touches a device. Prints the installer's own report so the
runbook can quote it.
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def make_pe(path: Path, subsystem: int, machine: int = 0xAA64) -> None:
    data = bytearray(0x200)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<H", data, 0x84, machine)
    data[0xDC] = subsystem
    path.write_bytes(bytes(data))


def stage(base: Path) -> dict[str, Path]:
    efiesp = base / "EFIESP"
    mainos = base / "MainOS"
    payload = base / "payload"
    (payload / "EFI" / "UniXNU" / "Drivers").mkdir(parents=True)
    (payload / "EFI" / "UniXNU" / "Payloads").mkdir(parents=True)
    efiesp.mkdir()
    mainos.mkdir()

    shim = base / "BootShim.efi"
    make_pe(shim, 0x0A)
    uefi = base / "UEFI.elf"
    uefi.write_bytes(b"\x7fELF" + b"\x00" * 64)

    make_pe(payload / "EFI" / "UniXNU" / "UniXNU.efi", 0x0A)
    make_pe(payload / "EFI" / "UniXNU" / "Drivers" / "DarwinBoot.efi", 0x0A)
    (payload / "EFI" / "UniXNU" / "unixnu.toml").write_text('[[entry]]\nname = "xnu"\n', encoding="utf-8")
    (payload / "EFI" / "UniXNU" / "Payloads" / "kernel.macho").write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 28)
    return {"efiesp": efiesp, "mainos": mainos, "payload": payload, "shim": shim, "uefi": uefi}


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        paths = stage(base)

        command = [
            sys.executable, str(ROOT / "scripts" / "phone-install.py"),
            "--efiesp", str(paths["efiesp"]),
            "--mainos", str(paths["mainos"]),
            "--stage", str(paths["payload"]),
            "--payload", str(paths["payload"]),
            "--bootshim", str(paths["shim"]),
            "--uefi-elf", str(paths["uefi"]),
            "--dry-run",
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        print("== dry-run exit:", result.returncode)
        print(result.stdout.rstrip())
        if result.stderr.strip():
            print("-- stderr --")
            print(result.stderr.rstrip())

        written = [p for p in base.rglob("*") if p.is_file() and "payload" not in p.relative_to(base).parts]
        outside_payload = [str(p.relative_to(base)) for p in written if p.name not in {"BootShim.efi", "UEFI.elf"}]
        print("== files outside the staged payload:", outside_payload or "none")
        print("== EFIESP still empty:", not any(paths["efiesp"].iterdir()))
        print("== MainOS still empty:", not any(paths["mainos"].iterdir()))
        return 0 if result.returncode == 0 and not outside_payload else 1


if __name__ == "__main__":
    sys.exit(main())
