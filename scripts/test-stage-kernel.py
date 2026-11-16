#!/usr/bin/env python3
"""Regression tests for the staging directory guard in scripts/stage-kernel.py.

The stage deletes its target before copying the menu tree over it (shutil.rmtree, then
copytree). The cases below are the ones that would have taken a checkout, a drive, or a phone's
EFIESP volume with it; every one of them used to succeed silently.

Run from the device repository:

    python3 scripts/test-stage-kernel.py
"""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "stage_kernel", Path(__file__).with_name("stage-kernel.py"))
STAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGE)

ROOT = STAGE.ROOT
SCRIPT = Path(__file__).with_name("stage-kernel.py")


def refused(test: unittest.TestCase, path, flag: str, force: bool, fragment: str) -> None:
    """check_output_target must raise SystemExit and say why."""
    with contextlib.redirect_stderr(io.StringIO()) as stderr:
        with test.assertRaises(SystemExit):
            STAGE.check_output_target(Path(path), flag, force)
    test.assertIn(fragment, stderr.getvalue())


def menu_tree(root: Path) -> Path:
    """The two files main() requires of a menu stage before it reaches the output guard."""
    tree = root / "menu"
    config = tree / STAGE.CONFIG_REL
    config.parent.mkdir(parents=True)
    config.write_text(f"# menu\n{STAGE.MARKER}\ndefault = \"exit\"\n")
    drivers = tree / "EFI/UniXNU/Drivers"
    drivers.mkdir(parents=True)
    (drivers / "DarwinBoot.efi").write_bytes(b"MZ")
    return tree


def kernel_image(root: Path) -> Path:
    """A minimal 64-bit ARM Mach-O header; check_kernel() reads nothing else before the guard."""
    path = root / "kernel.macho"
    header = (STAGE.MH_MAGIC_64.to_bytes(4, "little")
              + STAGE.CPU_TYPE_ARM64.to_bytes(4, "little")
              + (0).to_bytes(4, "little")
              + STAGE.MH_EXECUTE.to_bytes(4, "little")
              + (1).to_bytes(4, "little")
              + (8).to_bytes(4, "little")
              + b"\0" * 16)
    path.write_bytes(header)
    return path


class OutputTargetTests(unittest.TestCase):
    def test_repository_root_is_refused_even_with_force(self):
        for force in (False, True):
            refused(self, ROOT, "--out", force, "repository root")

    def test_ancestors_of_the_checkout_are_refused(self):
        # The outer workspace and the drive root above it: deleting either is unrecoverable.
        refused(self, ROOT.parent, "--out", False, "repository root")
        refused(self, Path(ROOT.anchor), "--out", True, "repository root")

    def test_mount_point_is_refused(self):
        # A mounted EFIESP is exactly the directory the roadmap forbids writing to.
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "EFIESP"
            target.mkdir()
            ismount = lambda path: Path(path) == target.resolve()
            with patch.object(STAGE.os.path, "ismount", ismount):
                refused(self, target, "--out", True, "mount point")

    def test_non_empty_directory_outside_the_build_trees_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary) / "work"
            work.mkdir()
            (work / "notes.md").write_text("someone's work")
            with patch.object(STAGE, "PRODUCT_ROOTS", (Path(temporary) / "build",)):
                refused(self, work, "--out", True, "not under build/")
            self.assertTrue((work / "notes.md").is_file(), "the guard must not delete anything")

    def test_non_empty_build_directory_needs_force(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary) / "build"
            target = build / "boot"
            target.mkdir(parents=True)
            (target / "old.efi").write_bytes(b"previous stage")
            with patch.object(STAGE, "PRODUCT_ROOTS", (build,)):
                refused(self, target, "--out", False, "already holds files")
                # --force is the documented way to replace a previous stage.
                STAGE.check_output_target(target, "--out", True)

    def test_empty_and_missing_directories_are_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            empty = Path(temporary) / "empty"
            empty.mkdir()
            STAGE.check_output_target(empty, "--out", False)
            STAGE.check_output_target(Path(temporary) / "new", "--out", False)


class MainWiringTests(unittest.TestCase):
    """The guard is only worth something if main() reaches it before the rmtree."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.menu = menu_tree(self.root)
        self.kernel = kernel_image(self.root)

    def run_main(self, out: str, extra=(), kernel: Path | None = None,
                 menu: Path | None = None):
        argv = [str(SCRIPT), "--kernel", str(kernel or self.kernel), "--unique-chip-id", "abc",
                "--menu-tree", str(menu or self.menu), "--out", out, *extra]
        with patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as caught:
                STAGE.main()
        return caught.exception.code, stderr.getvalue()

    def test_main_refuses_the_repository_root(self):
        code, stderr = self.run_main(str(ROOT))
        self.assertNotEqual(code, 0)
        self.assertIn("repository root", stderr)

    def test_main_refuses_a_relative_dot_out(self):
        # `--out .` is the invocation in the security finding: it resolves to the checkout.
        code, stderr = self.run_main(".")
        self.assertNotEqual(code, 0)
        self.assertIn("repository root", stderr)

    def test_main_refuses_a_kernel_that_lives_inside_the_target(self):
        # The stage replaces --out before it reads anything, so an input inside it would be
        # deleted first. This is easy to hit: the previous stage leaves the image in next to it.
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary) / "build"
            target = build / "boot"
            target.mkdir(parents=True)
            image = target / "from-previous-stage.macho"
            image.write_bytes(self.kernel.read_bytes())
            with patch.object(STAGE, "PRODUCT_ROOTS", (build,)):
                code, stderr = self.run_main(str(target), extra=("--force",), kernel=image)
        self.assertNotEqual(code, 0)
        self.assertIn("is inside --out", stderr)

    def test_a_report_that_marks_the_candidate_unqualified_is_refused(self):
        # The CI artifact is a merged candidate. docs/native-bringup.md says it is not staged;
        # this is the mechanical form of that sentence.
        report = self.root / "kernel.json"
        report.write_text(json.dumps({"loadable": False, "components": ["x"]}))
        code, stderr = self.run_main(str(self.root / "out-stage"),
                                     extra=("--report", str(report)))
        self.assertNotEqual(code, 0)
        self.assertIn("marks this candidate unqualified", stderr)

    def test_allow_unqualified_gets_past_the_report(self):
        report = self.root / "kernel.json"
        report.write_text(json.dumps({"loadable": False}))
        code, stderr = self.run_main(str(self.root / "out-stage"), menu=self.root / "no-menu",
                                     extra=("--report", str(report), "--allow-unqualified"))
        self.assertNotIn("unqualified", stderr)
        self.assertIn("has no EFI/UniXNU/unixnu.toml", stderr)


class CommandLineTest(unittest.TestCase):
    def test_the_cli_exits_nonzero_and_deletes_nothing(self):
        # The honest end-to-end check: the real interpreter, the real argument parser.
        checkout_efi = ROOT / "EFI"
        existed = checkout_efi.exists()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            menu = menu_tree(root)
            kernel = kernel_image(root)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--kernel", str(kernel),
                 "--unique-chip-id", "abc", "--menu-tree", str(menu), "--out", "."],
                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("repository root", result.stderr)
        self.assertEqual(checkout_efi.exists(), existed,
                         "a refused stage must not have written into the checkout")


if __name__ == "__main__":
    unittest.main()
