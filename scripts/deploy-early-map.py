#!/usr/bin/env python3
"""Deploy the early-map kernel to the handset: two volumes, real backups, a gate that is asked about the real object.

The chain does not live on one partition. Measured on the handset and recorded in docs/hardware/:

    EFIESP (R:)  EFI/UniXNU/unixnu.toml            the configuration whose args carry the boot argument
    MainOS (H:)  EFI/UniXNU/Payloads/kernel.macho  the kernel the loader starts
    MainOS (H:)  EFI/UniXNU/Payloads/kernel.macho.adt

An earlier version of this script looked for the kernel under --efiesp and called the boot-chain gate with `--boot-chain-gate`, which the
rehearsal satisfied by pointing at the *new* kernel. The gate only checked that the path was a file, so it authorised nothing. The order is now
the one that can be defended:

    1. read the object that is about to be replaced, from the volume it lives on;
    2. copy it outside the phone and prove the copy hashes the same;
    3. ask the gate about that object with that copy, and require the two to match;
    4. only now write, and re-hash what was written;
    5. do 1-4 again, separately, for the configuration.

Any refusal at any step stops the run before the next write. Dry run is the default.

    python scripts/deploy-early-map.py --efiesp R: --mainos H: --kernel out/earlymap/mach.development.bcm2837.unstripped --backup-dir out/handset-backup
    python scripts/deploy-early-map.py ... --apply
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = "EFI/UniXNU/unixnu.toml"
KERNEL = "EFI/UniXNU/Payloads/kernel.macho"
ADT = "EFI/UniXNU/Payloads/kernel.macho.adt"
TOKEN = "lumia-early-map"


def gate():
    spec = importlib.util.spec_from_file_location("boot_chain_io", ROOT / "scripts" / "boot-chain-io.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def add_token(text: str, token: str) -> str:
    """Append the token to the default entry's args, once."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith("args") and "=" in line:
            if token in line:
                return text
            quote = '"' if '"' in line else "'"
            head, _, tail = line.partition("=")
            value = tail.strip()
            if not (value.startswith(quote) and value.endswith(quote)):
                raise ValueError(f"cannot parse the args line: {line!r}")
            inner = value[1:-1]
            new_inner = (inner + " " + token).strip() if inner else token
            lines[index] = f"{head}= {quote}{new_inner}{quote}"
            return "\n".join(lines) + "\n"
    raise ValueError("no args line in the configuration")


def keep(original: Path, backup: Path) -> tuple[bool, str]:
    """Copy the object off the phone and prove the copy is the object."""
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, backup)
    if not backup.is_file():
        return False, f"the backup {backup} was not created"
    if digest(backup) != digest(original):
        return False, f"the backup {backup} does not hash to {original}"
    return True, f"kept {original} at {backup} sha256 {digest(backup)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--efiesp", required=True, type=Path, help="the EFIESP volume root (holds the configuration)")
    parser.add_argument("--mainos", required=True, type=Path, help="the MainOS volume root (holds the kernel and its adt)")
    parser.add_argument("--kernel", required=True, type=Path, help="the artifact to write")
    parser.add_argument("--adt", type=Path, default=None, help="the artifact's ADT, if it has one")
    parser.add_argument("--expect-sha256", default=None)
    parser.add_argument("--backup-dir", type=Path, default=None, help="outside the phone; required with --apply")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    if not args.kernel.is_file():
        print(f"error: {args.kernel} does not exist", file=sys.stderr)
        return 2
    if not args.efiesp.is_dir() or not args.mainos.is_dir():
        print("error: both volumes must be mounted (--efiesp and --mainos)", file=sys.stderr)
        return 2
    config = args.efiesp / CONFIG
    target = args.mainos / KERNEL
    adt_target = args.mainos / ADT
    if not config.is_file():
        print(f"error: {config} is missing; EFIESP is not the chain this script expects", file=sys.stderr)
        return 2
    if adt_target.is_file() and args.adt is None:
        print("error: the phone carries an adt beside the kernel; pass --adt or the pair would stop matching", file=sys.stderr)
        return 2
    if args.adt is not None and not args.adt.is_file():
        print(f"error: {args.adt} does not exist", file=sys.stderr)
        return 2

    artifact = digest(args.kernel)
    if args.expect_sha256 and args.expect_sha256.lower() != artifact:
        print(f"error: artifact hash {artifact} does not match --expect-sha256", file=sys.stderr)
        return 1

    existing = digest(target) if target.is_file() else None
    text = config.read_text(encoding="utf-8")
    updated = add_token(text, TOKEN)

    print(f"artifact  : {args.kernel} sha256 {artifact}")
    print(f"kernel    : {target} (current sha256 {existing or 'absent'})")
    print(f"adt       : {args.adt if args.adt else 'none'}")
    print(f"config    : {config} ({'change needed' if updated != text else 'argument already present'})")
    print(f"volumes   : efiesp={args.efiesp} mainos={args.mainos}")

    if not args.apply:
        print(f"dry run: would copy {target} to {args.backup_dir or '<--backup-dir>'}/, then ask the gate, then write")
        print("nothing was written. pass --apply (and --backup-dir) to do it")
        return 0

    if args.backup_dir is None:
        print("error: --apply needs --backup-dir, outside the phone", file=sys.stderr)
        return 1
    args.backup_dir.mkdir(parents=True, exist_ok=True)

    # 1-3: kernel. The backup must be the object being replaced, and the gate is told to check exactly that.
    kernel_backup = args.backup_dir / "kernel.macho.before-m1"
    if target.is_file():
        ok, message = keep(target, kernel_backup)
        print(("ok   " if ok else "FAIL ") + message)
        if not ok:
            return 1
    else:
        kernel_backup = None
        print("note  : the phone carries no kernel at that path, so there is nothing to keep")

    decision = gate().authorise(target, replace=True, backup=kernel_backup, backup_matches=target if kernel_backup else None,
                                reason="deploy the early-map kernel for the M1 pre-VM observation",
                                verify="the boot shows the marker's bar, or the state code through the console after the VM work")
    if not decision.allowed:
        print(decision.message, file=sys.stderr)
        return 1
    print(decision.message)

    # 4: write the kernel and prove the write.
    shutil.copy2(args.kernel, target)
    if digest(target) != artifact:
        print("error: the written kernel does not hash to the artifact; the previous one is in " + str(kernel_backup), file=sys.stderr)
        return 1
    if args.adt is not None:
        adt_backup = args.backup_dir / "kernel.macho.adt.before-m1"
        if adt_target.is_file():
            ok, message = keep(adt_target, adt_backup)
            print(("ok   " if ok else "FAIL ") + message)
            if not ok:
                return 1
        shutil.copy2(args.adt, adt_target)
        if digest(adt_target) != digest(args.adt):
            print("error: the adt does not hash to the artifact's", file=sys.stderr)
            return 1
        print(f"wrote {adt_target}")
    print(f"wrote {target} sha256 {artifact}")

    # 5: the configuration is a protected object too, and gets its own backup and its own decision.
    if updated != text:
        config_backup = args.backup_dir / "unixnu.toml.before-m1"
        ok, message = keep(config, config_backup)
        print(("ok   " if ok else "FAIL ") + message)
        if not ok:
            return 1
        decision = gate().authorise(config, replace=True, backup=config_backup, backup_matches=config,
                                    reason="add the early-map boot argument for the M1 run",
                                    verify="the loader log and the panel show the marker, and removing the token restores the previous boot")
        if not decision.allowed:
            print(decision.message, file=sys.stderr)
            return 1
        print(decision.message)
        config.write_text(updated, encoding="utf-8")
        if TOKEN not in config.read_text(encoding="utf-8"):
            print("error: the configuration does not carry the token after the write", file=sys.stderr)
            return 1
        print(f"wrote {config}")

    runbook = args.backup_dir / "handset-run.txt"
    runbook.write_text(
        "handset run of the early-map kernel\n"
        f"artifact        : {args.kernel}\n"
        f"artifact sha256 : {artifact}\n"
        f"previous kernel : {existing or 'absent'}\n"
        f"kernel backup   : {kernel_backup}\n"
        f"config backup   : {args.backup_dir / 'unixnu.toml.before-m1'}\n"
        f"volumes         : efiesp={args.efiesp} mainos={args.mainos}\n"
        f"boot argument   : {TOKEN}\n",
        encoding="utf-8")
    print(f"runbook written to {runbook}")
    print("next: unplug, power cycle, wait 90 s, photograph the panel (expect eight red rows at the top)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
