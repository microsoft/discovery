"""Offline behavior tests; no Discovery/model calls or network access."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "package_scenario.py"
SPEC = importlib.util.spec_from_file_location("package_scenario", MODULE)
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def save(path, data):
    write(path, json.dumps(data, indent=2) + "\n")


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        for name in package.SHARED_FILES:
            write(self.root / name, "# Fixture\n")
        for name in package.SCENARIOS:
            folder = self.root / "quickstarts" / name
            write(folder / "README.md", "# Fixture\n[Profile](profile.md)\n")
            write(folder / "profile.md", "# Profile\n")
            write(folder / "prompt.txt", "Exact owner prompt\n")
            save(folder / "assets.json", [])
            manifest = {
                "schemaVersion": 1, "id": name, "title": name,
                "vertical": name, "version": "0.1.0", "status": "draft",
                "guide": "README.md", "profile": "profile.md",
                "assetManifest": "assets.json",
                "files": ["README.md", "profile.md", "prompt.txt", "assets.json", "scenario.json"],
                "prompt": {"path": "prompt.txt", "sha256": package.prompt_digest(folder / "prompt.txt"),
                           "status": "owner-supplied", "source": "Owner fixture"},
                "components": [],
                "blockers": [{"id": "runtime", "detail": "Not executed"}],
                "validation": {"package": "not-run", "workflow": "not-run",
                               "scientific": "not-run", "evidence": None},
            }
            save(folder / "scenario.json", manifest)

    def manifest(self, scenario="biopharma"):
        return self.root / "quickstarts" / scenario / "scenario.json"

    def mutate(self, change):
        path = self.manifest()
        data = json.loads(path.read_text())
        change(data)
        save(path, data)

    def test_valid_drafts_are_not_release_ready(self):
        report = package.validate(self.root)
        self.assertEqual(report["status"], "passed")
        self.assertFalse(report["releaseReady"])
        self.assertEqual(package.validate(self.root, release=True)["status"], "blocked")

    def test_wrong_prompt_hash_fails(self):
        self.mutate(lambda d: d["prompt"].update(sha256="0" * 64))
        self.assertEqual(package.validate(self.root)["status"], "failed")

    def test_prompt_hash_is_portable_between_lf_and_crlf(self):
        path = self.manifest().parent / "prompt.txt"
        expected = package.prompt_digest(path)
        path.write_bytes(b"Exact owner prompt\r\n")
        self.assertEqual(package.prompt_digest(path), expected)
        self.assertEqual(package.validate(self.root)["status"], "passed")
        path.write_bytes(b"Changed owner prompt\r\n")
        self.assertEqual(package.validate(self.root)["status"], "failed")

    def test_missing_component_fails(self):
        self.mutate(lambda d: d["components"].append({"id": "missing", "kind": "agent",
            "status": "repository", "repository": "microsoft/discovery", "revision": "a" * 40,
            "path": "agents/missing/agent.yaml", "note": "Pinned source"}))
        self.assertEqual(package.validate(self.root)["status"], "failed")

    def test_unpublished_component_is_blocker_not_broken_link(self):
        self.mutate(lambda d: d["components"].append({"id": "pending-agent", "kind": "agent",
            "status": "unpublished", "repository": None, "revision": None,
            "path": None, "note": "Not published"}))
        report = package.validate(self.root)
        self.assertEqual(report["status"], "passed")
        self.assertFalse(report["releaseReady"])

    def test_malformed_json_fails(self):
        write(self.manifest(), "{")
        self.assertEqual(package.validate(self.root)["status"], "failed")

    def test_duplicate_json_keys_fail(self):
        write(self.manifest(), '{"id":"a","id":"b"}')
        self.assertEqual(package.validate(self.root)["status"], "failed")

    def test_unsafe_paths_rejected(self):
        for value in ("../secret", "/tmp/a", "C:/a", "a\\b", "a/../b", "a//b", "CON", "x.", "x:stream", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                package.safe_path(self.root, value)

    def test_unlisted_file_rejected(self):
        write(self.manifest().parent / "session.txt", "private")
        self.assertEqual(package.validate(self.root)["status"], "failed")

    def test_explicit_inventory_cannot_smuggle_runtime_state(self):
        for value in (".discovery/config.json", "sessions/old.json", ".local/cache.json",
                      ".venv-previous/settings.json", "results/old.json"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                package.safe_path(self.root, value)

    def test_duplicate_inventory_rejected(self):
        self.mutate(lambda d: d["files"].append("README.md"))
        self.assertEqual(package.validate(self.root)["status"], "failed")

    def test_broken_local_link_rejected(self):
        write(self.manifest().parent / "README.md", "[Missing](missing.md)\n")
        self.assertEqual(package.validate(self.root)["status"], "failed")

    def test_symlink_rejected(self):
        outside = Path(self.temp.name) / "outside.txt"
        write(outside, "outside")
        link = self.manifest().parent / "profile.md"
        link.unlink()
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("Host cannot create symlinks")
        self.assertEqual(package.validate(self.root)["status"], "failed")

    def test_staging_defaults_to_dry_run(self):
        target = Path(self.temp.name) / "new"
        report = package.stage(self.root, "biopharma", target, allow_draft=True)
        self.assertEqual(report["status"], "planned")
        self.assertFalse(target.exists())

    def test_draft_requires_explicit_flag(self):
        target = Path(self.temp.name) / "new"
        report = package.stage(self.root, "biopharma", target, apply=True)
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(target.exists())

    def test_existing_destination_untouched(self):
        target = Path(self.temp.name) / "new"
        write(target / "keep.txt", "keep")
        report = package.stage(self.root, "biopharma", target, allow_draft=True, apply=True)
        self.assertEqual(report["status"], "failed")
        self.assertEqual((target / "keep.txt").read_text(), "keep")

    def test_real_stage_is_complete_and_preserves_bytes(self):
        target = Path(self.temp.name) / "new"
        report = package.stage(self.root, "biopharma", target, allow_draft=True, apply=True)
        self.assertEqual(report["status"], "staged-draft")
        selection = json.loads((target / "quickstart-selection.json").read_text())
        self.assertEqual(selection["scenario"], "biopharma")
        self.assertEqual(selection["approvals"], {})
        self.assertEqual((self.root / "LICENSE").read_bytes(), (target / "LICENSE").read_bytes())
        self.assertTrue((target / ".github/skills/quickstart-runner/SKILL.md").is_file())
        source = self.root / "quickstarts/biopharma/prompt.txt"
        self.assertEqual(source.read_bytes(), (target / "quickstarts/biopharma/prompt.txt").read_bytes())
        self.assertFalse((target / ".discovery").exists())
        self.assertFalse((target / "sessions").exists())
        records = json.loads((target / "staged-files.json").read_text())
        for record in records["files"]:
            self.assertEqual(package.digest(target / record["path"]), record["sha256"])

    def test_invalid_source_leaves_no_destination(self):
        self.mutate(lambda d: d["prompt"].update(sha256="0" * 64))
        target = Path(self.temp.name) / "new"
        self.assertEqual(package.stage(self.root, "biopharma", target, True, True)["status"], "failed")
        self.assertFalse(target.exists())

    def test_verify_assets_detects_missing_changed_and_valid_files(self):
        source = Path(self.temp.name) / "assets"
        source.mkdir()
        payload = b"reference input\n"
        assets = [{"id": "input", "role": "fixture", "required": True,
                   "delivery": "unpublished", "path": "input.zip", "url": None,
                   "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                   "license": "not assessed", "redistribution": "pending", "note": "Test only"}]
        save(self.manifest().parent / "assets.json", assets)
        self.assertEqual(package.verify_assets(self.root, "biopharma", source)["status"], "blocked")
        (source / "input.zip").write_bytes(b"corrupt")
        self.assertEqual(package.verify_assets(self.root, "biopharma", source)["status"], "failed")
        (source / "input.zip").write_bytes(payload)
        self.assertEqual(package.verify_assets(self.root, "biopharma", source)["status"], "passed")

    def test_unsafe_asset_url_rejected(self):
        bad = [{"id": "input", "role": "fixture", "required": True, "delivery": "download",
                "path": "input.pdf", "url": "https://user:secret@example.org/input.pdf",
                "bytes": 1, "sha256": "a" * 64, "license": "test",
                "redistribution": "documented", "note": "test"}]
        save(self.manifest().parent / "assets.json", bad)
        self.assertEqual(package.validate(self.root)["status"], "failed")

    def test_ready_without_evidence_fails(self):
        self.mutate(lambda d: d.update(status="ready", blockers=[]))
        self.assertEqual(package.validate(self.root)["status"], "failed")


if __name__ == "__main__":
    unittest.main()