#!/usr/bin/env python3
"""Tests for scripts/build-manifest.py.

Each case builds a throwaway repository (and a throwaway UniXNU checkout) so the assertions are
about the script's rules, not about this repository's current state.

    python3 scripts/test-build-manifest.py
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("build-manifest.py")
KERNELCACHE = "2ec297bac95bcba01046fd0148e97e7e5885c05a6c18827f39f534ba375c1221"


def run(*command, cwd=None, expect=0):
    result = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
    if expect is not None and result.returncode != expect:
        raise AssertionError(f"{' '.join(map(str, command))} -> {result.returncode}\n"
                             f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def git(path, *arguments, expect=0):
    return run("git", "-C", str(path), "-c", "user.email=t@example.invalid",
               "-c", "user.name=test", *arguments, expect=expect)


def commit_all(path, message="init"):
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", message)
    return git(path, "rev-parse", "HEAD").stdout.strip()


BOARD = f"""[board]
name = "lumia950"
example = true

[kernel.prelink]
kernelcache_sha256 = "{KERNELCACHE}"
"""

SCRATCH_BOARD = BOARD.replace("example = true", "# guard cleared in the CI scratch copy")

REPORT = {"loadable": False, "components": ["com.apple.filesystems.apfs", "com.apple.kec.corecrypto"],
          "bindings": [{"slot": 1}], "sparse_index": {"headers": [1, 2, 3]}}


class ManifestTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "device"
        self.root.mkdir()

        self.framework = self.root / "unixnu"
        self.framework.mkdir()
        git(self.framework, "init", "-q")
        (self.framework / "unixnu").write_text("# the framework\n")
        self.framework_ref = commit_all(self.framework)
        self.framework_tree = git(self.framework, "rev-parse", "HEAD^{tree}").stdout.strip()

        # `unixnu fetch` writes the lock into the device repository, not into the framework
        # checkout; the manifest looks where the framework actually writes it.
        (self.root / ".gitignore").write_text("unixnu/\nout/\nscratch/\n")
        (self.root / "board.toml").write_text(BOARD)
        (self.root / "feeds.toml").write_text('[xnu]\nref = "8796.141.3"\n')
        (self.root / "ci").mkdir()
        (self.root / "ci/unixnu-16x.patch").write_text("diff --git a/x b/x\n")
        (self.root / ".github/workflows").mkdir(parents=True)
        (self.root / ".github/workflows/build.yml").write_text("name: build\n")
        git(self.root, "init", "-q")
        self.repo_commit = commit_all(self.root)

        self.scratch = self.root / "scratch/board.toml"
        self.scratch.parent.mkdir()
        self.scratch.write_text(SCRATCH_BOARD)
        # The device repository the build ran from; `unixnu fetch` writes unixnu.lock here.
        (self.scratch.parent / "unixnu.lock").write_text("xnu = 8796.141.3\n")

        kernel = self.root / "out/lumia950/kernel"
        kernel.mkdir(parents=True)
        (kernel / "kernel.macho").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 60)
        (kernel / "kernel.json").write_text(json.dumps(REPORT))
        obj = self.root / "out/lumia950/tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837"
        obj.mkdir(parents=True)
        (obj / "mach.development.bcm2837").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 60)
        archive = self.root / "out/lumia950/tree/build/native-sdhci"
        archive.mkdir(parents=True)
        (archive / "libNativeSdhci.a").write_bytes(b"!<arch>\n")

        self.manifest_path = self.root / "out/build-manifest.json"

    def write_manifest(self, *extra, expect=0):
        return run(sys.executable, str(SCRIPT), "--root", str(self.root),
                   "--output", str(self.manifest_path), "--framework-dir", "unixnu",
                   "--framework-ref", self.framework_ref, "--scratch-board", str(self.scratch),
                   "--os-version", "26.0", "--arch", "arm64", "--xcode", "Xcode 26.0",
                   "--iphoneos-sdk", "18.2", "--clang", "Apple clang 17.0", *extra,
                   expect=expect)

    def check_manifest(self, *extra, expect=0):
        return run(sys.executable, str(SCRIPT), "--check", str(self.manifest_path),
                   "--root", str(self.root), *extra, expect=expect)

    def manifest(self):
        return json.loads(self.manifest_path.read_text())


class WritingTests(ManifestTestCase):
    def test_writes_the_inputs_the_outputs_and_the_prelink_summary(self):
        self.write_manifest()
        manifest = self.manifest()
        self.assertEqual(manifest["schema"], "lumia950-build-manifest-v1")
        self.assertEqual(manifest["inputs"]["repo_commit"], self.repo_commit)
        self.assertEqual(manifest["inputs"]["framework_tree"], self.framework_tree)
        self.assertFalse(manifest["inputs"]["repo_dirty"])
        self.assertTrue(manifest["inputs"]["board_toml_guard_present"])
        self.assertFalse(manifest["inputs"]["framework_patched"])
        self.assertEqual(manifest["inputs"]["kernelcache_sha256_expected"], KERNELCACHE)
        self.assertTrue(manifest["inputs"]["scratch_board_toml_sha256"])
        self.assertIn("18.2", manifest["toolchain"]["iphoneos_sdk"])
        self.assertEqual(len(manifest["outputs"]["kernel_macho"]), 1)
        self.assertEqual(manifest["outputs"]["kernel_macho"][0]["path"],
                         "out/lumia950/kernel/kernel.macho")
        self.assertEqual(len(manifest["outputs"]["archives"]), 1)
        # The summary is what makes the prelink report auditable without carrying bytes around.
        self.assertEqual(manifest["prelink"],
                         {"loadable": False, "components": 2, "bindings": 1,
                          "sparse_index_headers": 3})

    def test_the_manifest_is_deterministic_ignoring_the_timestamp(self):
        self.write_manifest()
        first = self.manifest()
        self.write_manifest()
        second = self.manifest()
        for manifest in (first, second):
            manifest.pop("created_utc")
        self.assertEqual(first, second)

    def test_a_dirty_checkout_is_refused(self):
        self.write_manifest()
        (self.root / "feeds.toml").write_text("changed\n")
        output = self.write_manifest(expect=1)
        self.assertIn("tracked changes", output.stderr)
        # ... and an explicit opt-in still records the truth instead of hiding it.
        self.write_manifest("--allow-dirty")
        self.assertTrue(self.manifest()["inputs"]["repo_dirty"])

    def test_a_committed_board_without_the_guard_is_refused(self):
        (self.root / "board.toml").write_text(BOARD.replace("example = true", "example = false"))
        commit_all(self.root, "drop the guard")
        output = self.write_manifest(expect=1)
        self.assertIn("no `example = true`", output.stderr)

    def test_a_scratch_board_that_still_has_the_guard_is_refused(self):
        self.scratch.write_text(BOARD)
        output = self.write_manifest(expect=1)
        self.assertIn("did not run from the cleared scratch copy", output.stderr)

    def test_a_framework_checkout_that_is_not_the_pin_is_refused(self):
        (self.framework / "unixnu").write_text("# moved\n")
        commit_all(self.framework, "move the pin")
        output = self.write_manifest(expect=1)
        self.assertIn("the pinned ref is", output.stderr)

    def test_the_patched_framework_is_recorded(self):
        (self.framework / "unixnu").write_text("# patched by the 16.x shim\n")
        self.write_manifest()
        self.assertTrue(self.manifest()["inputs"]["framework_patched"])

    def test_a_missing_prelink_report_is_refused(self):
        (self.root / "out/lumia950/kernel/kernel.json").unlink()
        output = self.write_manifest(expect=1)
        self.assertIn("no kernel_prelink_report", output.stderr)

    def test_a_missing_device_lock_is_refused(self):
        # The lock lives in the device repository, not in the framework checkout.
        (self.scratch.parent / "unixnu.lock").unlink()
        output = self.write_manifest(expect=1)
        self.assertIn("unixnu fetch", output.stderr)

    def test_the_lock_is_read_from_the_device_directory(self):
        (self.scratch.parent / "unixnu.lock").write_text("xnu = 8796.141.3\n")
        other = self.root / "elsewhere"
        other.mkdir()
        (other / "unixnu.lock").write_text("xnu = 9999.1.1\n")
        self.write_manifest("--device-dir", str(other))
        # Hash the bytes on disk: a text-mode write turns \n into \r\n on Windows.
        expected = hashlib.sha256((other / "unixnu.lock").read_bytes()).hexdigest()
        self.assertEqual(self.manifest()["inputs"]["unixnu_lock_sha256"], expected)

    def test_the_sdk_prefix_guard_refuses_a_silent_change(self):
        output = self.write_manifest("--expect-sdk", "17.", expect=1)
        self.assertIn("silent SDK change", output.stderr)


class CheckingTests(ManifestTestCase):
    def test_a_fresh_manifest_passes_with_output_hashes_recomputed(self):
        self.write_manifest()
        output = self.check_manifest("--verify-outputs")
        self.assertIn("build manifest ok", output.stdout)

    def test_a_changed_artifact_fails_the_check(self):
        self.write_manifest()
        (self.root / "out/lumia950/kernel/kernel.macho").write_bytes(b"different")
        output = self.check_manifest("--verify-outputs", expect=1)
        self.assertIn("does not match the manifest", output.stderr)

    def test_a_missing_artifact_fails_the_check(self):
        self.write_manifest()
        (self.root / "out/lumia950/kernel/kernel.macho").unlink()
        output = self.check_manifest("--verify-outputs", expect=1)
        self.assertIn("is gone", output.stderr)

    def test_a_manifest_missing_an_input_fails_the_check(self):
        self.write_manifest()
        manifest = self.manifest()
        del manifest["inputs"]["feeds_sha256"]
        self.manifest_path.write_text(json.dumps(manifest))
        output = self.check_manifest(expect=1)
        self.assertIn("no inputs.feeds_sha256", output.stderr)

    def test_a_manifest_that_claims_a_dirty_tree_fails_the_check(self):
        self.write_manifest()
        manifest = self.manifest()
        manifest["inputs"]["repo_dirty"] = True
        self.manifest_path.write_text(json.dumps(manifest))
        output = self.check_manifest(expect=1)
        self.assertIn("dirty checkout", output.stderr)

    def test_a_manifest_without_a_toolchain_fails_the_check(self):
        self.write_manifest()
        manifest = self.manifest()
        manifest["toolchain"]["iphoneos_sdk"] = ""
        self.manifest_path.write_text(json.dumps(manifest))
        output = self.check_manifest(expect=1)
        self.assertIn("no toolchain.iphoneos_sdk", output.stderr)


if __name__ == "__main__":
    unittest.main()
