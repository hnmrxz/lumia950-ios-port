r"""Does the pre-MMU bar actually work?

Stages 0 and 1 are gated on the 'lumia-bars' token while the deployed config passes 'lumia-bars2', so they have never run -- in
emulation or on the handset. That matters now: stage 0 is the earliest marker the kernel can leave (it runs before
PE_init_platform), so if it works it would tell us whether the kernel starts at all on hardware.

This boots the deployed payload with 'lumia-bars' added and looks for the bar at rows 120-140 as well as for a fault at the
store. Both answers are useful: a bar means the marker is usable; a fault means the store path needs a mapping and the marker
has to be dropped.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(".").resolve()
esp = ROOT / "out" / "qemu-bars1"
if esp.exists():
    shutil.rmtree(esp)
(esp / "EFI" / "BOOT").mkdir(parents=True)
shutil.copy2("R:/EFI/BOOT/BOOTAA64.EFI", esp / "EFI" / "BOOT" / "BOOTAA64.EFI")
shutil.copytree("R:/EFI/UniXNU", esp / "EFI" / "UniXNU")
(esp / "EFI" / "UniXNU" / "Payloads").mkdir(exist_ok=True)
for name in ("kernel.macho", "kernel.macho.adt"):
    shutil.copy2(f"H:/EFI/UniXNU/Payloads/{name}", esp / "EFI" / "UniXNU" / "Payloads" / name)

config = esp / "EFI" / "UniXNU" / "unixnu.toml"
text = config.read_text(encoding="utf-8")
text = re.sub(r'^default = "xnu"$', 'default = "exit"', text, flags=re.M)
text = re.sub(r"^timeout = \d+$", "timeout = 300", text, flags=re.M)
text = re.sub(r'^args = "([^"]*)"$',
              lambda match: f'args = "{match.group(1).replace("lumia-bars2", "lumia-bars")}"', text, flags=re.M)
config.write_text(text, encoding="utf-8")
print("args:", [line for line in text.splitlines() if line.startswith("args")][0])

run = ROOT / "out" / "qemu-bars1-run"
if run.exists():
    shutil.rmtree(run)
subprocess.run([sys.executable, "scripts/test-native-xnu-entry.py",
                "--kernel", str(esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho"),
                "--esp", str(esp),
                "--firmware", r"C:\Program Files\qemu\share\edk2-aarch64-code.fd",
                "--output", str(run),
                "--qemu", r"C:\Program Files\qemu\qemu-system-aarch64.exe",
                "--crypto-post", "--past-bsd", "--dump-dmesg", "--dump-framebuffer",
                "--adt-profile", "qemu", "--memory", "2816", "--smp", "2", "--timeout", "300",
                "--gdb-transport", "tcp"], check=False)

report_path = run / "report.json"
if not report_path.is_file():
    print("no report; see", run)
    sys.exit(1)
report = json.loads(report_path.read_text(encoding="utf-8"))
print("past_bsd:", report.get("past_bsd_outcome"), "| stop:", report.get("stop_symbols"),
      "| fault:", report.get("fault_elr_symbol"))

frame = run / "framebuffer.bin"
if frame.is_file():
    data = frame.read_bytes()
    stride = len(data) // 600
    def bright(y0, y1):
        return sum(1 for y in range(y0, y1) for x in range(0, stride, 4)
                   if data[y * stride + x] + data[y * stride + x + 1] + data[y * stride + x + 2] > 60)
    print("rows 120-140 bright:", bright(120, 140))
    print("bottom 16 rows bright:", bright(584, 600))
