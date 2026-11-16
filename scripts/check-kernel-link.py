#!/usr/bin/env python3
"""Fail when a device driver compiled but never reached the kernel image.

AGENTS.md rule 6 and the `kernel-linked` label in docs/BUILD-VERIFICATION.md both require the
archive to be in the link and its symbols to be in the image. What the kernel job actually did
was print `ar t` for each archive and `shasum` them, always succeeding, so a driver that compiled
into an archive and was never linked left a green run. That is the difference between "the code
builds" and "the kernel contains the code".

    python3 scripts/check-kernel-link.py --image out/lumia950/kernel/kernel.macho.unstripped
    python3 scripts/check-kernel-link.py --symbols-from nm.txt --expect NativeSdhci

Symbols are matched case-insensitively against the mangled names `nm` prints, because that is
what an Itanium-ABI C++ class produces (`__ZN11NativeSdhci...`). --symbols-from exists so the
matching rules can be tested without a macOS kernel build.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The components this port links from source. A missing one means either it was not compiled or
# the link dropped it; both are the failure this file exists for. board.toml's [kernel] archives
# list is the single source when it is readable; this is the fallback.
DEFAULT_EXPECTED = ("ArmDTPlatform", "ArmCpu", "NativeSdhci", "NativeLegacyDisplay", "NativeMdss",
                    "NativeAdreno418")

# Not every component exports a symbol named after itself. The driver classes are C++ and land in
# the table as `__ZN11NativeSdhci...`, but NativeLegacyDisplay is a C entry point called by
# bsd_init.c and its symbol is `_native_legacy_display_probe` -- the image can contain that
# component and nothing spelled like the directory. A component counts as linked when any of its
# needles is found.
SYMBOL_ALIASES = {
    "NativeLegacyDisplay": ("NativeLegacyDisplay", "native_legacy_display_probe"),
}


def fail(message: str):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def excluded_from_board(path: Path) -> dict:
    """Components the board says cannot be in the source link yet, and why.

    An exclusion is a recorded decision: it has to name an archive the board actually builds and it
    has to say why. NativeSdhci subclasses IOBlockStorageDevice, which lives in IOStorageFamily --
    an Apple kext merged after the source kernel link -- so the source link cannot resolve it.
    """
    board = tomllib.loads(path.read_text())
    kernel = board.get("kernel") or {}
    excluded = kernel.get("link_excluded") or {}
    archives = set()
    for entry in kernel.get("archives") or []:
        parts = entry.split()
        if len(parts) == 2 and parts[0] == "build-arm-driver.py":
            archives.add(parts[1])
    for name, reason in excluded.items():
        if name not in archives:
            fail(f"{path} excludes {name} from the link, but [kernel] archives never builds it")
        if not str(reason or "").strip():
            fail(f"{path} excludes {name} from the link without saying why; an unexplained "
                 "exclusion is the silent gap this check exists to prevent")
    return excluded


def expected_from_board(path: Path) -> list[str]:
    """Every `build-arm-driver.py <Component>` entry in board.toml is a component to prove.

    Reading the list instead of copying it is the point: a driver added to board.toml becomes a
    link assertion without anyone remembering to edit a second list.
    """
    board = tomllib.loads(path.read_text())
    names = []
    for entry in (board.get("kernel") or {}).get("archives") or []:
        parts = entry.split()
        if len(parts) == 2 and parts[0] == "build-arm-driver.py":
            names.append(parts[1])
    if not names:
        fail(f"{path} [kernel] archives names no build-arm-driver.py component")
    return names


def symbol_dump(image: Path, nm: str) -> str:
    result = subprocess.run([nm, "-gU", "--defined-only", str(image)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        # -gU is llvm-nm's spelling; Apple nm takes -g -U separately.
        result = subprocess.run([nm, "-g", "-U", str(image)], capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"{nm} failed on {image}: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def find(dump: str, name: str) -> int:
    needles = [needle.casefold() for needle in SYMBOL_ALIASES.get(name, (name,))]
    return sum(1 for line in dump.splitlines() if any(needle in line.casefold()
                                                      for needle in needles))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", type=Path,
                        help="the linked kernel image, e.g. mach.development.bcm2837.unstripped")
    parser.add_argument("--symbols-from", type=Path,
                        help="read an `nm -gU --defined-only` dump instead of running nm (tests)")
    parser.add_argument("--nm", default="llvm-nm", help="the symbol reader (default: llvm-nm)")
    parser.add_argument("--board", type=Path, default=ROOT / "board.toml",
                        help="board.toml whose [kernel] archives name the components to prove "
                             "(default: this repository's board.toml)")
    parser.add_argument("--expect", action="append", metavar="NAME",
                        help="a component that has to be linked (repeatable; overrides --board)")
    parser.add_argument("--omit", action="append", default=[], metavar="NAME",
                        help="a component to leave out of the resolved set (for experiments)")
    parser.add_argument("--archives-root", type=Path,
                        help="also require lib<Component>.a under this directory; the archive "
                             "existing is the compile half, the symbol is the link half")
    args = parser.parse_args()

    if args.symbols_from:
        dump = args.symbols_from.read_text()
        source = str(args.symbols_from)
    else:
        if args.image is None:
            parser.error("pass --image, or --symbols-from for a recorded dump")
        if not args.image.is_file():
            fail(f"{args.image} is missing; the kernel was linked but no image was found")
        dump = symbol_dump(args.image, args.nm)
        source = str(args.image)

    if args.expect:
        expected = list(args.expect)
    elif args.board is not None and args.board.is_file():
        expected = expected_from_board(args.board)
        excluded = excluded_from_board(args.board)
        for name in expected:
            if name in excluded:
                print(f"excluded from the source link: {name} ({excluded[name]})")
        expected = [name for name in expected if name not in excluded]
    else:
        expected = list(DEFAULT_EXPECTED)
    expected = [name for name in expected if name not in args.omit]
    if not expected:
        parser.error("no component to prove; --omit removed them all")
    missing = [name for name in expected if not find(dump, name)]
    if missing:
        fail(f"{source} does not link {', '.join(missing)}: the archive compiled but the kernel "
             "image has no symbol for it, so `kernel-linked` is not established and a phone would "
             "boot a kernel without that driver")
    counts = ", ".join(f"{name} {find(dump, name)}" for name in expected)
    if args.archives_root is not None:
        missing_archives = [name for name in expected
                            if not list(args.archives_root.rglob(f"lib{name}.a"))]
        if missing_archives:
            fail(f"no archive for {', '.join(missing_archives)} under {args.archives_root}: the "
                 "component was not compiled, so the symbol cannot have come from this build")
    print(f"kernel link ok: {source} carries {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
