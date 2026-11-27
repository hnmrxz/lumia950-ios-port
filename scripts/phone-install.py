#!/usr/bin/env python3
r"""Install the handset chain from this checkout, and report what still needs a physical action.

Order comes from the upstream projects (Lumia950XLPkg README, postmarketOS wiki): unlock, put
BootShim.efi and give it a boot entry, put UEFI.elf on the EFIESP root, and only then the UniXNU payload
and the kernel. The shim's location is not the obvious one: the Lumia deployment scripts put it at
`\Windows\System32\Boot\bootshim.efi` on MainOS and point the store's `{default}` at it, which is what
the reference WOA image on this machine does (docs/hardware/2026-11-25-woa-ffu-reference.md). `--layout
efiesp` keeps the older placement for comparison. This script does the file parts, verifying every write by SHA-256, and
prints the boot entries and the one action it cannot perform (a power press).

    python scripts/phone-install.py --efiesp R: --mainos F: --stage efiesp --payload mainos --dry-run
    python scripts/phone-install.py --efiesp R: --mainos F: --stage efiesp --payload mainos --apply
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGING = ROOT.parent / "out"


def _shared_gate():
    import importlib.util

    module_path = Path(__file__).with_name("boot-chain-io.py")
    spec = importlib.util.spec_from_file_location("boot_chain_io", module_path)
    module = importlib.util.module_from_spec(spec)
    # Python 3.12 needs the module in sys.modules before exec_module, because the dataclass inside resolves its own module
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def refuse_protected(destination: Path, args) -> bool:
    """Ask the one shared gate, with the full evidence the rules require.

    This used to be a weaker local copy that accepted --replace-protected on its own. It now delegates to scripts/boot-chain-io.py,
    so an existing protected object needs --replace-protected *and* --backup *and* --reason *and* --verify, exactly like every other
    writer in the repository.
    """
    gate = _shared_gate()
    decision = gate.authorise(destination, replace=getattr(args, "replace_protected", False),
                              backup=getattr(args, "backup", None), reason=getattr(args, "reason", None),
                              verify=getattr(args, "verify", None))
    if decision.allowed:
        print(f"  {decision.message}")
        return True
    print(f"  {decision.message}", file=sys.stderr)
    return False


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()



SJM_SHIM = Path(r"C:\Program Files\chengcong\SJM\Core\Boot\bootaa64.efi")
LEGACY_SHIM = STAGING / "bootshim" / "elf-loader-pre3" / "BootShim.efi"


def resolve_bootshim(explicit: Path | None) -> Path:
    """Prefer a real EFI application: the boot manager only starts subsystem 0x0A.

    The historical staging file is an ARM32 driver and is only a last resort, kept so an explicit
    --bootshim keeps working; the subsystem check in install() refuses it either way.
    """
    if explicit is not None:
        return explicit
    for candidate in (SJM_SHIM, LEGACY_SHIM):
        if candidate.is_file():
            return candidate
    return LEGACY_SHIM




def pe_machine(path: Path) -> int | None:
    """Return the PE machine field, or None for anything that is not a PE image."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data[:2] != b"MZ" or len(data) < 0x40:
        return None
    offset = int.from_bytes(data[0x3C:0x40], "little")
    if data[offset:offset + 4] != b"PE\0\0" or offset + 6 > len(data):
        return None
    return int.from_bytes(data[offset + 4:offset + 6], "little")


def pe_subsystem(path: Path) -> int | None:
    """Return the PE subsystem, or None for anything that is not a PE image.

    The boot manager only starts EFI applications (0x0A). A boot service driver (0x0B) or a runtime
    driver (0x0C) placed at a boot path fails silently and the firmware falls back to its own sequence,
    which on this handset means the Windows reset flow. That is exactly what happened with the 42,976-byte
    module from the UEFI package, so the subsystem is checked before a binary may be installed.
    """
    data = path.read_bytes()
    if len(data) < 0x40 or data[0:2] != b"MZ":
        return None
    offset = int.from_bytes(data[0x3C:0x40], "little")
    if offset + 0x60 > len(data):
        return None
    return data[offset + 0x5C]


def install(src: Path, dst: Path, apply: bool, require_subsystem: int | None = None,
            args = None) -> bool:
    subsystem = pe_subsystem(src)
    note = "" if subsystem is None else f" subsystem 0x{subsystem:02X}"
    print(f"  {src.name:32} {src.stat().st_size:>10} B  sha256 {digest(src)[:16]}{note}")
    if require_subsystem is not None:
        if subsystem != require_subsystem:
            print(f"error: {src.name} has subsystem {subsystem}, which is not the required "
                  f"0x{require_subsystem:02X}; the boot manager would not start it", file=sys.stderr)
            return False
    if args is not None and not refuse_protected(dst, args) and apply:
        return False
    if not apply:
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if digest(dst) != digest(src):
        print(f"error: {dst} did not verify after the write", file=sys.stderr)
        return False
    return True



def verify_bcd(enum_file: Path, layout: str) -> bool:
    """Run the layout checker against a captured store, so the BCD step is verified rather than assumed."""
    checker = Path(__file__).with_name("check-bcd-layout.py")
    if not enum_file.is_file():
        print(f"error: --verify-bcd {enum_file} is missing", file=sys.stderr)
        return False
    expect = "mainos" if layout == "mainos" else "efiesp"
    print()
    print(f"checking the store against the {expect} layout: {enum_file}")
    result = subprocess.run([sys.executable, str(checker), "--enum-file", str(enum_file), "--expect", expect],
                            text=True)
    if result.returncode != 0:
        print("error: the store does not match what this run installed; apply the printed bcdedit commands",
              file=sys.stderr)
        return False
    print("store matches the layout")
    return True



# Subsystems a Lumia bootmgr will start: 0x0A for EFI applications, 0x10 for the Windows boot
# applications (`WINDOWS_BOOT_APP`) that the deployment tools put on the {default} path. The ARM32
# bootmgr cannot start an AArch64 image at all, so the class matters as much as the machine.
BOOT_APP_SUBSYSTEMS = {0x0A, 0x10}



def elf_machine(path: Path) -> int | None:
    """Return the ELF e_machine, or None for anything that is not an ELF64 image."""
    try:
        data = path.read_bytes()[:64]
    except OSError:
        return None
    if data[:4] != b"\x7fELF" or len(data) < 20:
        return None
    little = data[5] == 1
    if data[4] != 2:  # ELFCLASS64
        return None
    return int.from_bytes(data[18:20], "little" if little else "big")


def verify_kept_uefi_elf(destination: Path) -> bool:
    """Check the UEFI image already on EFIESP instead of overwriting it."""
    if not destination.is_file():
        print(f"error: --keep-uefi-elf was given but {destination} does not exist", file=sys.stderr)
        return False
    machine = elf_machine(destination)
    print(f"  {destination.name:32} {destination.stat().st_size:>10} B  "
          f"sha256 {digest(destination)[:16]}" + ("" if machine is None else f" ELF e_machine=0x{machine:X}"))
    print("UEFI.elf kept: the file the deployment tools installed is the one their shim chainloads")
    if machine != 0xB7:  # EM_AARCH64
        print(f"error: {destination.name} is not an AArch64 ELF (e_machine={machine}); the shim would not "
              "be able to chainload it", file=sys.stderr)
        return False
    return True


def verify_kept_shim(destination: Path) -> bool:
    """Check the shim already on the volume instead of overwriting it."""
    if not destination.is_file():
        print(f"error: --keep-shim was given but {destination} does not exist", file=sys.stderr)
        return False
    subsystem = pe_subsystem(destination)
    machine = pe_machine(destination)
    note = "" if subsystem is None else f" subsystem 0x{subsystem:02X}"
    machine_note = "" if machine is None else f" machine 0x{machine:04X}"
    print(f"  {destination.name:32} {destination.stat().st_size:>10} B  "
          f"sha256 {digest(destination)[:16]}{note}{machine_note}")
    print("shim kept: the file already on the volume is the one the store points at")
    if subsystem not in BOOT_APP_SUBSYSTEMS:
        print(f"error: {destination.name} has subsystem {subsystem}, which is neither 0x0A nor 0x10; "
              "the boot manager would not start it", file=sys.stderr)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--efiesp", required=True, help="EFIESP mount, for example R:")
    parser.add_argument("--mainos", required=True, help="MainOS mount, for example F:")
    parser.add_argument("--stage", type=Path, default=STAGING / "new-payload",
                        help="payload tree holding EFI/UniXNU")
    parser.add_argument("--payload", type=Path, default=STAGING / "redeploy-mainos",
                        help="staged MainOS tree holding EFI/UniXNU/Payloads")
    parser.add_argument("--bootshim", type=Path, default=None,
                        help="EFI application to install as the shim; defaults to the SJM application, "
                             "which is the only AArch64 application on this machine")
    parser.add_argument("--layout", choices=("mainos", "efiesp"), default="mainos",
                        help="mainos puts the shim at \\Windows\\System32\\Boot\\bootshim.efi as the Lumia "
                             "deployment scripts and the reference WOA image do; efiesp keeps the older "
                             "placement under EFI\\boot")
    parser.add_argument("--refind", type=Path, default=None,
                        help="optional rEFInd tree to copy to EFIESP\\EFI\\REFIND")
    parser.add_argument("--uefi-elf", type=Path,
                        default=STAGING / "xlpkg" / "extracted" / "MSM8992 UEFI (Lumia 950)" / "ELF" / "UEFI.elf")
    parser.add_argument("--apply", action="store_true", help="actually write")
    parser.add_argument("--loader-alias", action="store_true",
                        help="also write the UniXNU loader to EFI\\BOOT\\BOOTAA64.EFI, which is where the "
                             "custom UEFI looks when no boot entry is configured. Measured on the handset, "
                             "2026-11-26: the UEFI reported 'Failed to boot OS. No usable boot entry found' "
                             "with the loader only at EFI\\UniXNU\\UniXNU.efi")
    parser.add_argument("--backup", type=Path, default=None,
                        help="a file that can restore a protected object; required together with --replace-protected")
    parser.add_argument("--reason", default=None,
                        help="what is being replaced and why; required together with --replace-protected")
    parser.add_argument("--verify", default=None,
                        help="how the result will be proven; required together with --replace-protected")
    parser.add_argument("--replace-protected", action="store_true",
                        help="acknowledge that a protected boot-chain object is being written (UEFI.elf, BootShim.efi, "
                             "BOOTAA64.EFI, BCD, bootarm.efi, EFI/UniXNU/**); refused without it")
    parser.add_argument("--keep-uefi-elf", action="store_true",
                        help="do not write UEFI.elf; verify the one already on EFIESP. The deployment tools "
                             "install their own build there, and it is the file their shim chainloads, so "
                             "replacing it would change a chain that is already configured")
    parser.add_argument("--keep-shim", action="store_true",
                        help="do not write the shim; verify the one already at the layout's destination. "
                             "The Lumia firmware's bootmgr is ARM32 and starts subsystem 0x10 boot "
                             "applications, which is what the deployment tools put there; replacing it with "
                             "an AArch64 0x0A image would leave nothing the bootmgr can run")
    parser.add_argument("--verify-bcd", type=Path, default=None, metavar="ENUM_FILE",
                        help="also check a captured 'bcdedit /store ... /enum all' output against the layout "
                             "this run installs, so the store is verified in the same command")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be written and write nothing (the default; stated "
                             "explicitly so a runbook can spell it out)")
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run contradict each other")
    args.apply = args.apply and not args.dry_run

    efiesp = Path(args.efiesp.rstrip("\\/"))
    mainos = Path(args.mainos.rstrip("\\/"))
    for mount, name in ((efiesp, "EFIESP"), (mainos, "MainOS")):
        if not mount.is_dir():
            print(f"error: {name} is not mounted at {mount}", file=sys.stderr)
            return 2

    ok = True
    if args.layout == "mainos":
        shim_destination = mainos / "Windows" / "System32" / "Boot" / "bootshim.efi"
        print(r"BootShim.efi -> MainOS\Windows\System32\Boot")
    else:
        shim_destination = efiesp / "EFI" / "boot" / "BootShim.efi"
        print("BootShim.efi -> EFIESP\\EFI\\boot")
    if args.keep_shim:
        ok &= verify_kept_shim(shim_destination)
    else:
        shim = resolve_bootshim(args.bootshim)
        print(f"shim source: {shim}")
        ok &= install(shim, shim_destination, args.apply, require_subsystem=0x0A, args=args)

    if args.keep_uefi_elf:
        ok &= verify_kept_uefi_elf(efiesp / "UEFI.elf")
    else:
        print("UEFI.elf -> EFIESP root")
        ok &= install(args.uefi_elf, efiesp / "UEFI.elf", args.apply, args=args)

    print("UniXNU payload -> EFIESP")
    for name in ("UniXNU.efi", "unixnu.toml"):
        source = args.stage / "EFI" / "UniXNU" / name
        if source.is_file():
            ok &= install(source, efiesp / "EFI" / "UniXNU" / name, args.apply, args=args)
    drivers = args.stage / "EFI" / "UniXNU" / "Drivers"
    if drivers.is_dir():
        for source in sorted(drivers.iterdir()):
            if source.is_file():
                ok &= install(source, efiesp / "EFI" / "UniXNU" / "Drivers" / source.name, args.apply, args=args)

    if args.loader_alias:
        loader = args.stage / "EFI" / "UniXNU" / "UniXNU.efi"
        print("UniXNU loader -> EFI\\BOOT\\BOOTAA64.EFI (what the custom UEFI starts)")
        if not loader.is_file():
            print(f"error: {loader} is missing; stage the payload first", file=sys.stderr)
            ok = False
        else:
            ok &= install(loader, efiesp / "EFI" / "BOOT" / "BOOTAA64.EFI", args.apply,
                          require_subsystem=0x0A)

    print("kernel and device tree -> MainOS")
    payloads = args.payload / "EFI" / "UniXNU" / "Payloads"
    if payloads.is_dir():
        for source in sorted(payloads.iterdir()):
            if source.is_file():
                ok &= install(source, mainos / "EFI" / "UniXNU" / "Payloads" / source.name, args.apply, args=args)
    else:
        print("  (no staged kernel; run scripts/stage-kernel.py --payload-out first)")

    if args.refind:
        if not args.refind.is_dir():
            print(f"error: --refind {args.refind} is not a directory", file=sys.stderr)
            ok = False
        else:
            print("rEFInd -> EFIESP\\EFI\\REFIND")
            for source in sorted(args.refind.rglob("*")):
                if source.is_file():
                    relative = source.relative_to(args.refind)
                    ok &= install(source, efiesp / "EFI" / "REFIND" / relative, args.apply, args=args)

    if args.verify_bcd is not None:
        ok &= verify_bcd(args.verify_bcd, args.layout)

    print()
    if args.apply:
        print("files installed and verified")
    else:
        print("dry run only; pass --apply to write")
    if args.layout == "mainos":
        print()
        print("the shim is on MainOS, so the store has to point at it (run these elevated):")
        print(r"  bcdedit /store <EFIESP>:\\EFI\\Microsoft\\BOOT\\BCD /set {default} device partition=<MainOS>:")
        print(r"  bcdedit /store <EFIESP>:\\EFI\\Microsoft\\BOOT\\BCD /set {default} path \\windows\\system32\\boot\\bootshim.efi")
        print(r"  bcdedit /store <EFIESP>:\\EFI\\Microsoft\\BOOT\\BCD /set {default} description \"BootShim Application\"")
    print("still requires a physical action: detach USB, power off, power on to test the boot result")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
