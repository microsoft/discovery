"""Tests for the /scratch mount helper in cli_submit."""

from __future__ import annotations

import pytest
import typer

from discovery.poll import cli_submit
from discovery.poll.models.api_version import ApiVersion
from discovery.poll.models.compute import NodepoolInfo
from discovery.poll.models.config import EnvConfig


SC_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/supercomputers/sc1"
DC_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/datacontainers/scratch-dc"
SC_CONTAINER_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/storageContainers/scratch-sc"
)


def _np(scratch_dc: str = "") -> NodepoolInfo:
    return NodepoolInfo(
        id="/x/np1",
        name="np1",
        supercomputer_id=SC_ID,
        scratch_dc_id=scratch_dc,
    )


def test_build_scratch_mount_v1(tmp_path) -> None:
    env = EnvConfig(path=tmp_path / ".env")
    env.supercomputer_scratch_dcs = {SC_ID: DC_ID}
    np_info = _np(scratch_dc=DC_ID)
    av = ApiVersion.V2025_07_01_PREVIEW

    mount = cli_submit._build_scratch_mount(np_info, env, av)
    assert mount is not None
    assert mount.mount_path == "/scratch"
    assert mount.uri.startswith(f"discovery://dataassets{DC_ID}/dataassets/scratch/paths/")
    assert mount.storage_uri is None


def test_build_scratch_mount_v2(tmp_path) -> None:
    env = EnvConfig(path=tmp_path / ".env")
    env.supercomputer_scratch_scs = {SC_ID: SC_CONTAINER_ID}
    np_info = _np()
    av = ApiVersion.V2026_02_01_PREVIEW

    mount = cli_submit._build_scratch_mount(np_info, env, av)
    assert mount is not None
    assert mount.mount_path == "/scratch"
    assert mount.uri is None
    assert mount.storage_uri.startswith(
        f"discovery://storageassets{SC_CONTAINER_ID}/storageassets/scratch/paths/"
    )


def test_build_scratch_mount_returns_none_when_unmapped(tmp_path) -> None:
    env = EnvConfig(path=tmp_path / ".env")
    np_info = _np()
    assert cli_submit._build_scratch_mount(np_info, env, ApiVersion.V2025_07_01_PREVIEW) is None
    assert cli_submit._build_scratch_mount(np_info, env, ApiVersion.V2026_02_01_PREVIEW) is None


def test_scratch_mount_or_exit_returns_none_when_flag_off(tmp_path) -> None:
    env = EnvConfig(path=tmp_path / ".env")
    np_info = _np()
    assert (
        cli_submit._scratch_mount_or_exit(
            np_info, env, ApiVersion.V2025_07_01_PREVIEW, scratch=False,
        )
        is None
    )


def test_scratch_mount_or_exit_exits_when_flag_on_but_unmapped(tmp_path) -> None:
    env = EnvConfig(path=tmp_path / ".env")
    np_info = _np()
    with pytest.raises(typer.Exit) as exc:
        cli_submit._scratch_mount_or_exit(
            np_info, env, ApiVersion.V2026_02_01_PREVIEW, scratch=True,
        )
    assert exc.value.exit_code == 2


def test_scratch_mount_or_exit_returns_mount_when_mapped(tmp_path) -> None:
    env = EnvConfig(path=tmp_path / ".env")
    env.supercomputer_scratch_scs = {SC_ID: SC_CONTAINER_ID}
    np_info = _np()
    mount = cli_submit._scratch_mount_or_exit(
        np_info, env, ApiVersion.V2026_02_01_PREVIEW, scratch=True,
    )
    assert mount is not None
    assert mount.mount_path == "/scratch"


def test_no_cross_sc_fallback_v1(tmp_path) -> None:
    """V1: a wrapper mapped for a *different* SC must not be silently used."""
    env = EnvConfig(path=tmp_path / ".env")
    other_sc_id = SC_ID.replace("/sc1", "/sc2")
    env.supercomputer_scratch_dcs = {other_sc_id: DC_ID}
    np_info = _np()  # supercomputer_id == SC_ID, no cached scratch_dc_id

    assert cli_submit._build_scratch_mount(np_info, env, ApiVersion.V2025_07_01_PREVIEW) is None
    with pytest.raises(typer.Exit):
        cli_submit._scratch_mount_or_exit(
            np_info, env, ApiVersion.V2025_07_01_PREVIEW, scratch=True,
        )


def test_no_cross_sc_fallback_v2(tmp_path) -> None:
    """V2: a wrapper mapped for a *different* SC must not be silently used."""
    env = EnvConfig(path=tmp_path / ".env")
    other_sc_id = SC_ID.replace("/sc1", "/sc2")
    env.supercomputer_scratch_scs = {other_sc_id: SC_CONTAINER_ID}
    np_info = _np()

    assert cli_submit._build_scratch_mount(np_info, env, ApiVersion.V2026_02_01_PREVIEW) is None
    with pytest.raises(typer.Exit):
        cli_submit._scratch_mount_or_exit(
            np_info, env, ApiVersion.V2026_02_01_PREVIEW, scratch=True,
        )


def test_no_resolution_when_np_info_missing(tmp_path) -> None:
    """If we can't identify which SC the run lands on, we cannot resolve a wrapper."""
    env = EnvConfig(path=tmp_path / ".env")
    env.supercomputer_scratch_dcs = {SC_ID: DC_ID}
    env.supercomputer_scratch_scs = {SC_ID: SC_CONTAINER_ID}

    assert cli_submit._build_scratch_mount(None, env, ApiVersion.V2025_07_01_PREVIEW) is None
    assert cli_submit._build_scratch_mount(None, env, ApiVersion.V2026_02_01_PREVIEW) is None
