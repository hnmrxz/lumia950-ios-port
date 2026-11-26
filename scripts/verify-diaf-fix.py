r"""Boot the freshly built kernel with the phone's own configuration and judge the DAIF fix.

The point of this check is a single question: after the bar is painted, does the kernel now get past the allocation that used
to trip 'Calling {k,z}alloc from interrupt disabled context isn't allowed'? The bar must still be there -- a fix that removes
the bar would be worse than the bug.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(".").resolve()
kernel_root = ROOT / "out" / "daif-check"
kernel = kernel_root / "mach.development.bcm2837.unstripped"

if not kernel.is_file():
    print(f"error: no kernel at {kernel}; run: gh run download <id> -n lumia950-kernel-unstripped -D {kernel_root}")
    sys.exit(2)

esp = ROOT / "out" / "qemu-daif-check"
if esp.exists():
    shutil.rmtree(esp)
(esp / "EFI" / "BOOT").mkdir(parents=True)
shutil.copy2("R:/EFI/BOOT/BOOTAA64.EFI", esp / "EFI" / "BOOT" / "BOOTAA64.EFI")
shutil.copytree("R:/EFI/UniXNU", esp / "EFI" / "UniXNU")
(esp / "EFI" / "UniXNU" / "Payloads").mkdir(exist_ok=True)
shutil.copy2("H:/EFI/UniXNU/Payloads/kernel.macho.adt", esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho.adt")
shutil.copy2(kernel, esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho")

config = esp / "EFI" / "UniXNU" / "unixnu.toml"
text = config.read_text(encoding="utf-8")
text = re.sub(r'^default = "xnu"$', 'default = "exit"', text, flags=re.M)
text = re.sub(r"^timeout = \d+$", "timeout = 300", text, flags=re.M)
config.write_text(text, encoding="utf-8")
print("staged:", kernel.stat().st_size, "bytes with the phone's config")

run = ROOT / "out" / "qemu-daif-check-run"
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
print("panic:", report.get("panic_format"), report.get("panic_string_args"))

data = (run / "framebuffer.bin").read_bytes()
stride = len(data) // 600
bright = 0
for y in range(600 - 16, 600):
    row = data[y * stride:(y + 1) * stride]
    for x in range(0, len(row), 4):
        if row[x] + row[x + 1] + row[x + 2] > 60:
            bright += 1
print("bottom 16 rows bright pixels:", bright)
verdict = "ok" if "kalloc from interrupt disabled" not in json.dumps(report) else "still panicking"
print("verdict:", verdict)
