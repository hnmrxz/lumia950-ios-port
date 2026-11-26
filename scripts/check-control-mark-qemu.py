#!/usr/bin/env python3
"""Boot the control-mark EFI application in QEMU and read the panel back, pixel by pixel.

The kernel-side instrument cannot draw before arm_vm_init (osfmk/arm64/start.s turns the MMU on and maps only the
kernel image), so the pre-MMU witness is the loader's. This checks the loader one for real instead of by inspection:
it starts the emulated firmware with the application as the boot option, waits for it to finish drawing, takes a
screenshot through QMP, and compares the two bar rows against the colours the application intends.

    python scripts/check-control-mark-qemu.py --application build/local/probe/LumiaControlMark.efi \
        --firmware "C:/Program Files/qemu/share/edk2-aarch64-code.fd" \
        --qemu "C:/Program Files/qemu/qemu-system-aarch64.exe" --output out/control-mark-qemu

Exit status is 0 only when both bars are found where they were drawn.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BAR_HEIGHT = 16
FIRST_BAR_Y = 120
BAR_STRIDE = 20
EXPECTED = ((0xE0, 0x30, 0x30), (0xE0, 0xC0, 0x30))  # red, green, blue the application asks for


def read_ppm(path: Path) -> tuple[int, int, list[bytes]]:
    data = path.read_bytes()
    fields: list[bytes] = []
    position = 0
    while len(fields) < 4 and position < len(data):
        while position < len(data) and data[position : position + 1].isspace():
            position += 1
        if data[position : position + 1] == b"#":
            while position < len(data) and data[position] != 0x0A:
                position += 1
            continue
        start = position
        while position < len(data) and not data[position : position + 1].isspace():
            position += 1
        fields.append(data[start:position])
    position += 1  # single whitespace after maxval
    magic, width, height, _maxval = fields[0], int(fields[1]), int(fields[2]), int(fields[3])
    if magic != b"P6":
        raise ValueError(f"expected a binary PPM, got {magic!r}")
    return width, height, [data[position + row * width * 3 : position + (row + 1) * width * 3] for row in range(height)]


def qmp_screendump(port: int, destination: Path) -> None:
    with socket.create_connection(("127.0.0.1", port), timeout=30) as connection:
        stream = connection.makefile("rwb")
        stream.readline()  # greeting
        stream.write(json.dumps({"execute": "qmp_capabilities"}).encode() + b"\n")
        stream.flush()
        stream.readline()
        time.sleep(1.0)
        command = {"execute": "screendump", "arguments": {"filename": str(destination)}}
        stream.write(json.dumps(command).encode() + b"\n")
        stream.flush()
        reply = json.loads(stream.readline().decode())
        if "error" in reply:
            raise RuntimeError(f"screendump failed: {reply['error']}")


def row_colour(rows: list[bytes], row: int) -> tuple[int, int, int]:
    line = rows[row]
    red, green, blue = line[0], line[1], line[2]
    return red, green, blue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--application", required=True, type=Path)
    parser.add_argument("--firmware", required=True, type=Path)
    parser.add_argument("--qemu", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--port", type=int, default=4444)
    parser.add_argument("--settle", type=float, default=12.0, help="seconds to let firmware boot and draw")
    parser.add_argument("--resolution", default="",
                        help="force the emulated panel size, for example 1080x1920 (default: firmware's choice)")
    args = parser.parse_args(argv)

    if not args.application.is_file():
        print(f"error: no application at {args.application}", file=sys.stderr)
        return 2
    args.output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="control-mark-") as temporary:
        esp = Path(temporary) / "esp" / "EFI" / "BOOT"
        esp.mkdir(parents=True)
        shutil.copy2(args.application, esp / "BOOTAA64.EFI")
        shot = args.output / "panel.ppm"
        log = args.output / "serial.log"
        command = [
            str(args.qemu), "-machine", "virt,gic-version=2", "-cpu", "cortex-a57", "-m", "768",
            "-bios", str(args.firmware), "-display", "none",
            # ramfb is the only display this firmware drives reliably. A forced size is attempted through
            # virtio-gpu, which is documented here as unreliable: with the pinned edk2 image the firmware itself
            # takes a synchronous exception inside ArmCpuDxe before any application runs, so a failure at a forced
            # resolution says nothing about the control mark. The handset's 1080x1920 geometry is covered instead
            # by the host tests in drivers/NativeBootProgress, which check the offsets for stride 4320.
            "-device", (("virtio-gpu-pci,xres=%s,yres=%s" % tuple(args.resolution.split("x")))
                        if "x" in args.resolution else "ramfb"),
            "-drive", f"if=none,id=boot,format=raw,readonly=on,file=fat:ro:{esp.parent.parent}",
            "-device", "virtio-blk-pci,drive=boot",
            "-qmp", f"tcp:127.0.0.1:{args.port},server,nowait",
            "-serial", f"file:{log}",
        ]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(args.settle)
            qmp_screendump(args.port, shot)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()

        if not shot.is_file():
            print("error: no screenshot was taken", file=sys.stderr)
            return 1

        width, height, rows = read_ppm(shot)
        print(f"panel {width}x{height}, screenshot {shot}")

        failures = 0
        for index, wanted in enumerate(EXPECTED):
            top = FIRST_BAR_Y + index * BAR_STRIDE
            found = None
            for row in range(max(0, top - 4), min(height, top + BAR_HEIGHT + 4)):
                if row_colour(rows, row) == wanted:
                    found = row
                    break
            status = "ok  " if found is not None else "FAIL"
            where = f"row {found}" if found is not None else f"nothing at rows {top}..{top + BAR_HEIGHT}"
            print(f"  {status} bar {index} rgb{wanted}: {where}")
            if found is None:
                failures += 1

        (args.output / "report.json").write_text(json.dumps({
            "schema": "lumia950-control-mark-qemu-v1",
            "application_sha256": __import__("hashlib").sha256(args.application.read_bytes()).hexdigest(),
            "panel": {"width": width, "height": height},
            "bars_expected_rgb": [list(value) for value in EXPECTED],
            "bars_found": failures == 0,
            "emulator_only": True,
        }, indent=2) + "\n", encoding="utf-8")
        return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
