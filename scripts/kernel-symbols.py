"""Resolve kernel symbols so the fixture can be pointed at an address.

The fixture's --break-at takes an address, not a name, and --read takes a symbol or an address:pair. This reads the unstripped kernel's
Mach-O symbol table and prints the addresses the trace needs.
"""

import struct
import sys
from pathlib import Path

PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "out/refuse/mach.development.bcm2837.unstripped")
WANTED = sys.argv[2:] or ["_PE_init_platform", "_arm_vm_init", "_arm_init", "_bootstrap_pagetables",
                          "_panic", "_sleh_synchronous_sp1"]

data = PATH.read_bytes()
magic, _cpu, _subtype, _filetype, ncmds, _sizeofcmds, _flags, _reserved = struct.unpack_from("<IiiIIIII", data, 0)
assert magic == 0xFEEDFACF, f"unexpected Mach-O magic {magic:#x}"

offset = 32
symtab = None
for _ in range(ncmds):
    cmd, cmdsize = struct.unpack_from("<II", data, offset)
    if cmd == 0x2:
        symtab = struct.unpack_from("<IIII", data, offset + 8)
    offset += cmdsize

symoff, nsyms, stroff, strsize = symtab
strings = data[stroff:stroff + strsize]

found = {}
for index in range(nsyms):
    entry = symoff + index * 16
    strx, _ntype, sect, _desc, value = struct.unpack_from("<IBBHQ", data, entry)
    if value == 0 or sect == 0:
        continue
    end = strings.find(b"\0", strx)
    name = strings[strx:end].decode("utf-8", "replace")
    if name in WANTED and name not in found:
        found[name] = value

for name in WANTED:
    print(f"{name} = 0x{found[name]:x}" if name in found else f"{name} = (not found)")
