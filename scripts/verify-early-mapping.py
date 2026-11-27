r"""Acceptance for the C-side early mapping: zero regression off, a readable bar on, in QEMU.

Two runs, same kernel and same staged tree, differing only in the boot argument:

  off: the behaviour must be exactly what it was -- root-wait and the bottom bar;
  on : a bar at rows 120..135 must be readable from the framebuffer dump, and the kernel must still reach root-wait.

The second condition is what makes the handset test worth doing: if the emulator cannot see the bar, a missing bar on the handset would
say nothing.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(".").resolve()
KERNEL = ROOT / "out" / "earlymap" / "mach.development.bcm2837.unstripped"
BASE_ESP = ROOT / "out" / "qemu-phone-esp"
BAR_ROWS = (120, 136)
BAR_RGB = (0xE0, 0x30, 0x30)


def run_case(name: str, extra: str) -> dict:
    esp = ROOT / "out" / f"qemu-earlymap-{name}"
    if esp.exists():
        shutil.rmtree(esp)
    shutil.copytree(BASE_ESP, esp)
    shutil.copy2(KERNEL, esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho")

    config = esp / "EFI" / "UniXNU" / "unixnu.toml"
    text = config.read_text(encoding="utf-8")
    text = re.sub(r'^default = "xnu"$', 'default = "exit"', text, flags=re.M)
    text = re.sub(r"^timeout = \d+$", "timeout = 300", text, flags=re.M)
    base = "-v cpus=1 lumia-bars2 skmem_sysctl_skip=1"
    text = re.sub(r'^args = "[^"]*"$', f'args = "{base} {extra}"'.rstrip(), text, flags=re.M)
    config.write_text(text, encoding="utf-8")

    output = ROOT / "out" / f"qemu-earlymap-{name}-run"
    if output.exists():
        shutil.rmtree(output)
    subprocess.run([sys.executable, "scripts/test-native-xnu-entry.py",
                    "--kernel", str(esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho"),
                    "--esp", str(esp),
                    "--firmware", r"C:\Program Files\qemu\share\edk2-aarch64-code.fd",
                    "--output", str(output),
                    "--qemu", r"C:\Program Files\qemu\qemu-system-aarch64.exe",
                    "--crypto-post", "--past-bsd", "--dump-dmesg", "--dump-framebuffer",
                    "--adt-profile", "qemu", "--memory", "2816", "--smp", "2", "--timeout", "300",
                    "--gdb-transport", "tcp"], check=False)

    report_path = output / "report.json"
    if not report_path.is_file():
        return {"case": name, "outcome": "no report"}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    bar = 0
    frame = output / "framebuffer.bin"
    if frame.is_file():
        data = frame.read_bytes()
        stride = len(data) // 600
        for y in range(BAR_ROWS[0], BAR_ROWS[1]):
            row = data[y * stride:(y + 1) * stride]
            for x in range(0, len(row), 4):
                if (abs(row[x] - BAR_RGB[2]) < 16 and abs(row[x + 1] - BAR_RGB[1]) < 16
                        and abs(row[x + 2] - BAR_RGB[0]) < 16):
                    bar += 1
    return {"case": name, "outcome": report.get("past_bsd_outcome"), "stop": report.get("stop_symbols"),
            "early_bar_pixels": bar}


off = run_case("off", "")
print(f"off: outcome={off.get('outcome')} stop={off.get('stop')} early_bar={off.get('early_bar_pixels')}")
on = run_case("on", "lumia-early-map")
print(f"on : outcome={on.get('outcome')} stop={on.get('stop')} early_bar={on.get('early_bar_pixels')}")
