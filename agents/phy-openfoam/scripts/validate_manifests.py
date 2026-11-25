"""Validate the self-contained phy-openfoam entry against public Discovery schemas.

    python scripts/validate_manifests.py <path-to-discovery-repo>/docs/schemas
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import yaml
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

ROOT = Path(__file__).resolve().parents[1]
PAIRS = {
    "tool-definition-schema.json": ROOT / "tools" / "openfoam" / "tool.yaml",
    "agent-schema-v2.json": ROOT / "agent.yaml",
    "metadata-schema.json": ROOT / "metadata.yaml",
}


def main(schema_dir: Path, receipt: Path | None = None, source_commit: str | None = None) -> int:
    missing = [name for name in PAIRS if not (schema_dir / name).is_file()]
    if not schema_dir.is_dir() or missing:
        raise FileNotFoundError(f"public schema cache missing required schemas: {missing}")
    resources = {}
    for p in schema_dir.glob("*.json"):
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            resources[p.name] = Resource.from_contents(data, default_specification=DRAFT7)
    registry = Registry().with_resources(resources.items())
    bad, results = 0, []
    for schema_name, doc in PAIRS.items():
        schema = resources[schema_name].contents
        cls = jsonschema.validators.validator_for(schema)
        data = yaml.safe_load(doc.read_text(encoding="utf-8"))
        errors = list(cls(schema, registry=registry).iter_errors(data))
        name = f"agents/{ROOT.name}/{doc.relative_to(ROOT).as_posix()}"
        print(f"{name}: {'OK' if not errors else f'{len(errors)} error(s)'}")
        for e in errors:
            print(f"  {e.json_path}: {e.message[:300]}")
        bad += len(errors)
        results.append({
            "manifest": name, "schema": schema_name, "errors": len(errors),
            "manifest_sha256": hashlib.sha256(doc.read_bytes()).hexdigest(),
            "schema_sha256": hashlib.sha256((schema_dir / schema_name).read_bytes()).hexdigest(),
        })
    if receipt:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({
            "generated_utc": datetime.now(UTC).isoformat(), "source_commit": source_commit,
            "source_repository": "https://github.com/microsoft/discovery",
            "schema_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted(schema_dir.glob("*.json"))},
            "manifest_results": results, "errors": bad,
        }, indent=1) + "\n", encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schema_dir", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    try:
        raise SystemExit(main(args.schema_dir, args.receipt, args.source_commit))
    except FileNotFoundError as exc:
        parser.error(str(exc))
