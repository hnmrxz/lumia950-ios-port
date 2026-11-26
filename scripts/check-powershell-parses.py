#!/usr/bin/env python3
"""Parse every PowerShell script in scripts/ with the real PowerShell parser, without running anything.

A recovery script with a syntax error is worse than no recovery script: it fails exactly when it is needed and
the failure looks like a phone problem. The parser is the same one PowerShell uses, so this catches it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The path goes through the environment: with -Command, arguments after the script text are not bound to
# a param() block, which made every file look unreadable on the first attempt.
PARSER = (
    "$errors = $null; "
    "[System.Management.Automation.Language.Parser]::ParseFile($env:DSH_PS_SCRIPT, [ref]$null, [ref]$errors) > $null; "
    "if ($errors -and $errors.Count -gt 0) { "
    "$errors | ForEach-Object { Write-Output ($_.Extent.StartLineNumber.ToString() + ': ' + $_.Message) }; "
    "exit 1 } else { Write-Output 'ok'; exit 0 }"
)


def find_shell() -> str | None:
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def main() -> int:
    scripts = sorted((ROOT / "scripts").glob("*.ps1"))
    if not scripts:
        print("no PowerShell scripts to parse")
        return 0

    shell = find_shell()
    if shell is None:
        print("skipped: no PowerShell on this host (the macOS runner is not where these run)")
        print(json.dumps({"scripts": len(scripts), "failures": 0, "skipped": True}))
        return 0

    failures = 0
    for script in scripts:
        environment = dict(os.environ, DSH_PS_SCRIPT=str(script))
        result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", PARSER],
                                capture_output=True, text=True, timeout=120, env=environment)
        output = (result.stdout + result.stderr).strip()
        ok = result.returncode == 0
        print(f"{'ok  ' if ok else 'FAIL'} {script.name}: {output.splitlines()[0] if output else 'no output'}")
        if not ok:
            for line in output.splitlines()[1:]:
                print(f"     {line}")
            failures += 1
    print(json.dumps({"scripts": len(scripts), "failures": failures}))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
