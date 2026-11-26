"""Extract the embedded kext container from the unstripped kernel and place it in the merged image.

Everything here is local: the kernel we boot carries the mkext (the kernel prints its size), so the container can be pulled
out of it, the kext executable inside it can be found by its Mach-O magic, and its kmod record address computed from the
symbol table.
"""

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(".")


def module(path: str):
    spec = importlib.util.spec_from_file_location(pathlib.Path(path).stem.replace("-", "_"), ROOT / path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


check_kext = module("scripts/check-kext.py")

kernel = (ROOT / "out" / "unstripped9" / "mach.development.bcm2837.unstripped").read_bytes()
print("kernel:", len(kernel))

anchor = kernel.find(b"MKXT")
print("MKXT at", anchor)
if anchor < 0:
    raise SystemExit("the container is not in this kernel")

# the mkext header is big-endian: magic, signature, length, adler32, version, ...
import struct

magic, signature, length, checksum = struct.unpack_from(">IIII", kernel, anchor)
print(f"magic=0x{magic:08X} signature=0x{signature:08X} length={length} checksum=0x{checksum:08X}")
container = kernel[anchor: anchor + length]
print("container bytes:", len(container))
(ROOT / "out" / "prelinked-test" / "extracted.mkext").write_bytes(container)

# the executable inside is a Mach-O; take the first one that parses
start = 0
found = None
while True:
    at = container.find(b"\xCF\xFA\xED\xFE", start)
    if at < 0:
        break
    try:
        info = check_kext.read_macho(container[at:])
    except (ValueError, IndexError, struct.error):
        start = at + 4
        continue
    if "_kmod_info" in info["values"] or "kmod_info" in info["values"]:
        name = "_kmod_info" if "_kmod_info" in info["values"] else "kmod_info"
        found = (at, info, name)
        break
    start = at + 4

if found is None:
    raise SystemExit("no Mach-O with a kmod record inside the container")

at, info, name = found
print(f"executable at container offset {at}: {len(info['segments'])} segments, kmod {name} at 0x{info['values'][name]:x}")

# the executable's real size: the end of its last file-backed segment, not "everything that follows". read_macho
# reports segment names, so the geometry comes from the segment table directly.
inspect_prelink = module("scripts/inspect-prelink.py")
geometry = inspect_prelink.segments(container[at:])
end = max((segment["fileoff"] + segment["filesize"] for segment in geometry if segment["filesize"]), default=0)
size = end if 0 < end <= len(container) - at else len(container) - at
if geometry:
    print("segments:", [(segment["name"], hex(segment["vmaddr"]), hex(segment["filesize"])) for segment in geometry])
executable = container[at: at + size]
(ROOT / "out" / "prelinked-test" / "extracted-kext").write_bytes(executable)
print("extracted executable:", len(executable), "bytes ->", ROOT / "out" / "prelinked-test" / "extracted-kext")
print("kmod record offset within the executable: 0x%x" % info["values"][name])
