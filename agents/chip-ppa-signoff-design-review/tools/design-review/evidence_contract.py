"""Shared, fail-closed native gate identity and immutable artifact resolution."""
from pathlib import Path, PureWindowsPath


ARTIFACT_FIELDS = frozenset((
    "report", "log", "drc_report", "ir_report", "em_report", "lvs_report",
    "antenna_report", "spef", "gds", "routed_def", "floorplan_def", "netlist",
    "guide_file"))

# These are actual producer TOOL/stage identities, not arbitrary caller labels.
# An unknown producer cannot acquire gate coverage by supplying progress.stage_key.
NATIVE_GATES = {
    "drc": "drc", "lvs": "lvs", "antenna_erc": "antenna", "sta": "sta",
    "cdc_rdc": "cdc", "lec": "lec", "dft": "dft",
    "logic_synthesis": "synthesis", "formal_verification": "formal",
    "code_coverage": "codecov", "functional_coverage": "funccov",
    "functional_verification": "funcverif", "cts": "cts", "pdn": "pdn",
    "placement": "placement", "routing": "route", "floorplanning": "floorplan",
    "extraction": "extraction", "power_analysis": "power",
}


def normalize_gate(value):
    name = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return {"antenna_erc": "antenna", "erc": "antenna"}.get(name, name)


def envelope_gate(envelope):
    """Preserve legacy explicit gates; infer only from known native producers."""
    explicit = envelope.get("gate")
    if isinstance(explicit, str) and explicit.strip():
        return normalize_gate(explicit)
    tool = envelope.get("tool")
    if not isinstance(tool, str):
        return None
    gate = NATIVE_GATES.get(tool.strip().lower().replace("-", "_"))
    if gate is None:
        return None
    progress = envelope.get("progress") or {}
    stage = progress.get("stage_key") if isinstance(progress, dict) else None
    if stage and normalize_gate(stage) != normalize_gate(gate):
        return None  # Conflicting native identity is not gate evidence.
    return gate


def artifact_citations(envelope):
    """Yield named artifact strings through bounded nested objects and arrays.

    Unrecognized scalar fields are never paths. Artifact arrays retain their
    field semantics, so both per_engine.klayout.report and provenance.report[]
    are covered without treating every provenance string as a filename.
    """
    visited = 0

    def walk(node, location, depth, is_artifact=False):
        nonlocal visited
        visited += 1
        if visited > 10000 or depth > 12:
            raise ValueError("artifact citation structure exceeds review limits")
        if isinstance(node, dict):
            for key, value in node.items():
                # Native DRC records required deck variables as a bool map,
                # including report=True. That metadata is not a citation.
                # Exempt only this exact typed shape; strings under the same
                # key still traverse and undergo immutable-path validation.
                if key == "deck_variables" and isinstance(value, dict) and all(
                        isinstance(required, bool) for required in value.values()):
                    continue
                yield from walk(value, location + "." + str(key), depth + 1,
                                key in ARTIFACT_FIELDS)
        elif isinstance(node, (list, tuple)):
            for index, value in enumerate(node):
                yield from walk(value, location + "." + str(index), depth + 1,
                                is_artifact)
        elif is_artifact and node not in (None, ""):
            if not isinstance(node, str):
                raise ValueError("artifact citation must be a string: " + location)
            yield location, node

    for section in ("signoff_evidence", "provenance"):
        yield from walk(envelope.get(section) or {}, section, 0)


class CitationUnavailable(ValueError):
    """A safe citation could not be uniquely opened (never a verified artifact)."""

    def __init__(self, reason, candidates=()):
        super().__init__(reason)
        self.candidates = [str(path) for path in candidates]


def resolve_artifact(value, base=None, input_root=None):
    """Resolve exact paths or a unique basename in canonical output folders.

    No recursive search or basename guessing outside root/results/reports/logs.
    Both the launcher boundary and actual review use this exact implementation.
    """
    if not isinstance(value, str) or not value or len(value) > 4096 or "\0" in value:
        raise ValueError("invalid artifact path")
    path = Path(value)
    if ".." in path.parts or ("\\" in value and not path.is_absolute()):
        raise ValueError("artifact file path escapes immutable input or uses traversal")
    if not path.is_absolute() and (PureWindowsPath(value).drive or ":" in value):
        raise ValueError("artifact path is not a local immutable input path")
    base = Path(base).resolve() if base is not None else None
    root = Path(input_root).resolve() if input_root is not None else base
    if root is None:
        raise CitationUnavailable("relative path and no evidence_root supplied")
    if base is not None and not base.is_relative_to(root):
        raise ValueError("evidence root escapes immutable input")
    if path.is_absolute():
        candidates = [path]
    elif base is None:
        raise CitationUnavailable("relative path and no evidence_root supplied")
    else:
        candidates = [base / path]
        if len(path.parts) == 1:
            candidates += [base / folder / path for folder in ("logs", "reports", "results")]
    resolved = []
    for candidate in candidates:
        candidate = candidate.resolve()
        if not candidate.is_relative_to(root):
            raise ValueError("artifact file path escapes immutable input")
        if candidate not in resolved:
            resolved.append(candidate)
    matches = [candidate for candidate in resolved if candidate.is_file()]
    if len(matches) > 1:
        raise CitationUnavailable("ambiguous cited artifact in canonical output layout", matches)
    if not matches:
        raise CitationUnavailable("cited artifact does not exist", resolved)
    return matches[0]