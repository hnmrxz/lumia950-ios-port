"""Read the identity table start.s built, at the moment the marker runs.

Round 169 measured TTBR0_EL1 and TTBR1_EL1 as two adjacent pages of bootstrap_pagetables. What is still unknown is which entry covers the
framebuffer's physical range and at which level, and that is a read: break just after the marker, dump the first page of the tables, and
decode the entries here instead of guessing at macro names.
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

PE_INIT_PLATFORM = 0xFFFFFFF00794D970  # resolved by scripts/kernel-symbols.py for this kernel
ARM_VM_INIT = 0xFFFFFFF0073FCA68

DESCRIPTOR = {0: "invalid", 1: "block", 3: "table"}


def run_case(name: str, breakpoint: int, reads: list[str], extra: str = "") -> pathlib.Path:
    esp = ROOT / "out" / f"qemu-tables-{name}"
    if esp.exists():
        shutil.rmtree(esp)
    shutil.copytree(BASE_ESP, esp)
    shutil.copy2(KERNEL, esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho")

    config = esp / "EFI" / "UniXNU" / "unixnu.toml"
    text = config.read_text(encoding="utf-8")
    text = re.sub(r'^default = "xnu"$', 'default = "exit"', text, flags=re.M)
    text = re.sub(r"^timeout = \d+$", "timeout = 300", text, flags=re.M)
    arguments = f"-v cpus=1 lumia-bars2 skmem_sysctl_skip=1 {extra}".rstrip()
    text = re.sub(r'^args = "[^"]*"$', f'args = "{arguments}"', text, flags=re.M)
    config.write_text(text, encoding="utf-8")

    output = ROOT / "out" / f"qemu-tables-{name}-run"
    if output.exists():
        shutil.rmtree(output)
    command = [sys.executable, "scripts/test-native-xnu-entry.py",
               "--kernel", str(esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho"),
               "--esp", str(esp),
               "--firmware", r"C:\Program Files\qemu\share\edk2-aarch64-code.fd",
               "--output", str(output),
               "--qemu", r"C:\Program Files\qemu\qemu-system-aarch64.exe",
               "--dump-dmesg",
               "--adt-profile", "qemu", "--memory", "2816", "--smp", "2", "--timeout", "300",
               "--gdb-transport", "tcp",
               "--break-at", f"0x{breakpoint:x}"]
    for item in reads:
        command.append("--read-at")
        command.append(item)
    subprocess.run(command, capture_output=True, text=True)  # a pre-VM stop is expected here
    return output


def decode(report: dict) -> None:
    registers = report.get("system_registers") or {}
    ttbr0 = registers.get("ttbr0_el1")
    ttbr1 = registers.get("ttbr1_el1")
    print("   ttbr0_el1:", ttbr0, "ttbr1_el1:", ttbr1)
    reads = report.get("reads") or {}
    for address, value in (reads.items() if isinstance(reads, dict) else []):
        print(f"   read @{address}: {str(value)[:200]}")


for label, breakpoint in (("after-marker", PE_INIT_PLATFORM), ("vm-entry", ARM_VM_INIT)):
    output = run_case(label, breakpoint, ["0xFFFFFFF00718D000:128"], "lumia-early-map")
    report_path = output / "report.json"
    print(f"== {label}")
    if not report_path.is_file():
        print("   no report")
        continue
    report = json.loads(report_path.read_text(encoding="utf-8"))
    print("   stop:", report.get("stop_symbols"), report.get("pc_symbol"))
    decode(report)
