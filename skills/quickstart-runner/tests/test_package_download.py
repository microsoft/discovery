"""Test exact-byte author downloads, not scientific execution or permissions."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "package_download.py"
SPEC = importlib.util.spec_from_file_location("package_download", SOURCE)
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.dest = Path(self.tmp.name) / "customer"
        self.guide = b"\xef\xbb\xbf# Exact guide\r\n\r\nOriginal prompt.\r\n"
        self.binary = b"opaque exact archive\x00\x01\xff"
        self.put("quickstarts/biopharma/cdk-frozen-reference/Original Guide.md", self.guide)
        self.put("quickstarts/biopharma/cdk-frozen-reference/files/input.zip", self.binary)
        self.put("skills/quickstart-runner/SKILL.md", b"---\nname: quickstart-runner\ndescription: Run guide\n---\nRead the complete guide.\n")
        self.put("LICENSE", b"Test licence\n")
        self.data = {"formatVersion": 1, "packages": {"biopharma": {
            "title": "BioPharma", "guide": self.entry("quickstarts/biopharma/cdk-frozen-reference/Original Guide.md", "Original Guide.md", self.guide),
            "files": [self.entry("quickstarts/biopharma/cdk-frozen-reference/files/input.zip", "input.zip", self.binary)],
            "publicationApproved": False, "publicationReason": "Not yet approved",
            "releaseUrl": None, "runtimeStatus": "not run"}}}
        self.save()

    def put(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def entry(self, path, name, data):
        return {"path": path, "name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def save(self):
        self.put("skills/quickstart-runner/references/downloads.json", json.dumps(self.data).encode())

    def test_exact_source_check(self):
        result = package.check(self.root, "biopharma")
        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["publicationReady"])

    def test_wrong_hash_fails(self):
        self.put("quickstarts/biopharma/cdk-frozen-reference/files/input.zip", b"changed")
        self.assertEqual(package.check(self.root, "biopharma")["status"], "failed")

    def test_reformatted_guide_is_not_exact(self):
        self.put("quickstarts/biopharma/cdk-frozen-reference/Original Guide.md", self.guide.replace(b"\r\n", b"\n"))
        self.assertEqual(package.check(self.root, "biopharma")["status"], "failed")

    def test_missing_input_blocks(self):
        (self.root / "quickstarts/biopharma/cdk-frozen-reference/files/input.zip").unlink()
        self.assertEqual(package.check(self.root, "biopharma")["status"], "blocked")

    def test_no_completed_guide_blocks_download(self):
        self.data["packages"]["biopharma"]["guide"] = None
        self.save()
        result = package.prepare(self.root, "biopharma", self.dest, True, True)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(self.dest.exists())

    def test_plan_writes_nothing(self):
        result = package.prepare(self.root, "biopharma", self.dest, True, False)
        self.assertEqual(result["status"], "planned")
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.dest.with_suffix(".zip").exists())

    def test_versioned_folder_keeps_full_version_in_zip_name(self):
        destination = Path(self.tmp.name) / "BioPharma-v0.11"
        result = package.prepare(self.root, "biopharma", destination, True, False)
        self.assertEqual(Path(result["zip"]).name, "BioPharma-v0.11.zip")

    def test_publication_not_inferred_from_local_copy(self):
        result = package.prepare(self.root, "biopharma", self.dest, False, True)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(self.dest.exists())

    def test_exact_files_in_new_folder_and_outer_zip(self):
        self.put("quickstarts/cms/moisturizer-formulation/private.txt", b"must not be copied")
        self.put("sessions/old.json", b"must not be copied")
        result = package.prepare(self.root, "biopharma", self.dest, True, True)
        self.assertEqual(result["status"], "prepared-local-review")
        self.assertEqual((self.dest / "Original Guide.md").read_bytes(), self.guide)
        self.assertEqual((self.dest / "input.zip").read_bytes(), self.binary)
        self.assertEqual((self.dest / "LICENSE").read_bytes(), b"Test licence\n")
        self.assertTrue((self.dest / ".github/skills/quickstart-runner/SKILL.md").exists())
        self.assertFalse((self.dest / "sessions").exists())
        self.assertFalse((self.dest / ".discovery").exists())
        self.assertFalse((self.dest / "quickstarts").exists())
        with zipfile.ZipFile(self.dest.with_suffix(".zip")) as archive:
            self.assertEqual(archive.read("Original Guide.md"), self.guide)
            self.assertEqual(archive.read("input.zip"), self.binary)
            self.assertFalse(any("private" in x for x in archive.namelist()))
        self.assertEqual((self.root / "quickstarts/biopharma/cdk-frozen-reference/Original Guide.md").read_bytes(), self.guide)

    def test_sibling_scenario_not_bundled(self):
        sibling_readme = b"Sibling scenario must not be copied\n"
        self.put("quickstarts/biopharma/other-scenario/README.md", sibling_readme)
        self.put("quickstarts/biopharma/other-scenario/files/unrelated.zip", b"unrelated archive")
        result = package.prepare(self.root, "biopharma", self.dest, True, True)
        self.assertEqual(result["status"], "prepared-local-review")
        expected = {
            "Original Guide.md", "input.zip", "LICENSE", "quickstart-runner.md",
            ".github/skills/quickstart-runner/SKILL.md", "README.md", "PACKAGE-SHA256SUMS.txt",
        }
        self.assertEqual({p.relative_to(self.dest).as_posix() for p in self.dest.rglob("*") if p.is_file()}, expected)
        self.assertNotIn(sibling_readme, (self.dest / "README.md").read_bytes())
        with zipfile.ZipFile(self.dest.with_suffix(".zip")) as archive:
            self.assertEqual(set(archive.namelist()), expected)
            self.assertNotIn(sibling_readme, archive.read("README.md"))

    def test_existing_folder_not_overwritten(self):
        self.dest.mkdir()
        (self.dest / "keep.txt").write_bytes(b"keep")
        self.assertEqual(package.prepare(self.root, "biopharma", self.dest, True, True)["status"], "failed")
        self.assertEqual((self.dest / "keep.txt").read_bytes(), b"keep")

    def test_existing_zip_not_overwritten(self):
        self.dest.with_suffix(".zip").write_bytes(b"keep")
        self.assertEqual(package.prepare(self.root, "biopharma", self.dest, True, True)["status"], "failed")
        self.assertFalse(self.dest.exists())

    def test_bad_input_leaves_no_partial_output(self):
        self.put("quickstarts/biopharma/cdk-frozen-reference/files/input.zip", b"wrong")
        self.assertEqual(package.prepare(self.root, "biopharma", self.dest, True, True)["status"], "failed")
        self.assertFalse(self.dest.exists())

    def test_unsafe_paths_and_runtime_state_rejected(self):
        for name in ("../escape", "/absolute", "C:/drive", "a\\b", "a//b", "CON", "x:stream", "x.", "sessions/state.json", ".discovery/state.json", ".env", "a?b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                package.safe_path(self.root, name)

    def test_duplicate_download_name_rejected(self):
        self.data["packages"]["biopharma"]["files"].append(self.data["packages"]["biopharma"]["files"][0])
        self.save()
        self.assertEqual(package.check(self.root, "biopharma")["status"], "failed")

    def test_generated_name_collision_rejected(self):
        self.data["packages"]["biopharma"]["files"][0]["name"] = "README.md"
        self.save()
        self.assertEqual(package.check(self.root, "biopharma")["status"], "failed")

    def test_duplicate_json_key_rejected(self):
        self.put("skills/quickstart-runner/references/downloads.json", b'{"formatVersion":1,"formatVersion":2}')
        self.assertEqual(package.check(self.root, "biopharma")["status"], "failed")

    def test_symlink_source_rejected(self):
        path = self.root / "quickstarts/biopharma/cdk-frozen-reference/files/input.zip"
        outside = Path(self.tmp.name) / "other.zip"
        outside.write_bytes(self.binary)
        path.unlink()
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest("Host does not permit symlink creation")
        self.assertEqual(package.check(self.root, "biopharma")["status"], "failed")


if __name__ == "__main__":
    unittest.main()