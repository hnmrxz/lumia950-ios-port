r"""Does the post-VM marker print, and does the kernel still reach bsd_init?

The marker was added on the theory that the framebuffer only becomes writable after arm_vm_init. In emulation the same claim can
be checked directly: boot this kernel and look for the line in the dmesg capture. If the line is missing there, the theory is
wrong and the marker would not help on the handset either.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(".").resolve()
KERNEL = ROOT / "out" / "aftervm" / "mach.development.bcm2837.unstripped"

esp = ROOT / "out" / "qemu-aftervm"
if esp.exists():
    shutil.rmtree(esp)
(esp / "EFI" / "BOOT").mkdir(parents=True)
shutil.copy2("R:/EFI/BOOT/BOOTAA64.EFI", esp / "EFI" / "BOOT" / "BOOTAA64.EFI")
shutil.copytree("R:/EFI/UniXNU", esp / "EFI" / "UniXNU")
(esp / "EFI" / "UniXNU" / "Payloads").mkdir(exist_ok=True)
shutil.copy2("H:/EFI/UniXNU/Payloads/kernel.macho.adt", esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho.adt")
shutil.copy2(KERNEL, esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho")

config = esp / "EFI" / "UniXNU" / "unixnu.toml"
text = config.read_text(encoding="utf-8")
text = re.sub(r'^default = "xnu"$', 'default = "exit"', text, flags=re.M)
text = re.sub(r"^timeout = \d+$", "timeout = 300", text, flags=re.M)
config.write_text(text, encoding="utf-8")

run = ROOT / "out" / "qemu-aftervm-run"
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
line = next((entry for entry in dmesg.splitlines() if "arm_vm_init returned" in entry), None)
print("marker line:", line.strip() if line else "MISSING")
