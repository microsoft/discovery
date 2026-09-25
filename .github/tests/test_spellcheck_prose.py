"""Tests for trusted, prose-only catalog spellchecking."""

from __future__ import annotations

import subprocess
from pathlib import Path

from spellcheck_prose import ProseFragment, collect_fragments, run_codespell


def _write(repo: Path, relative_path: str, content: str) -> None:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_structured_files_include_only_approved_prose_fields(tmp_path):
    _write(tmp_path, "agents/demo/agent.yaml", """\
kind: prompt
name: teh-identifier
description: This prose contains teh mistake.
model:
  id: teh-model
instructions: |-
  Explain the recieve operation.
  `teh_inline_identifier()` must not be checked.
tools:
  - name: teh-tool
    description: A seperate tool description.
""")

    fragments = collect_fragments(tmp_path, ["agents/demo/agent.yaml"])
    prose = " ".join(fragment.text for fragment in fragments)

    assert "teh mistake" in prose
    assert "recieve operation" in prose
    assert "seperate tool" in prose
    assert "teh-identifier" not in prose
    assert "teh-model" not in prose
    assert "teh_inline_identifier" not in prose


def test_markdown_excludes_frontmatter_fences_inline_code_and_urls(tmp_path):
    _write(tmp_path, "agents/demo/README.md", """\
---
title: teh metadata
---
# A recieve guide

Use `teh_command` in the seperate workflow.

```python
teh_code = True
```

See [teh documentation](https://example.com/teh-url).
""")

    fragments = collect_fragments(tmp_path, ["agents/demo/README.md"])
    prose = " ".join(fragment.text for fragment in fragments)

    assert "recieve guide" in prose
    assert "seperate workflow" in prose
    assert "teh documentation" in prose
    assert "teh metadata" not in prose
    assert "teh_command" not in prose
    assert "teh_code" not in prose
    assert "teh-url" not in prose


def test_collection_ignores_paths_outside_catalog_or_repo(tmp_path):
    _write(tmp_path, "README.md", "This has teh typo.\n")
    _write(tmp_path, "agents/demo/README.md", "This has a seperate typo.\n")

    fragments = collect_fragments(tmp_path, [
        "README.md",
        "../outside.md",
        "agents/demo/README.md",
        "agents/demo/missing.md",
    ])

    assert [(fragment.file, fragment.line) for fragment in fragments] == [
        ("agents/demo/README.md", 1),
    ]


def test_codespell_output_maps_back_to_source_fragment(monkeypatch):
    fragments = [
        ProseFragment("agents/demo/README.md", 4, "Correct prose."),
        ProseFragment("starter-kits/demo/kit.json", 12, "A seperate phrase."),
    ]

    def fake_run(command, **kwargs):
        temp_path = command[-1]
        return subprocess.CompletedProcess(
            command,
            65,
            stdout=f"{temp_path}:2: seperate ==> separate\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert run_codespell(fragments) == [
        __import__("spellcheck_prose").SpellingWarning(
            "starter-kits/demo/kit.json",
            12,
            "Possible spelling issue: seperate ==> separate",
        )
    ]


def test_codespell_allowlist_ignores_product_name():
    fragments = [
        ProseFragment("starter-kits/demo/kit.json", 7, "Generate Synopsys constraints."),
    ]

    assert run_codespell(fragments) == []