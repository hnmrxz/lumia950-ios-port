#!/usr/bin/env python3
"""Check docs/evidence.json: a label has to be paid for.

AGENTS.md defines ten evidence labels and BUILD-VERIFICATION.md repeats them, but nothing read
them: README.md uses a different vocabulary, and any page could quietly promote a driver from
"compiles" to "works". This makes the ladder mechanical.

    python3 scripts/check-evidence.py
    python3 scripts/check-evidence.py --phases docs/phases

Two rules do the work:

* a subject may only claim a label that appears in its own evidence list, and may not cite
  evidence of a level above the one it claims;
* the two labels that would be most tempting to overclaim are tied to the phase that has to be
  met first: XNU-entry-tested needs P1, userland-booted needs P4. Both are open, so neither can
  be claimed by editing this file alone.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA = "lumia950-evidence-v1"
LABELS = (
    "source-reviewed",
    "host-tested",
    "QEMU-tested",
    "ABI-compiled",
    "kernel-linked",
    "prelink-checked",
    "EFI-tested",
    "XNU-entry-tested",
    "hardware-tested",
    "userland-booted",
)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# A claim at or above this label needs the phase that produces it to be met first.
PHASE_GATE = {"XNU-entry-tested": "P1", "userland-booted": "P4"}


def fail(message: str):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_phase_statuses(directory: Path) -> dict:
    statuses = {}
    for path in sorted(directory.glob("p*-exit.json")):
        statuses[json.loads(path.read_text()).get("phase")] = json.loads(path.read_text()).get("status")
    return statuses


def check(document: dict, root: Path, phases: dict | None) -> list[str]:
    errors: list[str] = []
    if document.get("schema") != SCHEMA:
        errors.append(f"schema is {document.get('schema')!r}, expected {SCHEMA!r}")
    labels = document.get("labels")
    if tuple(labels or ()) != LABELS:
        errors.append("labels is not the ladder from AGENTS.md, in order; a new label has to be "
                      "added there and here together")
        labels = list(LABELS)
    subjects = document.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        errors.append("subjects is missing or empty")
        return errors

    seen: set[str] = set()
    for index, subject in enumerate(subjects):
        identity = subject.get("id")
        where = identity or f"subjects[{index}]"
        if not identity:
            errors.append(f"subjects[{index}] has no id")
        elif identity in seen:
            errors.append(f"{identity} appears twice")
        seen.add(identity)
        if not str(subject.get("what") or "").strip():
            errors.append(f"{where} does not say what it is")
        label = subject.get("label")
        if label not in labels:
            errors.append(f"{where}.label is {label!r}, not a label")
            continue
        if phases is not None:
            gate = PHASE_GATE.get(label)
            if gate is not None and phases.get(gate) != "met":
                errors.append(f"{where} claims {label} but phase {gate} is "
                              f"{phases.get(gate, 'missing')}; the level is produced by that phase")
        evidence = subject.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{where} has no evidence")
            continue
        cited = set()
        for entry in evidence:
            cited.add(entry.get("label"))
            entry_label = entry.get("label")
            if entry_label not in labels:
                errors.append(f"{where} cites {entry_label!r}, not a label")
            elif labels.index(entry_label) > labels.index(label):
                errors.append(f"{where} claims {label} but cites {entry_label} evidence; evidence "
                              "may not be stronger than the claim")
            path, command = entry.get("path"), entry.get("command")
            if bool(path) == bool(command):
                errors.append(f"{where} evidence needs exactly one of path or command")
            if path and not (root / path).exists():
                errors.append(f"{where} cites {path}, which does not exist")
            if command and not DATE.fullmatch(str(entry.get("verified_at") or "")):
                errors.append(f"{where} cites a command with no verified_at date")
        if label not in cited:
            errors.append(f"{where} claims {label} but lists no evidence at that level")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("table", nargs="?", type=Path, default=Path("docs/evidence.json"),
                        help="the evidence table (default: docs/evidence.json)")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="repository the evidence paths are relative to")
    parser.add_argument("--phases", type=Path,
                        help="docs/phases; when given, XNU-entry-tested and userland-booted need "
                             "their phase met first")
    args = parser.parse_args()
    root = args.root.resolve()

    document = json.loads(args.table.read_text())
    phases = None
    if args.phases is not None:
        if not args.phases.is_dir():
            fail(f"{args.phases} is not a directory")
        phases = read_phase_statuses(args.phases)

    errors = check(document, root, phases)
    if errors:
        for error in sorted(set(errors)):
            print(f"error: {error}", file=sys.stderr)
        return 1
    counts: dict[str, int] = {}
    for subject in document["subjects"]:
        counts[subject["label"]] = counts.get(subject["label"], 0) + 1
    summary = ", ".join(f"{label} {counts[label]}" for label in LABELS if label in counts)
    print(f"evidence ok: {len(document['subjects'])} subjects ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
