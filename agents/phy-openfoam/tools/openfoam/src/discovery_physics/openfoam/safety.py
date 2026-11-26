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
    (re.compile(r"\bcoded\w*"), "coded boundary/function object compiles user C++"),
    (re.compile(r"\bsystemCall\b"), "systemCall executes shell commands"),
    (re.compile(r"\$\{?\s*(HOME|USER|PATH|WM_|FOAM_(?!CASE\b))"), "host environment expansion"),
]
_INCLUDE = re.compile(
    r'\s*(?:"([^"\r\n]*)"|<([^<>\r\n]*)>)(?=$|[\s;{}()#])'
)
_LIBS = re.compile(r"\blibs\s*\(([^)]*)\)")
_DIRECTIVE = re.compile(r"#\s*([A-Za-z][A-Za-z0-9_]*)")
ALLOWED_DIRECTIVES = {"include", "includeIfPresent", "inputMode", "remove"}

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


def _lex_foam(text: str) -> tuple[str, list[int], list[str]]:
    """Blank actual comments, preserve strings/offsets, and locate active '#' tokens."""
    chunks: list[str] = []
    directives: list[int] = []
    errors: list[str] = []
    i, start = 0, 0
    while i < len(text):
        if text[i] == '"':
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            else:
                errors.append("unterminated quoted string")
        elif text.startswith("//", i) or text.startswith("/*", i):
            if text[i + 1] == "/":
                end = text.find("\n", i + 2)
            else:
                end = text.find("*/", i + 2)
                if end != -1:
                    end += 2
            # The bundle linter separately reports unterminated block comments.
            if end == -1:
                end = len(text)
            chunks.append(text[start:i])
            chunks.append("".join(c if c in "\r\n" else " " for c in text[i:end]))
            i = start = end
        else:
            if text[i] == "#":
                directives.append(i)
            i += 1
    chunks.append(text[start:])
    return "".join(chunks), directives, errors


def validate_files(files: dict[str, str]) -> list[str]:
    """Return findings; an empty list means the case may be staged.

    Both include kinds must target bundled files relative to the including file.
    Missing optional targets are refused too: a mounted continuation case could
    otherwise supply unpinned field/time files that were absent from the bundle.
    """
    findings: list[str] = []
    total = 0
    control = ""
    for path, text in files.items():
        p = PurePosixPath(path)
        if (not _PATH.fullmatch(path) or any(part in (".", "..") for part in path.split("/"))
                or p.is_absolute()):
            findings.append(f"{path}: unsafe path")
            continue
        if p.parts[0] not in ALLOWED_ROOTS:
            findings.append(f"{path}: only 0/, constant/, system/ are allowed")
        if p.parts[:2] == ("constant", "polyMesh"):
            findings.append(f"{path}: supply mesh generators, not precomputed polyMesh data")
        elif p.parts[0] in ALLOWED_ROOTS and not _allowed_path(path):
            findings.append(f"{path}: not an allowlisted case file (system dictionaries, constant/ property "
                            "files, constant/geometry/*.stl|obj, 0/<field>, <root>/include/<file>)")
        clean, directives, lexical_errors = _lex_foam(text)
        findings.extend(f"{path}: {error}" for error in lexical_errors)
        if path == "system/controlDict":
            control = clean
        for offset in directives:
            match = _DIRECTIVE.match(clean, offset)
            directive = match.group(1) if match else ""
            if directive not in ALLOWED_DIRECTIVES:
                findings.append(f"{path}: directive #{directive} is not allowed")
            elif directive in ("include", "includeIfPresent"):
                token = _INCLUDE.match(clean, match.end())
                target = (token.group(1) if token.group(1) is not None else token.group(2)) if token else ""
                if (not _PATH.fullmatch(target)
                        or any(part in (".", "..") for part in target.split("/"))):
                    findings.append(f"{path}: #{directive} requires one quoted or bracketed relative path "
                                    "inside the case (no traversal, escapes or expansion)")
                    continue
                resolved = (p.parent / target).as_posix()
                if resolved not in files:
                    findings.append(f"{path}: #{directive} target {resolved!r} must be present in the bundle "
                                    "(including optional targets)")
        size = len(text.encode("utf-8"))
        total += size
        if size > MAX_FILE_BYTES:
            findings.append(f"{path}: exceeds {MAX_FILE_BYTES} bytes")
        if any(ord(c) < 9 or 13 < ord(c) < 32 for c in text):
            findings.append(f"{path}: control characters")
        for rule, why in FORBIDDEN:
            if rule.search(clean):
                findings.append(f"{path}: {why}")
        for libs in _LIBS.findall(clean):
            for lib in re.findall(r"\"([^\"]+)\"", libs):
                if not re.fullmatch(r"lib[A-Za-z0-9]+\.so", lib):
                    findings.append(f"{path}: library {lib!r} is not a solver-provided library name")
    if total > MAX_TOTAL_BYTES:
        findings.append(f"case exceeds {MAX_TOTAL_BYTES} bytes")
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
