import pathlib
import re
import subprocess
import sys
import shutil

ROOT = pathlib.Path(".").resolve()
KERNEL = ROOT / "out" / "earlymap" / "mach.development.bcm2837.unstripped"
BASE_ESP = ROOT / "out" / "qemu-phone-esp"

esp = ROOT / "out" / "qemu-sdhci-probe"
if esp.exists():
    shutil.rmtree(esp)
shutil.copytree(BASE_ESP, esp)
shutil.copy2(KERNEL, esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho")

config = esp / "EFI" / "UniXNU" / "unixnu.toml"
text = config.read_text(encoding="utf-8")
text = re.sub(r'^default = "xnu"$', 'default = "exit"', text, flags=re.M)
text = re.sub(r"^timeout = \d+$", "timeout = 300", text, flags=re.M)
text = re.sub(r'^args = "[^"]*"$', 'args = "-v cpus=1 lumia-bars2 skmem_sysctl_skip=1 lumia-sdhci-probe"', text, flags=re.M)
config.write_text(text, encoding="utf-8")

output = ROOT / "out" / "qemu-sdhci-probe-run"
if output.exists():
    shutil.rmtree(output)
subprocess.run([sys.executable, "scripts/test-native-xnu-entry.py",
                "--kernel", str(esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho"),
                "--esp", str(esp),
                "--firmware", r"C:\Program Files\qemu\share\edk2-aarch64-code.fd",
                "--output", str(output),
                "--qemu", r"C:\Program Files\qemu\qemu-system-aarch64.exe",
                "--dump-dmesg", "--past-bsd",
                "--adt-profile", "qemu", "--memory", "2816", "--smp", "2", "--timeout", "300",
                "--gdb-transport", "tcp"], check=False)

report = output / "report.json"
print("report exists:", report.is_file())
if report.is_file():
    import json
    data = json.loads(report.read_text(encoding="utf-8"))
    registers = data.get("system_registers") or {}
    print("outcome:", data.get("past_bsd_outcome"), "esr:", registers.get("esr_el1"), "far:", registers.get("far_el1"))
    dmesg = (output / "dmesg.txt").read_text(encoding="utf-8", errors="replace")
    lines = [line.strip() for line in dmesg.splitlines() if "LUMIA" in line]
    print("\n".join(lines[-6:]))
