#!/usr/bin/env python3
"""Run every test in scripts/ that needs no outside input, and say why the others are skipped.

The CI workflow used to list test files one command per line, so a new test could be added and
never run. This is the one place that decides what the suite is:

    python3 scripts/run-tests.py            # everything that is self-contained
    python3 scripts/run-tests.py --list     # just show the classification

`scripts/test-run-tests.py` fails if a `scripts/test-*.py` file is in neither list, so a new test
cannot be silently forgotten.
"""
import argparse
import pathlib
import subprocess
import sys
import time

SCRIPTS = pathlib.Path(__file__).resolve().parent

# Tests that read this repository only: safe to run anywhere, no QEMU, no SDK, no fetched source.
SELF_CONTAINED = (
    "test-action-pins.py",
    "test-adt-profile.py",
    "test-build-manifest.py",
    "test-check-phase.py",
    "test-checkpoints.py",
    "test-compare-xnu-reports.py",
    "test-phone-modes.py",
    "test-phone-tools.py",
    "test-phone-install.py",
    "test-rehearse-phone-install.py",
    "test-rehearse-phone-rollback.py",
    "test-powershell-parses.py",
    "test-boot-progress-hook.py",
    "test-kernel-personality.py",
    "test-deploy-kernel.py",
    "test-swap-loader.py",
    "test-evidence-paths.py",
    "test-make-mkext.py",
    "test-check-kext.py",
    "test-embed-blob.py",
    "test-prng-single-init.py",
    "test-check-bcd-layout.py",
    "test-check-host-tests-portable.py",
    "test-summarize-xnu-entry.py",
    "test-ramblock-hook.py",
    "test-skmem-skip.py",    "test-doc-references.py",
    "test-evidence.py",
    "test-gpu-tools.py",
    "test-graphics-profile.py",
    "test-kernel-link.py",
    "test-menu-render.py",
    "test-native-bringup.py",
    "test-native-install.py",
    "test-no-device-identifiers.py",
    "test-oem-scm-profile.py",
    "test-probe-fat.py",
    "test-probe-qemu-host.py",
    "test-reproducible.py",
    "test-stage-kernel.py",
    "test-xnu-entry-adt.py",
    "test-xnu-entry-flags.py",
    "test-run-tests.py",
)

# Tests that need something this repository does not contain: a built image, an ESP, QEMU, or
# source files CI fetches. Each row says what it needs, so a skipped test is not a mystery.
NEEDS_INPUT = {
    "test-armcpu-patch.py": "--source (the ArmCpu checkout the patch applies to)",
    "test-gicv2-qemu.py": "--image (a built EFI image) and QEMU",
    "test-handoff-qemu.py": "--esp, --firmware, --output",
    "test-native-clocks.py": "--identify, --routines (fetched xnu sources)",
    "test-native-xnu-entry.py": "--kernel, --esp, --firmware, --output (the QEMU fixture)",
    "test-probe-qemu.py": "--esp, --firmware",
    "test-xnu-build-flags.py": "--make-def, --startup, --bootstrap-patch (fetched xnu sources)",
}


def discover():
    return sorted(path.name for path in SCRIPTS.glob("test-*.py"))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="show the classification and exit")
    parser.add_argument("--check-classification", action="store_true",
                        help="exit 2 if any scripts/test-*.py is unclassified, without running "
                             "anything; the runner's own test uses this to avoid recursing")
    parser.add_argument("--verbose", action="store_true", help="stream each test's output")
    args = parser.parse_args()

    everything = discover()
    unclassified = [name for name in everything
                    if name not in SELF_CONTAINED and name not in NEEDS_INPUT]
    if unclassified:
        print(f"error: not classified, so never run: {', '.join(unclassified)}", file=sys.stderr)
        print("add each to SELF_CONTAINED or NEEDS_INPUT in scripts/run-tests.py", file=sys.stderr)
        return 2

    if args.check_classification:
        return 0

    if args.list:
        for name in SELF_CONTAINED:
            print(f"run    {name}")
        for name, reason in NEEDS_INPUT.items():
            print(f"skip   {name}: needs {reason}")
        return 0

    failures = []
    started = time.monotonic()
    for name in SELF_CONTAINED:
        begin = time.monotonic()
        result = subprocess.run([sys.executable, str(SCRIPTS / name)],
                                capture_output=True, text=True)
        took = time.monotonic() - begin
        if result.returncode == 0:
            print(f"PASS {name:32} {took:5.1f}s")
            continue
        print(f"FAIL {name:32} {took:5.1f}s")
        failures.append(name)
        output = (result.stdout + result.stderr).strip()
        if args.verbose:
            print(output)
        else:
            tail = output.splitlines()[-12:]
            print("\n".join(f"     {line}" for line in tail))
    for name, reason in NEEDS_INPUT.items():
        print(f"SKIP {name:32} needs {reason}")
    print(f"\n{len(SELF_CONTAINED) - len(failures)}/{len(SELF_CONTAINED)} passed, "
          f"{len(NEEDS_INPUT)} skipped with input requirements, "
          f"{time.monotonic() - started:.1f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

