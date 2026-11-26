#!/usr/bin/env python3
"""Put one chosen kernel on the handset and record which one is there.

The A/B that answers "did the kernel start" needs two images on the same phone (the source-built kernel and the
prelinked one), and every trip to mass-storage mode has to say afterwards which image was actually booted. A
directory of files cannot say that once the phone is unplugged, so this writes a manifest next to the kernel:

    EFI/UniXNU/Payloads/DEPLOYED.txt   what was written, when, and from which hashes

The previous kernel is kept as `kernel.macho.prev`, so a wrong choice costs one copy and not a re-stage.

    python scripts/deploy-kernel.py --efiesp R: --mainos H: --kernel out/handset-mainos-src --dry-run
    python scripts/deploy-kernel.py --efiesp R: --mainos H: --kernel out/handset-mainos-src --apply

It writes only inside EFI/UniXNU/Payloads on MainOS and verifies every write by SHA-256.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import shutil
import sys
from pathlib import Path

PAYLOAD_DIR = Path("EFI") / "UniXNU" / "Payloads"
KERNEL = "kernel.macho"
SIDECAR = "kernel.macho.adt"
MANIFEST = "DEPLOYED.txt"
PREVIOUS = "kernel.macho.prev"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def payload_dir(mainos: Path) -> Path:
    """Find the payload directory in a staged tree or on the mounted volume."""
    direct = mainos / PAYLOAD_DIR
    if direct.is_dir():
        return direct
    nested = mainos / "EFI" / "UniXNU" / "Payloads"
    return nested


def source_files(kernel_dir: Path) -> tuple[Path, Path | None]:
    kernel = kernel_dir / KERNEL
    if not kernel.is_file():
        # A staged tree keeps the kernel under EFI/UniXNU/Payloads/.
        alt = kernel_dir / PAYLOAD_DIR / KERNEL
        if alt.is_file():
            kernel = alt
    sidecar = kernel.with_name(SIDECAR)
    if not sidecar.is_file():
        alt = kernel_dir / PAYLOAD_DIR / SIDECAR
        sidecar = alt if alt.is_file() else None
    return kernel, sidecar


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--efiesp", required=True, help="EFIESP mount, for example R: (unused, kept for symmetry)")
    parser.add_argument("--mainos", required=True, help="MainOS mount, for example H:")
    parser.add_argument("--kernel", required=True, type=Path,
                        help="directory holding kernel.macho, or a staged EFI/UniXNU/Payloads tree")
    parser.add_argument("--apply", action="store_true", help="actually write")
    parser.add_argument("--dry-run", action="store_true", help="report only (the default)")
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run contradict each other")
    args.apply = args.apply and not args.dry_run

    mainos = Path(args.mainos.rstrip("\\/"))
    if not mainos.is_dir():
        print(f"error: MainOS is not mounted at {mainos}", file=sys.stderr)
        return 2

    kernel, sidecar = source_files(args.kernel)
    if not kernel.is_file():
        print(f"error: no {KERNEL} in {args.kernel}", file=sys.stderr)
        return 2
    kernel_sha = digest(kernel)
    sidecar_sha = digest(sidecar) if sidecar else "(none)"
    print(f"kernel   {kernel.name}  {kernel.stat().st_size} B  sha256 {kernel_sha[:16]}")
    print(f"sidecar  {sidecar.name if sidecar else '(none)'}  {sidecar_sha[:16] if sidecar else ''}")

    target = payload_dir(mainos)
    print(f"target   {target}")
    if not args.apply:
        print()
        print("dry run only; pass --apply to write")
        print("what would be written:")
        print(f"  {target / PREVIOUS}        <- the kernel that is there now, if any")
        print(f"  {target / KERNEL}          <- {kernel_sha[:16]}")
        if sidecar:
            print(f"  {target / SIDECAR}         <- {sidecar_sha[:16]}")
        print(f"  {target / MANIFEST}        <- which build this phone is running")
        return 0

    target.mkdir(parents=True, exist_ok=True)
    current = target / KERNEL
    previous_note = "(none)"
    if current.is_file():
        previous_sha = digest(current)
        if previous_sha != kernel_sha:
            shutil.copy2(current, target / PREVIOUS)
            previous_note = f"{previous_sha} kept as {PREVIOUS}"
        else:
            previous_note = f"{previous_sha} (identical, not copied)"
        print(f"previous {previous_sha[:16]}")

    shutil.copy2(kernel, current)
    written_sha = digest(current)
    if written_sha != kernel_sha:
        print(f"error: {current} hashes {written_sha}, expected {kernel_sha}", file=sys.stderr)
        return 1

    if sidecar:
        shutil.copy2(sidecar, target / SIDECAR)
        if digest(target / SIDECAR) != sidecar_sha:
            print(f"error: {target / SIDECAR} does not match its source", file=sys.stderr)
            return 1

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (target / MANIFEST).write_text(
        f"deployed   {stamp}\n"
        f"kernel     {kernel_sha}\n"
        f"sidecar    {sidecar_sha}\n"
        f"source     {args.kernel}\n"
        f"previous   {previous_note}\n",
        encoding="utf-8")

    print()
    print("written and verified:")
    print(f"  {current}  {written_sha[:16]}")
    if sidecar:
        print(f"  {target / SIDECAR}")
    print(f"  {target / MANIFEST}   (read this after the boot to say which image ran)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
