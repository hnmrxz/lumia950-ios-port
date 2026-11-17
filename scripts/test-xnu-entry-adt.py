#!/usr/bin/env python3
"""Tests for the emulation fixture's ADT-profile step, without QEMU.

`--adt-profile qemu` exists because the Lumia's GIC addresses are not where an emulated machine
puts one. The step only touches the ESP copy, and this checks that: the ADT is regenerated with
the named profile's windows, the result passes the profile checker, and the phone profile is left
producing the phone's windows.

    python3 scripts/test-xnu-entry-adt.py
"""
import importlib.util
import json
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FIXTURE = load("xnu_entry", "test-native-xnu-entry.py")
CHECK = load("check_adt", "check-adt.py")
STAGE = FIXTURE.STAGE
PAYLOADS = pathlib.Path("EFI/UniXNU/Payloads")


class AdtProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.esp = pathlib.Path(self.temporary.name) / "esp"
        (self.esp / PAYLOADS).mkdir(parents=True)
        self.adt = self.esp / PAYLOADS / "kernel.macho.adt"
        profile = STAGE.resolve_profile(STAGE.ROOT / "board.toml", "bringup")
        subprocess.run(STAGE.adt_command(profile, self.adt, "1122334455667788"),
                       check=True, cwd=STAGE.ROOT)

    def windows(self):
        tree = CHECK.parse(self.adt.read_bytes())
        reg = tree.child("arm-io").child("intc").value("reg")
        return [value for value in struct.unpack("<4Q", reg)]

    def test_the_staged_tree_starts_with_the_phone_windows(self):
        self.assertEqual(self.windows(), [0xF9000000, 0x1000, 0xF9002000, 0x1000])

    def test_the_qemu_profile_moves_the_controller_to_the_emulated_machine(self):
        metadata = FIXTURE.apply_adt_profile(self.esp, "qemu")
        self.assertEqual(self.windows(), [0x08000000, 0x10000, 0x08010000, 0x10000])
        self.assertEqual(metadata["adt_profile"], "qemu")
        self.assertEqual(metadata["gic_windows"]["distributor"], "0x08000000:0x10000")
        self.assertEqual(metadata["gic_windows"]["cpu_interface"], "0x08010000:0x10000")

    def test_the_checker_accepts_the_regenerated_tree(self):
        FIXTURE.apply_adt_profile(self.esp, "qemu")
        result = subprocess.run([sys.executable, str(SCRIPTS / "check-adt.py"), str(self.adt),
                                 "--profile", "qemu"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_phone_profile_keeps_the_phone_windows(self):
        # The function is profile-driven, so asking for bring-up must not move anything.
        FIXTURE.apply_adt_profile(self.esp, "bringup")
        self.assertEqual(self.windows(), [0xF9000000, 0x1000, 0xF9002000, 0x1000])

    def test_an_unknown_profile_is_refused(self):
        with self.assertRaises(SystemExit):
            FIXTURE.apply_adt_profile(self.esp, "definitely-not-a-profile")

    def test_a_tree_without_an_adt_is_refused(self):
        self.adt.unlink()
        with self.assertRaisesRegex(ValueError, "not a staged bring-up tree"):
            FIXTURE.apply_adt_profile(self.esp, "qemu")

    def test_the_fixture_never_asks_for_a_profile_unless_told(self):
        # The default path must leave the artifact's own ADT alone.
        captured = {}

        def fake_run(args):
            captured.update(vars(args))

        original_run, original_argv = FIXTURE.run, sys.argv
        FIXTURE.run = fake_run
        sys.argv = ["test-native-xnu-entry.py", "--kernel", "k", "--esp", "e",
                    "--firmware", "f", "--output", "o"]
        try:
            FIXTURE.main()
        finally:
            FIXTURE.run, sys.argv = original_run, original_argv
        self.assertIsNone(captured["adt_profile"])


class BsdProviderTests(unittest.TestCase):
    def test_a_kernel_without_the_source_pthread_component_is_named(self):
        # --finish-bsd must refuse with the reason rather than run into the panic.
        missing = FIXTURE.missing_bsd_providers({"_pthread_functions": 1, "_bsd_init": 2})
        self.assertEqual(missing, ["_pthread_start", "_source_pthread_bootstrap"])

    def test_a_kernel_with_both_providers_passes(self):
        names = {"_pthread_start": 1, "_source_pthread_bootstrap": 2, "_bsd_init": 3}
        self.assertEqual(FIXTURE.missing_bsd_providers(names), [])


class CheckpointContractTests(unittest.TestCase):
    def test_the_fixture_takes_its_symbols_from_the_shared_list(self):
        contract = json.loads((SCRIPTS.parent / "docs/native-checkpoints.json").read_text())
        expected = {}
        for checkpoint in contract["checkpoints"]:
            fixture = checkpoint.get("fixture")
            if fixture and fixture.endswith("_entry"):
                expected[fixture.removesuffix("_entry")] = checkpoint["symbol"]
        self.assertEqual(FIXTURE.checkpoint_symbols(), expected)
        # The milestones the gate and the --finish-*/--past-bsd flags rely on must all be in that list.
        for milestone in ("arm_vm_init", "source_crypto_bootstrap", "iokit",
                          "kernel_bootstrap", "bsd_init", "vfs_mountroot"):
            self.assertIn(milestone, expected, milestone)

    def test_every_observable_checkpoint_names_a_kernel_symbol(self):
        contract = json.loads((SCRIPTS.parent / "docs/native-checkpoints.json").read_text())
        for checkpoint in contract["checkpoints"]:
            if checkpoint.get("fixture"):
                self.assertTrue(checkpoint.get("symbol"), checkpoint["id"])


if __name__ == "__main__":
    unittest.main()
