"""Read the page tables the CPU walks, at two points of arm_init.

Three attempts to add a pre-VM mapping failed with the same nested fault, so the next question is a measurement, not another shape: break
at PE_init_platform (just after the marker) and at arm_vm_init, and record TTBR0/TTBR1 plus the first bytes of bootstrap_pagetables. The
fixture takes addresses for --break-at and addresses for --read-at, so the symbols are resolved first.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(".").resolve()
KERNEL = ROOT / "out" / "refuse" / "mach.development.bcm2837.unstripped"
BASE_ESP = ROOT / "out" / "qemu-phone-esp"

SYMBOLS = {
    "_PE_init_platform": 0xFFFFFFF00794D970,
    "_arm_vm_init": 0xFFFFFFF0073FCA68,
    "_bootstrap_pagetables": 0xFFFFFFF00718D000,
}


def run_case(name: str, breakpoint: int, reads: list[str], extra: str = "") -> dict:
    esp = ROOT / "out" / f"qemu-trace-{name}"
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

    output = ROOT / "out" / f"qemu-trace-{name}-run"
    if output.exists():
        shutil.rmtree(output)
    command = [sys.executable, "scripts/test-native-xnu-entry.py",
               "--kernel", str(esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho"),
               "--esp", str(esp),
               "--firmware", r"C:\Program Files\qemu\share\edk2-aarch64-code.fd",
               "--output", str(output),
               "--qemu", r"C:\Program Files\qemu\qemu-system-aarch64.exe",
               "--dump-dmesg", "--dump-framebuffer",
               "--adt-profile", "qemu", "--memory", "2816", "--smp", "2", "--timeout", "300",
               "--gdb-transport", "tcp",
               "--break-at", f"0x{breakpoint:x}"]
    for item in reads:
        command.extend(["--read-at", item])
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        return {"case": name, "error": (result.stderr or result.stdout)[-400:]}
    report_path = output / "report.json"
    if not report_path.is_file():
        return {"case": name, "error": "no report"}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return {"case": name, "stop": report.get("stop_symbols"), "pc_symbol": report.get("pc_symbol"),
            "system_registers": report.get("system_registers"), "reads": report.get("reads"),
            "dmesg": [line for line in (report.get("dmesg") or {}).get("lines", [])] if isinstance(report.get("dmesg"), dict) else None}


CASES = {
    "after-marker": (SYMBOLS["_PE_init_platform"], ["0xFFFFFFF00718D000:64", "0xFFFFFFF00718F000:64"], "lumia-early-map"),
    "vm-entry": (SYMBOLS["_arm_vm_init"], ["0xFFFFFFF00718D000:64"], "lumia-early-map"),
}

for name, (breakpoint, reads, extra) in CASES.items():
    outcome = run_case(name, breakpoint, reads, extra)
    print(f"== {name}: {outcome.get('stop')} {outcome.get('pc_symbol', '')} {outcome.get('error', '')}")
    registers = outcome.get("system_registers") or {}
    for key in ("ttbr0_el1", "ttbr1_el1", "tcr_el1", "sctlr_el1"):
        print(f"   {key}: {registers.get(key)}")
    reads = outcome.get("reads") or {}
    for address, value in (reads.items() if isinstance(reads, dict) else []):
        print(f"   read {address}: {str(value)[:120]}")
