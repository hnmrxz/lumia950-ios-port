"""After a dry run installs the mapping, read the identity table back and see whether the entry landed.

The five-form run says the fault is in the stores, and FAR 0x158 is the nested fault (the vector's own store), not the framebuffer -- so the
first fault is almost certainly the store itself. Whether the mapping took effect is a read: with the dry argument the marker writes the
entries and nothing else, so the table can be examined afterwards without a fault.
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
PE_INIT_PLATFORM = 0xFFFFFFF00794D970

esp = ROOT / "out" / "qemu-tables-dry"
if esp.exists():
    shutil.rmtree(esp)
shutil.copytree(BASE_ESP, esp)
shutil.copy2(KERNEL, esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho")

config = esp / "EFI" / "UniXNU" / "unixnu.toml"
text = config.read_text(encoding="utf-8")
text = re.sub(r'^default = "xnu"$', 'default = "exit"', text, flags=re.M)
text = re.sub(r"^timeout = \d+$", "timeout = 300", text, flags=re.M)
text = re.sub(r'^args = "[^"]*"$', 'args = "-v cpus=1 lumia-bars2 skmem_sysctl_skip=1 lumia-early-map-dry"',
              text, flags=re.M)
config.write_text(text, encoding="utf-8")

output = ROOT / "out" / "qemu-tables-dry-run"
if output.exists():
    shutil.rmtree(output)
subprocess.run([sys.executable, "scripts/test-native-xnu-entry.py",
                "--kernel", str(esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho"),
                "--esp", str(esp),
                "--firmware", r"C:\Program Files\qemu\share\edk2-aarch64-code.fd",
                "--output", str(output),
                "--qemu", r"C:\Program Files\qemu\qemu-system-aarch64.exe",
                "--dump-dmesg",
                "--adt-profile", "qemu", "--memory", "2816", "--smp", "2", "--timeout", "300",
                "--gdb-transport", "tcp",
                "--break-at", f"0x{PE_INIT_PLATFORM:x}",
                "--read-at", "0xFFFFFFF00718D000:128"], capture_output=True, text=True)

report = json.loads((output / "report.json").read_text(encoding="utf-8"))
registers = report.get("system_registers") or {}
print("stop:", report.get("stop_symbols"), "| ttbr0:", registers.get("ttbr0_el1"), "| ttbr1:", registers.get("ttbr1_el1"))
raw = next(iter((report.get("read") or {}).values()), "")
if raw:
    words = [int.from_bytes(bytes.fromhex(raw[index:index + 16]), "little") for index in range(0, len(raw) // 2, 16)]
    descriptors = {0: "invalid", 1: "block", 3: "table"}
    for index, word in enumerate(words[:8]):
        kind = descriptors.get(word & 3, "reserved")
        print(f"   entry {index}: {word:#018x} {kind}")
else:
    print("no table bytes read back")
