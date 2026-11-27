"""Run the two-store probe and read the first word back.

'lumia-early-map-probe' stores 0xA5A5A5A5 into the kernel's own data and then one word into the framebuffer, nothing else. If the fault comes
from the framebuffer store, the first word is intact in memory when the kernel stops; if the store path itself is broken, it is not.
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
PROBE_WORD_VA = 0xFFFFFFF007B5D000


def run(name: str, extra: str, output_name: str) -> dict:
    esp = ROOT / "out" / f"qemu-probe-{name}"
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

    output = ROOT / "out" / output_name
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
                    "--gdb-transport", "tcp",
                    "--read-at", f"0x{PROBE_WORD_VA:x}:8"], capture_output=True, text=True)

    report_path = output / "report.json"
    if not report_path.is_file():
        return {"name": name, "error": "no report"}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    registers = report.get("system_registers") or {}
    raw = next(iter((report.get("read") or {}).values()), "")
    word = int.from_bytes(bytes.fromhex(raw), "little") if raw else None
    return {"name": name, "outcome": report.get("past_bsd_outcome"), "esr": registers.get("esr_el1"),
            "far": registers.get("far_el1"), "word": hex(word) if word is not None else None,
            "stop": report.get("stop_symbols")}


probe = run("probe", "lumia-early-map-probe", "qemu-probe-probe-run")
print("probe:", probe)
