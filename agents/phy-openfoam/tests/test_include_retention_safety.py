"""Pinned include and export boundaries, using only strings and synthetic temporary files."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from discovery_physics.core import integrity
from discovery_physics.openfoam import retention
from discovery_physics.openfoam.safety import validate_files


@pytest.fixture(autouse=True)
def no_operator_state(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Isolated safety tests must not access operator state or execute anything.")

    for name in ("run_dir", "runs_root", "verify", "container_runtime", "execute"):
        monkeypatch.setattr(retention.runner, name, forbidden)
    for name in ("key_path", "_key", "key_id"):
        monkeypatch.setattr(integrity, name, forbidden)
    for name in ("home", "load"):
        monkeypatch.setattr(retention.runner.config, name, forbidden)


def case(text: str, **extra: str) -> dict[str, str]:
    return {"system/controlDict": "solver fluid;\n", "system/fvSchemes": text, **extra}


@pytest.mark.parametrize("kind", ["includeEtc", "includeFunc", "includeModel"])
@pytest.mark.parametrize("template", [
    '#{kind} caseDicts/../../etc/passwd\n',
    '#{kind} "caseDicts/../../etc/passwd"\n',
    '# \t{kind}\n<caseDicts/sub/../../../etc/passwd>\n',
    'entry 1; #{kind} "caseDicts/safe"\n',
    'outer {{ inner {{ # \t{kind} "caseDicts/safe" }} }}',
    '#/* gap */{kind}/* gap */"caseDicts/safe"\n',
    'note "https://example.invalid/a/*literal*/"; #{kind} "caseDicts/safe"\n',
    'note "escaped \\" // still quoted"; #{kind} "caseDicts/safe"\n',
])
def test_external_includes_are_rejected_everywhere(kind, template):
    findings = validate_files(case(template.format(kind=kind)))
    assert any(f"#{kind}" in finding and "not allowed" in finding for finding in findings)


@pytest.mark.parametrize("text", [
    '// #includeEtc "caseDicts/../../etc/passwd"\n',
    '/* #includeFunc bad;\n #includeModel bad; */\n',
    'note "#includeEtc caseDicts/../../etc/passwd";\n',
    'note "literal // #includeFunc bad";\n',
    'note "literal /* #includeModel bad */";\n',
    'note "escaped \\" // #includeEtc bad";\n',
    '/* " */ note 1; // #includeEtc bad\n',
    'note "#calc literal, not a directive";\n',
])
def test_comments_and_quoted_literals_are_not_directives(text):
    assert validate_files(case(text)) == []


@pytest.mark.parametrize("text", [
    '/* #includeEtc bad */ # include "include/local"\n',
    '// #includeFunc bad\n#include "include/local"\n',
    '#/* gap */include/* gap */<include/local>\n',
    'note "// and /* are literal"; #include "include/local"/* trailing */',
])
def test_comments_do_not_hide_or_corrupt_real_includes(text):
    assert validate_files(case(text, **{"system/include/local": "value 1;\n"})) == []


@pytest.mark.parametrize("kind", ["include", "includeIfPresent"])
@pytest.mark.parametrize("target", [
    '"../outside"', '"include/../local"', '"/etc/passwd"',
    '"$FOAM_CASE/include/local"', '"${FOAM_CASE}/include/local"', '"~/include/local"',
    '"C:/include/local"', '"include/a:local"', r'"include\local"',
    r'"include/\x6cocal"', '"include//local"', '"./include/local"',
    '"include/."', '"include/.."', '""', '<>', '"include/ white"',
    '"include/*local"', '"include/local"suffix', '"include/local"/../../outside',
    '<include/local>suffix', '<include/local', '"include/local',
    'include/local', "'include/local'", '""include/local""',
])
def test_include_target_must_be_one_safe_delimited_path(kind, target):
    files = case(f"#{kind} {target}\n", **{"system/include/local": "value 1;\n"})
    assert validate_files(files)


@pytest.mark.parametrize("kind", ["include", "includeIfPresent"])
@pytest.mark.parametrize("target", ['"include/local"', '<include/local>'])
def test_only_present_bundled_include_targets_are_allowed(kind, target):
    assert validate_files(case(f"outer {{ #{kind} {target} }}\n",
                               **{"system/include/local": "value 1;\n"})) == []


@pytest.mark.parametrize("kind", ["include", "includeIfPresent"])
def test_missing_targets_are_refused_even_for_optional_includes(kind):
    # A mounted case can contain an unbundled file at this otherwise valid field path.
    files = {"system/controlDict": "solver fluid;\n", "0/U": f'#{kind} "p"\n'}
    findings = validate_files(files)
    assert any("0/p" in finding and "bundle" in finding for finding in findings)


def test_targets_resolve_against_each_including_files_parent():
    files = {
        "system/controlDict": "solver fluid;\n",
        "0/U": 'boundaryField { # include "include/ic" }\n',
        "0/include/ic": '#include "nested"\n',
        "0/include/nested": "value uniform 0;\n",
        "system/fvSchemes": '#include <include/common>\n',
        "system/include/common": '#includeIfPresent "defaults"\n',
        "system/include/defaults": "divSchemes {}\n",
        "constant/physicalProperties": '#include "include/properties"\n',
        "constant/include/properties": "nu 1;\n",
    }
    assert validate_files(files) == []


def test_same_named_file_at_wrong_bundle_root_does_not_satisfy_an_include():
    findings = validate_files(case('#include "include/local"\n',
                                   **{"0/include/local": "value 1;\n"}))
    assert any("system/include/local" in finding and "bundle" in finding
               for finding in findings)


@pytest.mark.parametrize("kind", ["includeEtc", "includeFunc", "includeModel"])
def test_nested_bundled_files_are_also_scanned(kind):
    files = case('#include "include/local"\n',
                 **{"system/include/local": f'nested {{ #{kind} "caseDicts/safe" }}\n'})
    assert any(finding.startswith("system/include/local:") and f"#{kind}" in finding
               for finding in validate_files(files))


def test_input_mode_and_remove_remain_allowed_in_nested_dictionaries():
    text = 'outer { # inputMode merge\n# remove "old.*"\n#include "include/local" }\n'
    assert validate_files(case(text, **{"system/include/local": "value 1;\n"})) == []


@pytest.mark.parametrize("text", [
    'entry 1; #calc "1 + 1";', 'outer { #codeStream {} }',
    'outer { #{ anything #}; }', '#"includeEtc" "caseDicts/safe"',
    'note "never closed',
])
def test_unsupported_directives_and_unterminated_lexical_content_fail_closed(text):
    assert validate_files(case(text))


def snapshot(root: Path) -> dict[str, bytes | None]:
    return {p.relative_to(root).as_posix(): None if p.is_dir() else p.read_bytes()
            for p in root.rglob("*")}


@pytest.fixture()
def synthetic_run(tmp_path, monkeypatch):
    run_id = "20261124T000000Z-01234567"
    source = tmp_path / "synthetic-source" / run_id
    contents = {
        "bundle.json": b'{"synthetic":true}\n',
        "journal.jsonl": b'synthetic journal, not a signed record\n',
        "report.md": b'synthetic report\n',
        "output/evidence.json": b'{"synthetic":true}\n',
        "output/log.worker": b'worker log\n',
        "output/case/log.foamRun": b'solver log\n',
        "output/case/log.checkMesh": b'mesh log\n',
        "output/case/0/U": b'initial field\n',
        "output/case/1/U": b'final field\n',
        "output/case/system/controlDict": b'dictionary\n',
        "output/case/constant/polyMesh/points": b'mesh\n',
        "output/case/nested/log.details": b'not a top-level retained case log\n',
    }
    for name, data in contents.items():
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    check = {"run_id": run_id, "ok": True, "records": 1, "verdict": None, "final": None}

    def run_dir(requested):
        assert requested == run_id
        return source

    monkeypatch.setattr(retention.runner, "run_dir", run_dir)
    monkeypatch.setattr(retention.runner, "verify", lambda requested: check)
    return run_id, source, contents, check


@pytest.mark.parametrize("include_fields", [False, True])
def test_valid_export_preserves_fields_logs_and_receipt(
        synthetic_run, tmp_path, monkeypatch, include_fields):
    run_id, source, contents, check = synthetic_run
    dest = tmp_path / "exports" / "run.zip"
    before = snapshot(source)
    calls = []

    def verify(requested):
        assert requested == run_id
        assert not dest.parent.exists()
        calls.append(requested)
        return check

    monkeypatch.setattr(retention.runner, "verify", verify)
    result = retention.export(run_id, dest, include_fields=include_fields)
    expected = {f"{run_id}/{name}": data for name, data in contents.items()
                if include_fields or not name.startswith("output/case/")
                or (name.count("/") == 2 and name.startswith("output/case/log."))}
    with zipfile.ZipFile(dest) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == expected
        assert all(info.compress_type == zipfile.ZIP_DEFLATED for info in archive.infolist())
    assert result == {"run_id": run_id, "archive": str(dest), "files": len(expected),
                      "integrity": check, "fields_included": include_fields}
    assert calls == [run_id]
    assert snapshot(source) == before


@pytest.mark.parametrize("check", [
    {"ok": False, "error": "synthetic tampering"}, {}, {"ok": None}, {"ok": "true"}, {"ok": 1},
])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("include_fields", [False, True])
def test_failed_verification_never_mutates_destination_or_source(
        synthetic_run, tmp_path, monkeypatch, check, existing, include_fields):
    run_id, _, _, _ = synthetic_run
    dest = tmp_path / "exports" / "nested" / "run.zip"
    if existing:
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"existing archive must not change")
    before = snapshot(tmp_path)
    monkeypatch.setattr(retention.runner, "verify", lambda requested: check)
    with pytest.raises(integrity.IntegrityError, match="verif"):
        retention.export(run_id, dest, include_fields=include_fields)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("existing", [False, True])
def test_raised_integrity_error_propagates_before_any_destination_write(
        synthetic_run, tmp_path, monkeypatch, existing):
    run_id, _, _, _ = synthetic_run
    dest = tmp_path / "exports" / "run.zip"
    if existing:
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"existing archive")
    before = snapshot(tmp_path)
    error = integrity.IntegrityError("synthetic verification exception")

    def verify(requested):
        raise error

    monkeypatch.setattr(retention.runner, "verify", verify)
    with pytest.raises(integrity.IntegrityError) as caught:
        retention.export(run_id, dest, include_fields=True)
    assert caught.value is error
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("include_fields", [False, True])
def test_verified_export_never_clobbers_existing_destination(
        synthetic_run, tmp_path, include_fields):
    run_id, _, _, _ = synthetic_run
    dest = tmp_path / "exports" / "run.zip"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"pre-existing archive")
    before = snapshot(tmp_path)
    with pytest.raises(FileExistsError):
        retention.export(run_id, dest, include_fields=include_fields)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("include_fields", [False, True])
@pytest.mark.parametrize("relative", [
    "archive.zip", "output/case/nested/archives/run.zip", "output/../archive.zip",
])
def test_export_refuses_destination_inside_source_before_creating_anything(
        synthetic_run, tmp_path, monkeypatch, include_fields, relative):
    run_id, source, _, _ = synthetic_run
    before = snapshot(tmp_path)

    def archive_must_not_open(*args, **kwargs):
        pytest.fail("An archive inside the source must be refused before it is opened.")

    monkeypatch.setattr(retention.zipfile, "ZipFile", archive_must_not_open)
    with pytest.raises(ValueError, match="outside.*run"):
        retention.export(run_id, source / relative, include_fields=include_fields)
    assert snapshot(tmp_path) == before