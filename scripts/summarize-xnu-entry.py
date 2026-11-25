#!/usr/bin/env python3
"""Summarise an archived emulated-boot report into the boot ladder it actually reached.

The QEMU fixture writes `report.json`; reading it by hand means scanning a 54 KB document for a handful of
fields. This prints the ordered checkpoints, whether BSD initialisation returned, where the boot stopped,
and what the next missing rung is -- the thing every round of kernel work has needed.

    python scripts/summarize-xnu-entry.py out/ci-report-xnu-entry/report.json
    python scripts/summarize-xnu-entry.py --latest     # newest report under out/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def newest_report() -> Path | None:
    reports = sorted(ROOT.glob("out/**/report.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return reports[0] if reports else None


def summarize(report: dict) -> dict:
    milestones = report.get("milestones") or []
    watched = report.get("watched") or {}
    reached = [name for name, value in watched.items() if value]
    missing = [name for name, value in watched.items() if not value]
    return {
        "past_bsd_outcome": report.get("past_bsd_outcome"),
        "fault_elr_symbol": report.get("fault_elr_symbol"),
        "fault_far": report.get("fault_far"),
        "milestones": len(milestones),
        "last_milestone": milestones[-1] if milestones else None,
        "watched_reached": reached,
        "watched_missing": missing,
        "vfs_mountroot": bool(watched.get("_vfs_mountroot")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", nargs="?", type=Path, help="path to report.json")
    parser.add_argument("--latest", action="store_true", help="use the newest report under out/")
    args = parser.parse_args(argv)

    path = args.report
    if args.latest or path is None:
        path = newest_report()
    if path is None or not path.is_file():
        print("error: no report.json found; pass a path", file=sys.stderr)
        return 2

    report = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    summary = summarize(report)

    print(f"report: {path}")
    print(f"past bsd init : {summary['past_bsd_outcome']}")
    print(f"fault symbol  : {summary['fault_elr_symbol']}")
    print(f"fault address : {summary['fault_far']}")
    print(f"milestones    : {summary['milestones']}  last={summary['last_milestone']}")
    print(f"vfs_mountroot : {'reached' if summary['vfs_mountroot'] else 'never reached'}")
    print()
    print("watched reached:", ", ".join(summary["watched_reached"]) or "(none)")
    print("watched missing:", ", ".join(summary["watched_missing"]) or "(none)")
    if summary["past_bsd_outcome"] == "stopped" and summary["fault_elr_symbol"]:
        print()
        print("verdict: BSD initialisation has not returned; the boot stops in "
              f"{summary['fault_elr_symbol']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
