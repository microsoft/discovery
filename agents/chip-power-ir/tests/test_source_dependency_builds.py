"""Cross-package regressions for the source-locked, no-index Python builds."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import tarfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIMULATORS = ("chip-code-coverage", "chip-functional-coverage", "chip-functional-verification",
              "chip-testbench-uvm-generation")
PACKAGES = SIMULATORS + ("chip-dfm-litho-yield",)


def context(package):
    return next((ROOT / package).glob("tools/*/Dockerfile")).parent


class SourceDependencyBuildTests(unittest.TestCase):
    def test_all_installers_identical_and_index_free(self):
        bodies = [(context(package) / "install_python_sources.py").read_bytes() for package in PACKAGES]
        self.assertEqual(len(set(bodies[:len(SIMULATORS)])), 1)
        self.assertIn(b"def extract_sources", bodies[-1])
        for package in PACKAGES:
            with self.subTest(package=package):
                dockerfile = (context(package) / "Dockerfile").read_text(encoding="utf-8")
                self.assertIn("install_python_sources.py", dockerfile)
                self.assertIn("PYTHON_SOURCES_OFFLINE", dockerfile)
                self.assertNotIn("pip install", dockerfile)
                self.assertNotIn("--trusted-host", dockerfile)
                self.assertNotIn("--break-system-packages", dockerfile)
                self.assertIn("@sha256:", dockerfile)
        text = bodies[0].decode("utf-8")
        self.assertIn('"--no-index"', text)
        self.assertIn('"--no-build-isolation"', text)
        self.assertIn('filter="data"', text)
        self.assertNotIn("_create_unverified_context", text)

    def test_compatible_simulator_locks(self):
        locks = [json.loads((context(package) / "python_sources.lock.json").read_text(encoding="utf-8"))
                 for package in SIMULATORS]
        self.assertTrue(all(lock == locks[0] for lock in locks))
        versions = {item["name"]: item["version"] for item in locks[0]["sources"]}
        self.assertEqual(versions["cocotb"], "2.0.1")
        self.assertEqual(versions["cocotb-coverage"], "2.0")
        self.assertIn("find-libpython", versions)
        self.assertIn("python-constraint", versions)
        for package in PACKAGES:
            lock = json.loads((context(package) / "python_sources.lock.json").read_text(encoding="utf-8"))
            for spec in lock["sources"]:
                self.assertRegex(spec["commit"], r"^[0-9a-f]{40}$")
                self.assertRegex(spec["sha256"], r"^[0-9a-f]{64}$")

    def test_simulator_build_probe_and_ccache_are_required(self):
        probes = []
        for package in SIMULATORS:
            with self.subTest(package=package):
                dockerfile = (context(package) / "Dockerfile").read_text(encoding="utf-8")
                self.assertIn("make g++ ccache perl", dockerfile)
                self.assertIn("RUN python3 /opt/verify_simulator_toolchain.py", dockerfile)
                probe = (context(package) / "verify_simulator_toolchain.py").read_bytes()
                probes.append(probe)
                self.assertIn(b'"--binary"', probe)
                self.assertIn(b'"ccache"', probe)
                self.assertIn(b"$fatal", probe)
                self.assertIn(b"result.stdout", probe)
        self.assertEqual(len(set(probes)), 1)

    def test_offline_missing_tampered_and_verified_archives(self):
        path = context(SIMULATORS[0]) / "install_python_sources.py"
        spec = importlib.util.spec_from_file_location("source_installer_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = {"name": "fixture", "repository": "owner/project", "commit": "a" * 40,
                  "sha256": hashlib.sha256(b"approved bytes").hexdigest()}
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
                module.urllib.request, "urlopen", side_effect=AssertionError("offline must not fetch")):
            root = Path(temporary)
            with self.assertRaises(FileNotFoundError):
                module.checked_archive(source, root, offline=True)
            archive = root / ("fixture-" + "a" * 40 + ".tar.gz")
            archive.write_bytes(b"tampered bytes")
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                module.checked_archive(source, root, offline=True)
            archive.write_bytes(b"approved bytes")
            self.assertEqual(module.checked_archive(source, root, offline=True), archive)

    def test_invalid_lock_fails_before_download(self):
        path = context(SIMULATORS[0]) / "install_python_sources.py"
        spec = importlib.util.spec_from_file_location("source_installer_bad_lock_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(module.urllib.request, "urlopen") as fetch:
            with self.assertRaisesRegex(ValueError, "full upstream commit"):
                module.checked_archive({"commit": "main", "sha256": "0" * 64}, Path(temporary))
            fetch.assert_not_called()

    def test_dfm_old_python_extraction_is_restricted(self):
        dockerfile = (context("chip-dfm-litho-yield") / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("KLAYOUT_SETUP_MULTICORE=4 CFLAGS=-g0 CXXFLAGS=-g0", dockerfile)
        self.assertNotIn("-O0", dockerfile)
        path = context("chip-dfm-litho-yield") / "install_python_sources.py"
        spec = importlib.util.spec_from_file_location("dfm_source_installer_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
                module.tarfile, "data_filter", None, create=True):
            root = Path(temporary)
            archive = root / "source.tar.gz"
            with tarfile.open(archive, "w:gz") as stream:
                member = tarfile.TarInfo("source/data.txt")
                member.size = 8
                stream.addfile(member, io.BytesIO(b"approved"))
                link = tarfile.TarInfo("source/alias.txt")
                link.type, link.linkname = tarfile.SYMTYPE, "data.txt"
                stream.addfile(link)
            target = root / "valid"
            target.mkdir()
            module.extract_sources(archive, target)
            self.assertEqual((target / "source/alias.txt").read_bytes(), b"approved")
            self.assertFalse((target / "source/alias.txt").is_symlink())
            for name in ("../escape.txt", "/absolute.txt", "source/C:\\escape.txt"):
                with self.subTest(name=name):
                    with tarfile.open(archive, "w:gz") as stream:
                        member = tarfile.TarInfo(name)
                        member.size = 1
                        stream.addfile(member, io.BytesIO(b"x"))
                    with self.assertRaisesRegex(ValueError, "unsafe source archive path"):
                        module.extract_sources(archive, root / "unsafe")


if __name__ == "__main__":
    unittest.main()