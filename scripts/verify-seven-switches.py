r"""Sanity check for the seven-switch kernel in QEMU, with all seven switched on.

Before the handset is asked to run it, the same kernel has to show that skipping those calls does not break the path it is meant to
bisect: with every switch on, the emulated boot should still walk through the milestones and reach root-wait, and print the post-VM
marker. If it does not, a handset result would be unreadable.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(".").resolve()
KERNEL = ROOT / "out" / "seven" / "mach.development.bcm2837.unstripped"
BASE_ESP = ROOT / "out" / "qemu-phone-esp"

SWITCHES = ("lumia-skip-rtclock lumia-skip-topology lumia-skip-timercall lumia-skip-cpuinit "
            "lumia-skip-processor lumia-skip-wfe lumia-skip-startup")

if not KERNEL.is_file():
    print(f"error: no kernel at {KERNEL}")
    sys.exit(2)
if not (BASE_ESP / "EFI" / "BOOT" / "BOOTAA64.EFI").is_file():
    print(f"error: {BASE_ESP} does not hold the staged loader; stage it while the phone is attached")
    sys.exit(2)

esp = ROOT / "out" / "qemu-seven-switches"
if esp.exists():
    shutil.rmtree(esp)
shutil.copytree(BASE_ESP, esp)
shutil.copy2(KERNEL, esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho")

config = esp / "EFI" / "UniXNU" / "unixnu.toml"
text = config.read_text(encoding="utf-8")
text = re.sub(r'^default = "xnu"$', 'default = "exit"', text, flags=re.M)
text = re.sub(r"^timeout = \d+$", "timeout = 300", text, flags=re.M)
text = re.sub(r"^args = \"[^\"]*\"$",
              f'args = "-v cpus=1 lumia-bars2 skmem_sysctl_skip=1 {SWITCHES}"'.rstrip(), text, flags=re.M)
config.write_text(text, encoding="utf-8")
print("args:", next(line for line in text.splitlines() if line.startswith("args")))

run = ROOT / "out" / "qemu-seven-switches-run"
if run.exists():
    shutil.rmtree(run)
subprocess.run([sys.executable, "scripts/test-native-xnu-entry.py",
                "--kernel", str(esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho"),
                "--esp", str(esp),
                "--firmware", r"C:\Program Files\qemu\share\edk2-aarch64-code.fd",
                "--output", str(run),
                "--qemu", r"C:\Program Files\qemu\qemu-system-aarch64.exe",
                "--crypto-post", "--past-bsd", "--dump-dmesg", "--dump-framebuffer",
                "--adt-profile", "qemu", "--memory", "2816", "--smp", "2", "--timeout", "300",
                "--gdb-transport", "tcp"], check=False)

report = json.loads((run / "report.json").read_text(encoding="utf-8"))
print("past_bsd:", report.get("past_bsd_outcome"), "| milestones:", report.get("milestones"))
dmesg = (run / "dmesg.txt").read_text(encoding="utf-8", errors="replace")
marker = next((line.strip() for line in dmesg.splitlines() if "arm_vm_init returned" in line), None)
print("post-VM marker:", marker or "MISSING")
frame = (run / "framebuffer.bin").read_bytes()
stride = len(frame) // 600
bottom = sum(1 for y in range(584, 600) for x in range(0, stride, 4)
             if frame[y * stride + x] + frame[y * stride + x + 1] + frame[y * stride + x + 2] > 60)
print("bottom bar pixels:", bottom)
