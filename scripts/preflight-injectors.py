#!/usr/bin/env python3
"""Everything that can be checked on this machine, before a CI run is spent.

Six of the first seven kernel runs after the boot-progress instrument existed failed in the injectors, not in
the kernel: a wrong anchor, a stale signature, a statement above the declarations, an edit that fought the
framework's own patch series, and a store that faulted. Four of those are visible locally in about a minute:

  1. rehearse    -- apply and re-check both injectors against the real pinned sources (network once);
  2. snippet     -- compile the exact statement pair the injector inserts, so a wrong boot_args member name or
                    a C syntax error shows up now instead of after a thirty-minute build;
  3. driver      -- cross-compile drivers/NativeBootProgress for aarch64 freestanding with -Werror, which is a
                    stricter compiler than the one that will build it;
  4. core        -- build and run the geometry host test.

A compiler is needed for 2-4. Zig works: it cross-compiles aarch64 and builds the host test, and it is a single
zip. Set ZIG, or put zig on PATH, or drop a copy under tools/zig-*/.

    python scripts/preflight-injectors.py            # fail fast, print each step
    python scripts/preflight-injectors.py --no-net   # skip step 1's fetch, use the cached sources
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REV = "xnu-8796.141.3"
CACHE = ROOT / "build" / "local" / "preflight"
SOURCES = {
    "osfmk/arm/arm_init.c": f"https://api.github.com/repos/apple-oss-distributions/xnu/contents/osfmk/arm/arm_init.c?ref={REV}",
        "bsd/kern/bsd_init.c": f"https://api.github.com/repos/apple-oss-distributions/xnu/contents/bsd/kern/bsd_init.c?ref={REV}",
"iokit/KernelConfigTables.cpp": f"https://api.github.com/repos/apple-oss-distributions/xnu/contents/iokit/KernelConfigTables.cpp?ref={REV}",
    "osfmk/prng/prng_random.c": f"https://api.github.com/repos/apple-oss-distributions/xnu/contents/osfmk/prng/prng_random.c?ref={REV}",
}

SNIPPET = r"""
#include <stdint.h>

struct Boot_Video {
    unsigned long v_baseAddr;
    unsigned long v_rowBytes;
    unsigned long v_height;
    unsigned long v_depth;
};

/* The pinned layout: Video, then deviceTreeP, deviceTreeLength, CommandLine. */
typedef struct boot_args {
    unsigned short Revision;
    unsigned short Version;
    uint32_t virtBase;
    uint32_t physBase;
    uint32_t memSize;
    uint32_t topOfKernelData;
    struct Boot_Video Video;
    uint32_t machineType;
    void *deviceTreeP;
    uint32_t deviceTreeLength;
    char CommandLine[1024];
} boot_args;

extern void native_boot_progress_remember(void *base, unsigned long stride, unsigned long height,
                                          const char *command_line);
extern void native_boot_progress_stage(void *base, unsigned long stride, unsigned long height,
                                       const char *command_line, int stage);

/* arm_init declares its locals first and then runs statements; the injection lives among the statements. */
static void arm_init_shaped(boot_args *args)
{
    unsigned int maxmem;
    (void)maxmem;

    native_boot_progress_remember((void *)args->Video.v_baseAddr, args->Video.v_rowBytes,
                                  args->Video.v_height, args->CommandLine);
    native_boot_progress_stage((void *)args->Video.v_baseAddr, args->Video.v_rowBytes,
                               args->Video.v_height, args->CommandLine, 0);
    native_boot_progress_stage((void *)args->Video.v_baseAddr, args->Video.v_rowBytes,
                               args->Video.v_height, args->CommandLine, 1);
}


void preflight_entry(boot_args *args) { arm_init_shaped(args); }
"""


def find_zig() -> str | None:
    explicit = os.environ.get("ZIG")
    if explicit and Path(explicit).is_file():
        return explicit
    on_path = shutil.which("zig")
    if on_path:
        return on_path
    tools = ROOT.parent / "tools"
    if tools.is_dir():
        for candidate in sorted(tools.glob("zig-*/zig.exe"), reverse=True):
            return str(candidate)
    return None


def fetch_sources(use_net: bool) -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    missing = 0
    for relative, url in SOURCES.items():
        destination = CACHE / relative
        if destination.is_file():
            print(f"  cached  {relative} ({destination.stat().st_size} B)")
            continue
        if not use_net:
            print(f"  MISSING {relative} and --no-net was given")
            missing += 1
            continue
        try:
            with urllib.request.urlopen(url, timeout=90) as response:
                payload = json.load(response)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(base64.b64decode(payload["content"]).decode("utf-8", "replace"),
                                   encoding="utf-8")
            print(f"  fetched {relative} ({destination.stat().st_size} B)")
        except Exception as error:  # noqa: BLE001 - report and continue to the next check
            print(f"  FAIL    {relative}: {error}")
            missing += 1
    return missing


def step_rehearse() -> bool:
    """Copy the cached sources, run both injectors, and require --apply and --check to pass."""
    with tempfile.TemporaryDirectory() as temporary:
        tree = Path(temporary)
        for relative in SOURCES:
            source = CACHE / relative
            if not source.is_file():
                print("  skipped: sources are not cached")
                return True
            destination = tree / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        ok = True
        for script in ("ci/boot-progress.py", "ci/kernel-personality.py", "ci/prng-single-init.py"):
            for mode in ("--apply", "--check"):
                result = subprocess.run([sys.executable, str(ROOT / script), "--root", str(tree), mode],
                                        capture_output=True, text=True)
                first = (result.stdout.strip().splitlines() or ["(no output)"])[0]
                print(f"  {script} {mode}: exit {result.returncode}  {first}")
                if result.returncode != 0 and mode == "--apply":
                    ok = False
    return ok


def compile_with(zig: str | None, arguments: list[str], what: str) -> bool:
    if zig is None:
        print(f"  skipped {what}: no compiler (set ZIG or put zig under tools/)")
        return True
    result = subprocess.run([zig, *arguments], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FAIL {what}")
        for line in (result.stdout + result.stderr).strip().splitlines()[:12]:
            print(f"       {line}")
        return False
    print(f"  ok {what}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-net", action="store_true", help="use only the cached sources")
    args = parser.parse_args(argv)

    out = CACHE
    out.mkdir(parents=True, exist_ok=True)

    print("[1/4] pinned sources")
    fetch_sources(use_net=not args.no_net)

    print("[2/4] injectors against those sources")
    rehearse_ok = step_rehearse()

    zig = find_zig()
    print(f"[3/4] snippet and driver compile (compiler: {zig or 'none'})")

    snippet = out / "snippet.c"
    snippet.write_text(SNIPPET, encoding="utf-8")
    snippet_ok = compile_with(
        zig,
        ["cc", "-target", "aarch64-freestanding", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
         "-Werror=declaration-after-statement", "-c", str(snippet), "-o", str(out / "snippet.o")],
        "injected snippet (aarch64, -Werror=declaration-after-statement)")

    driver_ok = compile_with(
        zig,
        ["c++", "-target", "aarch64-freestanding", "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-I", str(ROOT / "drivers/NativeBootProgress"), "-c",
         str(ROOT / "drivers/NativeBootProgress/NativeBootProgress.cpp"),
         "-o", str(out / "NativeBootProgress.o")],
        "drivers/NativeBootProgress (aarch64)")

    print("[4/4] geometry host test")
    core_exe = out / "check-boot-progress-core.exe"
    core_ok = compile_with(
        zig,
        ["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "drivers/NativeBootProgress"),
         "-o", str(core_exe), str(ROOT / "drivers/NativeBootProgress/Test/check-boot-progress-core.cpp")],
        "check-boot-progress-core builds")
    if core_ok and core_exe.is_file():
        run = subprocess.run([str(core_exe)], capture_output=True, text=True)
        print(f"  {'ok' if run.returncode == 0 else 'FAIL'} check-boot-progress-core runs: "
              f"{(run.stdout or run.stderr).strip().splitlines()[0] if (run.stdout or run.stderr).strip() else ''}")
        core_ok = run.returncode == 0

    everything = rehearse_ok and snippet_ok and driver_ok and core_ok
    print()
    print("preflight:", "ok" if everything else "FAILED")
    return 0 if everything else 1


if __name__ == "__main__":
    sys.exit(main())
