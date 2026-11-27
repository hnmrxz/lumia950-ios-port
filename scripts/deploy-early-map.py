#!/usr/bin/env python3
"""Deploy the early-map kernel to the handset and add its boot argument, with the guards the chain requires.

This is the step the objective now waits on, so it is a script rather than a list of manual commands: it refuses when the phone is not the
expected one, keeps the kernel it replaces, writes the artifact only after its SHA-256 matches, and adds the boot argument through the same
gate that protects the boot-chain objects (`scripts/boot-chain-io.py`).

    python scripts/deploy-early-map.py --efiesp R: --kernel out/earlymap/mach.development.bcm2837.unstripped --dry-run
    python scripts/deploy-early-map.py --efiesp R: --kernel ... --apply --backup out/phone-backups/kernel.before

Dry run is the default; nothing is written without --apply.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNEL = "EFI/UniXNU/Payloads/kernel.macho"
CONFIG = "EFI/UniXNU/unixnu.toml"
TOKEN = "lumia-early-map"


def gate():
    spec = importlib.util.spec_from_file_location("boot_chain_io", ROOT / "scripts" / "boot-chain-io.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--efiesp", required=True, type=Path)
    parser.add_argument("--kernel", required=True, type=Path)
    parser.add_argument("--expect-sha256", default=None,
                        help="the artifact's SHA-256; defaults to whatever the file hashes to, recorded in the output")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path, default=None,
                        help="where to keep the kernel being replaced; required with --apply")
    parser.add_argument("--boot-chain-gate", default=None,
                        help="the guard's acknowledgement file; defaults to --backup")
    args = parser.parse_args(argv)

    if not args.kernel.is_file():
        print(f"error: {args.kernel} does not exist", file=sys.stderr)
        return 2
    target = args.efiesp / KERNEL
    config = args.efiesp / CONFIG
    if not args.efiesp.is_dir():
        print(f"error: {args.efiesp} is not mounted", file=sys.stderr)
        return 2
    if not config.is_file():
        print(f"error: {config} is missing; the phone is not the chain this script expects", file=sys.stderr)
        return 2

    artifact = digest(args.kernel)
    if args.expect_sha256 and args.expect_sha256.lower() != artifact:
        print(f"error: artifact hash {artifact} does not match --expect-sha256", file=sys.stderr)
        return 1

    existing = digest(target) if target.is_file() else None
    text = config.read_text(encoding="utf-8")
    updated = add_token(text, TOKEN)

    print(f"artifact  : {args.kernel} sha256 {artifact}")
    print(f"target    : {target} (current sha256 {existing or 'absent'})")
    print(f"argument  : {TOKEN} {'already present' if updated == text else 'will be appended to args'}")

    if args.apply and target.is_file():
        decision = gate().authorise(target, replace=True, backup=args.boot_chain_gate or args.backup,
                                    reason="deploy the early-map kernel for the M1 pre-VM observation",
                                    verify="the boot shows the marker's bar, or the state code through the console after the VM work")
        if not decision.allowed:
            print(decision.message, file=sys.stderr)
            return 1
        print(decision.message)
    if args.apply and (args.backup is None or not args.backup.parent.is_dir()):
        print("error: --apply needs --backup pointing into a directory that exists", file=sys.stderr)
        return 1

    if not args.apply:
        print("dry run only; pass --apply to write (and keep the current kernel in --backup)")
        print(f"after the write, the boot arguments must contain: {TOKEN}")
        return 0

    # The runbook: what the phone looked like before the write, so a later report can be checked against it.
    runbook = args.backup.parent / "handset-run.txt"
    if not runbook.is_file():
        runbook.write_text(
            "handset run of the early-map kernel\n"
            f"artifact        : {args.kernel}\n"
            f"artifact sha256 : {artifact}\n"
            f"previous kernel : {existing or 'absent'}\n"
            f"boot argument   : {TOKEN}\n"
            f"config before   : {text.strip()}\n",
            encoding="utf-8")
        print(f"runbook written to {runbook}")

    args.backup.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        shutil.copy2(target, args.backup)
        print(f"kept the previous kernel at {args.backup} sha256 {digest(args.backup)}")
    if not args.backup.is_file():
        print(f"error: the backup {args.backup} is missing after the copy", file=sys.stderr)
        return 1
    shutil.copy2(args.kernel, target)
    if digest(target) != artifact:
        print("error: the target does not hash to the artifact", file=sys.stderr)
        return 1
    if updated != text:
        config.write_text(updated, encoding="utf-8")
    print(f"wrote {target} sha256 {artifact}")
    print("next: power off, power on, wait 90 s, photograph the panel (expect eight red rows at the top)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
