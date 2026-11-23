import importlib.util
import hashlib
import hmac
import json
from pathlib import Path
import struct
import tempfile
import unittest


spec = importlib.util.spec_from_file_location("native_stage", Path(__file__).with_name("stage-native-bringup.py"))
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)
ROOT = Path(__file__).resolve().parents[1]


def image():
    data = bytearray(4096)
    base = 0xFFFFFFF007004000
    struct.pack_into("<8I", data, 0, 0xFEEDFACF, 0x0100000C, 0, 2, 3, 464, 0, 0)
    struct.pack_into("<II16sQQQQIIII", data, 32, 0x19, 152, b"__TEXT", base, 4096, 0, 4096, 5, 5, 1, 0)
    struct.pack_into("<16s16sQQ8I", data, 104, b"__text", b"__TEXT", base + 512, 256, 512, 2, 0, 0, 0x80000400, 0, 0, 0)
    struct.pack_into("<4I", data, 184, 5, 288, 6, 68)
    struct.pack_into("<Q", data, 184 + 272, base + 512)
    struct.pack_into("<6I", data, 472, 2, 24, 2048, 1, 2064, 8)
    struct.pack_into("<IBBHQ", data, 2048, 1, 0x0F, 1, 0, base + 512)
    data[2064:2072] = b"\0_start\0"
    data[512:516] = bytes.fromhex("1f2003d5")
    return data


def crypto_image():
    data = bytearray(4096)
    base = 0xFFFFFFF007004000
    names = sorted(stage.CRYPTO_SYMBOLS)
    strings = b"\0" + b"\0".join(name.encode() for name in names) + b"\0"
    struct.pack_into("<8I", data, 0, 0xFEEDFACF, 0x0100000C, 0, 2, 3, 544, 0, 0)
    struct.pack_into("<II16sQQQQIIII", data, 32, 0x19, 232, b"__TEXT", base, 4096, 0, 4096, 5, 5, 2, 0)
    struct.pack_into("<16s16sQQ8I", data, 104, b"__text", b"__TEXT", base + 1024, 256, 1024, 2, 0, 0, 0x80000400, 0, 0, 0)
    struct.pack_into("<16s16sQQ8I", data, 184, b"__fips_hmacs", b"__TEXT", base + 1536, 32, 1536, 2, 0, 0, 0, 0, 0, 0)
    struct.pack_into("<4I", data, 264, 5, 288, 6, 68)
    struct.pack_into("<Q", data, 264 + 272, base + 1024)
    struct.pack_into("<6I", data, 552, 2, 24, 2048, 3, 2096, len(strings))
    for index, name in enumerate(names):
        struct.pack_into("<IBBHQ", data, 2048 + index * 16, strings.index(name.encode()), 0x0F, 1, 0, base + 1024 + index * 4)
    data[2096:2096 + len(strings)] = strings
    data[1024:1280] = bytes.fromhex("1f2003d5") * 64
    data[1536:1568] = hmac.digest(b"\0", data[1024:1280], "sha256")
    return data


class NativeBringupTests(unittest.TestCase):
    def test_valid_source_kernel(self):
        data = image()
        result = stage.contract(data)
        self.assertEqual(result["entry"], 0xFFFFFFF007004200)
        self.assertEqual(len(result["external_symbols"]), 1)
        self.assertEqual(stage.verify_strip(data, data), (3600, 1))

    def test_invalid_native_contracts(self):
        for mutation in range(10):
            with self.subTest(mutation=mutation):
                data = image()
                if mutation == 0:
                    struct.pack_into("<I", data, 8, 2)
                elif mutation == 1:
                    struct.pack_into("<I", data, 12, 0xC)
                elif mutation == 2:
                    struct.pack_into("<I", data, 20, 5000)
                elif mutation == 3:
                    data[40:56] = b"__PRELINK_TEXT\0\0"
                elif mutation == 4:
                    struct.pack_into("<Q", data, 184 + 272, 0)
                elif mutation == 5:
                    data[2048 + 4] = 1
                elif mutation == 6:
                    struct.pack_into("<I", data, 472 + 12, 1000)
                elif mutation == 7:
                    struct.pack_into("<Q", data, 32 + 24, 3)
                elif mutation == 8:
                    struct.pack_into("<I", data, 32 + 60, 7)
                elif mutation == 9:
                    struct.pack_into("<Q", data, 32 + 48, 8192)
                with self.assertRaises(ValueError):
                    stage.contract(data)

    def test_text_change_never_qualifies_as_debug_stripping(self):
        original = image()
        changed = image()
        changed[516] ^= 1
        with self.assertRaisesRegex(ValueError, "runtime bytes"):
            stage.verify_strip(original, changed)

    def test_external_symbol_change_refused(self):
        original = image()
        changed = image()
        struct.pack_into("<Q", changed, 2048 + 8, 0xFFFFFFF007004204)
        with self.assertRaisesRegex(ValueError, "external symbol"):
            stage.verify_strip(original, changed)

    def test_menu_does_not_claim_ios_or_autoboot_a_test(self):
        import tomllib
        menu = tomllib.loads(stage.menu_config(ROOT / "payload"))
        self.assertEqual(menu["boot"]["default"], "exit")
        self.assertEqual(len(menu["entry"]), 3)
        self.assertIn("no iOS userspace", menu["entry"][1]["title"])

    def test_the_pthread_requirement_is_recorded_with_its_reason(self):
        # bsd_init panics without the source pthread component, and enabling it does not build on
        # this pin (its builder fails against the 8796 compile records and the builder's own make
        # run loses the force-loaded archives). The configuration has to say that, rather than
        # leave a bare omission. Measured in
        # docs/emulation/2026-11-17-local-qemu-bsd-init-panic.json
        config = (ROOT / "configs/lumia950_defconfig").read_text()
        enabled = [line.strip() for line in config.splitlines()
                   if line.strip().startswith("CONFIG_")]
        self.assertIn("CONFIG_XNU_SOURCE_CORECRYPTO14=y", enabled,
                      "ArmCpu is only accepted with the real source crypto provider")
        self.assertNotIn("CONFIG_XNU_SOURCE_PTHREAD=y", enabled)
        self.assertIn("pthread kernel extension not loaded", config)

    def test_source_provider_integrity_is_not_optional(self):
        with self.assertRaisesRegex(ValueError, "bootstrap/provider"):
            stage.crypto_contract(image())
        data = crypto_image()
        report = stage.crypto_contract(data)
        self.assertEqual(report["code_bytes"], 256)
        self.assertFalse(report["runtime_post_observed"])
        data[1536] ^= 1
        with self.assertRaisesRegex(ValueError, "not sealed"):
            stage.crypto_contract(data)

    def test_instruction_changes_invalidate_the_real_post_field(self):
        data = crypto_image()
        data[1028] ^= 1
        with self.assertRaisesRegex(ValueError, "not sealed"):
            stage.crypto_contract(data)


class BuildManifestTests(unittest.TestCase):
    """--manifest: the kernel has to be an output of the run that reported it.

    Without it the stager only checked a hash the operator typed, which proves the file did not
    change since the operator typed it -- not that CI produced it.
    """

    COMMIT = "a" * 40
    FRAMEWORK = "b" * 40
    CACHE = "c" * 64

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.kernel = self.root / "mach.development.bcm2837.unstripped"
        self.kernel.write_bytes(b"a kernel")
        self.sha = hashlib.sha256(b"a kernel").hexdigest()

    def write(self, manifest) -> Path:
        path = self.root / "build-manifest.json"
        path.write_text(json.dumps(manifest))
        return path

    def manifest(self, sha=None, name=None, **inputs):
        base = {"repo_commit": self.COMMIT, "repo_dirty": False, "framework_ref": self.FRAMEWORK,
                "kernelcache_sha256_expected": self.CACHE}
        base.update(inputs)
        return {"schema": "lumia950-build-manifest-v1", "inputs": base,
                "outputs": {"kernel_unstripped": [
                    {"path": f"out/lumia950/tree/build/xnu/ios-obj/{name or self.kernel.name}",
                     "bytes": 8, "sha256": sha or self.sha}]}}

    def test_a_kernel_the_run_recorded_is_accepted(self):
        record = stage.verify_build_manifest(self.write(self.manifest()), self.kernel, self.sha,
                                            self.COMMIT)
        self.assertEqual(record["build_repo_commit"], self.COMMIT)
        self.assertEqual(record["build_framework_ref"], self.FRAMEWORK)
        self.assertEqual(record["build_kernelcache_sha256"], self.CACHE)
        self.assertEqual(len(record["build_manifest_sha256"]), 64)
        self.assertIn("mach.development.bcm2837.unstripped", record["build_manifest_output"])

    def test_a_kernel_the_manifest_does_not_record_is_refused(self):
        path = self.write(self.manifest(name="something-else"))
        with self.assertRaisesRegex(ValueError, "records no"):
            stage.verify_build_manifest(path, self.kernel, self.sha, self.COMMIT)

    def test_a_kernel_whose_hash_differs_from_the_record_is_refused(self):
        path = self.write(self.manifest(sha="d" * 64))
        with self.assertRaisesRegex(ValueError, "does not hash to the value"):
            stage.verify_build_manifest(path, self.kernel, self.sha, self.COMMIT)

    def test_a_dirty_manifest_is_refused(self):
        path = self.write(self.manifest(repo_dirty=True))
        with self.assertRaisesRegex(ValueError, "dirty checkout"):
            stage.verify_build_manifest(path, self.kernel, self.sha, self.COMMIT)

    def test_a_manifest_from_another_commit_is_refused(self):
        path = self.write(self.manifest())
        with self.assertRaisesRegex(ValueError, "was built from"):
            stage.verify_build_manifest(path, self.kernel, self.sha, "e" * 40)

    def test_a_missing_manifest_is_refused(self):
        with self.assertRaisesRegex(ValueError, "build manifest not found"):
            stage.verify_build_manifest(self.root / "absent.json", self.kernel, self.sha)

    def test_a_foreign_manifest_is_refused(self):
        path = self.write({"schema": "something-else", "inputs": {}, "outputs": {}})
        with self.assertRaisesRegex(ValueError, "is not a lumia950 build manifest"):
            stage.verify_build_manifest(path, self.kernel, self.sha)


if __name__ == "__main__":
    unittest.main()