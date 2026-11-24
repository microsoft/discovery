"""Minimal, fail-closed readers for ASCII OpenFOAM Foundation 14 data.

Only formats written by the solver are parsed. Anything unexpected raises
``FoamFormatError`` so diagnostics become UNKNOWN rather than silently passing.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

_HEADER_END = re.compile(r"\\\*-{3,}.*?\*/|FoamFile\s*\{.*?\}", re.S)


class FoamFormatError(ValueError):
    pass


def _strip(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def _list_body(text: str, start: int) -> tuple[int, str, int]:
    """Return (count, body, end) for ``N ( ... )`` beginning at/after ``start``."""
    m = re.compile(r"(\d+)\s*\(").search(text, start)
    if not m:
        raise FoamFormatError("list header not found")
    depth, i = 1, m.end()
    while depth:
        if i >= len(text):
            raise FoamFormatError("unterminated list")
        c = text[i]
        depth += c == "("
        depth -= c == ")"
        i += 1
    return int(m.group(1)), text[m.end(): i - 1], i


def _values(body: str, count: int, vector: bool) -> np.ndarray:
    nums = np.array(body.replace("(", " ").replace(")", " ").split(), dtype=float)
    width = 3 if vector else 1
    if nums.size != count * width:
        raise FoamFormatError(f"expected {count * width} numbers, found {nums.size}")
    return nums.reshape(count, 3) if vector else nums


def _value_entry(block: str, key: str, n: int | None, vector: bool) -> np.ndarray | None:
    m = re.search(rf"\b{key}\s+(uniform|nonuniform)\s+", block)
    if not m:
        return None
    if m.group(1) == "uniform":
        rest = block[m.end():]
        if vector:
            v = re.match(r"\(\s*([^)]+)\)", rest)
            if not v:
                raise FoamFormatError("bad uniform vector")
            arr = np.array(v.group(1).split(), dtype=float)
            if arr.size != 3:
                raise FoamFormatError("bad uniform vector size")
            return np.tile(arr, (n or 1, 1))
        v = re.match(r"([^;\s]+)", rest)
        return np.full(n or 1, float(v.group(1)))
    count, body, _ = _list_body(block, m.end())
    if n is not None and count != n:
        raise FoamFormatError(f"{key} has {count} entries, expected {n}")
    return _values(body, count, vector)


def read_field(path: Path, n_cells: int | None = None) -> tuple[np.ndarray, dict[str, str]]:
    """Return internal values and raw boundary blocks of a vol field."""
    text = _strip(Path(path).read_text(encoding="utf-8", errors="strict"))
    cls = re.search(r"\bclass\s+(\w+)\s*;", text)
    vector = bool(cls and "Vector" in cls.group(1))
    head = re.search(r"\binternalField\s+", text)
    if not head:
        raise FoamFormatError(f"{path}: no internalField")
    block = text[head.start():]
    values = _value_entry(block, "internalField", n_cells, vector)
    if values is None:
        raise FoamFormatError(f"{path}: unreadable internalField")
    if n_cells is not None and len(values) != n_cells:
        if len(values) == 1:
            values = np.repeat(values, n_cells, axis=0)
        else:
            raise FoamFormatError(f"{path}: cell count mismatch")
    return values, _boundary_blocks(text)


def _boundary_blocks(text: str) -> dict[str, str]:
    m = re.search(r"\bboundaryField\s*\{", text)
    if not m:
        return {}
    out: dict[str, str] = {}
    i = m.end()
    while True:
        k = re.compile(r"\s*(\"[^\"]+\"|[A-Za-z_][\w.:-]*)\s*\{").match(text, i)
        if not k:
            break
        depth, j = 1, k.end()
        while depth and j < len(text):
            depth += text[j] == "{"
            depth -= text[j] == "}"
            j += 1
        out[k.group(1).strip('"')] = text[k.end(): j - 1]
        i = j
    return out


def patch_value(block: str, n: int, vector: bool) -> np.ndarray | None:
    return _value_entry(block, "value", n, vector)


def read_boundary(mesh_dir: Path) -> dict[str, dict[str, object]]:
    text = _strip((Path(mesh_dir) / "boundary").read_text(encoding="utf-8"))
    body_start = text.find("(", text.find("}") + 1 if "FoamFile" in text else 0)
    out: dict[str, dict[str, object]] = {}
    for name, body in re.findall(r"([A-Za-z_][\w.:-]*)\s*\{([^{}]*)\}", text[body_start:]):
        typ = re.search(r"\btype\s+(\w+)\s*;", body)
        nf = re.search(r"\bnFaces\s+(\d+)\s*;", body)
        sf = re.search(r"\bstartFace\s+(\d+)\s*;", body)
        if not (typ and nf and sf):
            raise FoamFormatError(f"incomplete boundary entry {name}")
        out[name] = {"type": typ.group(1), "nFaces": int(nf.group(1)), "startFace": int(sf.group(1))}
    if not out:
        raise FoamFormatError("no boundary patches")
    return out


def read_label_list(path: Path) -> np.ndarray:
    text = _strip(Path(path).read_text(encoding="utf-8"))
    start = text.find("}") + 1 if "FoamFile" in text else 0
    count, body, _ = _list_body(text, start)
    arr = np.array(body.split(), dtype=np.int64)
    if arr.size != count:
        raise FoamFormatError(f"{path}: label count mismatch")
    return arr


def read_table(path: Path) -> tuple[list[str], np.ndarray]:
    """Read a function-object .dat table; header names come from the last comment line."""
    header: list[str] = []
    rows: list[list[float]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            parts = line[1:].split()
            if parts and parts[0] == "Time":
                header = parts
            continue
        if line.strip():
            rows.append([float(v) for v in line.replace("(", " ").replace(")", " ").split()])
    if not rows:
        raise FoamFormatError(f"{path}: empty table")
    width = {len(r) for r in rows}
    if len(width) != 1:
        raise FoamFormatError(f"{path}: ragged table")
    data = np.array(rows, dtype=float)
    return header, data


def _cells(text: str) -> list:
    """Split a row/header into top-level cells; parenthesised groups become nested lists."""
    out: list = []
    stack: list[list] = [out]
    for tok in re.findall(r"\(|\)|[^\s()]+", text):
        if tok == "(":
            stack[-1].append([])
            stack.append(stack[-1][-1])
        elif tok == ")":
            if len(stack) == 1:
                raise FoamFormatError("unbalanced parenthesis")
            stack.pop()
        else:
            stack[-1].append(tok)
    if len(stack) != 1:
        raise FoamFormatError("unbalanced parenthesis")
    return out


def _header_cells(text: str) -> list[str]:
    """Header names; ``forces(pressure viscous)`` stays one name."""
    return re.findall(r"[^\s(]+(?:\([^)]*\))?", text)


def _flatten(name: str, cell, out: dict[str, float]) -> None:
    if isinstance(cell, str):
        out[name] = float(cell)
        return
    if all(isinstance(c, str) for c in cell):
        vals = [float(c) for c in cell]
        if len(vals) == 3:
            for axis, v in zip("xyz", vals):
                out[f"{name}.{axis}"] = v
            out[f"{name}.mag"] = float(np.linalg.norm(vals))
        else:
            for i, v in enumerate(vals):
                out[f"{name}.{i}"] = v
        return
    # Nested groups, e.g. forces ((pressure)(viscous)); labels come from the header "forces(pressure viscous)".
    m = re.fullmatch(r"([^(]+)\(([^)]*)\)", name)
    base, labels = (m.group(1), m.group(2).split()) if m else (name, [])
    if len(labels) != len(cell):
        labels = [str(i) for i in range(len(cell))]
    parts: dict[str, float] = {}
    for label, sub in zip(labels, cell):
        _flatten(f"{base}.{label}", sub, parts)
    out.update(parts)
    for axis in ("x", "y", "z"):
        keys = [f"{base}.{label}.{axis}" for label in labels]
        if all(k in parts for k in keys):
            out[f"{base}.total.{axis}"] = sum(parts[k] for k in keys)
    if all(f"{base}.total.{a}" in out for a in "xyz"):
        out[f"{base}.total.mag"] = float(np.linalg.norm([out[f"{base}.total.{a}"] for a in "xyz"]))


def read_quantity_table(path: Path) -> dict[str, np.ndarray]:
    """Read any Foundation function-object table into named columns (rows in file order).

    Vectors expand to ``name.x|y|z|mag``; forces/moments to ``forces.pressure.x``,
    ``forces.viscous.x`` and ``forces.total.x``; a text column (e.g. yPlus ``patch``)
    prefixes the names of its row (``walls/average``). Probes are named by probe index.
    """
    header: list[str] = []
    rows: list[dict[str, float]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            parts = _header_cells(line[1:])
            if parts and parts[0] == "Time":
                header = parts
            continue
        if not line.strip():
            continue
        cells = _cells(line)
        if len(cells) != len(header):
            raise FoamFormatError(f"{path}: row has {len(cells)} cells for {len(header)} header names")
        row: dict[str, float] = {}
        prefix = ""
        for name, cell in zip(header, cells):
            if isinstance(cell, str):
                try:
                    float(cell)
                except ValueError:
                    prefix = f"{cell}/"
                    continue
            _flatten(name if name == "Time" else prefix + name, cell, row)
        rows.append(row)
    if not rows:
        raise FoamFormatError(f"{path}: empty table")
    names = sorted({k for r in rows for k in r} - {"Time"})
    cols: dict[str, np.ndarray] = {}
    for n in names:
        sel = [r for r in rows if n in r]
        cols[n] = np.array([[r["Time"], r[n]] for r in sel], dtype=float)
    return cols


def read_quantity(case: Path, name: str, column: str) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Concatenate a quantity column across restart segments: (times, values, available columns)."""
    root = Path(case) / "postProcessing" / name
    if not root.is_dir():
        raise FoamFormatError(f"no output for {name}")
    segs = []
    for folder in root.iterdir():
        try:
            start = float(folder.name)
        except ValueError:
            continue
        files = [f for f in folder.iterdir() if f.is_file()]
        if len(files) != 1:
            raise FoamFormatError(f"{folder}: expected exactly one output file, found {len(files)}")
        segs.append((start, read_quantity_table(files[0])))
    if not segs:
        raise FoamFormatError(f"no output for {name}")
    segs.sort(key=lambda s: s[0])
    available = sorted(segs[-1][1])
    if column not in segs[-1][1]:
        raise FoamFormatError(f"column {column!r} not in {available}")
    t = np.concatenate([s[1][column][:, 0] for s in segs if column in s[1]])
    v = np.concatenate([s[1][column][:, 1] for s in segs if column in s[1]])
    return t, v, available


def read_monitor(case: Path, name: str) -> list[tuple[float, np.ndarray, list[str]]]:
    """Return function-object segments (start time, table, header) in time order."""
    root = Path(case) / "postProcessing" / name
    segments = []
    if not root.is_dir():
        return segments
    for folder in root.iterdir():
        try:
            start = float(folder.name)
        except ValueError:
            continue
        files = sorted(folder.glob("*.dat"))
        if len(files) != 1:
            raise FoamFormatError(f"{folder}: expected exactly one .dat file")
        header, data = read_table(files[0])
        segments.append((start, data, header))
    segments.sort(key=lambda s: s[0])
    return segments


def time_dirs(case: Path) -> list[tuple[float, Path]]:
    out = []
    for p in Path(case).iterdir():
        if p.is_dir() and re.fullmatch(r"[0-9.eE+-]+", p.name):
            try:
                out.append((float(p.name), p))
            except ValueError:
                continue
    return sorted(out, key=lambda t: t[0])


def set_dict_entry(text: str, key: str, value: str) -> str:
    """Replace a top-level ``key value;`` entry, or append it, in a dictionary file."""
    pattern = re.compile(rf"(?m)^(\s*){re.escape(key)}\s+[^;{{}}]*;")
    if pattern.search(text):
        return pattern.sub(lambda m: f"{m.group(1)}{key} {value};", text, count=1)
    return text.rstrip() + f"\n{key} {value};\n"
