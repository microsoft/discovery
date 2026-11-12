"""Transport/preparation tests only; never execute the scientific package."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

SPEC = importlib.util.spec_from_file_location(
    "download_inputs", Path(__file__).with_name("download_inputs.py")
)
download = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(download)


class Response(io.BytesIO):
    status = 200


class DownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "repo"
        self.root.mkdir()
        self.destination = self.root.parent / "CDK-run"
        self.snapshot = b"frozen archive bytes\x00\xff"
        self.entries = []
        names = [
            "QuickStart-BioPharma LeadGen v0.11.md",
            "cdk_operational_bundle_v1.zip",
            "cdk_operational_bundle_v1.sha256",
            "cdk_operational_bundle_v1_manifest.csv",
            "cdk_operational_bundle_v1_validation.json",
            "cdk_non_md_deliverables.sha256",
            download.SNAPSHOT,
        ]
        for name in names:
            data = self.snapshot if name == download.SNAPSHOT else name.encode()
            path = "quickstarts/biopharma/cdk-frozen-reference/files/" + name
            self.entries.append({
                "name": name, "path": path, "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
            if name != download.SNAPSHOT:
                self.put(path, data)
        self.put("skills/quickstart-runner/references/downloads.json", json.dumps({
            "formatVersion": 1, "packages": {"biopharma": {
                "title": "BioPharma", "guide": self.entries[0], "files": self.entries[1:],
                "publicationApproved": False,
            }},
        }).encode())
        self.put("skills/quickstart-runner/SKILL.md", b"Runner")
        self.put("LICENSE", b"Licence")
        for name, value in (
            ("SNAPSHOT_BYTES", len(self.snapshot)),
            ("SNAPSHOT_SHA256", hashlib.sha256(self.snapshot).hexdigest()),
        ):
            context = patch.object(download, name, value)
            context.start()
            self.addCleanup(context.stop)

    def put(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def run_download(self, data=None, error=None):
        with patch.object(download, "build_opener") as opener:
            if error is not None:
                opener.return_value.open.side_effect = error
            else:
                opener.return_value.open.return_value = Response(
                    self.snapshot if data is None else data
                )
            result = download.prepare(self.root, self.destination)
            opener.return_value.open.assert_called_once_with(download.RELEASE_URL, timeout=60)
            return result

    def assert_no_output(self):
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.parent.glob("cdk-download-*")), [])

    def test_exact_output_shape_and_bytes(self):
        self.run_download()
        expected = {entry["name"] for entry in self.entries} | {"quickstart-runner.md", "LICENSE"}
        self.assertEqual({p.name for p in self.destination.iterdir()}, expected)
        for entry in self.entries:
            download.verify(self.destination / entry["name"], entry)
        self.assertFalse((self.root / self.entries[-1]["path"]).exists())

    def test_missing_release_blocks_and_cleans_up(self):
        error = HTTPError(download.RELEASE_URL, 404, "Not Found", {}, None)
        with self.assertRaisesRegex(ValueError, "maintainer must publish"):
            self.run_download(error=error)
        self.assert_no_output()

    def test_access_denial_not_reinterpreted_as_missing(self):
        error = HTTPError(download.RELEASE_URL, 403, "Forbidden", {}, None)
        with self.assertRaises(HTTPError) as raised:
            self.run_download(error=error)
        self.assertEqual(raised.exception.code, 403)
        self.assert_no_output()

    def test_network_failure_blocks(self):
        with self.assertRaises(URLError):
            self.run_download(error=URLError("offline"))
        self.assert_no_output()

    def test_corrupt_same_size_blocks(self):
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            self.run_download(data=b"x" * len(self.snapshot))
        self.assert_no_output()

    def test_truncated_download_blocks(self):
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            self.run_download(data=self.snapshot[:-1])
        self.assert_no_output()

    def test_oversized_download_blocks(self):
        with self.assertRaisesRegex(ValueError, "exceeds expected size"):
            self.run_download(data=self.snapshot + b"x")
        self.assert_no_output()

    def test_existing_destination_not_overwritten(self):
        self.destination.mkdir()
        marker = self.destination / "keep"
        marker.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.run_download()
        self.assertEqual(marker.read_bytes(), b"keep")

    def test_destination_inside_checkout_refused(self):
        self.destination = self.root / "output"
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            self.run_download()
        self.assert_no_output()

    def test_local_corruption_blocks_before_network(self):
        self.put(self.entries[0]["path"], b"modified")
        with patch.object(download, "build_opener") as opener:
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                download.prepare(self.root, self.destination)
            opener.assert_not_called()
        self.assert_no_output()

    def test_changed_authorized_hash_blocks(self):
        with patch.object(download, "SNAPSHOT_SHA256", "0" * 64):
            with self.assertRaisesRegex(ValueError, "authorized frozen snapshot"):
                self.run_download()
        self.assert_no_output()

    def test_private_local_snapshot_is_not_fallback(self):
        self.put(self.entries[-1]["path"], self.snapshot)
        with self.assertRaises(URLError):
            self.run_download(error=URLError("offline"))
        self.assert_no_output()

    def test_http_downgrade_refused(self):
        with self.assertRaisesRegex(ValueError, "non-HTTPS"):
            download.HTTPSRedirects().redirect_request(
                Request(download.RELEASE_URL), None, 302, "Found", {}, "http://example.org/file"
            )

    def test_https_release_redirect_allowed(self):
        request = download.HTTPSRedirects().redirect_request(
            Request(download.RELEASE_URL), None, 302, "Found", {},
            "https://release-assets.githubusercontent.com/file",
        )
        self.assertEqual(request.full_url, "https://release-assets.githubusercontent.com/file")


if __name__ == "__main__":
    unittest.main()
