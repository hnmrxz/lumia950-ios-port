#!/usr/bin/env python3
"""Compare two XNU emulation reports and say what changed between them.

The QEMU fixture writes one report per run, and the interesting question after a kernel change is
always the same: what did it reach that it did not before, and did anything regress? This answers
that from the reports alone, with no QEMU:

    python3 scripts/compare-xnu-reports.py out/before/report.json out/after/report.json
    python3 scripts/compare-xnu-reports.py --require-milestones iokit_return,bsd_init_entry a.json b.json

Exit codes: 0 means the later report reached everything the earlier one did (and any required
milestones), 3 means a regression, 2 means bad input.
"""
import argparse
import json
import pathlib
import sys

MILESTONE_ORDER = (
    "arm_vm_init_entry",
    "arm_vm_init_return",
    "kernel_bootstrap_entry",
    "source_crypto_bootstrap_entry",
    "source_crypto_bootstrap_return",
    "iokit_entry",
    "iokit_return",
    "bsd_init_entry",
)


def load(path: pathlib.Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"error: {path} is missing")
    try:
        report = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise SystemExit(f"error: {path} is not JSON: {error}")
    if not isinstance(report, dict) or "milestones" not in report:
        raise SystemExit(f"error: {path} is not an XNU emulation report (no milestones)")
    return report


def ordered(milestones: list[str]) -> list[str]:
    known = [name for name in MILESTONE_ORDER if name in milestones]
    extra = [name for name in milestones if name not in MILESTONE_ORDER]
    return known + extra


def compare(before: dict, after: dict) -> tuple[list[str], list[str], list[str]]:
    """Return (gained, lost, notes) for the later report."""
    was, now = set(before["milestones"]), set(after["milestones"])
    gained = [name for name in ordered(list(after["milestones"])) if name not in was]
    lost = [name for name in ordered(list(before["milestones"])) if name not in now]
    notes = []
    for field in ("stop_symbols", "panic_format", "pc_symbol", "fault_elr_symbol",
                  "adt_profile", "architectural_counter_hz"):
        if before.get(field) != after.get(field):
            notes.append(f"{field}: {before.get(field)!r} -> {after.get(field)!r}")
    for field in ("source_crypto_status", "iokit_return_observed", "bsd_init_entry_observed"):
        if field in before or field in after:
            if before.get(field) != after.get(field):
                notes.append(f"{field}: {before.get(field)!r} -> {after.get(field)!r}")
    return gained, lost, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("before", type=pathlib.Path)
    parser.add_argument("after", type=pathlib.Path)
    parser.add_argument("--require-milestones", default="",
                        help="comma-separated milestones the later report must contain")
    args = parser.parse_args()

    before, after = load(args.before), load(args.after)
    gained, lost, notes = compare(before, after)
    required = [name.strip() for name in args.require_milestones.split(",") if name.strip()]

    print(f"before: {args.before} ({len(before['milestones'])} milestones)")
    print(f"after:  {args.after} ({len(after['milestones'])} milestones)")
    for name in gained:
        print(f"  + {name}")
    for name in lost:
        print(f"  - {name}")
    for note in notes:
        print(f"  ~ {note}")
    if not (gained or lost or notes):
        print("  (identical in every compared field)")

    problems = []
    if lost:
        problems.append(f"regressed: {', '.join(lost)} no longer observed")
    missing = [name for name in required if name not in after["milestones"]]
    if missing:
        problems.append(f"did not reach: {', '.join(missing)}")
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    return 3 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
