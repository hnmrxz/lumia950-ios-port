r"""Does adding the skmem arguments to the phone's own config get past the kzalloc panic?

The deployed config says `args = "-v cpus=1 lumia-bars2"` and the emulated boot of exactly that reaches bsd_init and then
panics with 'Calling {k,z}alloc from interrupt disabled context isn't allowed'. The CI has worked around that for many rounds
with skmem_* boot arguments; this checks whether the phone's config with those added gets further, so the next handset boot
is worth more than one screenshot.
"""

import pathlib
import re
import shutil

ROOT = pathlib.Path(".").resolve()
SKMEM = ("skmem_seg_size=16384 skmem_md_seg_size=16384 skmem_drv_buf_seg_size=65536 "
         "skmem_usr_buf_seg_size=16384 skmem_sysctl_skip=1")

esp = ROOT / "out" / "qemu-phone-esp-skmem"
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
text = re.sub(r'^args = "([^"]*)"$', lambda m: f'args = "{m.group(1)} {SKMEM}"', text, flags=re.M)
config.write_text(text, encoding="utf-8")
print("args now:", [line for line in text.splitlines() if line.startswith("args")])
