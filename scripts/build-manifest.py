#!/usr/bin/env python3
"""Write, and check, the provenance manifest for one kernel job run.

The artifact alone cannot say what produced it. Two runs seven days apart both hand over a
`kernel.macho` and a `kernel.log`, and neither says which framework commit, which 16.x shim,
which kernelcache or which SDK was behind it — so a prelinked image cannot be traced back to a
build, and the `prelink-checked` label is not reproducible.

This writes one JSON file that answers that for a single run: the commit of this repository,
the hashes of the four files that decide what gets built, the pinned framework ref and its tree,
the resolved feeds lock, the kernelcache the merge is tied to, the toolchain, the guard state of
board.toml, and the SHA-256 of every artifact the job produced.

    python3 scripts/build-manifest.py --framework-ref <pin> --scratch-board <copy> --probe-toolchain
    python3 scripts/build-manifest.py --check out/build-manifest.json --verify-outputs

Two rules it enforces instead of recording:

* `--framework-ref` must equal the checked-out framework's HEAD, so the pin in the workflow and
  the tree that was actually compiled cannot drift apart silently.
* `board.toml` keeps `example = true`, and the scratch copy the build ran from must not — that
  is the difference between "a build of a research board" and "a board claimed complete", and
  the manifest records both hashes so the difference survives the run.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - the runners have 3.11+
    sys.exit("python3.11 or newer is required (tomllib)")

SCHEMA = "lumia950-build-manifest-v1"

SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")

# Everything the build consumed that can change the output. A manifest without one of these is
# not provenance, so --check rejects it.
REQUIRED_INPUTS = (
    "repo_commit", "repo_dirty",
    "workflow_sha256", "ci_patch_sha256", "feeds_sha256", "board_toml_sha256",
    "board_toml_guard_present", "framework_ref", "framework_tree", "framework_patched",
    "unixnu_lock_sha256", "kernelcache_sha256_expected",
)
REQUIRED_DIGESTS = (
    "workflow_sha256", "ci_patch_sha256", "feeds_sha256", "board_toml_sha256",
    "unixnu_lock_sha256", "kernelcache_sha256_expected",
)

INPUT_FILES = (
    ("workflow_sha256", ".github/workflows/build.yml"),
    ("ci_patch_sha256", "ci/unixnu-16x.patch"),
    ("feeds_sha256", "feeds.toml"),
    ("board_toml_sha256", "board.toml"),
)

OUTPUT_PATTERNS = (
    ("kernel_macho", "out/*/kernel/kernel.macho"),
    ("kernel_prelink_report", "out/*/kernel/kernel.json"),
    ("kernel_stripped", "out/*/tree/build/xnu/ios-obj/*/mach.development.bcm2837"),
    ("kernel_unstripped", "out/*/tree/build/xnu/ios-obj/*/mach.development.bcm2837.unstripped"),
    ("archives", "out/*/tree/build/*/lib*.a"),
)
# The job is worthless without the image and the report that qualifies it; the rest is evidence
# when present and absent when the step that writes it did not run.
REQUIRED_OUTPUTS = ("kernel_macho", "kernel_prelink_report")

TOOLCHAIN_KEYS = ("os_version", "arch", "xcode", "iphoneos_sdk", "clang")


def fail(message: str):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"git {' '.join(arguments)} failed in {root}: "
             f"{(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def probe(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"{' '.join(command)} failed: {(result.stderr or result.stdout).strip()}")
    lines = result.stdout.strip().splitlines()
    if not lines:
        fail(f"{' '.join(command)} printed nothing; the manifest cannot record it")
    return lines[0].strip()


def collect_toolchain(args: argparse.Namespace) -> dict:
    values: dict[str, str] = {}
    if args.probe_toolchain:
        values["os_version"] = probe(["sw_vers", "-productVersion"])
        values["arch"] = probe(["uname", "-m"])
        values["xcode"] = probe(["xcodebuild", "-version"])
        values["iphoneos_sdk"] = probe(["xcrun", "--sdk", "iphoneos", "--show-sdk-version"])
        values["clang"] = probe(["clang", "--version"])
    for key in TOOLCHAIN_KEYS:
        override = getattr(args, key)
        if override is not None:
            values[key] = override
    missing = [key for key in TOOLCHAIN_KEYS if not values.get(key)]
    if missing:
        fail(f"the toolchain is not recorded ({', '.join(missing)}); pass --probe-toolchain on "
             "macOS, or the individual --os-version/--arch/--xcode/--iphoneos-sdk/--clang values")
    if args.expect_sdk:
        if not values["iphoneos_sdk"].startswith(args.expect_sdk):
            fail(f"the iPhoneOS SDK is {values['iphoneos_sdk']} but this build expects "
                 f"{args.expect_sdk}*; a silent SDK change is exactly what must not happen")
    return values


def collect_inputs(root: Path, args: argparse.Namespace) -> dict:
    board_path = root / "board.toml"
    if not board_path.is_file():
        fail(f"{board_path} is missing; run this from the device repository")
    board = tomllib.loads(board_path.read_text())
    if not board.get("board", {}).get("example"):
        fail(f"{board_path} has no `example = true`; the committed board keeps the incomplete-"
             "board guard even when a build works, so a cleared guard here means the workspace "
             "was edited and this run does not describe the committed board")

    inputs: dict = {
        "repo_commit": git(root, "rev-parse", "HEAD"),
        # Tracked changes only: the job writes logs and out/ trees that are gitignored, and a
        # build is not dirty because of its own output.
        "repo_dirty": bool(git(root, "status", "--porcelain", "--untracked-files=no")),
        "board_toml_guard_present": True,
    }
    for name, relative in INPUT_FILES:
        path = root / relative
        if not path.is_file():
            fail(f"{path} is missing; it decides what this build contains")
        inputs[name] = sha256_file(path)

    framework = root / args.framework_dir
    if not (framework / ".git").exists():
        fail(f"{framework} is not a git checkout; pass --framework-dir for the UniXNU pin")
    head = git(framework, "rev-parse", "HEAD")
    if head != args.framework_ref:
        fail(f"{framework} is at {head}, but the pinned ref is {args.framework_ref}; the pin in "
             "the workflow and the tree that compiled have to be the same commit")
    inputs["framework_ref"] = args.framework_ref
    inputs["framework_tree"] = git(framework, "rev-parse", "HEAD^{tree}")
    # The 16.x overlay applies on top of the pin. Whether it applied, or was already in the
    # checkout, changes nothing about the tree hash, so it is recorded separately.
    inputs["framework_patched"] = bool(
        git(framework, "status", "--porcelain", "--untracked-files=no"))

    lock = framework / "unixnu.lock"
    if not lock.is_file():
        fail(f"{lock} is missing; it is the resolved feeds record and the only place the "
             "component refs of this run exist")
    inputs["unixnu_lock_sha256"] = sha256_file(lock)

    prelink = board.get("kernel", {}).get("prelink") or {}
    expected = prelink.get("kernelcache_sha256")
    if not expected or not SHA256.fullmatch(str(expected)):
        fail(f"{board_path} [kernel.prelink] has no kernelcache_sha256; the merge is not tied "
             "to a component ABI without it")
    inputs["kernelcache_sha256_expected"] = str(expected)

    if args.scratch_board:
        scratch = Path(args.scratch_board)
        if not scratch.is_file():
            fail(f"{scratch} is missing; pass the board.toml copy the build actually used")
        scratch_board = tomllib.loads(scratch.read_text())
        if scratch_board.get("board", {}).get("example"):
            fail(f"{scratch} still has `example = true`; the build did not run from the cleared "
                 "scratch copy, so its guard state is not what this manifest describes")
        inputs["scratch_board_toml_sha256"] = sha256_file(scratch)
    return inputs


def collect_outputs(root: Path) -> dict:
    outputs: dict[str, list[dict]] = {}
    for name, pattern in OUTPUT_PATTERNS:
        entries = []
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                entries.append({"path": path.relative_to(root).as_posix(),
                                "bytes": path.stat().st_size, "sha256": sha256_file(path)})
        if entries:
            outputs[name] = entries
    return outputs


def collect_prelink(root: Path, outputs: dict) -> dict | None:
    entries = outputs.get("kernel_prelink_report") or []
    if not entries:
        return None
    report = json.loads((root / entries[0]["path"]).read_text())
    sparse = report.get("sparse_index") or {}
    return {
        "loadable": report.get("loadable"),
        "components": len(report.get("components") or []),
        "bindings": len(report.get("bindings") or []),
        "sparse_index_headers": len(sparse.get("headers") or []),
    }


def check(manifest: dict, root: Path, verify_outputs: bool, allow_dirty: bool = False) -> None:
    if manifest.get("schema") != SCHEMA:
        fail(f"{root}: schema is {manifest.get('schema')!r}, expected {SCHEMA!r}")
    inputs = manifest.get("inputs") or {}
    for key in REQUIRED_INPUTS:
        if inputs.get(key) in (None, "", []):
            fail(f"the manifest has no inputs.{key}")
    if inputs["repo_dirty"] is not False and not allow_dirty:
        fail("the manifest describes a dirty checkout; the artifact cannot be attributed to "
             f"{inputs.get('repo_commit')}")
    if not COMMIT.fullmatch(str(inputs["repo_commit"])):
        fail(f"inputs.repo_commit is {inputs['repo_commit']!r}, not a 40-hex commit")
    if not COMMIT.fullmatch(str(inputs["framework_ref"])):
        fail(f"inputs.framework_ref is {inputs['framework_ref']!r}, not a 40-hex commit")
    # A git tree id is 40 hex, not 64: it is the framework's content address, and it is what
    # changes if the pin is the same commit reached through a different history.
    if not COMMIT.fullmatch(str(inputs["framework_tree"])):
        fail(f"inputs.framework_tree is {inputs['framework_tree']!r}, not a git tree id")
    for key in REQUIRED_DIGESTS:
        if not SHA256.fullmatch(str(inputs.get(key))):
            fail(f"inputs.{key} is {inputs.get(key)!r}, not a SHA-256")
    toolchain = manifest.get("toolchain") or {}
    for key in TOOLCHAIN_KEYS:
        if not toolchain.get(key):
            fail(f"the manifest has no toolchain.{key}")

    outputs = manifest.get("outputs") or {}
    for name in REQUIRED_OUTPUTS:
        if not outputs.get(name):
            fail(f"the manifest has no outputs.{name}; the job produced no {name} to attribute")
    for name, entries in outputs.items():
        if not isinstance(entries, list) or not entries:
            fail(f"outputs.{name} is not a non-empty list")
        for entry in entries:
            for key in ("path", "bytes", "sha256"):
                if key not in entry:
                    fail(f"outputs.{name} entry has no {key}")
            if not SHA256.fullmatch(str(entry["sha256"])):
                fail(f"outputs.{name} {entry['path']} sha256 is {entry['sha256']!r}")
            if verify_outputs:
                path = root / entry["path"]
                if not path.is_file():
                    fail(f"{path} is gone; the manifest advertised it")
                if sha256_file(path) != entry["sha256"]:
                    fail(f"{path} does not match the manifest; the artifact changed after it "
                         "was recorded")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="the device repository (default: this script's repository)")
    parser.add_argument("--output", type=Path, default=Path("out/build-manifest.json"),
                        help="where to write the manifest (default: out/build-manifest.json)")
    parser.add_argument("--check", type=Path,
                        help="validate an existing manifest instead of writing one")
    parser.add_argument("--verify-outputs", action="store_true",
                        help="with --check, re-hash every output the manifest names")
    parser.add_argument("--framework-dir", default="unixnu",
                        help="the UniXNU checkout the pin names (default: unixnu)")
    parser.add_argument("--framework-ref",
                        help="the pinned framework commit the workflow checks out; required "
                             "unless --check, and it must equal the checkout's HEAD")
    parser.add_argument("--scratch-board",
                        help="the board.toml copy the build ran from (the guard-cleared one)")
    parser.add_argument("--probe-toolchain", action="store_true",
                        help="read sw_vers/uname/xcodebuild/xcrun/clang (macOS)")
    parser.add_argument("--expect-sdk", default="",
                        help="refuse the run unless the iPhoneOS SDK starts with this prefix")
    for flag, key in (("--os-version", "os_version"), ("--arch", "arch"), ("--xcode", "xcode"),
                      ("--iphoneos-sdk", "iphoneos_sdk"), ("--clang", "clang")):
        parser.add_argument(flag, dest=key, help=f"record {key} explicitly (CI probes it)")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="record a dirty checkout instead of refusing (local experiments; "
                             "the manifest then cannot be attributed to a commit)")
    args = parser.parse_args()

    root = args.root.resolve()
    if args.check:
        manifest = json.loads(args.check.read_text())
        check(manifest, root, args.verify_outputs, args.allow_dirty)
        print(f"build manifest ok: {args.check} "
              f"({manifest['inputs']['repo_commit'][:12]}, "
              f"{sum(len(v) for v in manifest['outputs'].values())} outputs)")
        return 0

    if not args.framework_ref:
        fail("--framework-ref is required when writing a manifest; it must equal the pinned "
             "commit the workflow checks out")
    inputs = collect_inputs(root, args)
    if inputs["repo_dirty"] and not args.allow_dirty:
        fail(f"{root} has tracked changes; the artifact would not be attributable to "
             f"{inputs['repo_commit']}. Commit them, or pass --allow-dirty knowing the manifest "
             "then records a dirty tree")
    outputs = collect_outputs(root)
    manifest = {
        "schema": SCHEMA,
        "created_utc": datetime.datetime.now(datetime.timezone.utc)
                       .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "inputs": inputs,
        "toolchain": collect_toolchain(args),
        "outputs": outputs,
        "prelink": collect_prelink(root, outputs),
    }
    check(manifest, root, verify_outputs=True, allow_dirty=args.allow_dirty)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.output}: {len(outputs)} output groups, "
          f"{sum(len(v) for v in outputs.values())} files, framework "
          f"{inputs['framework_ref'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
