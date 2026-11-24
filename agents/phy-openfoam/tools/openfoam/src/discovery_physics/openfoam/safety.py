"""Refuse dangerous or unauditable case content before anything executes."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
ALLOWED_ROOTS = {"0", "constant", "system"}
_PATH = re.compile(r"^[A-Za-z0-9_.+-]+(/[A-Za-z0-9_.+-]+)*$")

# Each rule names the risk so a refusal is actionable for the agent.
FORBIDDEN = [
    (re.compile(r"#\s*codeStream"), "dynamic C++ compilation (#codeStream)"),
    (re.compile(r"#\s*calc\b"), "dynamic C++ compilation (#calc)"),
    (re.compile(r"#\s*\{"), "inline code block"),
    (re.compile(r"\bcoded\w*"), "coded boundary/function object compiles user C++"),
    (re.compile(r"\bsystemCall\b"), "systemCall executes shell commands"),
    (re.compile(r"\$\{?\s*(HOME|USER|PATH|WM_|FOAM_(?!CASE\b))"), "host environment expansion"),
]
_INCLUDE = re.compile(
    r"#\s*(includeIfPresent|includeEtc|includeFunc|includeModel|include)\s+\"?([^\"\s;]+)"
)
_LIBS = re.compile(r"\blibs\s*\(([^)]*)\)")
_DIRECTIVE = re.compile(r"(?m)^[ \t]*#\s*([A-Za-z]+)")
ALLOWED_DIRECTIVES = {"include", "includeEtc", "includeIfPresent", "inputMode", "remove"}

# Allowlist of case files. Anything else is refused with the reason, so an agent can adapt.
SYSTEM_FILES = {
    "controlDict", "fvSchemes", "fvSolution", "blockMeshDict", "snappyHexMeshDict", "surfaceFeaturesDict",
    "decomposeParDict", "setFieldsDict", "meshQualityDict", "extrudeMeshDict", "topoSetDict",
    "createPatchDict", "createBafflesDict", "mirrorMeshDict", "refineMeshDict", "changeDictionaryDict",
    "fvConstraints", "fvModels", "collapseDict", "renumberMeshDict",
}
CONSTANT_FILES = re.compile(
    r"(physicalProperties|thermophysicalProperties|momentumTransport|thermophysicalTransport|"
    r"transportProperties|turbulenceProperties|viscosityProperties|g|pRef|hRef|fvModels|fvConstraints|"
    r"dynamicMeshDict|MRFProperties|radiationProperties|combustionProperties|chemistryProperties|"
    r"reactions|speciesThermo|phaseProperties|porosityProperties|thermo|fluxProperties|"
    r"solidProperties|regionProperties|cloudProperties)(\.[A-Za-z0-9_]+)?"
)
GEOMETRY = re.compile(r"constant/(geometry|triSurface)/[A-Za-z0-9_.+-]+\.(stl|obj|vtk|eMesh|ftr)")
FIELD = re.compile(r"0/[A-Za-z][A-Za-z0-9_.:]*")


def _allowed_path(path: str) -> bool:
    parts = path.split("/")
    if len(parts) == 3 and parts[1] == "include" and parts[0] in ALLOWED_ROOTS:
        return True
    if parts[0] == "system":
        return len(parts) == 2 and parts[1] in SYSTEM_FILES
    if parts[0] == "constant":
        return bool(GEOMETRY.fullmatch(path)) or (len(parts) == 2 and bool(CONSTANT_FILES.fullmatch(parts[1])))
    return bool(FIELD.fullmatch(path))


class CaseRejected(ValueError):
    pass


def validate_files(files: dict[str, str]) -> list[str]:
    """Return findings; an empty list means the case may be staged."""
    findings: list[str] = []
    total = 0
    for path, text in files.items():
        p = PurePosixPath(path)
        if not _PATH.match(path) or ".." in p.parts or p.is_absolute():
            findings.append(f"{path}: unsafe path")
            continue
        if p.parts[0] not in ALLOWED_ROOTS:
            findings.append(f"{path}: only 0/, constant/, system/ are allowed")
        if p.parts[:2] == ("constant", "polyMesh"):
            findings.append(f"{path}: supply mesh generators, not precomputed polyMesh data")
        elif p.parts[0] in ALLOWED_ROOTS and not _allowed_path(path):
            findings.append(f"{path}: not an allowlisted case file (system dictionaries, constant/ property "
                            "files, constant/geometry/*.stl|obj, 0/<field>, <root>/include/<file>)")
        for directive in _DIRECTIVE.findall(text):
            if directive not in ALLOWED_DIRECTIVES:
                findings.append(f"{path}: directive #{directive} is not allowed")
        size = len(text.encode("utf-8"))
        total += size
        if size > MAX_FILE_BYTES:
            findings.append(f"{path}: exceeds {MAX_FILE_BYTES} bytes")
        if any(ord(c) < 9 or 13 < ord(c) < 32 for c in text):
            findings.append(f"{path}: control characters")
        for rule, why in FORBIDDEN:
            if rule.search(text):
                findings.append(f"{path}: {why}")
        for kind, target in _INCLUDE.findall(text):
            if kind == "includeEtc" and not target.startswith("caseDicts/"):
                findings.append(f"{path}: #includeEtc limited to caseDicts/")
            elif kind in ("include", "includeIfPresent") and (
                target.startswith("/") or ".." in target or "$" in target
            ):
                findings.append(f"{path}: include must be a relative path inside the case")
        for libs in _LIBS.findall(text):
            for lib in re.findall(r"\"([^\"]+)\"", libs):
                if not re.fullmatch(r"lib[A-Za-z0-9]+\.so", lib):
                    findings.append(f"{path}: library {lib!r} is not a solver-provided library name")
    if total > MAX_TOTAL_BYTES:
        findings.append(f"case exceeds {MAX_TOTAL_BYTES} bytes")
    control = files.get("system/controlDict", "")
    if re.search(r"(?m)^\s*functions\b", control):
        findings.append("system/controlDict: declare outputs as diagnostics.quantities; monitors are injected")
    if not re.search(r"(?m)^\s*solver\s+\w+\s*;", control):
        findings.append("system/controlDict: a foamRun 'solver <module>;' entry is required")
    if re.search(r"(?m)^\s*application\s+(?!foamRun\s*;)", control):
        findings.append("system/controlDict: only foamRun modular solvers are supported")
    return findings


def require_safe(files: dict[str, str]) -> None:
    findings = validate_files(files)
    if findings:
        raise CaseRejected("; ".join(findings))
