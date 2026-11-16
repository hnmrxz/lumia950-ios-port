#!/usr/bin/env python3
"""Tests for scripts/check-kernel-link.py.

The point of the check is the gap between "the archive compiled" and "the kernel contains it":
the kernel job printed `ar t` and always passed, so a driver that was never linked looked green.
These cases pin the matching rules, the component list derived from board.toml, and the refusal.

    python3 scripts/test-kernel-link.py
"""
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check-kernel-link.py")
ROOT = SCRIPT.parent.parent

# What `nm -gU --defined-only` looks like for a linked IOKit C++ class: the name is length-prefixed
# inside the mangled symbol, and the case of the source identifier is not preserved verbatim.
DUMP = textwrap.dedent("""\
    00000000000a1000 T __ZN11NativeSdhci4initEv
    00000000000a2000 T __ZN10NativeMdss5probeEP4OSObject
    00000000000a3000 T __ZN15NativeAdreno4185startEPS_P4site
    00000000000a4000 T __ZN19NativeLegacyDisplay5probeEv
    00000000000a5000 T __ZN13ArmDTPlatform5startEv
    00000000000a6000 T __ZN6ArmCpu11interruptsEv
    """)


class KernelLinkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def dump(self, text=DUMP) -> Path:
        path = self.root / "nm.txt"
        path.write_text(text)
        return path

    def _run(self, expected, extra):
        result = subprocess.run([sys.executable, str(SCRIPT), *extra],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, expected,
                         f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def test_a_complete_dump_passes(self):
        result = self._run(0, ("--symbols-from", str(self.dump()),
                               "--expect", "NativeSdhci", "--expect", "ArmCpu"))
        self.assertIn("kernel link ok", result.stdout)

    def test_a_component_that_never_reached_the_link_fails(self):
        partial = "\n".join(line for line in DUMP.splitlines() if "NativeMdss" not in line)
        result = self._run(1, ("--symbols-from", str(self.dump(partial)),
                               "--expect", "NativeSdhci", "--expect", "NativeMdss"))
        self.assertIn("does not link NativeMdss", result.stderr)

    def test_matching_is_case_insensitive_through_the_mangled_name(self):
        # The class is NativeSdhci; the symbol says 11NativeSdhci and a grep for the exact
        # spelling in either direction must still find it.
        result = self._run(0, ("--symbols-from", str(self.dump()),
                               "--expect", "nativesdhci"))
        self.assertIn("nativesdhci 1", result.stdout)

    def test_the_component_list_comes_from_board_toml(self):
        board = self.root / "board.toml"
        board.write_text(textwrap.dedent("""\
            [kernel]
            archives = [
              "build-corecrypto-14.py",
              "build-arm-driver.py ArmCpu",
              "build-arm-driver.py NativeSdhci",
              "build-arm-driver.py NativeMdss",
              "build-corecrypto-14.py --namespace",
            ]
            """))
        partial = "\n".join(line for line in DUMP.splitlines() if "NativeMdss" not in line)
        result = self._run(1, ("--symbols-from", str(self.dump(partial)), "--board", str(board)))
        self.assertIn("does not link NativeMdss", result.stderr)

    def test_the_committed_board_names_every_archive_as_a_component(self):
        # The driver list is in board.toml; the check reads it rather than keeping a second copy.
        import importlib.util
        spec = importlib.util.spec_from_file_location("check_kernel_link", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        names = module.expected_from_board(ROOT / "board.toml")
        self.assertEqual(sorted(names),
                         sorted(["ArmDTPlatform", "ArmCpu", "NativeSdhci", "NativeAdreno418",
                                 "NativeMdss", "NativeLegacyDisplay"]))
        # ... and the fallback list is not allowed to be smaller than the board.
        self.assertTrue(set(names) <= set(module.DEFAULT_EXPECTED))

    def test_an_experiment_can_leave_a_component_out(self):
        partial = "\n".join(line for line in DUMP.splitlines() if "NativeAdreno418" not in line)
        result = self._run(0, ("--symbols-from", str(self.dump(partial)),
                               "--omit", "NativeAdreno418",
                               "--expect", "NativeSdhci"))
        self.assertNotIn("NativeAdreno418", result.stdout)

    def test_a_missing_image_is_refused(self):
        result = self._run(1, ("--image", str(self.root / "no-such-image")))
        self.assertIn("is missing", result.stderr)

    def test_neither_input_is_a_usage_error(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--symbols-from", result.stderr)

    def test_a_component_whose_symbol_is_not_named_after_it_is_still_found(self):
        # The image can carry the C entry point without any symbol spelled like the directory.
        dump = "00000000000a4000 T _native_legacy_display_probe\n"
        result = self._run(0, ("--symbols-from", str(self.dump(dump)),
                               "--expect", "NativeLegacyDisplay"))
        self.assertIn("NativeLegacyDisplay 1", result.stdout)

    def test_an_excluded_component_is_not_required(self):
        board = self.root / "board.toml"
        board.write_text(textwrap.dedent("""\
            [kernel]
            archives = [
              "build-arm-driver.py NativeSdhci",
              "build-arm-driver.py NativeMdss",
            ]
            [kernel.link_excluded]
            NativeSdhci = "superclass lives in a kext merged after the source link"
            """))
        partial = "\n".join(line for line in DUMP.splitlines() if "NativeSdhci" not in line)
        result = self._run(0, ("--symbols-from", str(self.dump(partial)),
                               "--expect", "NativeMdss"))
        self.assertIn("kernel link ok", result.stdout)
        # ... and the board-driven path reports the exclusion rather than silently skipping it.
        result = self._run(0, ("--symbols-from", str(self.dump(partial)), "--board", str(board)))
        self.assertIn("excluded from the source link: NativeSdhci", result.stdout)

    def test_an_exclusion_without_a_reason_is_refused(self):
        board = self.root / "board.toml"
        board.write_text(textwrap.dedent("""\
            [kernel]
            archives = ["build-arm-driver.py NativeSdhci"]
            [kernel.link_excluded]
            NativeSdhci = ""
            """))
        result = self._run(1, ("--symbols-from", str(self.dump()), "--board", str(board)))
        self.assertIn("without saying why", result.stderr)

    def test_an_exclusion_for_an_archive_the_board_does_not_build_is_refused(self):
        board = self.root / "board.toml"
        board.write_text(textwrap.dedent("""\
            [kernel]
            archives = ["build-arm-driver.py NativeMdss"]
            [kernel.link_excluded]
            NativeSdhci = "not built here"
            """))
        result = self._run(1, ("--symbols-from", str(self.dump()), "--board", str(board)))
        self.assertIn("never builds it", result.stderr)

    def test_a_component_without_an_archive_is_refused(self):
        # The compile half: the symbol can only legitimately be there if the archive was built.
        tree = self.root / "out/lumia950/tree/build"
        (tree / "native-sdhci").mkdir(parents=True)
        (tree / "native-sdhci/libNativeSdhci.a").write_bytes(b"!<arch>\n")
        result = self._run(1, ("--symbols-from", str(self.dump()),
                               "--expect", "NativeSdhci", "--expect", "NativeMdss",
                               "--archives-root", str(tree)))
        self.assertIn("no archive for NativeMdss", result.stderr)


if __name__ == "__main__":
    unittest.main()
