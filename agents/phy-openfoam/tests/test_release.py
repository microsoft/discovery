"""Release metadata and defaults must not drift from the installed package version."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
import yaml

from scripts import validate_manifests

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT


def test_release_manifest_versions_match_package():
    package = tomllib.loads(
        (AGENT / "tools" / "openfoam" / "pyproject.toml").read_text(encoding="utf-8")
    )
    version = package["project"]["version"]
    for path in (AGENT / "agent.yaml", AGENT / "metadata.yaml",
                 AGENT / "tools" / "openfoam" / "tool.yaml"):
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["version"] == version
    from discovery_physics import __version__

    assert __version__ == version
    assert package["project"]["license"] == "MIT"


def test_local_setup_and_companion_use_the_release_image():
    package = tomllib.loads(
        (AGENT / "tools" / "openfoam" / "pyproject.toml").read_text(encoding="utf-8")
    )
    image = f"localhost/phy-openfoam:{package['project']['version']}"
    from discovery_physics.openfoam import runner

    assert runner.DEFAULT_IMAGE == image
    for path in (ROOT / "scripts" / "setup.ps1", ROOT / "scripts" / "install-runtime.ps1",
                 ROOT / "integrations" / "phy-openfoam.agent.md"):
        assert image in path.read_text(encoding="utf-8")


def test_catalog_name_and_references_are_self_contained():
    metadata = yaml.safe_load((ROOT / "metadata.yaml").read_text(encoding="utf-8"))
    agent = yaml.safe_load((ROOT / "agent.yaml").read_text(encoding="utf-8"))
    tool = yaml.safe_load((ROOT / "tools/openfoam/tool.yaml").read_text(encoding="utf-8"))
    assert metadata["name"] == agent["name"] == tool["name"] == ROOT.name == "phy-openfoam"
    assert metadata["associated_tools"] == ["agents/phy-openfoam/tools/openfoam"]
    assert "party" not in metadata["publisher"]  # Maintainers classify, not the installer.
    assert "phyOpenfoamToolId" in agent["discoveryExtensions"]["tools"][0]["toolId"]


def test_source_and_image_license_scopes_are_distinct():
    for path in (ROOT / "LICENSE", ROOT / "tools/openfoam/LICENSE"):
        assert "MIT License" in path.read_text(encoding="utf-8")
    licenses = ROOT / "tools/openfoam/LICENSES"
    assert "Version 3, 29 June 2007" in (licenses / "GPL-3.0-or-later.txt").read_text(encoding="utf-8")
    gmsh = (licenses / "Gmsh-4.13-LICENSE.txt").read_text(encoding="utf-8")
    assert "Version 2 or later" in gmsh and "End of exception." in gmsh


def test_manifest_inputs_follow_catalog_shape_and_bounds():
    tool = yaml.safe_load((ROOT / "tools/openfoam/tool.yaml").read_text(encoding="utf-8"))
    for action in tool["actions"]:
        schema = action["input_schema"]
        # Discovery's ToolInputSchema does not expose JSON Schema's
        # additionalProperties keyword at this level.
        assert set(schema) <= {"type", "required", "properties"}
        for value in schema["properties"].values():
            assert 0 < value["maxLength"] <= 65536 and value["pattern"]
    evaluate = next(a for a in tool["actions"] if a["name"] == "evaluate")
    assert "confirmations_b64" in evaluate["input_schema"]["required"]


def test_missing_schema_cache_cannot_report_success(tmp_path):
    with pytest.raises(FileNotFoundError, match="missing required schemas"):
        validate_manifests.main(tmp_path)