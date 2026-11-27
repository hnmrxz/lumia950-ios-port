r"""Is the staged ESP or the new kernel responsible for the early fault?

Copies the staged tree, swaps in the kernel that was known to reach root-wait, and runs it with the same fixture arguments. If this also
faults early, the staged tree is the variable and the switch bisect results mean nothing yet.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(".").resolve()
base = ROOT / "out" / "qemu-phone-esp"
old = ROOT / "out" / "aftervm" / "mach.development.bcm2837.unstripped"

if not base.is_dir():
    raise SystemExit(f"no staged tree at {base}")
if not old.is_file():
    raise SystemExit(f"no reference kernel at {old}")

esp = ROOT / "out" / "qemu-esp-check"
if esp.exists():
    shutil.rmtree(esp)
shutil.copytree(base, esp)
shutil.copy2(old, esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho")

config = esp / "EFI" / "UniXNU" / "unixnu.toml"
text = config.read_text(encoding="utf-8")
text = re.sub(r'^default = "xnu"$', 'default = "exit"', text, flags=re.M)
text = re.sub(r"^timeout = \d+$", "timeout = 300", text, flags=re.M)
text = re.sub(r'^args = "[^"]*"$',
              'args = "-v cpus=1 lumia-bars2 skmem_sysctl_skip=1 lumia-skip-rtclock lumia-skip-topology '
              'lumia-skip-timercall lumia-skip-cpuinit lumia-skip-processor"', text, flags=re.M)
config.write_text(text, encoding="utf-8")

run = ROOT / "out" / "qemu-esp-check-run"
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
print("reference kernel in the same tree:", report.get("past_bsd_outcome"), report.get("stop_symbols"))
dmesg = (run / "dmesg.txt").read_text(encoding="utf-8", errors="replace")
print("marker:", any("arm_vm_init returned" in line for line in dmesg.splitlines()))
