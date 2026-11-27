#!/usr/bin/env python3
"""Build the control-mark probe as an EFI application, locally.

The probe is this repository's own EFI code, so it can be built without the macOS runner: Zig's clang compiles for
aarch64-unknown-uefi against the vendored EDK2 headers, and its lld links the PE image. Two units are needed -- the mark itself
and FramebufferCore.c, which draws the text and the bars.

    python scripts/build-control-mark.py --out build/local/probe/LumiaControlMark.efi
    python scripts/check-control-mark-qemu.py --application build/local/probe/LumiaControlMark.efi
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [
    "tools/uefi-probe/LumiaControlMark.c",
    "tools/uefi-probe/FramebufferCore.c",
    "tools/uefi-probe/ProbeCore.c",
]
# The EDK II headers live beside the checkout in this workspace (the build workspace root holds tools/), and inside it in a
# checkout that vendors them. Both are tried, the same way the zig lookup is.
INCLUDE_CANDIDATES = [
    ROOT.parent / "tools" / "edk2" / "MdePkg" / "Include",
    ROOT / "tools" / "edk2" / "MdePkg" / "Include",
]


def find_include() -> Path:
    for candidate in INCLUDE_CANDIDATES:
        if (candidate / "Uefi.h").is_file():
            return candidate
    raise SystemExit("error: no EDK II MdePkg/Include with Uefi.h; set it up or pass --include")


def find_zig(explicit: str | None) -> str:
    if explicit:
        return explicit
    for candidate in (os.environ.get("ZIG"), str(ROOT.parent / "tools" / "zig-x86_64-windows-0.17.1" / "zig.exe")):
        if candidate and Path(candidate).is_file():
            return candidate
    found = shutil.which("zig")
    if found:
        return found
    raise SystemExit("error: no zig; pass --zig or set ZIG")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "local" / "probe" / "LumiaControlMark.efi")
    parser.add_argument("--zig", default=None)
    parser.add_argument("--include", type=Path, default=None, help="EDK II MdePkg/Include")
    parser.add_argument("--hold", action="store_true", help="define CONTROL_MARK_HOLD, which makes the mark wait forever")
    args = parser.parse_args(argv)

    zig = find_zig(args.zig)
    args.include = args.include or find_include()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Measured with the bundled toolchain: Zig 0.17 has no aarch64-unknown-uefi target ('UnknownOperatingSystem'), and its cc
    # rejects the MSVC-style /entry and /subsystem flags, but aarch64-windows-msvc with -nostdlib and the lld spellings produces
    # the same PE image the authored build-probe.sh produces with clang.
    command = [zig, "cc", "-target", "aarch64-windows-msvc", "-nostdlib",
               "-fno-stack-protector", "-fshort-wchar", "-mgeneral-regs-only", "-mstrict-align",
               "-fno-asynchronous-unwind-tables", "-fno-unwind-tables", "-O2",
               "-I", str(args.include), "-I", str(args.include / "AArch64"),
               "-Wl,--subsystem,efi_application", "-Wl,--entry,EfiMain",
               "-o", str(args.out)]
    if args.hold:
        command.append("-DCONTROL_MARK_HOLD")
    command += [str(ROOT / source) for source in SOURCES]
    print("+", " ".join(command))
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode
    print(f"{args.out}: {args.out.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
