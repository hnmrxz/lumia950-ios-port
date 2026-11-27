#!/usr/bin/env python3
"""Snapshot the handset's boot-critical files, and put them back in one command.

Every failure so far came from changing files on EFIESP or the BCD store. Both are small (EFIESP is
33 MB, most of it unused) and both are reachable in mass storage mode, so a full copy is cheap and makes
the restore a file copy instead of an FFU reflash.

    python scripts/phone-snapshot.py save --efiesp R: --out out/phone-backups
    python scripts/phone-snapshot.py list --out out/phone-backups
    python scripts/phone-snapshot.py restore --efiesp R: --name 20261125-124500
    python scripts/phone-snapshot.py restore --efiesp R: --name 20261125-124500 --apply

The manifest records a SHA-256 per file, and restore verifies both the copy it writes and the manifest it
reads, so a half-finished backup cannot be restored silently.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
import importlib.util as _importlib_util

_GATE_SPEC = _importlib_util.spec_from_file_location("boot_chain_io", Path(__file__).with_name("boot-chain-io.py"))
GATE = _importlib_util.module_from_spec(_GATE_SPEC)
_GATE_SPEC.loader.exec_module(GATE)

SKIP = {"System Volume Information"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def walk(root: Path):
    for path in sorted(root.rglob("*")):
        parts = set(path.relative_to(root).parts)
        if parts & SKIP:
            continue
        if path.is_file():
            yield path



def mount_root(text: str) -> Path:
    """The volume root for a mount argument, on Windows (`R:`) and on a POSIX path alike.

    `R:` names the current directory of that drive, so the root needs a separator; a directory argument must
    not gain one, or it stops being a directory on POSIX.
    """
    value = text.rstrip("\\/")
    if re.fullmatch(r"[A-Za-z]:", value):
        return Path(value + os.sep)
    return Path(value)


def save(args) -> int:
    root = mount_root(args.efiesp)
    if not root.is_dir():
        print(f"error: {args.efiesp} is not mounted", file=sys.stderr)
        return 2
    name = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = Path(args.out) / name
    files = {}
    for path in walk(root):
        relative = path.relative_to(root).as_posix()
        destination = target / "efiesp" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        if digest(destination) != digest(path):
            print(f"error: {relative} changed while it was being copied", file=sys.stderr)
            return 1
        files[relative] = {"bytes": path.stat().st_size, "sha256": digest(path)}
    (target / "manifest.json").write_text(
        json.dumps({"created": name, "efiesp": str(args.efiesp), "files": files}, indent=2) + "\n")
    print(f"saved {len(files)} files to {target}")
    bcd = target / "efiesp" / "EFI" / "Microsoft" / "BOOT" / "BCD"
    print(f"BCD captured: {bcd.is_file()}")
    return 0


def list_backups(args) -> int:
    base = Path(args.out)
    if not base.is_dir():
        print(f"no backups under {base}")
        return 0
    for entry in sorted(base.iterdir(), reverse=True):
        manifest = entry / "manifest.json"
        if manifest.is_file():
            data = json.loads(manifest.read_text())
            print(f"{entry.name}  {len(data.get('files', {}))} files")
    return 0


def restore(args) -> int:
    source = Path(args.out) / args.name
    manifest = source / "manifest.json"
    if not manifest.is_file():
        print(f"error: {manifest} is missing", file=sys.stderr)
        return 2
    data = json.loads(manifest.read_text())
    root = mount_root(args.efiesp)
    if not root.is_dir():
        print(f"error: {args.efiesp} is not mounted", file=sys.stderr)
        return 2
    missing = [name for name in data["files"] if not (source / "efiesp" / name).is_file()]
    if missing:
        print(f"error: the backup is incomplete ({len(missing)} files missing)", file=sys.stderr)
        return 2

    # A snapshot restore writes files that may be protected objects (the BCD store, bootarm.efi, the whole UniXNU tree). The snapshot's
    # own manifest is not a rollback for the *current* state, so every differing protected file is listed and gated individually.
    protected_changes = []
    for name, record in data["files"].items():
        target = root / name
        if GATE.protected_object(target) is None:
            continue
        if target.is_file() and digest(target) == record["sha256"]:
            continue
        protected_changes.append(name)
    if protected_changes:
        print(f"this snapshot would replace {len(protected_changes)} protected object(s):")
        for name in sorted(protected_changes):
            print(f"  {name}")
        decisions = [GATE.authorise(root / name, replace=True, backup=args.backup,
                                    reason=args.reason, verify=args.verify) for name in sorted(protected_changes)]
        denied = [decision for decision in decisions if not decision.allowed]
        if denied:
            for decision in denied[:3]:
                print(decision.message, file=sys.stderr)
            print("refused: a snapshot restore that overwrites protected objects needs --replace-protected with "
                  "--backup, --reason and --verify", file=sys.stderr)
            return 1
        for decision in decisions:
            print(decision.message)
    else:
        print("no protected object would change")

    print(f"restoring {len(data['files'])} files from {args.name} onto {args.efiesp}")
    if not args.apply:
        print("dry run only; pass --apply to write")
        return 0
    for name, record in data["files"].items():
        payload = source / "efiesp" / name
        if digest(payload) != record["sha256"]:
            print(f"error: {name} does not match its manifest", file=sys.stderr)
            return 2
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(payload, destination)
        if digest(destination) != record["sha256"]:
            print(f"error: {name} did not verify after the write", file=sys.stderr)
            return 1
    print("restored and verified")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_save = sub.add_parser("save", help="copy EFIESP (including the BCD store) to a local folder")
    p_save.add_argument("--efiesp", required=True)
    p_save.add_argument("--out", default="out/phone-backups")
    p_save.set_defaults(func=save)

    p_list = sub.add_parser("list", help="list local snapshots")
    p_list.add_argument("--out", default="out/phone-backups")
    p_list.set_defaults(func=list_backups)

    p_restore = sub.add_parser("restore", help="copy a snapshot back onto EFIESP")
    p_restore.add_argument("--efiesp", required=True)
    p_restore.add_argument("--out", default="out/phone-backups")
    p_restore.add_argument("--name", required=True)
    p_restore.add_argument("--apply", action="store_true")
    p_restore.add_argument("--replace-protected", action="store_true",
                           help="allow this restore to overwrite protected boot-chain objects")
    p_restore.add_argument("--backup", type=Path, default=None,
                           help="a file that can restore the current state; required with --replace-protected")
    p_restore.add_argument("--reason", default=None, help="why the restore is needed; required with --replace-protected")
    p_restore.add_argument("--verify", default=None, help="how the result will be proven; required with --replace-protected")
    p_restore.set_defaults(func=restore)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
