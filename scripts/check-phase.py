#!/usr/bin/env python3
"""Check the phase exit criteria under docs/phases.

The roadmap's exit conditions were prose: "the same commit yields a repeatable payload, kernel
candidate and build report", "the rollback strategy is verified", "the desktop is visible and
basically interactive". None of them could be judged, so none of them could fail, so a phase
could be called finished because it felt finished.

Each phase now has a JSON file whose criteria are machine-checked here. The rule that matters is
the one for "met": a criterion cannot be marked met without naming the thing that proves it -- a
file that exists, or a command with a date it was run. A judgement call is written down as
"open", which is what an honest phase looks like before its evidence exists.

    python3 scripts/check-phase.py docs/phases
    python3 scripts/check-phase.py --root . docs/phases/p0-exit.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA = "lumia950-phase-exit-v1"
PHASES = ("P0", "P1", "P2", "P3", "P4", "P5")
PHASE_STATUS = ("open", "met", "blocked")
CRITERION_STATUS = ("met", "open", "not-applicable")
EVIDENCE_KINDS = ("artifact", "run", "document", "command", "hardware")
NAME = re.compile(r"p([0-5])-exit\.json$")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def fail(message: str):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load(path: Path, root: Path) -> dict:
    match = NAME.search(path.name)
    if not match:
        fail(f"{path.name} is not pN-exit.json")
    document = json.loads(path.read_text())
    phase = f"P{match.group(1)}"
    errors: list[str] = []

    if document.get("schema") != SCHEMA:
        errors.append(f"schema is {document.get('schema')!r}, expected {SCHEMA!r}")
    if document.get("phase") != phase:
        errors.append(f"phase is {document.get('phase')!r}, but the file name says {phase}")
    status = document.get("status")
    if status not in PHASE_STATUS:
        errors.append(f"status is {status!r}, not one of {', '.join(PHASE_STATUS)}")
    if status == "blocked" and not str(document.get("blocked_by") or "").strip():
        errors.append("status is blocked but blocked_by says nothing")

    criteria = document.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        errors.append("criteria is missing or empty")
        criteria = []
    seen: set[str] = set()
    for index, criterion in enumerate(criteria):
        where = f"criteria[{index}]"
        if not isinstance(criterion, dict):
            errors.append(f"{where} is not an object")
            continue
        identity = criterion.get("id")
        if not isinstance(identity, str) or not identity.startswith(phase + "."):
            errors.append(f"{where}.id is {identity!r}; it has to start with {phase}.")
            continue
        if identity in seen:
            errors.append(f"{identity} appears twice")
        seen.add(identity)
        where = identity
        if not str(criterion.get("requirement") or "").strip():
            errors.append(f"{where} has no requirement")
        if criterion.get("evidence") not in EVIDENCE_KINDS:
            errors.append(f"{where}.evidence is {criterion.get('evidence')!r}, not one of "
                          f"{', '.join(EVIDENCE_KINDS)}")
        if criterion.get("status") not in CRITERION_STATUS:
            errors.append(f"{where}.status is {criterion.get('status')!r}, not one of "
                          f"{', '.join(CRITERION_STATUS)}")
        if criterion.get("status") == "met":
            # The whole point: a met criterion names what proves it.
            path = criterion.get("path")
            command = criterion.get("command")
            verified = criterion.get("verified_at")
            if path and not (root / path).exists():
                errors.append(f"{where} is met through {path}, which does not exist")
            if not path and not command:
                errors.append(f"{where} is met but names no path and no command")
            if not path and not (verified and DATE.fullmatch(str(verified))):
                errors.append(f"{where} is met through a command with no verified_at date")
        script = criterion.get("verified_by")
        if script and not (root / script).exists():
            errors.append(f"{where}.verified_by names {script}, which does not exist")
    if status == "met":
        unfinished = [c.get("id") for c in criteria
                      if isinstance(c, dict) and c.get("status") not in ("met", "not-applicable")]
        if unfinished:
            errors.append(f"phase is met but these criteria are not: {', '.join(map(str, unfinished))}")
    return {"phase": phase, "status": status, "document": document, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", type=Path,
                        help="pN-exit.json files, or the docs/phases directory")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="repository the criteria paths are relative to")
    args = parser.parse_args()
    root = args.root.resolve()

    files: list[Path] = []
    for path in args.paths:
        if path.is_dir():
            files.extend(sorted(path.glob("p*-exit.json")))
        else:
            files.append(path)
    if not files:
        fail(f"no pN-exit.json under {', '.join(str(path) for path in args.paths)}")

    results = [load(path, root) for path in files]
    errors = [f"{path.name}: {error}" for path, result in zip(files, results)
              for error in result["errors"]]

    by_phase = {result["phase"]: result for result in results}
    for index, phase in enumerate(PHASES):
        if phase not in by_phase:
            continue
        if by_phase[phase]["status"] != "met":
            continue
        for earlier in PHASES[:index]:
            if earlier not in by_phase:
                errors.append(f"{phase} is met but {earlier} has no exit file")
            elif by_phase[earlier]["status"] != "met":
                errors.append(f"{phase} is met but {earlier} is {by_phase[earlier]['status']}")

    if errors:
        for error in sorted(set(errors)):
            print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)

    for path, result in zip(files, results):
        criteria = result["document"]["criteria"]
        counts = {state: sum(1 for c in criteria if c.get("status") == state)
                  for state in CRITERION_STATUS}
        print(f"{result['phase']} {result['status']:<7} {len(criteria)} criteria "
              f"(met {counts['met']}, open {counts['open']}, "
              f"n/a {counts['not-applicable']})  {path}")
    print(f"phase exits ok: {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
