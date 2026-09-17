"""POL-015 — approved file types under agents/ and starter-kits/."""

from __future__ import annotations

import pytest
from conftest import files, run_rule, write

from rules.pol_015 import RULE


@pytest.mark.parametrize("rel", [
    "agents/demo/tools/t/utils.py",
    "agents/demo/tools/t/Dockerfile",
    "agents/demo/tools/t/Dockerfile.gpu",
    "agents/demo/tools/t/requirements-dev.txt",
    "agents/demo/tools/t/environment.yml",
    "agents/demo/tools/t/.dockerignore",
    "agents/demo/metadata.yaml",
    "agents/demo/README.md",
    "agents/demo/LICENSE",
    "agents/demo/tools/t/example-input-files/mol.sdf",
    "agents/demo/tools/t/example-input-files/seq.fasta",
    "agents/demo/tools/t/design.sv",
    "starter-kits/demo/kit.json",
])
def test_approved_types_pass(repo, rel):
    write(repo, rel, "content\n")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


@pytest.mark.parametrize("rel", [
    "agents/demo/notes.docx",
    "agents/demo/sheet.xlsx",
    "agents/demo/tools/t/archive.tar",
    "agents/demo/tools/t/lib.so",
    "agents/demo/tools/t/thing.unknownext",
])
def test_unapproved_types_are_blocked(repo, rel):
    write(repo, rel, "content\n")
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "source-allowlist.yaml" in result.findings[0].message


def test_unapproved_type_outside_guarded_trees_is_ignored(repo):
    rel = write(repo, "utilities/toolbox/extension.vsix", "content\n")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


@pytest.mark.parametrize("rel", [
    # Simulator inputs whose extensions are domain conventions, not file types.
    "agents/demo/tools/t/example-input-files/in.lj.ehex",
    "agents/demo/tools/t/example-input-files/data.spce",
    "agents/demo/tools/t/example-input-files/silicon/si.scf.in",
    "agents/demo/tools/t/example-input-files/no-extension-at-all",
])
def test_example_input_files_are_exempt_from_the_extension_check(repo, rel):
    write(repo, rel, "units real\natom_style full\n")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_exemption_does_not_extend_to_the_agent_root(repo):
    rel = write(repo, "agents/demo/in.lj.ehex", "content\n")
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]


def test_model_weights_are_left_to_pol_009(repo):
    rel = write(repo, "agents/demo/tools/t/model.safetensors", "content\n")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_deleted_file_is_not_flagged(repo):
    result = run_rule(repo, RULE, ["agents/demo/gone.docx"])
    assert result.findings == []
