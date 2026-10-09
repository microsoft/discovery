"""Standard-library-only artifact/JSON regressions; no GPU required."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from enum import Enum
from unittest.mock import patch

import alchemi_artifacts as artifacts


class Array:
    def __init__(self, value):
        self.value = value

    def tolist(self):
        return self.value


class Scalar:
    def item(self):
        return 7


class Tensor(Array):
    device = "cpu"

    def detach(self):
        return self


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()  # Windows TEMP may contain 8.3 aliases.
        self.work, self.output = self.root / "work", self.root / "output"
        self.work.mkdir()
        self.output.mkdir()

    def put(self, name, data=b"payload", root=None):
        path = (root or self.work) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def export(self, **files):
        return artifacts.export_artifacts(files, self.work, self.output)

    def test_arbitrary_files_directory_aliases_and_metadata(self):
        declared = {name: self.put("nested/" + name) for name in ("state.npz", "notes.txt", "run.py")}
        self.put("nested/store.zarr/z/1", b"123")
        self.put("nested/store.zarr/a", b"45678")
        (self.work / "nested/store.zarr/empty").mkdir()
        declared.update(store="nested/store.zarr", alias="nested/state.npz", directory_alias="nested/store.zarr")
        with patch.object(artifacts.shutil, "copy2", wraps=shutil.copy2) as copy:
            mapped, manifest = self.export(**declared)
        self.assertEqual(copy.call_count, 5)
        self.assertEqual(mapped["alias"], mapped["state.npz"])
        self.assertEqual(mapped["store"], mapped["directory_alias"])
        self.assertEqual(manifest["schema_version"], 1)
        for entry in manifest["artifacts"]:
            path = Path(entry["path"])
            self.assertEqual(path, Path(mapped[entry["label"]]))
            self.assertEqual(entry["relative_path"], path.relative_to(self.output).as_posix())
            self.assertTrue(entry["verified"])
            self.assertTrue(path.is_absolute())
            base = path if path.is_dir() else path.parent
            for item in entry["files"]:
                data = (base / item["relative_path"]).read_bytes()
                self.assertEqual((item["size"], item["sha256"]), (len(data), hashlib.sha256(data).hexdigest()))
            self.assertEqual(entry["total_bytes"], sum(item["size"] for item in entry["files"]))
            if path.is_dir():
                self.assertEqual([f["relative_path"] for f in entry["files"]], ["a", "z/1"])
                canonical = json.dumps(entry["files"], sort_keys=True, separators=(",", ":"))
                self.assertEqual(entry["sha256"], hashlib.sha256(canonical.encode()).hexdigest())
                self.assertTrue((path / "empty").is_dir())
            else:
                self.assertEqual(entry["sha256"], entry["files"][0]["sha256"])
        self.assertFalse((self.output / "artifact_manifest.json").exists())
        nested = self.work / "exports"
        mapped, _ = artifacts.export_artifacts({"a": "nested/run.py"}, self.work, nested)
        self.assertEqual(Path(mapped["a"]), nested / "nested/run.py")
        outside = self.put("external.pickle", root=self.root)
        self.assertEqual(Path(self.export(a=outside)[0]["a"]), self.output / outside.name)

    def test_passthrough_rewrite_and_unrelated_preservation(self):
        direct = self.put("direct.txt", root=self.output)
        with patch.object(artifacts.shutil, "copy2", side_effect=AssertionError("same-file copy")):
            self.assertEqual(self.export(direct=direct)[0]["direct"], str(direct))
        for root in (self.output, self.work):
            self.put("tree/old", root=root)
            self.put("data.bin", root=root)
        self.put("unrelated/keep", root=self.output)
        self.export(tree="tree", data="data.bin")
        (self.work / "tree/old").unlink()
        self.put("tree/new", b"new")
        self.put("data.bin", b"changed")
        self.export(tree="tree", data="data.bin")
        self.assertFalse((self.output / "tree/old").exists())
        self.assertEqual((self.output / "tree/new").read_bytes(), b"new")
        self.assertEqual((self.output / "data.bin").read_bytes(), b"changed")
        self.assertTrue((self.output / "unrelated/keep").exists())
        self.assertFalse(list(self.output.glob(".alchemi-*")))
        with patch.object(artifacts.shutil, "copytree", side_effect=AssertionError("same-directory copy")):
            self.export(tree=self.output / "tree")

    def test_invalid_declarations_and_reserved_reports(self):
        self.put("tree/leaf")
        outside = self.put("other/leaf", root=self.root)
        self.put("leaf")
        self.put("folder.bin")
        (self.output / "folder.bin").mkdir()
        self.put("blocked", root=self.output)
        self.put("blocked/leaf")
        cases = [dict(a="missing"), dict(a="../escape"), dict(a="tree/../leaf"), dict(a="..\\escape"),
                 dict(a="C:relative"), dict(a=""), dict(a=object()), dict(a=self.work), dict(a=self.output),
             dict(a="tree", b="tree/leaf"), dict(a=outside, b="leaf"), dict(a="folder.bin"),
                 dict(a="blocked/leaf")]
        for name in ("final_results.json", "ARTIFACT_MANIFEST.JSON"):
            self.put(name)
            self.put(name, b"preserve", self.output)
            cases.append(dict(a=name))
        for files in cases:
            with self.subTest(files=files), self.assertRaises((ValueError, OSError, TypeError)):
                self.export(**files)
        self.put("tree", root=self.output)
        with self.assertRaises(ValueError):
            self.export(a="tree")
        self.assertEqual((self.output / "final_results.json").read_bytes(), b"preserve")
        for name in ("final_results.json", "ARTIFACT_MANIFEST.JSON"):
            (self.work / name).unlink()
            self.put(name + "/payload")
            with self.assertRaises(ValueError):
                self.export(a=name)
        with self.assertRaises(ValueError):
            artifacts.export_artifacts({"a": self.work / "tree"}, self.work, self.work / "tree/out")
        with self.assertRaises(FileNotFoundError):
            self.export(valid="leaf", missing="absent")
        self.assertFalse((self.output / "leaf").exists())

    def test_portable_collisions(self):
        a = self.put("a/STATE.bin", root=self.root)
        b = self.put("b/state.bin", root=self.root)
        with self.assertRaises(ValueError):
            self.export(a=a, b=b)
        self.put("state.bin", root=self.output)
        with self.assertRaises(ValueError):
            self.export(a=a)
        if os.name != "nt":
            self.put("tree/A")
            self.put("tree/a")
            with self.assertRaises(ValueError):
                self.export(a="tree")
            self.put("Parent/a")
            self.put("parent/b")
            with self.assertRaises(ValueError):
                self.export(a="Parent/a", b="parent/b")

    def test_symlinks(self):
        source = self.put("tree/leaf")
        link = self.work / "link"
        try:
            link.symlink_to(source)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks not permitted on this platform")
        with self.assertRaises(ValueError):
            self.export(a="link")
        link.unlink()
        link.symlink_to(source.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.export(a="link/leaf")
        (source.parent / "link").symlink_to(source)
        with self.assertRaises(ValueError):
            self.export(a="tree")
        (self.output / "tree").symlink_to(source.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.export(a="tree/leaf")
        with self.assertRaises(ValueError):
            artifacts.export_artifacts({"a": source}, self.work, self.output / "tree/out")
        self.put("other/leaf")
        (self.output / "other").mkdir()
        (self.output / "other/link").symlink_to(source)
        with self.assertRaises(ValueError):
            self.export(a="other")

    def test_copy_corruption_and_directory_rollback(self):
        original = shutil.copy2

        def corrupt(source, destination, **kwargs):
            result = original(source, destination, **kwargs)
            Path(destination).write_bytes(b"bad")  # Same size; detecting it requires hashing.
            return result

        for name in ("file.bin", "tree/leaf"):
            self.put(name, b"new")
            self.put(name, b"old", self.output)
        for name in ("file.bin", "tree"):
            with patch.object(artifacts.shutil, "copy2", side_effect=corrupt), self.assertRaises(OSError):
                self.export(a=name)
        self.assertEqual((self.output / "file.bin").read_bytes(), b"old")
        self.assertEqual((self.output / "tree/leaf").read_bytes(), b"old")
        original_replace = os.replace

        for fail_before in (True, False):
            def fail_publish(source, destination):
                publishing = Path(source).parent.name == "candidate"
                if publishing and fail_before:
                    raise OSError("injected publication failure")
                result = original_replace(source, destination)
                if publishing:
                    (Path(destination) / "leaf").write_bytes(b"bad")
                return result

            with patch.object(artifacts.os, "replace", side_effect=fail_publish), self.assertRaises(OSError):
                self.export(a="tree")
            self.assertEqual((self.output / "tree/leaf").read_bytes(), b"old")
            self.assertFalse(list(self.output.glob(".alchemi-*")))

    def test_strict_json_and_atomic_preservation(self):
        class Choice(Enum):
            A = "chosen"

        value = {"values": Array([float("nan"), float("inf"), float("-inf")]),
                 "tensor": Tensor([[Scalar(), 2]]), "path": Path("file"), "enum": Choice.A,
                 "tuple": (1, None), 3: True}
        clean = artifacts.to_jsonable(value)
        self.assertEqual([v["encoding"] for v in clean["values"]], ["nan", "+inf", "-inf"])
        self.assertTrue(all(v["value"] is None and v["finite"] is False for v in clean["values"]))
        self.assertEqual(clean["tensor"], [[7, 2]])
        self.assertEqual((clean["enum"], clean["path"], clean["tuple"], clean["3"]), ("chosen", "file", [1, None], True))
        path = self.output / "final_results.json"
        artifacts.write_json_atomic(path, value)
        saved = path.read_bytes()
        self.assertEqual(json.loads(saved, parse_constant=lambda x: self.fail(x)), clean)
        cycle = []
        cycle.append(cycle)
        cyclic_dict = {}
        cyclic_dict["self"] = cyclic_dict
        cyclic_array = Array(None)
        cyclic_array.value = [cyclic_array]
        gpu = Tensor([1])
        gpu.device = "cuda:0"
        shared = [1]
        self.assertEqual(artifacts.to_jsonable([shared, shared]), [[1], [1]])
        for bad in (object(), {1, 2}, b"bytes", 1j, cycle, cyclic_dict, cyclic_array, gpu,
                {1: "a", "1": "b"}, {Path("a"): 1, "a": 2}, {(1,): 2}, {float("nan"): 1}):
            with self.subTest(bad=type(bad)), self.assertRaises((TypeError, ValueError)):
                artifacts.write_json_atomic(path, bad)
            self.assertEqual(path.read_bytes(), saved)
        with patch.object(artifacts.os, "replace", side_effect=OSError("replace failed")), self.assertRaises(OSError):
            artifacts.write_json_atomic(path, {"new": 1})
        self.assertEqual(path.read_bytes(), saved)
        artifacts.write_json_atomic(path, {"new": 1})
        self.assertEqual(json.loads(path.read_bytes()), {"new": 1})
        self.assertFalse(list(self.output.glob(".json-*")))


if __name__ == "__main__":
    unittest.main()