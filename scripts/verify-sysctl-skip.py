r"""Does the phone's config with skmem_sysctl_skip get past the skmem_sysctl_init fault?

The fixed-kernel boot now stops at _skmem_sysctl_init+0x44, which is the publication the CI gates behind skmem_sysctl_skip=1
(workflow step 'Gate the skmem sysctl publication behind a boot argument'). The phone's config does not carry that argument.
This boots the same kernel with it and reports where the boot ends.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(".").resolve()
KERNEL = ROOT / "out" / "daif-check" / "mach.development.bcm2837.unstripped"
EXTRA = sys.argv[1] if len(sys.argv) > 1 else "skmem_sysctl_skip=1"

esp = ROOT / "out" / "qemu-sysctl-skip"
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
text = re.sub(r'^args = "([^"]*)"$', lambda m: f'args = "{m.group(1)} {EXTRA}"', text, flags=re.M)
config.write_text(text, encoding="utf-8")
print("args:", [line for line in text.splitlines() if line.startswith("args")][0])

run = ROOT / "out" / "qemu-sysctl-skip-run"
if run.exists():
    shutil.rmtree(run)
subprocess.run([sys.executable, "scripts/test-native-xnu-entry.py",
                "--kernel", str(esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho"),
                "--esp", str(esp),
                "--firmware", r"C:\Program Files\qemu\share\edk2-aarch64-code.fd",
                "--output", str(run),
                "--qemu", r"C:\Program Files\qemu\qemu-system-aarch64.exe",
                "--crypto-post", "--past-bsd", "--dump-dmesg", "--dump-framebuffer",
                "--adt-profile", "qemu", "--smp", "2", "--timeout", "300", "--gdb-transport", "tcp"],
               check=False)

report = json.loads((run / "report.json").read_text(encoding="utf-8"))
print("past_bsd_outcome:", report.get("past_bsd_outcome"))
print("stop_symbols:", report.get("stop_symbols"))
print("fault_elr_symbol:", report.get("fault_elr_symbol"))
print("panic:", report.get("panic_format"), report.get("panic_string_args"))
print("milestones:", report.get("milestones"))
