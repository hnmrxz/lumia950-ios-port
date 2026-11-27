r"""Read vinfo at the moment PE_init_platform() returns, in QEMU.

The question the handset raised: when the platform expert has run, is vinfo.v_baseaddr a mapped virtual address, or zero? The
source says initialize_screen() calls ml_io_map_unmappable() when kernel_map == VM_MAP_NULL, which is the state before
arm_vm_init, and sets v_baseaddr from its result. This run stops the kernel at the instruction after that call and dumps the
struct, so the answer is measured rather than inferred.

    python scripts/read-vinfo-early.py
"""

import json
import pathlib
import re
import shutil
import struct
import subprocess
import sys

ROOT = pathlib.Path(".").resolve()
KERNEL = ROOT / "out" / "earlybar" / "mach.development.bcm2837.unstripped"


def symbol(name: str) -> int:
    data = KERNEL.read_bytes()
    magic, _cpu, _sub, _filetype, ncmds, _sizeofcmds, _flags, _res = struct.unpack_from("<IiiIIIII", data, 0)
    offset = 32
    symtab = None
    for _ in range(ncmds):
        command, length = struct.unpack_from("<II", data, offset)
        if command == 0x02:  # LC_SYMTAB
            symtab = struct.unpack_from("<IIII", data, offset + 8)
        offset += length
    if symtab is None:
        raise SystemExit("kernel has no symbol table")
    symoff, nsyms, stroff, strsize = symtab
    for index in range(nsyms):
        entry = symoff + index * 16
        strx, ntype, nsect, desc, value = struct.unpack_from("<IBBHQ", data, entry)
        if value == 0:
            continue
        start = stroff + strx
        end = data.find(b"\0", start)
        if data[start:end].decode("utf-8", "replace") == name:
            return value
    raise SystemExit(f"symbol {name} not found")


esp = ROOT / "out" / "qemu-vinfo-early"
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
config.write_text(text, encoding="utf-8")

# stop where the platform expert has returned: wfe_timeout_configure() is the next statement in arm_init
stop = symbol("_wfe_timeout_configure")
print(f"break at _wfe_timeout_configure = 0x{stop:x}")

output = ROOT / "out" / "qemu-vinfo-early-run"
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
                "--gdb-transport", "tcp",
                "--break-at", hex(stop), "--read-at", "0xfffffff007af17e8:128"], check=False)

report = json.loads((output / "report.json").read_text(encoding="utf-8"))
print("stop symbols:", report.get("stop_symbols"))
print("watched:", report.get("watched"))
reads = report.get("read") or report.get("reads") or {}
print("reads keys:", list(reads) if isinstance(reads, dict) else reads)
raw = reads.get("0xfffffff007af17e8") if isinstance(reads, dict) else None
if raw:
    data = bytes.fromhex(raw) if isinstance(raw, str) else bytes(raw)
    print("vinfo bytes:", data[:96].hex())
    # struct vc_info: v_height, v_width, v_depth, v_rowbytes, v_baseaddr, ...
    height, width, depth, rowbytes = struct.unpack_from("<IIII", data, 0)
    baseaddr = struct.unpack_from("<Q", data, 16)[0]
    print(f"  v_height={height} v_width={width} v_depth={depth} v_rowbytes={rowbytes} v_baseaddr=0x{baseaddr:x}")
