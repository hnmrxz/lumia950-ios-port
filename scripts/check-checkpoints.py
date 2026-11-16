#!/usr/bin/env python3
"""Check the XNU checkpoint contract, and judge a recorded bring-up log against it.

The roadmap's P1 exit was "a real-device log proves XNU took control, with explicit checkpoints".
Nothing defined the checkpoints, so nothing could check the log. This is that contract: the
sequence scripts/test-native-xnu-entry.py already asserts in QEMU, plus a handset log reader.

    python3 scripts/check-checkpoints.py docs/native-checkpoints.json
    python3 scripts/check-checkpoints.py docs/native-checkpoints.json --log out/bringup.log
    python3 scripts/check-checkpoints.py docs/native-checkpoints.json --log out/bringup.log \
        --require-through arm_vm_init_return

A log passes when its markers appear in contract order up to the required checkpoint. A log that
reaches a later marker while an earlier one is missing did not happen; it is a transcription error
or a different image, and both matter more than the milestone it seemed to reach.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCHEMA = "lumia950-xnu-checkpoint-v1"
TRANSPORTS = ("undecided", "gop-framebuffer", "ram-mailbox")


def fail(message: str):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_contract(path: Path) -> list[dict]:
    document = json.loads(path.read_text())
    if document.get("schema") != SCHEMA:
        fail(f"{path}: schema is {document.get('schema')!r}, expected {SCHEMA!r}")
    transport = document.get("transport")
    if transport not in TRANSPORTS:
        fail(f"{path}: transport is {transport!r}, not one of {', '.join(TRANSPORTS)}")
    checkpoints = document.get("checkpoints")
    if not isinstance(checkpoints, list) or not checkpoints:
        fail(f"{path}: checkpoints is missing or empty")
    seen: set[str] = set()
    markers: set[str] = set()
    for index, checkpoint in enumerate(checkpoints):
        identity, marker = checkpoint.get("id"), checkpoint.get("marker")
        if not identity:
            fail(f"{path}: checkpoints[{index}] has no id")
        if identity in seen:
            fail(f"{path}: {identity} appears twice")
        seen.add(identity)
        if not marker or not str(marker).strip():
            fail(f"{path}: {identity} has no marker; a checkpoint without a marker cannot be found "
                 "in a log")
        if marker in markers:
            fail(f"{path}: {marker!r} is used by two checkpoints")
        markers.add(marker)
        if not str(checkpoint.get("proves") or "").strip():
            fail(f"{path}: {identity} does not say what it proves")
    if transport == "undecided":
        print("note: the transport is still undecided, so no handset record can be produced yet",
              file=sys.stderr)
    return checkpoints


def judge(log: Path, checkpoints: list[dict], require_through: str | None) -> list[str]:
    lines = log.read_text(errors="replace").splitlines()
    reached: list[str] = []
    cursor = 0
    for number, line in enumerate(lines, 1):
        if cursor >= len(checkpoints):
            break
        checkpoint = checkpoints[cursor]
        if checkpoint["marker"] in line:
            rate = sum(1 for other in lines if checkpoint["marker"] in other)
            print(f"checkpoint {checkpoint['id']:<20} line {number:<5} ({rate} occurrence(s))")
            reached.append(checkpoint["id"])
            cursor += 1
    expected = checkpoints if require_through is None else checkpoints[:(
        [c["id"] for c in checkpoints].index(require_through) + 1)]
    missing = [c["id"] for c in expected if c["id"] not in reached]
    if missing:
        fail(f"{log} does not reach {', '.join(missing)} in order; reached "
             f"{', '.join(reached) if reached else 'nothing'}")
    return reached


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("contract", type=Path, help="docs/native-checkpoints.json")
    parser.add_argument("--log", type=Path,
                        help="a recorded bring-up log to judge against the contract")
    parser.add_argument("--require-through", metavar="ID",
                        help="the checkpoint the log has to reach (default: the last one)")
    args = parser.parse_args()

    checkpoints = load_contract(args.contract)
    if args.log is None:
        print(f"checkpoint contract ok: {len(checkpoints)} checkpoints, transport "
              f"{json.loads(args.contract.read_text())['transport']}")
        return 0
    if not args.log.is_file():
        fail(f"{args.log} is missing")
    ids = [checkpoint["id"] for checkpoint in checkpoints]
    if args.require_through is not None and args.require_through not in ids:
        fail(f"--require-through {args.require_through!r} is not one of {', '.join(ids)}")
    reached = judge(args.log, checkpoints, args.require_through)
    print(f"bring-up log ok: {args.log} reaches {len(reached)} checkpoint(s), through "
          f"{reached[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
