"""YAML -> JSON shim for the DiscoveryHealth PowerShell module.

Reads newline-separated file paths on stdin and prints one JSON object mapping
each path to {"ok": true, "doc": ...} or {"ok": false, "error": "..."}.
Uses yaml.safe_load only; output is ASCII-escaped so any console encoding works.
"""

import json
import sys

import yaml


def normalize(value):
    """Make a YAML document JSON-safe (stringify non-string keys such as dates)."""
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def main() -> int:
    results = {}
    for raw in sys.stdin.read().splitlines():
        path = raw.strip()
        if not path:
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                doc = normalize(yaml.safe_load(handle))
            json.dumps(doc)
            results[path] = {"ok": True, "doc": doc}
        except Exception as exc:  # report every parse problem per file
            results[path] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    json.dump(results, sys.stdout, ensure_ascii=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
