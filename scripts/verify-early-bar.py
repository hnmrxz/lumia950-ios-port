r"""Positive and negative control for the early bar, in QEMU.

The bar is drawn from `vinfo.v_baseaddr` right after PE_init_platform(). Two questions have to be answered before the handset is
asked anything:

  positive: with 'lumia-early-bar' in the arguments, does the bar appear at rows 120..135 of the panel?
  negative: without the argument, are those rows free of the bar's colour, so the bar cannot be confused with console text?

Both runs use the same kernel, the same staged tree and the same memory size; only the argument differs.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(".").resolve()
KERNEL = ROOT / "out" / "earlybar" / "mach.development.bcm2837.unstripped"

# kFirstBarY = 120, kBarHeight = 16, colour {0x00E03030} for the first stage (BootProgressCore.h)
BAR_ROWS = (120, 136)
BAR_RGB = (0xE0, 0x30, 0x30)


def stage(extra: str, name: str) -> pathlib.Path:
    esp = ROOT / "out" / f"qemu-earlybar-{name}"
    if esp.exists():
        shutil.rmtree(esp)
    (esp / "EFI" / "BOOT").mkdir(parents=True)
    shutil.copy2("R:/EFI/BOOT/BOOTAA64.EFI", esp / "EFI" / "BOOT" / "BOOTAA64.EFI")
    shutil.copytree("R:/EFI/UniXNU", esp / "EFI" / "UniXNU")
    (esp / "EFI" / "UniXNU" / "Payloads").mkdir(exist_ok=True)
    shutil.copy2("H:/EFI/UniXNU/Payloads/kernel.macho.adt", esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho.adt")
    shutil.copy2(KERNEL, esp / "EFI" / "UniXNU" / "Payloads" / "kernel.macho")

    config = esp / "EFI" / "UniXNU" / "unixnu.toml"
    text = config.read_text(encoding="utf-8")
    text = re.sub(r'^default = "xnu"$', 'default = "exit"', text, flags=re.M)
    text = re.sub(r"^timeout = \d+$", "timeout = 300", text, flags=re.M)
    text = re.sub(r"^args = \"[^\"]*\"$", f'args = "-v cpus=1 lumia-bars2 skmem_sysctl_skip=1 {extra}"'.rstrip(),
                  text, flags=re.M)
    config.write_text(text, encoding="utf-8")
    return esp


def run(esp: pathlib.Path, name: str) -> dict:
    output = ROOT / "out" / f"qemu-earlybar-{name}-run"
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
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    frame = (output / "framebuffer.bin").read_bytes()
    height = 600
    stride = len(frame) // height
    count = 0
    for y in range(BAR_ROWS[0], BAR_ROWS[1]):
        row = frame[y * stride:(y + 1) * stride]
        for x in range(0, len(row), 4):
            if (abs(row[x] - BAR_RGB[2]) < 16 and abs(row[x + 1] - BAR_RGB[1]) < 16
                    and abs(row[x + 2] - BAR_RGB[0]) < 16):
                count += 1
    return {"report": report, "bar_pixels": count, "output": output}


pos_esp = stage("lumia-early-bar", "pos")
pos = run(pos_esp, "pos")
print("positive: bar pixels in rows 120-135:", pos["bar_pixels"],
      "| past_bsd:", pos["report"].get("past_bsd_outcome"),
      "| stop:", pos["report"].get("stop_symbols"))

neg_esp = stage("", "neg")
neg = run(neg_esp, "neg")
print("negative: bar pixels in rows 120-135:", neg["bar_pixels"],
      "| past_bsd:", neg["report"].get("past_bsd_outcome"),
      "| stop:", neg["report"].get("stop_symbols"))

print()
print("verdict:", "positive control ok" if pos["bar_pixels"] > 1000 else "POSITIVE CONTROL FAILED")
print("         ", "negative control ok" if neg["bar_pixels"] < 100 else "NEGATIVE CONTROL FAILED")
