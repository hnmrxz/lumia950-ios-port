"""Run the early marker in its three forms against one artifact: off, dry (map only), and map-and-draw."""

import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(".").resolve()
KERNEL = ROOT / "out" / "earlymap" / "mach.development.bcm2837.unstripped"
BASE_ESP = ROOT / "out" / "qemu-phone-esp"

CASES = {
    "off": "",
    "dry": "lumia-early-map-dry",
    "draw": "lumia-early-map",
}
BASE_ARGS = "-v cpus=1 lumia-bars2 skmem_sysctl_skip=1"


def run_case(name: str, extra: str) -> dict:
    esp = ROOT / "out" / f"qemu-split-{name}"
    if esp.exists():
        shutil.rmtree(esp)
    shutil.copytree(BASE_ESP, esp)
    shutil.copy2(KERNEL, esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho")

    config = esp / "EFI" / "UniXNU" / "unixnu.toml"
    text = config.read_text(encoding="utf-8")
    text = re.sub(r'^default = "xnu"$', 'default = "exit"', text, flags=re.M)
    text = re.sub(r"^timeout = \d+$", "timeout = 300", text, flags=re.M)
    text = re.sub(r'^args = "[^"]*"$', f'args = "{BASE_ARGS} {extra}"'.rstrip(), text, flags=re.M)
    config.write_text(text, encoding="utf-8")

    output = ROOT / "out" / f"qemu-split-{name}-run"
    if output.exists():
        shutil.rmtree(output)
    subprocess.run([sys.executable, "scripts/test-native-xnu-entry.py",
                    "--kernel", str(esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho"),
                    "--esp", str(esp),
                    "--firmware", r"C:\Program Files\qemu\share\edk2-aarch64-code.fd",
                    "--output", str(output),
                    "--qemu", r"C:\Program Files\qemu\qemu-system-aarch64.exe",
                    "--dump-dmesg", "--dump-framebuffer", "--past-bsd",
                    "--adt-profile", "qemu", "--memory", "2816", "--smp", "2", "--timeout", "300",
                    "--gdb-transport", "tcp"], check=False)

    report_path = output / "report.json"
    if not report_path.is_file():
        return {"case": name, "error": "no report"}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    dmesg = (output / "dmesg.txt").read_text(encoding="utf-8", errors="replace")
    state = next((line.split("early map state")[-1].strip() for line in dmesg.splitlines() if "early map state" in line), None)
    registers = report.get("system_registers") or {}
    return {"case": name, "outcome": report.get("past_bsd_outcome"), "esr": registers.get("esr_el1"),
            "far": registers.get("far_el1"), "state": state, "stop": report.get("stop_symbols")}


for name, extra in CASES.items():
    result = run_case(name, extra)
    print(f"{result['case']:5s} outcome={result.get('outcome')} esr={result.get('esr')} far={result.get('far')} "
          f"state={result.get('state')} stop={result.get('stop')} {result.get('error', '')}")
