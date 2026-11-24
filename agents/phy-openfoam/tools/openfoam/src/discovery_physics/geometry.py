"""CAD -> ASCII STL conversion (runs inside the isolated image; gmsh + OpenCASCADE).

``python -m discovery_physics.geometry in.step out.stl [--mesh-size H]`` prints a JSON
report: bounding box, triangle count, closedness, and the source digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np


def _read_ascii_stl(path: Path) -> np.ndarray:
    pts = [list(map(float, ln.split()[1:4])) for ln in path.read_text(errors="replace").splitlines()
           if ln.strip().startswith("vertex")]
    return np.array(pts).reshape(-1, 3, 3)


def _closed(tris: np.ndarray) -> bool:
    edges: dict[tuple, int] = {}
    keys = np.round(tris, 9)
    for t in keys:
        for i in range(3):
            a, b = tuple(t[i]), tuple(t[(i + 1) % 3])
            e = (a, b) if a < b else (b, a)
            edges[e] = edges.get(e, 0) + 1
    return bool(edges) and all(c == 2 for c in edges.values())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("dest", type=Path)
    ap.add_argument("--mesh-size", type=float)
    a = ap.parse_args(argv)
    digest = hashlib.sha256(a.source.read_bytes()).hexdigest()
    import gmsh

    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Mesh.Binary", 0)
        gmsh.option.setNumber("Mesh.StlOneSolidPerSurface", 0)
        gmsh.model.add("geometry")
        if a.source.suffix.lower() == ".stl":
            gmsh.merge(str(a.source))
        else:
            gmsh.model.occ.importShapes(str(a.source))
            gmsh.model.occ.synchronize()
            if a.mesh_size:
                gmsh.option.setNumber("Mesh.MeshSizeMax", a.mesh_size)
            gmsh.model.mesh.generate(2)
        gmsh.write(str(a.dest))
    finally:
        gmsh.finalize()
    tris = _read_ascii_stl(a.dest)
    if tris.size == 0:
        print(json.dumps({"ok": False, "error": "no triangles produced"}))
        return 1
    flat = tris.reshape(-1, 3)
    print(json.dumps({"ok": True, "source_sha256": digest, "triangles": int(len(tris)),
                      "closed": _closed(tris), "bbox_min": flat.min(0).tolist(), "bbox_max": flat.max(0).tolist(),
                      "units_note": "CAD units are preserved; scale in snappyHexMeshDict/geometry if needed"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
