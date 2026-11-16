#!/usr/bin/env python3
"""Tests for scripts/menu_render.py and for the two stagers that share it.

The finding: scripts/stage-native-bringup.py kept a second, hand-written menu configuration with
its own countdown, title, logo flag and entry set, so a change to the committed menu reached one
staging path and not the other. The test that matters is the last one here: change the committed
file, and both renders carry the change.

    python3 scripts/test-menu-render.py
"""
import importlib.util
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import menu_render  # noqa: E402


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STAGE = load("stage_kernel", "stage-kernel.py")
NATIVE = load("stage_native", "stage-native-bringup.py")

COMMITTED = (ROOT / "payload/EFI/UniXNU/unixnu.toml").read_text()
SPEC = {"title": "iOS 16.7.16"}


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.tree = Path(self.temporary.name)
        (self.tree / "EFI/UniXNU").mkdir(parents=True)

    def write(self, text=COMMITTED):
        (self.tree / "EFI/UniXNU/unixnu.toml").write_text(text)
        return self.tree

    def native(self, text=COMMITTED):
        return tomllib.loads(NATIVE.menu_config(self.write(text)))

    def kernel(self, text=COMMITTED):
        return tomllib.loads(STAGE.render_config(SPEC, self.write(text), False, "-v cpus=1", False))

    def test_the_native_menu_is_three_entries_with_exit_as_default(self):
        menu = self.native()
        self.assertEqual([entry["id"] for entry in menu["entry"]], ["gpu", "xnu", "exit"])
        self.assertEqual(menu["boot"]["default"], "exit")

    def test_the_native_menu_keeps_its_three_deliberate_differences(self):
        menu = self.native()
        self.assertEqual(menu["boot"]["timeout"], 300)
        self.assertEqual(menu["ui"]["title"], "Native Lumia 950")
        self.assertFalse(menu["ui"]["logo"])

    def test_the_kernel_menu_keeps_the_firmware_action_entries(self):
        menu = self.kernel()
        self.assertEqual([entry["id"] for entry in menu["entry"]],
                         ["xnu", "exit", "reset", "shutdown"])
        self.assertEqual(menu["boot"]["default"], "xnu")

    def test_the_native_menu_drops_the_firmware_action_entries(self):
        menu = self.native()
        self.assertNotIn("reset", [entry["id"] for entry in menu["entry"]])
        self.assertNotIn("shutdown", [entry["id"] for entry in menu["entry"]])

    def test_keys_neither_stager_overrides_are_identical(self):
        # The point of one source: everything not named as a difference has to match.
        native, kernel = self.native(), self.kernel()
        for key in ("fallback_timeout", "connect_all"):
            self.assertEqual(kernel["boot"][key], native["boot"][key], key)
        for key in ("layout", "console"):
            self.assertEqual(kernel["ui"][key], native["ui"][key], key)
        self.assertEqual(kernel["kits"], native["kits"])

    def test_a_change_to_the_committed_menu_reaches_both_stagers(self):
        # This is the regression the finding described: one path changed, the other did not.
        changed = COMMITTED.replace('layout = "auto"', 'layout = "portrait_below"')
        self.assertEqual(self.native(changed)["ui"]["layout"], "portrait_below")
        self.assertEqual(self.kernel(changed)["ui"]["layout"], "portrait_below")

    def test_a_menu_without_the_marker_is_refused(self):
        broken = COMMITTED.replace(menu_render.MARKER, "# marker removed")
        with self.assertRaises(SystemExit):
            self.native(broken)
        with self.assertRaises(SystemExit):
            self.kernel(broken)

    def test_a_missing_action_block_is_refused_rather_than_silently_kept(self):
        # The drop list lives in menu_render; if the committed file loses the block, the stage
        # has to say so instead of shipping a menu the installer will refuse.
        label, block = menu_render.FIRMWARE_ACTIONS[1]
        broken = COMMITTED.replace(block, "")
        with self.assertRaises(SystemExit):
            self.native(broken)

    def test_a_changed_title_line_is_refused(self):
        broken = COMMITTED.replace('title = "UniXNU"', 'title = "UniXNU 950"')
        with self.assertRaises(SystemExit):
            self.native(broken)

    def test_replace_once_refuses_a_second_match(self):
        with self.assertRaises(SystemExit):
            menu_render.replace_once("a\na\n", "a", "b", "duplicate")


if __name__ == "__main__":
    unittest.main()
