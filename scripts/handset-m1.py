#!/usr/bin/env python3
"""One command for the handset M1 run: find both volumes, check the chain, deploy, and print what to photograph.

The chain spans two partitions -- the configuration on EFIESP, the kernel and its adt on MainOS -- so this looks for a volume that carries
`EFI/UniXNU/unixnu.toml` and a volume that carries `EFI/UniXNU/Payloads/kernel.macho`. Either missing means the phone is not connected, and it
says so instead of guessing. Everything below that was rehearsed on copies of the staged tree (scripts/rehearse-handset-run.py).

    python scripts/handset-m1.py                          # report what it would do
    python scripts/handset-m1.py --apply                  # back up (three objects) and write
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_KERNEL = ROOT / "out" / "earlymap" / "mach.development.bcm2837.unstripped"
CANDIDATE_VOLUMES = ["R:", "H:", "S:", "T:", "U:", "V:", "W:", "X:", "Y:", "Z:"]


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def volumes() -> tuple[pathlib.Path | None, pathlib.Path | None]:
    efiesp = mainos = None
    for letter in CANDIDATE_VOLUMES:
        root = pathlib.Path(f"{letter}\\")
        if not root.is_dir():
            continue
        if efiesp is None and (root / "EFI" / "UniXNU" / "unixnu.toml").is_file():
            efiesp = root
        if mainos is None and (root / "EFI" / "UniXNU" / "Payloads" / "kernel.macho").is_file():
            mainos = root
    return efiesp, mainos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kernel", type=pathlib.Path, default=DEFAULT_KERNEL)
    parser.add_argument("--adt", type=pathlib.Path, default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    if not args.kernel.is_file():
        print(f"stop: no kernel artifact at {args.kernel}")
        return 2
    artifact = digest(args.kernel)
    adt = args.adt
    if adt is None:
        candidate = args.kernel.with_suffix(args.kernel.suffix + ".adt")
        adt = candidate if candidate.is_file() else None

    efiesp, mainos = volumes()
    if efiesp is None or mainos is None:
        print(f"stop: the phone is not connected -- efiesp={'found' if efiesp else 'missing'}, "
              f"mainos={'found' if mainos else 'missing'}")
        print(f"the artifact that would be written is {args.kernel.name} ({artifact[:16]}...)")
        print("nothing was written.")
        return 1

    command = [sys.executable, str(ROOT / "scripts" / "deploy-early-map.py"),
               "--efiesp", str(efiesp), "--mainos", str(mainos),
               "--kernel", str(args.kernel), "--expect-sha256", artifact]
    if adt is not None:
        command += ["--adt", str(adt)]
    if args.apply:
        command += ["--apply", "--backup-dir", str(ROOT / "out" / "handset-backup")]

    print(f"efiesp   : {efiesp}")
    print(f"mainos   : {mainos}")
    print(f"artifact : {args.kernel} sha256 {artifact}")
    print(f"adt      : {adt if adt else 'none'}")
    print(f"mode     : {'apply' if args.apply else 'dry run'}")
    result = subprocess.run(command, capture_output=True, text=True)
    print(result.stdout.strip() or result.stderr.strip())
    if result.returncode != 0:
        return result.returncode

    if args.apply:
        print("\nnow: unplug, power cycle, wait about 90 seconds, then photograph the panel.")
        print("expect: eight red rows across the top, or the console telling you which state code it reached.")
        print("the runbook in out/handset-backup/ records the three hashes that a rollback would need.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
