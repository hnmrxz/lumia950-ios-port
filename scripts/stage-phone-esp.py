r"""Boot exactly what is on the phone, in emulation.

The phone holds the loader, the UniXNU tree (menu, drivers, config) and a kernel that were never run together here. The first
attempt copied only the config and the payload and the menu reported 'no loader protocol installed' -- because
\EFI\UniXNU\Drivers\DarwinBoot.efi was not in the staged tree, not because of anything on the phone. This copies the tree as
it actually is.
"""

import pathlib
import re
import shutil

ROOT = pathlib.Path(".").resolve()
esp = ROOT / "out" / "qemu-phone-esp"
if esp.exists():
    shutil.rmtree(esp)
(esp / "EFI" / "BOOT").mkdir(parents=True)

shutil.copy2("R:/EFI/BOOT/BOOTAA64.EFI", esp / "EFI" / "BOOT" / "BOOTAA64.EFI")
shutil.copytree("R:/EFI/UniXNU", esp / "EFI" / "UniXNU")
# the phone keeps the payload on the other volume; the staged tree needs both in one place
(esp / "EFI" / "UniXNU" / "Payloads").mkdir(exist_ok=True)
for name in ("kernel.macho", "kernel.macho.adt"):
    shutil.copy2(f"H:/EFI/UniXNU/Payloads/{name}", esp / "EFI" / "UniXNU" / "Payloads" / name)

config = esp / "EFI" / "UniXNU" / "unixnu.toml"
text = config.read_text(encoding="utf-8")
text = re.sub(r'^default = "xnu"$', 'default = "exit"', text, flags=re.M)
text = re.sub(r"^timeout = \d+$", "timeout = 300", text, flags=re.M)
config.write_text(text, encoding="utf-8")

print("staged:", sorted(str(path.relative_to(esp)) for path in esp.rglob("*") if path.is_file()))
