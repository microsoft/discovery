"""Pre-run cost estimate from the case files (no solver). Crude by design; reported with its basis."""

from __future__ import annotations

import re

# Serial seconds per cell-step, calibrated on the forward-step benchmark (rhoCentral-type
# shockFluid, 16,128 cells) on the reference workstation. Pressure-based solvers with
# several linear solves per step can be several times slower; the estimate states that.
SECONDS_PER_CELL_STEP = 6.0e-6
_HEX = re.compile(r"hex\s*\(([\d\s]+)\)\s*(?:[A-Za-z_]\w*\s*)?\(\s*(\d+)\s+(\d+)\s+(\d+)\s*\)")


def _num(control: str, key: str) -> float | None:
    m = re.search(rf"(?m)^\s*{key}\s+([-+0-9.eE]+)\s*;", control)
    return float(m.group(1)) if m else None


def block_cells(block_mesh: str) -> int | None:
    blocks = _HEX.findall(block_mesh)
    if not blocks or "$" in block_mesh.split("blocks", 1)[-1].split(");", 1)[0]:
        return None
    return sum(int(a) * int(b) * int(c) for _, a, b, c in blocks)


def estimate(files: dict[str, str], mesh_commands: list[str], ranks: int, wall_budget: float,
             calibration: float = SECONDS_PER_CELL_STEP) -> dict:
    out: dict = {"cells": None, "steps": None, "wall_s": None, "basis": []}
    bm = files.get("system/blockMeshDict")
    if bm and "snappyHexMesh" not in mesh_commands:
        out["cells"] = block_cells(bm)
        out["basis"].append("cells from blockMeshDict block counts" if out["cells"] else
                            "blockMeshDict uses variables; cell count unknown before meshing")
    else:
        out["basis"].append("cell count known only after meshing (snappyHexMesh or no blockMeshDict)")
    control = files["system/controlDict"]
    adjustable = re.search(r"(?m)^\s*adjustTimeStep\s+(yes|on|true)\s*;", control)
    dt, t0, t1 = _num(control, "deltaT"), _num(control, "startTime") or 0.0, _num(control, "endTime")
    if dt and t1 is not None and not adjustable and dt > 0:
        out["steps"] = int(round((t1 - t0) / dt))
        out["basis"].append("steps from fixed deltaT")
    else:
        out["basis"].append("adaptive time step; step count unknown before running")
    if out["cells"] and out["steps"]:
        out["wall_s"] = round(out["cells"] * out["steps"] * calibration / max(1, ranks) ** 0.8, 1)
        out["basis"].append(f"{calibration:g} s per cell-step (serial calibration), uncertain by ~3x")
        out["exceeds_budget"] = out["wall_s"] > wall_budget
    return out
