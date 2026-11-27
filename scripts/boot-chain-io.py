#!/usr/bin/env python3
"""One decision point for writing or deleting a protected boot-chain object.

`boot-chain-guard.py` knows *which* objects are protected; this module knows *what it takes* to touch one, and every writer in this
repository is meant to go through it. The rules are deliberately the same for all six classes and for both operations:

    replace a protected object   -> --replace-protected + --backup FILE (an existing file) + --reason TEXT + --verify TEXT
    delete it                    -> --delete-protected  + --backup FILE + --reason TEXT + --verify TEXT
    create it on a blank volume  -> nothing (there is nothing to destroy)

`--replace-protected` on its own is not authorisation for a file that already carries hand-off evidence: the caller has to say which
object, why, what the recovery file is and how the result will be verified. The strings are recorded in the output so a log shows
what was claimed.

    from boot_chain_io import Decision, authorise
    decision = authorise(destination, replace=True, backup=args.backup, reason=args.reason, verify=args.verify)
    if not decision.allowed: fail(decision.message)
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _guard():
    spec = importlib.util.spec_from_file_location("boot_chain_guard", _HERE / "boot-chain-guard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD = _guard()


@dataclasses.dataclass
class Decision:
    allowed: bool
    message: str
    protected: str | None = None


def protected_object(path: Path) -> str | None:
    """The protected class this path belongs to, by suffix match on the volume-relative path."""
    text = path.as_posix().replace("\\", "/").casefold()
    for name in GUARD.PROTECTED:
        if text == name or text.endswith("/" + name):
            return name
    marker = "/" + GUARD.PROTECTED_TREE + "/"
    if marker in "/" + text or text == GUARD.PROTECTED_TREE:
        return GUARD.PROTECTED_TREE + "/**"
    return None


def authorise(destination: Path, *, replace: bool = False, delete: bool = False,
              backup: Path | None = None, reason: str | None = None,
              verify: str | None = None, exists: bool | None = None) -> Decision:
    """Decide whether this write/delete may proceed.

    `exists` lets a caller say what the *volume* holds rather than what the local filesystem does, which matters when the destination
    path is the phone's but only reachable through a mount that may lag.
    """
    protected = protected_object(destination)
    if protected is None:
        return Decision(True, f"allowed: {destination} is not a protected boot-chain object")

    present = destination.exists() if exists is None else exists
    if not present and not delete:
        return Decision(True, f"allowed: {destination} is protected ({protected}) and does not exist yet", protected)

    if not (replace or delete):
        verb = "delete" if delete else "replace"
        return Decision(False, f"refused: {destination} is protected ({protected}); to {verb} it pass "
                               f"--{'delete' if delete else 'replace'}-protected together with --backup, --reason and --verify",
                        protected)

    missing = []
    if backup is None or not Path(backup).is_file():
        missing.append("--backup (an existing file that can restore this object)")
    if not reason:
        missing.append("--reason (what is being replaced and why)")
    if not verify:
        missing.append("--verify (how the result will be proven)")
    if missing:
        return Decision(False, f"refused: {destination} is protected ({protected}) and the request is incomplete: "
                               + "; ".join(missing), protected)

    verb = "delete" if delete else "replace"
    return Decision(True, f"allowed: {verb} {destination} ({protected}); backup={backup}; reason={reason!r}; verify={verify!r}",
                    protected)


def inventory_of(root: Path) -> dict:
    return GUARD.inventory(root)


def main(argv: list[str] | None = None) -> int:
    """Command line so a shell script can ask the same question."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path)
    parser.add_argument("--replace-protected", action="store_true")
    parser.add_argument("--delete-protected", action="store_true")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--reason")
    parser.add_argument("--verify")
    args = parser.parse_args(argv)

    decision = authorise(args.path, replace=args.replace_protected, delete=args.delete_protected,
                         backup=args.backup, reason=args.reason, verify=args.verify)
    stream = sys.stdout if decision.allowed else sys.stderr
    print(decision.message, file=stream)
    return 0 if decision.allowed else 1


if __name__ == "__main__":
    sys.exit(main())
