"""POL-008 — content-based binary detection.

The rule this replaces compared file extensions, so the cases that matter most
here are the disguised binaries: a real binary carrying a text extension must
still be blocked.
"""

from __future__ import annotations

import pytest
from conftest import (
    ELF_BYTES,
    GZIP_BYTES,
    PDF_BYTES,
    PE_BYTES,
    PNG_BYTES,
    SQLITE_BYTES,
    WASM_BYTES,
    ZIP_BYTES,
    files,
    run_rule,
    write,
)

from rules.pol_008 import RULE


# ── Disguised binaries: the whole point of the rule ──────────────────────────

@pytest.mark.parametrize("rel,payload", [
    ("agents/demo/tools/t/notes.txt", ELF_BYTES),
    ("agents/demo/tools/t/data.csv", ZIP_BYTES),
    ("agents/demo/README.md", GZIP_BYTES),
    ("agents/demo/tools/t/helper.py", PE_BYTES),
    ("agents/demo/metadata.yaml", SQLITE_BYTES),
    ("starter-kits/demo/kit.json", WASM_BYTES),
])
def test_binary_with_text_extension_is_blocked(repo, rel, payload):
    write(repo, rel, payload)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "disguised" in result.findings[0].message


def test_disguised_binary_is_flagged_as_spoofed_not_generic(repo):
    rel = write(repo, "agents/demo/tools/t/config.yaml", ELF_BYTES)
    result = run_rule(repo, RULE, [rel])
    assert "disguised with a text extension" in result.findings[0].message


# ── Honestly-named binaries ──────────────────────────────────────────────────

@pytest.mark.parametrize("rel,payload", [
    ("agents/demo/logo.png", PNG_BYTES),
    ("agents/demo/guide.pdf", PDF_BYTES),
    ("agents/demo/tools/t/lib.so", ELF_BYTES),
])
def test_binary_with_matching_extension_is_blocked(repo, rel, payload):
    write(repo, rel, payload)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "disguised" not in result.findings[0].message


# ── Legitimate source must pass ──────────────────────────────────────────────

@pytest.mark.parametrize("rel,content", [
    ("agents/demo/tools/t/utils.py", "import os\n\n\ndef main():\n    return os.getcwd()\n"),
    ("agents/demo/README.md", "# Demo\n\n## Overview\n\nA demo agent.\n"),
    ("agents/demo/metadata.yaml", "name: demo\ntype: agent\nversion: 1.0.0\n"),
    ("starter-kits/demo/kit.json", '{"name": "demo", "version": "1.0.0"}\n'),
    ("agents/demo/tools/t/Dockerfile", "FROM mcr.microsoft.com/azurelinux/base/python:3.12\n"),
    ("agents/demo/tools/t/run.sh", "#!/usr/bin/env bash\nset -euo pipefail\necho hi\n"),
])
def test_source_files_pass(repo, rel, content):
    write(repo, rel, content)
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_non_ascii_utf8_text_passes(repo):
    rel = write(
        repo, "agents/demo/README.md",
        "# Démo — Ångström\n\nSchrödinger's β-sheet, 25 °C, ±0.5 Å.\n中文说明。\n",
    )
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_scientific_text_input_files_pass(repo):
    rel = write(
        repo, "agents/demo/tools/t/example-input-files/protein.pdb",
        "ATOM      1  N   MET A   1      20.154  29.699   5.276  1.00 49.05           N\n"
        "ATOM      2  CA  MET A   1      21.125  28.640   5.135  1.00 49.05           C\n"
        "END\n",
    )
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_svg_is_treated_as_text(repo):
    rel = write(
        repo, "agents/demo/diagram.svg",
        '<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>\n',
    )
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


# ── Scope and exemptions ─────────────────────────────────────────────────────

def test_binaries_outside_guarded_trees_are_ignored(repo):
    rel = write(repo, "utilities/toolbox/vendor.dll", PE_BYTES)
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_model_weight_extensions_are_left_to_pol_009(repo):
    rel = write(repo, "agents/demo/tools/t/model.safetensors", ELF_BYTES)
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_deleted_binary_is_not_flagged(repo):
    # Present in the diff but absent from the checkout — i.e. the contributor
    # removed it, which is exactly the remediation we ask for.
    result = run_rule(repo, RULE, ["agents/demo/tools/t/old.bin"])
    assert result.findings == []


def test_empty_file_is_not_flagged_as_binary(repo):
    rel = write(repo, "agents/demo/tools/t/__init__.py", b"")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_multiple_binaries_all_reported_in_one_pass(repo):
    a = write(repo, "agents/demo/a.txt", ELF_BYTES)
    b = write(repo, "agents/demo/b.txt", ZIP_BYTES)
    c = write(repo, "agents/demo/c.py", "print('ok')\n")
    result = run_rule(repo, RULE, [a, b, c])
    assert sorted(files(result)) == sorted([a, b])
