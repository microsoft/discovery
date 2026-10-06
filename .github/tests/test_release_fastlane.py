from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from catalog_validation.runner import run_validation


REPO_ROOT = Path(__file__).resolve().parents[2]


def _copy_schema(repo: Path, name: str) -> None:
    target = repo / "docs" / "schemas" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / "docs" / "schemas" / name, target)


def _write_json(repo: Path, relative: str, document: dict) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def _manifest() -> dict:
    return {
        "ring": "preview",
        "latestVersion": "0.15.16",
        "minimumVersion": "0.15.13",
        "schemaVersion": 1,
        "platforms": {
            platform: {
                "installerUrl": url,
                "sha256": "a" * 64,
            }
            for platform, url in {
                "osx-arm64": "https://aka.ms/discovery/download/osx/current",
                "win-arm64": "https://aka.ms/discovery/download/arm64/current",
                "win-x64": "https://aka.ms/discovery/download/current",
            }.items()
        },
        "releaseNotesUrl": "",
        "releaseNotesSummary": "",
        "releasedAt": "2026-09-28T05:10:43Z",
    }


def test_release_manifest_schema_and_cross_field_validation(tmp_path: Path):
    _copy_schema(tmp_path, "discovery-release-manifest-schema.json")
    relative = "docs/discovery-app/releases/manifests/preview.json"
    _write_json(tmp_path, relative, _manifest())

    result = run_validation(tmp_path, [relative])

    assert result.blocking == []


def test_preview_release_manifest_passes_rel001():
    relative = "docs/discovery-app/releases/manifests/preview.json"

    result = run_validation(REPO_ROOT, [relative])

    assert result.blocking == []


@pytest.mark.parametrize("installer_url", [
    "https://example.com/discovery.rpm",
    "PLACEHOLDER_PENDING_PUBLISH",
])
def test_release_manifest_accepts_optional_rhel(tmp_path: Path, installer_url: str):
    _copy_schema(tmp_path, "discovery-release-manifest-schema.json")
    relative = "docs/discovery-app/releases/manifests/preview.json"
    document = _manifest()
    document["platforms"]["rhel-x64"] = {
        "installerUrl": installer_url,
        "sha256": "a" * 64,
    }
    _write_json(tmp_path, relative, document)

    result = run_validation(tmp_path, [relative])

    assert result.blocking == []


@pytest.mark.parametrize("entry", [
    {"installerUrl": url, "sha256": "a" * 64}
    for url in [
        "",
        "http://example.com/discovery.rpm",
        "https://",
        "https://example.com/discovery rpm",
        "https://example.com/discovery.rpm\n",
        "https://example.com/" + "a" * 2048,
        "PLACEHOLDER",
        "placeholder_pending_publish",
        "PLACEHOLDER_PENDING_PUBLISH_OTHER",
        "PLACEHOLDER_PENDING_PUBLISH\n",
        None,
        123,
    ]
] + [
    {"installerUrl": url, "sha256": digest}
    for url in [
        "https://example.com/discovery.rpm",
        "PLACEHOLDER_PENDING_PUBLISH",
    ]
    for digest in ["a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n", "", None, 123]
] + [
    {"installerUrl": "PLACEHOLDER_PENDING_PUBLISH"},
    {"sha256": "a" * 64},
    {"installerUrl": "PLACEHOLDER_PENDING_PUBLISH", "sha256": "a" * 64, "extra": True},
    {},
    None,
])
def test_release_manifest_rejects_invalid_rhel(tmp_path: Path, entry: object):
    _copy_schema(tmp_path, "discovery-release-manifest-schema.json")
    relative = "docs/discovery-app/releases/manifests/preview.json"
    document = _manifest()
    document["platforms"]["rhel-x64"] = entry
    _write_json(tmp_path, relative, document)

    result = run_validation(tmp_path, [relative])

    assert result.blocking
    assert all(
        failure.rule_id == "REL-001" and "platforms.rhel-x64" in failure.message
        for failure in result.blocking
    )


@pytest.mark.parametrize("platform", ["linux-x64", "rhel-arm64", "unexpected"])
def test_release_manifest_rejects_unknown_platforms(tmp_path: Path, platform: str):
    _copy_schema(tmp_path, "discovery-release-manifest-schema.json")
    relative = "docs/discovery-app/releases/manifests/preview.json"
    document = _manifest()
    document["platforms"][platform] = {
        "installerUrl": "https://example.com/discovery.rpm",
        "sha256": "a" * 64,
    }
    _write_json(tmp_path, relative, document)

    result = run_validation(tmp_path, [relative])

    assert [failure.rule_id for failure in result.blocking] == ["REL-001"]


@pytest.mark.parametrize("platform", ["osx-arm64", "win-arm64", "win-x64"])
@pytest.mark.parametrize("change", [
    {"installerUrl": "PLACEHOLDER_PENDING_PUBLISH"},
    {"installerUrl": "http://example.com/installer"},
    {"installerUrl": "https://example.com/installer"},
    {"sha256": "A" * 64},
    {"extra": True},
])
def test_release_manifest_preserves_existing_platform_rules(
    tmp_path: Path, platform: str, change: dict,
):
    _copy_schema(tmp_path, "discovery-release-manifest-schema.json")
    relative = "docs/discovery-app/releases/manifests/preview.json"
    document = _manifest()
    document["platforms"][platform].update(change)
    _write_json(tmp_path, relative, document)

    result = run_validation(tmp_path, [relative])

    assert result.blocking
    assert all(failure.rule_id == "REL-001" for failure in result.blocking)


@pytest.mark.parametrize("platform", ["osx-arm64", "win-arm64", "win-x64"])
def test_release_manifest_keeps_existing_platforms_required(tmp_path: Path, platform: str):
    _copy_schema(tmp_path, "discovery-release-manifest-schema.json")
    relative = "docs/discovery-app/releases/manifests/preview.json"
    document = _manifest()
    del document["platforms"][platform]
    _write_json(tmp_path, relative, document)

    result = run_validation(tmp_path, [relative])

    assert [failure.rule_id for failure in result.blocking] == ["REL-001"]


def test_release_manifest_rejects_ring_and_version_regressions(tmp_path: Path):
    _copy_schema(tmp_path, "discovery-release-manifest-schema.json")
    relative = "docs/discovery-app/releases/manifests/preview.json"
    document = _manifest()
    document["ring"] = "stable"
    document["minimumVersion"] = "0.16.0"
    _write_json(tmp_path, relative, document)

    result = run_validation(tmp_path, [relative])

    assert [failure.rule_id for failure in result.blocking] == [
        "REL-001",
        "REL-001",
    ]


def test_toolbox_pointer_must_match_published_vsix_digest(tmp_path: Path):
    _copy_schema(tmp_path, "discovery-toolbox-release-schema.json")
    vsix = (
        tmp_path
        / "utilities"
        / "discovery-toolbox"
        / "vsix"
        / "DiscoveryToolbox-v2.0.0.vsix"
    )
    vsix.parent.mkdir(parents=True)
    vsix.write_bytes(b"trusted package")
    pointer = "utilities/discovery-toolbox/vsix/latest.json"
    _write_json(tmp_path, pointer, {
        "version": "2.0.0",
        "vsixPath": "vsix/DiscoveryToolbox-v2.0.0.vsix",
        "sha256": hashlib.sha256(b"trusted package").hexdigest(),
        "publishedAt": "2026-09-30T01:00:00Z",
    })

    result = run_validation(
        tmp_path,
        [pointer, vsix.relative_to(tmp_path).as_posix()],
    )

    assert result.blocking == []

    document = json.loads((tmp_path / pointer).read_text(encoding="utf-8"))
    document["sha256"] = "0" * 64
    _write_json(tmp_path, pointer, document)
    result = run_validation(tmp_path, [pointer])

    assert [failure.rule_id for failure in result.blocking] == ["REL-002"]


def test_toolbox_rejects_unreviewed_source_surface(tmp_path: Path):
    source = "utilities/discovery-toolbox/src/extension.ts"
    path = tmp_path / source
    path.parent.mkdir(parents=True)
    path.write_text("export {};\n", encoding="utf-8")

    result = run_validation(tmp_path, [source])

    assert [failure.rule_id for failure in result.blocking] == ["REL-002"]
