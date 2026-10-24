"""Checkpoint download-order regressions; no model dependencies required."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import download_checkpoints as downloader


class DownloadCheckpointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checkpoint = self.root / "model.pt"
        self.checkpoint.write_bytes(b"checkpoint")
        self.entry = {
            "loader": "mace",
            "name": "small-0b",
            "path": str(self.checkpoint),
            "size": self.checkpoint.stat().st_size,
            "sha256": hashlib.sha256(self.checkpoint.read_bytes()).hexdigest(),
        }
        self.spec = self.root / "checkpoints.json"
        self.spec.write_text(json.dumps({"checkpoints": [self.entry]}))

    def test_verifies_before_deserializing(self):
        events = []

        def resolve(entry):
            events.append("resolve")
            return self.checkpoint

        def load(entry, path):
            events.append("load")

        with patch.object(downloader, "resolve", side_effect=resolve), \
                patch.object(downloader, "sha256", side_effect=lambda path: (
                    events.append("hash"),
                    hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                )[1]), \
                patch.object(downloader, "load", side_effect=load):
            self.assertEqual(downloader.main(self.spec), 0)
        self.assertEqual(events, ["resolve", "hash", "load"])

    def test_checksum_failure_never_deserializes(self):
        self.entry["sha256"] = "0" * 64
        self.spec.write_text(json.dumps({"checkpoints": [self.entry]}))
        with patch.object(downloader, "resolve", return_value=self.checkpoint), \
                patch.object(downloader, "load") as load:
            self.assertEqual(downloader.main(self.spec), 1)
        load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
