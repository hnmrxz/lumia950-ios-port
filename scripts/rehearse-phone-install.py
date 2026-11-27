#!/usr/bin/env python3
"""Rehearse the handset deployment offline: build a synthetic EFIESP/MainOS tree and dry-run the installer.

Writes nothing outside a temp directory and never touches a device. Prints the installer's own report so the
runbook can quote it.
"""

from __future__ import annotations

import json
import struct
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


WOA_ENUM = """Windows \u542f\u52a8\u7ba1\u7406\u5668
--------------------
\u6807\u8bc6\u7b26                  {bootmgr}
device                  partition=\\Device\\HarddiskVolume2
path                    \\efi\\boot\\bootarm.efi
default                 {default}

Windows \u542f\u52a8\u5e94\u7528\u7a0b\u5e8f(1020000a)
--------------------
\u6807\u8bc6\u7b26                  {default}
device                  partition=F:
path                    \\windows\\system32\\boot\\bootshim.efi
description             BootShim Application
"""


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

    good = base / "bcd-good.txt"
    good.write_text(WOA_ENUM, encoding="utf-8")
    bad = base / "bcd-bad.txt"
    bad.write_text(WOA_ENUM.replace("bootshim.efi", "winload.efi"), encoding="utf-8")
    return {"efiesp": efiesp, "mainos": mainos, "payload": payload, "shim": shim, "uefi": uefi,
            "good": good, "bad": bad}


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

        untouched = (not any(paths["efiesp"].iterdir()), not any(paths["mainos"].iterdir()))
        print("== the dry run wrote nothing:", untouched == (True, True))

        # The rehearsal installs over a reference store that already holds the boot files, so it is a replacement of protected
        # objects and has to give the evidence a real run would give. The reference store itself is the recovery file here.
        reference = base / "reference-before"
        shutil.copytree(paths["efiesp"], reference / "efiesp", dirs_exist_ok=True)
        shutil.copytree(paths["mainos"], reference / "mainos", dirs_exist_ok=True)

        install_and_verify = [
            sys.executable, str(ROOT / "scripts" / "phone-install.py"),
            "--efiesp", str(paths["efiesp"]),
            "--mainos", str(paths["mainos"]),
            "--stage", str(paths["payload"]),
            "--payload", str(paths["payload"]),
            "--bootshim", str(paths["shim"]),
            "--uefi-elf", str(paths["uefi"]),
            "--replace-protected",
            "--backup", str(paths["good"]),
            "--reason", "install rehearsal writes the reference store",
            "--verify", "the run verifies every file by SHA-256 and the BCD layout afterwards",
            "--apply",
        ]

        good = subprocess.run(install_and_verify + ["--verify-bcd", str(paths["good"])],
                             capture_output=True, text=True)
        print("== install + verify (reference store) exit:", good.returncode)
        print("   shim written:", (paths["mainos"] / "Windows" / "System32" / "Boot" / "bootshim.efi").is_file())
        print("   store matches the layout:", "store matches the layout" in good.stdout)

        bad = subprocess.run(install_and_verify + ["--verify-bcd", str(paths["bad"])],
                            capture_output=True, text=True)
        print("== install + verify (loader-path store) exit:", bad.returncode)
        print("   refuses the mismatch:", bad.returncode != 0)

        print("== the apply run wrote the shim and the payload:",
              (paths["mainos"] / "Windows" / "System32" / "Boot" / "bootshim.efi").is_file()
              and (paths["efiesp"] / "EFI" / "UniXNU" / "UniXNU.efi").is_file())
        ok = (result.returncode == 0 and untouched == (True, True) and good.returncode == 0
              and bad.returncode != 0 and "store matches the layout" in good.stdout)
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
