#!/usr/bin/env python3
"""Insert one entry into a merged image's prelink dictionary, without touching anything else.

The dictionary inside `__PRELINK_INFO` is an XML fragment, and the segment has slack: on the pinned merged image the text is
108,416 bytes inside a 110,592-byte segment, so 2,176 bytes can be added before the segment has to grow. This tool inserts a
new `<dict>` before the closing `</array>` of `_PrelinkInfoDictionary`, shifts the remainder (the KCID and friends) to the
right, and writes the slack back as zeros -- every existing byte other than the insertion point is left exactly as it was.

What it does NOT do, on purpose: place a kext executable. A real entry needs `_PrelinkExecutableLoadAddr` to point at the
module's mapped text inside the image, and that means choosing an address, appending segments and fixing PC-relative
instructions -- the prelinker work ADR-0003 describes. This tool exists so that the dictionary half is done and testable
before that work starts.

    python scripts/add-prelink-entry.py --image merged.macho --bundle-id org.unixnu.NativeSdhci \
        --load-addr 0xfffffff0082cc000 --size 0x2000 --output merged-with-sdhci.macho
"""

from __future__ import annotations

import argparse
import plistlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib.util

spec = importlib.util.spec_from_file_location("inspect_prelink", Path(__file__).resolve().parent / "inspect-prelink.py")
inspect_prelink = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = inspect_prelink
spec.loader.exec_module(inspect_prelink)

ARRAY_CLOSE = b"</array>"


KPI_LIBRARIES = {
    "com.apple.kpi.bsd": "8.0",
    "com.apple.kpi.iokit": "8.0",
    "com.apple.kpi.libkern": "8.0",
    "com.apple.kpi.mach": "8.0",
    "com.apple.kpi.private": "8.0",
    "com.apple.kpi.unsupported": "8.0",
}


def entry_xml(bundle_id: str, load_addr: int, size: int, executable: str = "NativeSdhci",
              version: str = "0.1.0", kmod_info: int | None = None,
              source_addr: int | None = None) -> bytes:
    """A complete kext entry.

    Two loader complaints shaped this list. The first insertion had no CFBundleVersion and the kernel said
    'Kext org.unixnu.NativeSdhci error - CFBundleVersion missing/invalid type'; adding it moved the complaint to
    'can not find prelinked kext kmod_info address', which is _PrelinkKmodInfo -- the address of the module's record, i.e.
    the load address plus the module's own offset.
    """
    libraries = "".join(f"<key>{name}</key><string>{wanted}</string>" for name, wanted in KPI_LIBRARIES.items())
    fields = [
        "<dict>",
        f"<key>CFBundleIdentifier</key><string>{bundle_id}</string>",
        f"<key>CFBundleVersion</key><string>{version}</string>",
        f"<key>CFBundleExecutable</key><string>{executable}</string>",
        "<key>CFBundlePackageType</key><string>KEXT</string>",
        f"<key>OSBundleLibraries</key><dict>{libraries}</dict>",
        f'<key>_PrelinkExecutableLoadAddr</key><integer size="64">0x{load_addr:x}</integer>',
        f'<key>_PrelinkExecutableSize</key><integer size="64">0x{size:x}</integer>',
        f"<key>_PrelinkBundlePath</key><string>/System/Library/Extensions/{bundle_id}.kext</string>",
    ]
    if kmod_info is not None:
        fields.append(f'<key>_PrelinkKmodInfo</key><integer size="64">0x{kmod_info:x}</integer>')
    if source_addr is not None:
        fields.append(f'<key>_PrelinkExecutableSourceAddr</key><integer size="64">0x{source_addr:x}</integer>')
    fields.append("</dict>")
    return "".join(fields).encode("utf-8")


def _dictionary_array_end(text: bytes) -> int:
    """The offset of the </array> that closes _PrelinkInfoDictionary.

    A plain find() is wrong: entries contain nested arrays of their own, so the first </array> in the file can belong to a
    kext's personality list. This walks the tags after the key and returns the matching close.
    """
    key = text.find(b"<key>_PrelinkInfoDictionary</key>")
    if key < 0:
        return -1
    start = text.find(b"<array>", key)
    if start < 0:
        return -1
    depth = 0
    offset = start
    while offset < len(text):
        open_at = text.find(b"<array>", offset)
        close_at = text.find(b"</array>", offset)
        if close_at < 0:
            return -1
        if 0 <= open_at < close_at:
            depth += 1
            offset = open_at + len(b"<array>")
        else:
            depth -= 1
            if depth == 0:
                return close_at
            offset = close_at + len(b"</array>")
    return -1

def insert(image: bytes, bundle_id: str, load_addr: int, size: int,
           kmod_info: int | None = None, source_addr: int | None = None) -> tuple[bytes, dict]:
    payload_start, segment = _locate(image)
    text = image[payload_start: payload_start + segment["filesize"]].rstrip(b"\0")
    if b"_PrelinkInfoDictionary" not in text:
        raise ValueError("the segment does not contain _PrelinkInfoDictionary")
    at = _dictionary_array_end(text)
    if at < 0:
        raise ValueError("no closing </array> for _PrelinkInfoDictionary")
    entry = entry_xml(bundle_id, load_addr, size, kmod_info=kmod_info, source_addr=source_addr)
    updated = text[:at] + entry + text[at:]
    if len(updated) > segment["filesize"]:
        raise ValueError(f"the entry does not fit: {len(updated)} > {segment['filesize']} bytes of segment")
    padded = updated + b"\0" * (segment["filesize"] - len(updated))
    output = bytearray(image)
    output[payload_start: payload_start + segment["filesize"]] = padded
    return bytes(output), {"inserted_at": at, "segment_size": segment["filesize"], "used": len(updated)}


def _locate(image: bytes) -> tuple[int, dict]:
    table = inspect_prelink.segments(image)
    segment = next((entry for entry in table if entry["name"] == inspect_prelink.PRELINK_INFO_SEGMENT), None)
    if segment is None:
        raise ValueError("no __PRELINK_INFO segment")
    return segment["fileoff"], segment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--load-addr", required=True, type=lambda value: int(value, 0))
    parser.add_argument("--size", required=True, type=lambda value: int(value, 0))
    parser.add_argument("--kmod-info", type=lambda value: int(value, 0),
                        help="address of the module's kmod_info record (load address plus its offset)")
    parser.add_argument("--source-addr", type=lambda value: int(value, 0),
                        help="the module's own vmaddr for that record, before placement")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    if not args.image.is_file():
        print(f"error: no image at {args.image}", file=sys.stderr)
        return 2
    image = args.image.read_bytes()
    try:
        updated, detail = insert(image, args.bundle_id, args.load_addr, args.size,
                                 kmod_info=args.kmod_info, source_addr=args.source_addr)
    except ValueError as error:
        print(f"FAIL {args.image}: {error}")
        return 1

    # read it back before writing: a dictionary that does not parse is worse than no change at all
    try:
        payload, _ = inspect_prelink.prelink_info(updated)
        parsed = inspect_prelink.parse_dictionary(payload)
        rows = inspect_prelink.summarise(parsed)
        found = next((row for row in rows if row["id"] == args.bundle_id), None)
        if found is None:
            raise ValueError("the inserted entry does not read back")
    except (ValueError, plistlib.InvalidFileException) as error:
        print(f"FAIL {args.image}: the edited dictionary does not parse: {error}")
        return 1

    args.output.write_bytes(updated)
    print(f"{args.output}: inserted {args.bundle_id} at offset {detail['inserted_at']}, "
          f"{detail['used']} of {detail['segment_size']} bytes used; {len(rows)} entries parse back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
