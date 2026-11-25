#!/usr/bin/env python3
import argparse
import hashlib
import hmac
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
# scripts/ is not a package; the shared ADT profile resolver is one file beside this one.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from board_profile import resolve_profile  # noqa: E402  (import after the path is set)
import menu_render  # noqa: E402

CRYPTO_SYMBOLS = {"_source_corecrypto14_bootstrap", "_source_corecrypto14_status", "_corecrypto_kext_start"}


def adt_command(profile, adt, unique_chip_id):
    """The generator flags for this profile.

    Kept as a function, not inlined: scripts/test-adt-profile.py runs both this and the one in
    scripts/stage-kernel.py and requires them to agree flag for flag. They used to disagree about
    the CPU count and the PSCI conduit, so the tree CI checked was not the tree the phone ran.
    """
    command = [sys.executable, str(ROOT / profile["tool"]), "--output", str(adt),
               "--dram-size", hex(profile["dram_size"])]
    if profile.get("owned_memory_size") is not None:
        command += ["--owned-memory-size", hex(profile["owned_memory_size"])]
    if profile.get("cpu_regs"):
        command += ["--cpu-regs", str(profile["cpu_regs"])]
    if profile.get("psci_method"):
        command += ["--psci-method", str(profile["psci_method"])]
    if profile.get("chip_id") is not None:
        command += ["--chip-id", hex(profile["chip_id"])]
    if profile.get("dram_base") is not None:
        command += ["--dram-base", hex(profile["dram_base"])]
    # Only an emulated profile carries these; on the phone the generator's defaults are the SoC's.
    if profile.get("gic_distributor"):
        command += ["--gic-distributor", str(profile["gic_distributor"])]
    if profile.get("gic_cpu_interface"):
        command += ["--gic-cpu-interface", str(profile["gic_cpu_interface"])]
    if profile.get("soc_base"):
        command += ["--soc-base", hex(profile["soc_base"])]
    command += ["--unique-chip-id", unique_chip_id]
    return command


# Evidence-only: see the __PRELINK branch inside contract().
ALLOW_PRELINKED = False


def contract(blob):
    if len(blob) < 32:
        raise ValueError("short Mach-O")
    magic, cpu, subtype, kind, count, length = struct.unpack_from("<6I", blob)
    if (magic, cpu, subtype, kind) != (0xFEEDFACF, 0x0100000C, 0, 2):
        raise ValueError("requires ARM64_ALL MH_EXECUTE, not arm64e or a container")
    if not count or count > 256 or not length or length > len(blob) - 32:
        raise ValueError("invalid Mach-O commands")
    offset, end = 32, 32 + length
    segments, symbols, crypto_symbols, entry = {}, {}, {}, None
    for _ in range(count):
        if offset + 8 > end:
            raise ValueError("truncated command")
        command, size = struct.unpack_from("<II", blob, offset)
        if size < 8 or size % 8 or offset + size > end:
            raise ValueError("invalid command extent")
        if command == 0x19:
            if size < 72:
                raise ValueError("short segment command")
            name = blob[offset + 8:offset + 24].split(b"\0")[0].decode("ascii")
            address, span, file_offset, file_size, maximum, protection, sections = struct.unpack_from("<QQQQIII", blob, offset + 24)
            if name in segments or sections > (size - 72) // 80:
                raise ValueError("duplicate segment or invalid section count")
            if file_size > span or file_offset > len(blob) or file_size > len(blob) - file_offset:
                raise ValueError("invalid segment file range")
            if address + span > (1 << 64) or address % 4096 or protection & ~maximum:
                raise ValueError("invalid virtual segment")
            if (name.startswith("__PRELINK") or name.startswith("__PLK_")) and (span or file_size):
                # A merged image is refused for the handset route because its segments carry Apple
                # kernelcache content. A caller that only asks what the image reaches (the QEMU evidence
                # boot) may set ALLOW_PRELINKED; the segment is then kept rather than rejected. Every other
                # contract violation still raises.
                if not ALLOW_PRELINKED:
                    raise ValueError(
                        "merged/prelinked kernel refused; its runtime qualification gate is not bypassed")
            segments[name] = {"address": address, "span": span, "file_offset": file_offset,
                              "file_size": file_size, "protection": protection}
        elif command == 5:
            if entry is not None or size != 288 or struct.unpack_from("<II", blob, offset + 8) != (6, 68):
                raise ValueError("invalid ARM64 thread entry")
            entry = struct.unpack_from("<Q", blob, offset + 272)[0]
        elif command == 2:
            if size != 24:
                raise ValueError("invalid symbol command")
            table, entries, strings, string_bytes = struct.unpack_from("<4I", blob, offset + 8)
            if table + entries * 16 > len(blob) or strings + string_bytes > len(blob):
                raise ValueError("invalid symbol table")
            for index in range(entries):
                name_offset, symbol_type, section, description, value = struct.unpack_from("<IBBHQ", blob, table + index * 16)
                if symbol_type & 0xE0 or not name_offset:
                    continue
                if name_offset >= string_bytes:
                    raise ValueError("invalid symbol name")
                stop = blob.find(b"\0", strings + name_offset, strings + string_bytes)
                if stop < 0:
                    raise ValueError("unterminated symbol")
                name = blob[strings + name_offset:stop].decode("utf-8")
                if symbol_type & 0x0E == 0:
                    raise ValueError(f"unresolved native symbol: {name}")
                if name in CRYPTO_SYMBOLS and symbol_type & 0x0E == 0x0E:
                    if name in crypto_symbols:
                        raise ValueError("ambiguous source crypto symbol")
                    crypto_symbols[name] = value
                if symbol_type & 1:
                    if name in symbols and symbols[name] != value:
                        raise ValueError("ambiguous external symbol")
                    symbols[name] = value
        offset += size
    if offset != end or entry is None or entry & 3 or not segments or not symbols:
        raise ValueError("missing entry, segments or native symbol table")
    live = [value for value in segments.values() if value["span"]]
    for index, segment in enumerate(live):
        for previous in live[:index]:
            if segment["address"] < previous["address"] + previous["span"] and previous["address"] < segment["address"] + segment["span"]:
                raise ValueError("overlapping virtual segments")
    if not any(segment["protection"] & 4 and segment["address"] <= entry < segment["address"] + segment["file_size"] for segment in live):
        raise ValueError("entry is not file-backed executable code")
    base = min(segment["address"] for segment in live)
    span = max(segment["address"] + segment["span"] for segment in live) - base
    if span > 512 * 1024 * 1024 - 2 * 1024 * 1024:
        raise ValueError("native kernel exceeds the loader's owned window")
    return {"entry": entry, "base": base, "span": span, "header_bytes": end,
            "segments": segments, "external_symbols": symbols, "source_crypto_symbols": crypto_symbols}


def crypto_contract(blob):
    parsed = contract(blob)
    if set(parsed["source_crypto_symbols"]) != CRYPTO_SYMBOLS:
        raise ValueError("source-only image lacks its real crypto bootstrap/provider symbols")
    code, integrity = None, None
    offset = 32
    for _ in range(struct.unpack_from("<I", blob, 16)[0]):
        command, length = struct.unpack_from("<II", blob, offset)
        if command == 0x19:
            for index in range(struct.unpack_from("<I", blob, offset + 64)[0]):
                section = offset + 72 + index * 80
                name, segment, address, size, position = struct.unpack_from("<16s16sQQI", blob, section)
                name, segment = name.rstrip(b"\0"), segment.rstrip(b"\0")
                if position > len(blob) or size > len(blob) - position:
                    if name in (b"__text", b"__fips_hmacs"):
                        raise ValueError("crypto code or integrity section outside the file")
                if name == b"__text" and segment in (b"__TEXT", b"__TEXT_EXEC") and code is None:
                    code = (position, size, address)
                if name == b"__fips_hmacs":
                    if integrity is not None or size != 32:
                        raise ValueError("source provider must have one 32-byte POST integrity field")
                    integrity = position
        offset += length
    if code is None or integrity is None or not code[1] or code[2] - parsed["base"] != code[0] or \
        code[0] <= integrity < code[0] + code[1]:
        raise ValueError("invalid source provider POST mapping")
    expected = hmac.digest(b"\0", blob[code[0]:code[0] + code[1]], "sha256")
    if not hmac.compare_digest(blob[integrity:integrity + 32], expected):
        raise ValueError("source provider POST integrity field is not sealed for these instructions")
    return {"hmac_sha256": expected.hex(), "code_bytes": code[1], "runtime_post_observed": False}


def verify_strip(original, stripped):
    before, after = contract(original), contract(stripped)
    if before["entry"] != after["entry"] or before["base"] != after["base"] or before["external_symbols"] != after["external_symbols"]:
        raise ValueError("stripping changed the entry, base or external symbol values")
    if before["segments"].keys() != after["segments"].keys():
        raise ValueError("stripping changed segment names")
    checked = 0
    for name, segment in before["segments"].items():
        if name == "__LINKEDIT":
            continue
        lean = after["segments"][name]
        for key in ["address", "span", "file_size", "protection"]:
            if segment[key] != lean[key]:
                raise ValueError(f"stripping changed {name} {key}")
        skip = before["header_bytes"] if segment["file_offset"] == 0 and segment["file_size"] else 0
        if skip != (after["header_bytes"] if lean["file_offset"] == 0 and lean["file_size"] else 0):
            raise ValueError("stripping changed load-command extent")
        size = segment["file_size"]
        if original[segment["file_offset"] + skip:segment["file_offset"] + size] != stripped[lean["file_offset"] + skip:lean["file_offset"] + size]:
            raise ValueError(f"stripping changed runtime bytes in {name}")
        checked += size - skip
    return checked, len(after["external_symbols"])


def menu_config(menu_tree):
    '''The test menu, rendered from the committed one rather than maintained beside it.

    This used to be a second configuration written out by hand: its own countdown (300 against
    20), its own title, `logo = false`, its own entry set. A change to the committed menu reached
    one staging path and not the other. Everything that genuinely differs is an argument here,
    and each one fails loudly if the committed file stops matching it.
    '''
    source = (Path(menu_tree) / "EFI/UniXNU/unixnu.toml").read_text()
    insert = ('[[driver]]\npath = "Drivers/DarwinBoot.efi"\n\n'
              '[[entry]]\nid = "gpu"\ntitle = "Native Adreno hardware test"\n'
              'type = "efi"\npath = "Drivers/LumiaGpuPower.efi"\n\n'
              '[[entry]]\nid = "xnu"\ntitle = "Experimental XNU kernel - no iOS userspace"\n'
              'type = "xnu"\npath = "Payloads/kernel.macho"\n'
              'args = "-v keepsyms=1 debug=0x100 cpus=1"\n')
    overrides = (
        # A test menu is picked by hand: 300 s leaves time to watch the panel and choose.
        ("timeout = 20", "timeout = 300", "boot countdown"),
        ('title = "UniXNU"', 'title = "Native Lumia 950"', "menu title"),
        ("logo = true", "logo = false", "logo flag"),
    )
    return menu_render.render(source, insert=insert, default="exit",
                              overrides=overrides, drop=menu_render.FIRMWARE_ACTIONS)


def verify_build_manifest(manifest_path, kernel_path, kernel_sha256, repo_commit=None):
    """Tie the kernel to the run that produced it.

    --kernel-sha256 proved the file did not change since the operator typed the hash; it did not
    prove CI produced the file. The manifest does: the kernel has to be one of the outputs that
    run recorded, with the hash it recorded, from a clean checkout of a named commit.
    """
    manifest_file = Path(manifest_path)
    if not manifest_file.is_file():
        raise ValueError(f"build manifest not found: {manifest_file}")
    manifest = json.loads(manifest_file.read_text())
    if manifest.get("schema") != "lumia950-build-manifest-v1":
        raise ValueError(f"{manifest_file} is not a lumia950 build manifest")
    inputs = manifest.get("inputs") or {}
    if inputs.get("repo_dirty"):
        raise ValueError(f"{manifest_file} describes a dirty checkout; the artifact cannot be "
                         "attributed to a commit")
    if repo_commit is not None and inputs.get("repo_commit") != repo_commit:
        raise ValueError(f"{manifest_file} was built from {inputs.get('repo_commit')}, not the "
                         f"checked-out {repo_commit}")
    name = Path(kernel_path).name
    recorded = {entry["sha256"]: entry["path"]
                for items in (manifest.get("outputs") or {}).values()
                for entry in items if Path(entry["path"]).name == name}
    if not recorded:
        raise ValueError(f"{manifest_file} records no {name}; this kernel is not an output of "
                         "the run that produced the manifest")
    if kernel_sha256 not in recorded:
        raise ValueError(f"{name} does not hash to the value {manifest_file} recorded for it "
                         f"({sorted(recorded)[0][:16]}...); the file is not the artifact that run "
                         "produced")
    return {
        "build_manifest_sha256": hashlib.sha256(manifest_file.read_bytes()).hexdigest(),
        "build_manifest_output": recorded[kernel_sha256],
        "build_repo_commit": inputs.get("repo_commit"),
        "build_framework_ref": inputs.get("framework_ref"),
        "build_kernelcache_sha256": inputs.get("kernelcache_sha256_expected"),
    }


def main():
    parser = argparse.ArgumentParser(description="Stage firmware-native GPU and source-only XNU bring-up; never installs or claims iOS")
    parser.add_argument("--kernel", required=True, type=Path)
    parser.add_argument("--kernel-sha256", required=True)
    parser.add_argument("--menu-tree", required=True, type=Path)
    parser.add_argument("--gpu", required=True, type=Path)
    parser.add_argument("--strip", default="/usr/bin/strip")
    parser.add_argument("--unique-chip-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--manifest", type=Path,
                        help="the build manifest from the run that produced --kernel; without it "
                             "the kernel hash is an operator claim, not provenance")
    parser.add_argument("--expect-repo-commit",
                        help="the commit this staging is meant to correspond to (the manifest "
                             "has to agree)")
    args = parser.parse_args()
    original = args.kernel.read_bytes()
    if hashlib.sha256(original).hexdigest() != args.kernel_sha256:
        raise ValueError("native kernel does not match the explicit source-build hash")
    provenance = {"build_manifest_sha256": None, "build_manifest_output": None,
                  "build_repo_commit": None, "build_framework_ref": None,
                  "build_kernelcache_sha256": None}
    if args.manifest is not None:
        provenance = verify_build_manifest(args.manifest, args.kernel, args.kernel_sha256,
                                           args.expect_repo_commit)
    else:
        print("note: no --manifest, so the kernel hash is an operator claim and the tree carries "
              "no record of the run that produced it")
    contract(original)
    crypto = crypto_contract(original)
    if args.out.exists():
        raise ValueError("output must be a new directory, not an existing ESP or installation")
    with tempfile.TemporaryDirectory(prefix="lumia-native-kernel-") as temporary:
        lean = Path(temporary) / "kernel.macho"
        subprocess.run([args.strip, "-S", "-o", str(lean), str(args.kernel)], check=True)
        stripped = lean.read_bytes()
    checked, symbols = verify_strip(original, stripped)
    if crypto_contract(stripped) != crypto:
        raise ValueError("debug stripping changed the source provider integrity contract")
    output = args.out.resolve()
    files = {
        "EFI/UniXNU/UniXNU.efi": (args.menu_tree / "EFI/UniXNU/UniXNU.efi").read_bytes(),
        "EFI/BOOT/BOOTAA64.EFI": (args.menu_tree / "EFI/UniXNU/UniXNU.efi").read_bytes(),
        "EFI/UniXNU/Drivers/DarwinBoot.efi": (args.menu_tree / "EFI/UniXNU/Drivers/DarwinBoot.efi").read_bytes(),
        "EFI/UniXNU/Drivers/LumiaGpuPower.efi": args.gpu.read_bytes(),
        "EFI/UniXNU/Payloads/kernel.macho": stripped,
        "EFI/UniXNU/unixnu.toml": menu_config(args.menu_tree).encode(),
    }
    for name, data in files.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    adt = output / "EFI/UniXNU/Payloads/kernel.macho.adt"
    profile = resolve_profile(ROOT / "board.toml")
    subprocess.run(adt_command(profile, adt, args.unique_chip_id), check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/check-adt.py"), str(adt),
                    "--profile", profile["profile"]], check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/check-payload.py"), "--config",
        str(output / "EFI/UniXNU/unixnu.toml"), "--payload-dir", str(output), "--panel", "1080x1920"], check=True)
    manifest = {"schema": "lumia950-native-bringup-v1", "native_kernel_sha256": args.kernel_sha256,
        "stripped_kernel_sha256": hashlib.sha256(stripped).hexdigest(), "runtime_bytes_compared": checked,
        "external_symbol_values_preserved": symbols, "merged_kernel_qualification_bypassed": False,
        "root_filesystem_included": False, "ios_userspace_included": False, "handset_boot_observed": False,
        "exposed_boot_cpu_affinity": 0, "secondary_cpu_conduit_qualified": False,
        "source_crypto_integrity_verified": True, "source_crypto": crypto,
        "gpu_frame_observed": False, "adt_profile": profile["profile"],
        "adt_dram_size": profile["dram_size"], "files": {}, **provenance}
    for destination in sorted(output.rglob("*")):
        if destination.is_file():
            blob = destination.read_bytes()
            manifest["files"][destination.relative_to(output).as_posix()] = {
                "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}
    (output / "native-bringup.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Staged {sum(value['bytes'] for value in manifest['files'].values())} bytes; no phone writes.")
    print("Source-only XNU early boot and native GPU hardware activation, NOT working iOS or a rendered frame.")


if __name__ == "__main__":
    main()
