r"""Which of the two new switches keeps QEMU booting?

The seven-switch configuration faults early in QEMU (`_sleh_synchronous_sp1`), and a configuration that already breaks in the emulator
cannot say anything useful about the handset. This runs the two new switches separately, with the five older ones on, and reports which
combinations still reach root-wait so the handset test uses one of those.
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

FIVE = "lumia-skip-rtclock lumia-skip-topology lumia-skip-timercall lumia-skip-cpuinit lumia-skip-processor"
CASES = {
    "five": FIVE,
    "five+wfe": FIVE + " lumia-skip-wfe",
    "five+startup": FIVE + " lumia-skip-startup",
    "all-seven": FIVE + " lumia-skip-wfe lumia-skip-startup",
}


def run_case(name: str, switches: str) -> dict:
    esp = ROOT / "out" / f"qemu-case-{name.replace('+', '-')}"
    if esp.exists():
        shutil.rmtree(esp)
    shutil.copytree(BASE_ESP, esp)
    shutil.copy2(KERNEL, esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho")
    config = esp / "EFI" / "UniXNU" / "unixnu.toml"
    text = config.read_text(encoding="utf-8")
    text = re.sub(r'^default = "xnu"$', 'default = "exit"', text, flags=re.M)
    text = re.sub(r"^timeout = \d+$", "timeout = 300", text, flags=re.M)
    text = re.sub(r"^args = \"[^\"]*\"$",
                  f'args = "-v cpus=1 lumia-bars2 skmem_sysctl_skip=1 {switches}"'.rstrip(), text, flags=re.M)
    config.write_text(text, encoding="utf-8")

    output = ROOT / "out" / f"qemu-case-{name.replace('+', '-')}-run"
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
    dmesg = (output / "dmesg.txt").read_text(encoding="utf-8", errors="replace")
    marker = any("arm_vm_init returned" in line for line in dmesg.splitlines())
    return {"case": name, "outcome": report.get("past_bsd_outcome"), "stop": report.get("stop_symbols"),
            "marker": marker}


for name, switches in CASES.items():
    result = run_case(name, switches)
    print(f"{result['case']:14s} outcome={result.get('outcome')} stop={result.get('stop')} marker={result.get('marker')}")
