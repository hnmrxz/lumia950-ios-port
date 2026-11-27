"""Read the leaf table the marker installed, at the physical page its table entry points at.

The dry run landed entry 3 as a table at physical 0x48b5c000. This reads that page (as a virtual address through the kernel's own mapping
delta) to see whether the leaf block entry for the framebuffer is really there.
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
BOOTSTRAP_VA = 0xFFFFFFF00718D000
BOOTSTRAP_PA = 0x4818D000
LEAF_PA = 0x48B5C000

leaf_va = BOOTSTRAP_VA - BOOTSTRAP_PA + LEAF_PA + 352 * 8
print(f"reading leaf table at VA {leaf_va:#x}")

esp = ROOT / "out" / "qemu-tables-leaf"
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

output = ROOT / "out" / "qemu-tables-leaf-run"
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
                "--read-at", f"0x{leaf_va:x}:64"], capture_output=True, text=True)

report = json.loads((output / "report.json").read_text(encoding="utf-8"))
raw = next(iter((report.get("read") or {}).values()), "")
if raw:
    words = [int.from_bytes(bytes.fromhex(raw[index:index + 16]), "little") for index in range(0, len(raw) // 2, 16)]
    descriptors = {0: "invalid", 1: "block", 3: "table"}
    for index, word in enumerate(words[:4], start=352):
        kind = descriptors.get(word & 3, "reserved")
        print(f"   leaf entry {index}: {word:#018x} {kind} address {{}}".format(hex(word & 0x0000FFFFFFFFF000)))
else:
    print("no bytes read back")
