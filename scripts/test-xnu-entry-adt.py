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


class DmesgTests(unittest.TestCase):
    """The kernel's own message buffer is how a machine with no console reports anything."""

    def read_with(self, layout, reads=None):
        def fake_read(connection, address, size):
            if reads is not None:
                reads.append((address, size))
            return bytes(layout.get(address + index, 0) for index in range(size))

        original = FIXTURE.read_memory
        FIXTURE.read_memory = fake_read
        try:
            return FIXTURE.read_dmesg(None, {"_msgbufp": 0x1000})
        finally:
            FIXTURE.read_memory = original

    @staticmethod
    def layout(text, size=16, bufx=None, bufr=0, magic=0x063061):
        layout = {}
        struct_address, buffer_address = 0x2000, 0x4000
        layout.update({0x1000 + index: byte for index, byte in
                       enumerate(struct_address.to_bytes(8, "little"))})
        fields = [magic, size, len(text) if bufx is None else bufx, bufr]
        header = b"".join(value.to_bytes(4, "little") for value in fields) + \
            buffer_address.to_bytes(8, "little")
        layout.update({struct_address + index: byte for index, byte in enumerate(header)})
        layout.update({buffer_address + index: byte for index, byte in enumerate(text)})
        return layout

    def test_a_plain_buffer_is_read_as_text(self):
        result = self.read_with(self.layout(b"hello kernel"))
        self.assertEqual(result["text"], "hello kernel")
        self.assertEqual(result["magic"], 0x063061)

    def test_a_wrapped_buffer_is_reassembled_in_order(self):
        # bufr 6, bufx 4 on a ten byte buffer means the text is data[6:] followed by data[:4].
        result = self.read_with(self.layout(b"0123456789", size=10, bufx=4, bufr=6))
        self.assertEqual(result["text"], "67890123")

    def test_an_uninitialised_buffer_is_refused(self):
        with self.assertRaisesRegex(ValueError, "uninitialised"):
            self.read_with(self.layout(b"", size=0))

    def test_a_large_buffer_is_read_in_packets(self):
        text = b"x" * 9000
        reads = []
        result = self.read_with(self.layout(text, size=0x20000), reads)
        self.assertEqual(len(result["text"]), 9000)
        self.assertTrue(all(size <= 4096 for _, size in reads), reads)


class DebugBufferTests(unittest.TestCase):
    """The panic output XNU keeps for a debugger, when it keeps any."""

    def run_with(self, base, write, size, payload):
        layout = {}
        for address, value, width in ((0x1000, base, 8), (0x1008, write, 8), (0x1010, size, 4)):
            layout.update({address + index: byte for index, byte in
                           enumerate(value.to_bytes(width, "little"))})
        layout.update({base + index: byte for index, byte in enumerate(payload)})
        names = {"_debug_buf_base": 0x1000, "_debug_buf_ptr": 0x1008, "_debug_buf_size": 0x1010}

        def fake_read(connection, address, count):
            return bytes(layout.get(address + index, 0) for index in range(count))

        original = FIXTURE.read_memory
        FIXTURE.read_memory = fake_read
        try:
            return FIXTURE.read_debug_buffer(None, names)
        finally:
            FIXTURE.read_memory = original

    def test_an_empty_buffer_yields_nothing(self):
        self.assertEqual(self.run_with(0x4000, 0x4000, 0x1000, b""), "")

    def test_the_text_between_base_and_pointer_is_returned(self):
        text = self.run_with(0x4000, 0x4000 + 5, 0x1000, b"panic")
        self.assertEqual(text, "panic")

    def test_a_buffer_without_symbols_yields_nothing(self):
        self.assertEqual(FIXTURE.read_debug_buffer(None, {}), "")


class ScreenTests(unittest.TestCase):
    """The framebuffer geometry comes from the kernel's own initialize_screen line."""

    LINE = "[    7.079863]: initialize_screen: b=6C7A0000, w=00000320, h=00000258, r=00000C80, d=00000000"

    def test_the_geometry_is_read_from_the_log(self):
        geometry = FIXTURE.screen_geometry(self.LINE)
        self.assertEqual(geometry["base"], 0x6C7A0000)
        self.assertEqual(geometry["width"], 800)
        self.assertEqual(geometry["height"], 600)
        self.assertEqual(geometry["row_bytes"], 3200)
        # The kernel logs d=0 when it does not know the depth; the row width implies 32 bpp.
        self.assertEqual(geometry["bpp"], 32)

    def test_a_log_without_the_line_yields_nothing(self):
        self.assertIsNone(FIXTURE.screen_geometry("no screen here"))

    def test_a_ppm_swaps_bgr_to_rgb_and_drops_the_row_padding(self):
        geometry = {"base": 0, "width": 2, "height": 1, "row_bytes": 12, "bpp": 32}
        pixels = bytes([1, 2, 3, 0, 4, 5, 6, 0, 9, 9, 9, 9])
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "screen.ppm"
            FIXTURE.write_ppm(path, pixels, geometry)
            data = path.read_bytes()
        self.assertTrue(data.startswith(b"P6\n2 1\n255\n"))
        self.assertEqual(data.split(b"\n", 3)[3], bytes([3, 2, 1, 6, 5, 4]))

    def test_a_non_32bpp_framebuffer_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "32 bpp"):
                FIXTURE.write_ppm(pathlib.Path(temporary) / "x.ppm", b"", {"width": 1, "height": 1,
                                                                          "row_bytes": 2, "bpp": 16})


class BootArgsTests(unittest.TestCase):
    """The hand-off structure DarwinBoot built, decoded from the arm64 boot_args layout."""

    @staticmethod
    def build(command_line=b"-v cpus=1"):
        data = bytearray(0x480)
        data[0x00:0x02] = (2).to_bytes(2, "little")
        data[0x02:0x04] = (2).to_bytes(2, "little")
        for offset, value in ((0x08, 0xFFFFFFF007004000), (0x10, 0x48004000),
                              (0x18, 0x20000000), (0x20, 0x48F6C000)):
            data[offset:offset + 8] = value.to_bytes(8, "little")
        for index, value in enumerate((0x6C7A0000, 1, 3200, 800, 600, 32)):
            offset = 0x28 + index * 8
            data[offset:offset + 8] = value.to_bytes(8, "little")
        data[0x60:0x68] = (0xFFFFFFF007F69000).to_bytes(8, "little")
        data[0x68:0x6C] = (0x2C58).to_bytes(4, "little")
        data[0x6C:0x6C + len(command_line)] = command_line
        return bytes(data)

    def test_the_fields_are_decoded(self):
        decoded = FIXTURE.decode_boot_args(self.build())
        self.assertEqual(decoded["Revision"], 2)
        self.assertEqual(decoded["physBase"], 0x48004000)
        self.assertEqual(decoded["video"]["v_baseAddr"], 0x6C7A0000)
        self.assertEqual(decoded["video"]["v_rowBytes"], 3200)
        self.assertEqual(decoded["video"]["depth_bits"], 32)
        self.assertEqual(decoded["deviceTreeLength"], 0x2C58)

    def test_the_command_line_starts_at_0x6c(self):
        # Reading it four bytes later drops "-v ", which is exactly the bug this pins.
        decoded = FIXTURE.decode_boot_args(self.build())
        self.assertEqual(decoded["commandLine"], "-v cpus=1")

    def test_a_short_buffer_is_refused(self):
        with self.assertRaisesRegex(ValueError, "boot_args needs"):
            FIXTURE.decode_boot_args(b"\0" * 16)

    def test_the_address_is_read_from_darwinboots_line(self):
        log = ("DARWINBOOT: ARM64 va=0xFFFFFFF007004000 pa=0x48004000 args=0x48F68000 "
               "entry=0x483E8488 owned=0x20000000")
        self.assertEqual(FIXTURE.boot_args_address(log), 0x48F68000)
        self.assertIsNone(FIXTURE.boot_args_address("no hand-off here"))


if __name__ == "__main__":
    unittest.main()
