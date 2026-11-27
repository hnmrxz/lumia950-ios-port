#!/usr/bin/env python3
"""Compile the SDHCI register-model test for the host and run it.

The test drives the real PollingHost/SdhciCore against drivers/NativeSdhci/Test/ModelSdhci.h, so a broken command sequence fails here instead of
hanging a phone. A missing compiler is a skip, not a pass.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
ZIG = os.environ.get("ZIG") or str(pathlib.PureWindowsPath("E:/lumia950-ios-port-bootstrap/tools/zig-x86_64-windows-0.17.1/zig.exe"))
SOURCES = [ROOT / "drivers" / "NativeSdhci" / "Test" / "check-model-sdhci.cpp"]


def main() -> int:
    if not pathlib.Path(ZIG).is_file():
        print(f"skipped: no C++ compiler at {ZIG}; set ZIG to run the register-model test")
        return 0
    with tempfile.TemporaryDirectory() as temporary:
        binary = pathlib.Path(temporary) / ("check-model-sdhci.exe" if os.name == "nt" else "check-model-sdhci")
        build = subprocess.run([ZIG, "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                                "-I", str(ROOT / "drivers" / "NativeSdhci"),
                                "-I", str(ROOT / "drivers" / "NativeSdhci" / "Test"),
                                *[str(source) for source in SOURCES], "-o", str(binary)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            print(build.stderr[-1500:])
            return 1
        # the same synthetic GPT image the Python reader and the parser parity test use, so both sides parse identical bytes
        fixture = pathlib.Path(temporary) / "gpt.img"
        make = subprocess.run([sys.executable, str(ROOT / "scripts" / "make-gpt-fixture.py"), "--out", str(fixture)],
                              capture_output=True, text=True)
        if make.returncode != 0:
            print(make.stderr[-600:])
            return 1
        run = subprocess.run([str(binary), str(fixture)], capture_output=True, text=True)
        print(run.stdout.strip())
        if run.stderr.strip():
            print(run.stderr.strip()[-500:])
        return run.returncode


if __name__ == "__main__":
    sys.exit(main())
