"""Integrity checks for the source-backed validation inventory."""

from __future__ import annotations

import csv
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = REPO_ROOT / "docs" / "validation-rules.csv"
IMPLEMENTED_RULE_ID = re.compile(
    r"\b(?:CFG|STR|SCH|POL|DOC|TAG|SKT-(?:SCH|STR|REF|POL|AST|DUP))-\d{3}\b"
)


def _inventory_rows() -> list[dict[str, str]]:
    with INVENTORY_PATH.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_inventory_rows_are_complete_and_sources_exist() -> None:
    rows = _inventory_rows()
    assert rows
    assert set(rows[0]) == {"rule_id", "name", "purpose", "implementation_source"}
    assert all(row["name"] and row["purpose"] and row["implementation_source"] for row in rows)

    rule_ids = [row["rule_id"] for row in rows if row["rule_id"]]
    assert len(rule_ids) == len(set(rule_ids))

    missing_sources = [
        source
        for row in rows
        for source in (
            item.strip() for item in row["implementation_source"].split(";")
        )
        if source and not (REPO_ROOT / source).exists()
    ]
    assert not missing_sources


def test_python_validator_rule_ids_are_inventoried() -> None:
    inventoried = {row["rule_id"] for row in _inventory_rows() if row["rule_id"]}
    implemented = {
        match.group()
        for path in (REPO_ROOT / ".github" / "scripts").rglob("*.py")
        for match in IMPLEMENTED_RULE_ID.finditer(path.read_text(encoding="utf-8"))
    }
    assert implemented <= inventoried