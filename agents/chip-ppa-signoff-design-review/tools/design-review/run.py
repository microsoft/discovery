#!/usr/bin/env python3
"""Strict file-only transport for the native, envelope-consuming reviewer."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys

import design_review_utils as utils

SUPPORTED_SCENARIOS = ("review_signoff", "adjudicate_waivers", "check_evidence")
OBJECT_PARAMS = ("pdk_binding", "deck_vars", "budget", "constraints", "metrics")


def input_path(value, root, base=None):
    if not isinstance(value, str) or not value:
        raise ValueError("input path must be a nonempty string")
    path = Path(value)
    if not path.is_absolute():
        if base is None:
            raise ValueError("file paths must be absolute under /input")
        path = base / path
    path = path.resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("file path escapes immutable /input")
    return path


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError("nonfinite JSON number: " + value)
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                       parse_constant=constant)
    if not isinstance(value, dict):
        raise ValueError("JSON must be one object")
    return value


def validate(params, root):
    if params.get("scenario") not in SUPPORTED_SCENARIOS:
        raise ValueError("explicit supported top-level scenario is required")
    for key in OBJECT_PARAMS:
        if key in params and not isinstance(params[key], dict):
            raise ValueError(key + " must be an inline object")
    if not isinstance(params.get("envelopes"), list) or not params["envelopes"]:
        raise ValueError("envelopes must be a nonempty array")
    for key in ("required_gates", "required_fields"):
        if key in params and (not isinstance(params[key], list) or
                              any(not isinstance(v, str) or not v for v in params[key])):
            raise ValueError(key + " must be an array of nonempty strings")
    if "require_artifacts" in params and not isinstance(params["require_artifacts"], bool):
        raise ValueError("require_artifacts must be boolean")
    if "waivers" in params and not isinstance(params["waivers"], list):
        raise ValueError("waivers must be an array")
    if params["scenario"] == "adjudicate_waivers" and "waivers" not in params:
        raise ValueError("adjudicate_waivers requires waivers")
    for key, spec in params.get("budget", {}).items():
        if not isinstance(spec, dict) or not spec or set(spec) - {"min", "max"}:
            raise ValueError("budget limits require min/max objects")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
               not math.isfinite(v) for v in spec.values()):
            raise ValueError("budget limits must be finite numbers")
    evidence_root = input_path(params["evidence_root"], root) if "evidence_root" in params else None
    files = []
    for entry in params["envelopes"]:
        base = evidence_root
        if isinstance(entry, str):
            path = input_path(entry, root)
            env = load_json(path)
            files.append(path)
            base = base or path.parent
        elif isinstance(entry, dict):
            env = entry
            if not env.get("id"):
                raise ValueError("inline envelopes require id")
        else:
            raise ValueError("envelope entries must be objects or /input paths")
        for section in ("results", "qor_metrics", "metrics", "qor", "signoff_evidence",
                        "provenance", "validation"):
            if section in env and not isinstance(env[section], dict):
                raise ValueError("envelope " + section + " must be an object")
        for section in ("signoff_evidence", "provenance"):
            for key, value in env.get(section, {}).items():
                if key in utils._ARTIFACT_FIELDS and isinstance(value, str) and value:
                    if not Path(value).is_absolute() and base is None:
                        continue  # Preserve native unresolvable-citation reporting.
                    path = input_path(value, root, base)
                    if path.is_file():
                        files.append(path)
    return files


def persist(results, output, files):
    results.setdefault("objective", "design review")
    results.setdefault("results", {})
    results.setdefault("provenance", {})
    results["provenance"]["bookshelves_consulted"] = "none_relevant"
    artifacts = {"envelope": "common_design_envelope.json",
                 "report": "reports/REPORT.md"}
    mapping = {}
    for source in dict.fromkeys(files):
        if source.is_file():
            relative = "results/evidence/" + hashlib.sha256(str(source).encode()).hexdigest()[:16] + "-" + source.name
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            mapping[str(source)] = relative
            artifacts["evidence_" + str(len(mapping))] = relative
    audit = results.get("signoff_evidence", {}).get("evidence_audit", {})
    for group in ("envelopes", "artifacts"):
        for item in audit.get(group, []):
            source = item.get("path")
            if source in mapping:
                item["source_path"] = source
                item["path"] = mapping[source]
    results["artifacts"] = artifacts
    utils.save_final_results(results)
    actual = load_json(output / "common_design_envelope.json")
    verdict = actual.get("validation", {}).get("verdict")
    code = 0 if actual.get("status") == "completed" and verdict in (
        "pass", "pass_with_caveats", "review", "not_assessable") else 1
    if code:
        print("CDE_JSON=" + json.dumps(actual, ensure_ascii=True, separators=(",", ":")), flush=True)
    return code


def execute(params_file, input_root=Path("/input"), output=Path("/output"),
            workdir=Path("/workdir")):
    for key in ("CHIP_OUTPUT_DIR", "OUTPUT_DIR", "CHIP_WORK_DIR", "WORK_DIR"):
        os.environ.pop(key, None)
    files = []
    try:
        for directory in (output, workdir):
            directory.mkdir(parents=True, exist_ok=True)
            if any(directory.iterdir()):
                raise ValueError("fresh /output and /workdir are required")
        utils.quick_setup(str(output), str(workdir))
        params_path = input_path(str(params_file), input_root)
        params = load_json(params_path)
        files = [params_path] + validate(params, input_root)
        results = utils.dispatch(params)
    except Exception as error:
        utils.quick_setup(str(output), str(workdir))
        results = {"tool": utils.TOOL, "status": "failed", "error": str(error),
                   "validation": {"verdict": "fail", "note": str(error)}}
    return persist(results, output, files)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--params-file", required=True)
    try:
        args = parser.parse_args()
    except SystemExit:
        return execute(Path("/input/__invalid_arguments__.json"))
    return execute(Path(args.params_file))


if __name__ == "__main__":
    sys.exit(main())
