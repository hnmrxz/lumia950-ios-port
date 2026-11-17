#!/usr/bin/env python3
"""Tests for the shared ADT profile and the two stagers that consume it.

The finding this closes: scripts/stage-kernel.py staged a six-CPU tree with a PSCI/HVC conduit
(from board.toml) while scripts/stage-native-bringup.py, the path with the installer behind it,
staged one CPU and no conduit by hardcoding it. CI therefore checked a tree that was never the
tree the phone ran, and the first real XNU entry would have been a test of an unrecorded
configuration.

    python3 scripts/test-adt-profile.py
"""
import argparse
import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

from board_profile import resolve_profile  # noqa: E402


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STAGE = load("stage_kernel", "stage-kernel.py")
NATIVE = load("stage_native", "stage-native-bringup.py")

CHIP = "1122334455667788"


def parse_flags(command):
    """--flag value pairs from a generator command line, ignoring the interpreter and script."""
    flags, index, body = {}, 0, list(command[2:])
    while index < len(body):
        item = body[index]
        if item.startswith("--"):
            following = body[index + 1] if index + 1 < len(body) else None
            value = None if following is None or following.startswith("--") else following
            flags[item] = value
            index += 2 if value is not None else 1
        else:
            index += 1
    return flags


class BoardProfileTests(unittest.TestCase):
    def test_the_committed_board_resolves_to_the_bring_up_profile(self):
        profile = resolve_profile(ROOT / "board.toml")
        self.assertEqual(profile["profile"], "bringup")
        self.assertEqual(profile["cpu_regs"], "0")
        self.assertEqual(profile["psci_method"], "none")
        self.assertEqual(profile["owned_memory_size"], 0x20000000)
        self.assertEqual(profile["chip_id"], 0x8015)
        self.assertEqual(profile["dram_base"], 0)
        # 2806 MiB, the measured conventional memory, not the advertised 3 GiB.
        self.assertEqual(profile["dram_size"], 0xAF600000)
        self.assertEqual(profile["tool"], "scripts/make-lumia950-adt.py")

    def test_the_committed_board_keeps_one_answer_per_question(self):
        payload = tomllib.loads((ROOT / "board.toml").read_text())["payload"]
        adt = payload["adt"]
        # These belong to the profiles only. A second copy in [payload.adt] is how the two
        # stagers drifted apart in the first place.
        self.assertNotIn("cpu_regs", adt)
        self.assertNotIn("psci_method", adt)
        self.assertNotIn("owned_memory_size", adt)
        self.assertIn("bringup", adt["profiles"])
        self.assertIn("target", adt["profiles"])
        self.assertIn("qemu", adt["profiles"])

    def test_the_qemu_profile_moves_the_interrupt_controller(self):
        profile = resolve_profile(ROOT / "board.toml", "qemu")
        self.assertEqual(profile["profile"], "qemu")
        self.assertEqual(profile["cpu_regs"], "0")
        self.assertEqual(profile["psci_method"], "none")
        self.assertEqual(profile["gic_distributor"], "0x08000000:0x10000")
        self.assertEqual(profile["gic_cpu_interface"], "0x08010000:0x10000")

    def test_the_phone_profiles_leave_the_gic_to_the_generator(self):
        # The phone's GIC addresses are the generator's defaults; only an emulated profile names
        # them, so a staged handset tree cannot accidentally get QEMU's addresses.
        self.assertIsNone(resolve_profile(ROOT / "board.toml", "bringup").get("gic_distributor"))
        self.assertIsNone(resolve_profile(ROOT / "board.toml", "target").get("gic_cpu_interface"))


    def test_the_target_profile_still_records_the_madt_topology(self):
        board = (ROOT / "board.toml").read_text().replace('profile = "bringup"',
                                                          'profile = "target"', 1)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "board.toml"
            path.write_text(board)
            profile = resolve_profile(path)
        self.assertEqual(profile["profile"], "target")
        self.assertEqual(len(profile["cpu_regs"].split(",")), 6)
        self.assertEqual(profile["psci_method"], "hvc")

    def resolve(self, body: str):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "board.toml"
            path.write_text(body)
            with contextlib.redirect_stderr(io.StringIO()):
                return resolve_profile(path)

    def board(self, profiles: str, profile: str = "bringup") -> str:
        return f'[payload]\ndram_size = 0xC0000000\ndram_base = 0\n[payload.adt]\ntool = "t"\nprofile = "{profile}"\n{profiles}'

    def test_a_bring_up_profile_with_two_cpus_is_refused(self):
        with self.assertRaises(SystemExit) as caught:
            self.resolve(self.board(
                '[payload.adt.profiles.bringup]\ncpu_regs = "0,1"\npsci_method = "none"\n'
                'owned_memory_size = 0x20000000\n'))
        self.assertEqual(caught.exception.code, 1)

    def test_a_bring_up_profile_that_publishes_a_conduit_is_refused(self):
        with self.assertRaises(SystemExit) as caught:
            self.resolve(self.board(
                '[payload.adt.profiles.bringup]\ncpu_regs = "0"\npsci_method = "hvc"\n'
                'owned_memory_size = 0x20000000\n'))
        self.assertEqual(caught.exception.code, 1)

    def test_a_bring_up_profile_without_an_ownership_bound_is_refused(self):
        with self.assertRaises(SystemExit) as caught:
            self.resolve(self.board(
                '[payload.adt.profiles.bringup]\ncpu_regs = "0"\npsci_method = "none"\n'))
        self.assertEqual(caught.exception.code, 1)

    def test_an_unknown_profile_is_refused(self):
        with self.assertRaises(SystemExit) as caught:
            self.resolve(self.board("", profile="quiet"))
        self.assertEqual(caught.exception.code, 1)

    def test_a_selected_profile_that_describes_nothing_is_refused(self):
        with self.assertRaises(SystemExit) as caught:
            self.resolve(self.board(""))
        self.assertEqual(caught.exception.code, 1)


class StagerAgreementTests(unittest.TestCase):
    """The acceptance criterion: the two stagers ask the generator the same question."""

    def test_both_stagers_emit_the_same_generator_flags(self):
        profile = resolve_profile(ROOT / "board.toml")
        spec = STAGE.board_section()
        with tempfile.TemporaryDirectory() as temporary:
            staged = STAGE.adt_command(profile, spec, Path(temporary) / "a.adt",
                                       argparse.Namespace(chip_id=None, dram_base=None,
                                                          unique_chip_id=CHIP,
                                                          trustcache=None, data=None))
            native = NATIVE.adt_command(profile, Path(temporary) / "a.adt", CHIP)
        self.assertEqual(Path(staged[1]), Path(native[1]))
        staged_flags, native_flags = parse_flags(staged), parse_flags(native)
        for flags in (staged_flags, native_flags):
            flags.pop("--output", None)
            flags.pop("--unique-chip-id", None)
        self.assertEqual(staged_flags, native_flags)
        # And the answer itself is the bring-up shape, not the target one.
        self.assertEqual(native_flags["--cpu-regs"], "0")
        self.assertEqual(native_flags["--psci-method"], "none")
        self.assertEqual(native_flags["--dram-size"], hex(0xAF600000))

    def test_both_stagers_emit_the_gic_windows_for_an_emulated_profile(self):
        profile = resolve_profile(ROOT / "board.toml", "qemu")
        spec = STAGE.board_section()
        with tempfile.TemporaryDirectory() as temporary:
            staged = STAGE.adt_command(profile, spec, Path(temporary) / "a.adt",
                                       argparse.Namespace(chip_id=None, dram_base=None,
                                                          unique_chip_id=CHIP,
                                                          trustcache=None, data=None))
            native = NATIVE.adt_command(profile, Path(temporary) / "a.adt", CHIP)
        staged_flags, native_flags = parse_flags(staged), parse_flags(native)
        for flags in (staged_flags, native_flags):
            flags.pop("--output", None)
            flags.pop("--unique-chip-id", None)
        self.assertEqual(staged_flags, native_flags)
        self.assertEqual(native_flags["--gic-distributor"], "0x08000000:0x10000")
        self.assertEqual(native_flags["--gic-cpu-interface"], "0x08010000:0x10000")

    def test_the_bringup_staging_carries_no_gic_override(self):
        # A staged handset tree must not get the emulator's addresses by accident.
        profile = resolve_profile(ROOT / "board.toml", "bringup")
        with tempfile.TemporaryDirectory() as temporary:
            command = NATIVE.adt_command(profile, Path(temporary) / "a.adt", CHIP)
        flags = parse_flags(command)
        self.assertNotIn("--gic-distributor", flags)
        self.assertNotIn("--gic-cpu-interface", flags)

    def test_stage_kernel_honours_a_chip_id_override_without_duplicating_the_flag(self):
        profile = resolve_profile(ROOT / "board.toml")
        with tempfile.TemporaryDirectory() as temporary:
            command = STAGE.adt_command(profile, STAGE.board_section(),
                                        Path(temporary) / "a.adt",
                                        argparse.Namespace(chip_id=0x1234, dram_base=None,
                                                           unique_chip_id=CHIP,
                                                           trustcache=None, data=None))
        self.assertEqual(command.count("--chip-id"), 1)
        self.assertEqual(parse_flags(command)["--chip-id"], "0x1234")


class CheckerProfileTests(unittest.TestCase):
    """check-adt has to reject a tree that contradicts the profile it was staged under."""

    def generate(self, *, cpus: str, psci: str, owned=None) -> Path:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        adt = Path(self.temporary.name) / "test.adt"
        command = [sys.executable, str(ROOT / "scripts/make-lumia950-adt.py"), "--output", str(adt),
                   "--dram-size", "0xAF600000", "--dram-base", "0", "--unique-chip-id", CHIP,
                   "--chip-id", "0x8015", "--cpu-regs", cpus, "--psci-method", psci]
        if owned is not None:
            command += ["--owned-memory-size", owned]
        subprocess.run(command, check=True, capture_output=True, text=True)
        return adt

    def check(self, adt: Path, profile: str):
        return subprocess.run([sys.executable, str(ROOT / "scripts/check-adt.py"), str(adt),
                               "--profile", profile], capture_output=True, text=True)

    def test_the_bring_up_shape_passes_its_own_profile(self):
        result = self.check(self.generate(cpus="0", psci="none", owned="0x20000000"), "bringup")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_conduit_tree_fails_the_bring_up_profile(self):
        result = self.check(self.generate(cpus="0,1", psci="hvc", owned="0x20000000"), "bringup")
        self.assertEqual(result.returncode, 1)
        self.assertIn("/psci is present in the bring-up profile", result.stderr)

    def test_a_tree_without_the_ownership_bound_fails_the_bring_up_profile(self):
        result = self.check(self.generate(cpus="0", psci="none"), "bringup")
        self.assertEqual(result.returncode, 1)
        self.assertIn("darwinboot-memory-size is absent", result.stderr)

    def test_the_target_shape_passes_its_own_profile_and_fails_the_bring_up_one(self):
        adt = self.generate(cpus="0,1,2,3,0x100,0x101", psci="hvc", owned="0x20000000")
        target = self.check(adt, "target")
        self.assertEqual(target.returncode, 0, target.stderr)
        self.assertEqual(self.check(adt, "bringup").returncode, 1)

    def test_without_a_profile_the_checker_is_unchanged(self):
        # The existing CI step and the checker's own fixtures call it this way.
        result = subprocess.run([sys.executable, str(ROOT / "scripts/check-adt.py"),
                                 str(self.generate(cpus="0", psci="none", owned="0x20000000"))],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
