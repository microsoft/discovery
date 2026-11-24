"""Measure evidence from a finished OpenFOAM case. Runs inside the worker container.

Every metric records where it came from. A computation that cannot be completed
yields status "missing"/"invalid" (UNKNOWN to the checker), never a default pass.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from ..core.models import Diagnostics, Metric
from . import foamio

# Real fatal signatures. Foundation prints "sigFpe : Enabling floating point
# exception trapping (FOAM_SIGFPE).", at every start-up: that banner is NOT a fault.
# Signatures are case-sensitive so the banner's lower-case phrase cannot match.
FATAL = re.compile(
    r"FOAM FATAL (IO )?ERROR|Floating point exception \(core dumped\)|Segmentation fault|"
    r"Foam::sigFpe::sigHandler|Foam::sigSegv::sigHandler|^Killed\b|std::bad_alloc",
    re.M,
)
COURANT = re.compile(r"^Courant Number mean: (\S+) max: (\S+)", re.M)
TIME = re.compile(r"^Time = (\S+?)s?\s*$", re.M)


class Metrics:
    def __init__(self) -> None:
        self.values: dict[str, Metric] = {}
        self.errors: list[str] = []

    def put(self, name: str, value: Any, unit: str = "1", source: str = "derived") -> None:
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, float) and not math.isfinite(value):
            self.values[name] = Metric(value=None, unit=unit, source=source, status="invalid")
        else:
            self.values[name] = Metric(value=value, unit=unit, source=source)

    def missing(self, name: str, reason: str, unit: str = "1") -> None:
        self.values[name] = Metric(value=None, unit=unit, source=reason[:1000], status="missing")

    def guard(self, names: list[str], fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as exc:  # measurement failure must be visible, not fatal
            self.errors.append(f"{names[0].split('.')[0]}: {type(exc).__name__}: {exc}"[:500])
            for n in names:
                if n not in self.values:
                    self.missing(n, f"extraction failed: {type(exc).__name__}")


def _rel_span(a: np.ndarray) -> float:
    return float(np.ptp(a) / max(abs(float(np.mean(a))), 1e-300))


class CaseData:
    def __init__(self, case: Path, d: Diagnostics):
        self.case, self.d = case, d
        self.boundary = foamio.read_boundary(case / "constant/polyMesh")
        self.centres, _ = foamio.read_field(case / "0/C")
        self.n = len(self.centres)
        self.volumes, _ = foamio.read_field(case / "0/Vc", self.n)
        self.times = [(t, p) for t, p in foamio.time_dirs(case) if t > 0 or p.name != "0"]
        self._cache: dict[tuple[float, str], tuple[np.ndarray, dict[str, str]]] = {}

    def field(self, time_path: Path, name: str):
        key = (time_path.name, name)
        if key not in self._cache:
            self._cache[key] = foamio.read_field(time_path / name, self.n)
        return self._cache[key]

    def saved(self) -> list[tuple[float, Path]]:
        return [(t, p) for t, p in self.times if t > 0]

    def patch_faces(self, patch: str) -> np.ndarray:
        """Face area vectors of a patch (polygon cross-product formula)."""
        b = self.boundary[patch]
        mesh = self.case / "constant/polyMesh"
        if not hasattr(self, "_points"):
            text = foamio._strip((mesh / "points").read_text(encoding="utf-8"))
            count, body, _ = foamio._list_body(text, text.find("}") + 1)
            self._points = foamio._values(body, count, True)
            ftext = foamio._strip((mesh / "faces").read_text(encoding="utf-8"))
            _, fbody, _ = foamio._list_body(ftext, ftext.find("}") + 1)
            self._faces = [list(map(int, f.split())) for f in re.findall(r"\d+\(([^)]*)\)", fbody)]
        out = []
        for f in self._faces[b["startFace"]: b["startFace"] + b["nFaces"]]:
            p = self._points[f]
            out.append(0.5 * np.cross(p, np.roll(p, -1, axis=0)).sum(axis=0))
        return np.array(out).reshape(-1, 3)

    def patch_field(self, time_path: Path, name: str, patch: str) -> np.ndarray:
        """Face values; zeroGradient faces take owner-cell values."""
        values, blocks = self.field(time_path, name)
        block = blocks.get(patch)
        if block is None:
            raise foamio.FoamFormatError(f"{name}: no boundary entry for {patch}")
        nf = int(self.boundary[patch]["nFaces"])
        vector = values.ndim == 2
        v = foamio.patch_value(block, nf, vector)
        if v is not None:
            return v
        if re.search(r"\btype\s+zeroGradient\s*;", block):
            if not hasattr(self, "_owner"):
                self._owner = foamio.read_label_list(self.case / "constant/polyMesh/owner")
            s = int(self.boundary[patch]["startFace"])
            return values[self._owner[s: s + nf]]
        raise foamio.FoamFormatError(f"{name}/{patch}: unsupported boundary storage")


def _mesh(m: Metrics, case: Path, d: Diagnostics, mesh_ok_steps: bool) -> None:
    log = (case / "log.checkMesh").read_text(encoding="utf-8", errors="replace")
    cells = re.search(r"^\s*cells:\s+(\d+)", log, re.M)
    dirs = re.search(r"Mesh has (\d) solution \(non-empty\) directions", log)
    m.put("mesh.check_ok", "Mesh OK." in log and "***" not in log, source="log.checkMesh")
    m.put("mesh.stage_clean", mesh_ok_steps, source="worker command exit codes")
    if cells:
        m.put("mesh.cells", int(cells.group(1)), source="log.checkMesh")
        if d.expected_cells:
            m.put("mesh.cell_count_matches", int(cells.group(1)) == d.expected_cells, source="log.checkMesh")
    for key, pat in (("max_nonorthogonality", r"non-orthogonality Max:\s*(\S+)"),
                     ("max_skewness", r"Max skewness = (\S+)"),
                     ("max_aspect_ratio", r"Max aspect ratio = (\S+)")):
        x = re.search(pat, log)
        if x:
            m.put(f"mesh.{key}", float(x.group(1)), source="log.checkMesh")
    if dirs:
        m.put("mesh.solution_directions", int(dirs.group(1)), source="log.checkMesh")
        if d.dimensions:
            m.put("mesh.dimension_matches", int(dirs.group(1)) == d.dimensions, source="log.checkMesh")
    boundary = foamio.read_boundary(case / "constant/polyMesh")
    types = [b["type"] for b in boundary.values()]
    m.put("mesh.expected_patches_present", set(d.patches).issubset(boundary), source="polyMesh/boundary")
    m.put("mesh.cyclic_patch_count", sum(t.startswith("cyclic") for t in types), source="polyMesh/boundary")
    m.put("mesh.planar_patch_present", any(t in ("empty", "wedge") for t in types), source="polyMesh/boundary")


def _solver(m: Metrics, case: Path, d: Diagnostics, exit_code: int | None, requested_end: float) -> None:
    logs = sorted(case.glob("log.foamRun*"))
    if not logs:
        raise FileNotFoundError("no solver log")
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in logs)
    last = logs[-1].read_text(encoding="utf-8", errors="replace")
    times = [float(t) for t in TIME.findall(text)]
    final = max([t for t, _ in foamio.time_dirs(case)] + times[-1:]) if times else None
    hits = [ln.strip()[:200] for ln in text.splitlines() if FATAL.search(ln)]
    m.put("solver.exit_code", exit_code if exit_code is not None else -1, source="worker")
    m.put("solver.fatal_error", bool(hits), source="solver logs")
    m.put("solver.steps", len(times), source="solver logs")
    if final is None:
        m.missing("solver.final_time", "no time steps logged")
    else:
        tol = 1e-9 * max(1.0, abs(requested_end))
        # Steady (SIMPLE-type) runs stop early when residualControl is met; that is a normal finish.
        converged = bool(re.search(r"solution converged in \S+ iterations", last))
        m.put("solver.converged_by_residual_control", converged, source="solver logs")
        m.put("solver.final_time", final, source="solver logs and time directories")
        m.put("solver.requested_end_time", requested_end, source="controlDict")
        m.put("solver.reached_requested_end", final >= requested_end - tol or converged, source="solver logs")
        m.put("solver.reached_target_time", final >= d.target_time - 1e-9 * d.target_time or converged,
              source="solver logs")
        m.put("solver.completed", exit_code == 0 and bool(re.search(r"^End\s*$", last, re.M))
              and (final >= requested_end - tol or converged) and not hits, source="solver logs")
    co = [(float(a), float(b)) for a, b in COURANT.findall(text)]
    if co:
        mx = np.array([b for _, b in co])
        m.put("solver.courant_max", float(np.max(mx)) if np.isfinite(mx).all() else float("nan"))
        m.put("solver.courant_finite_positive", bool(np.isfinite(mx).all() and (mx > 0).all()))
    else:
        m.missing("solver.courant_max", "no Courant lines (solver may not report Courant number)")
        m.missing("solver.courant_finite_positive", "no Courant lines")
    _residuals(m, text)


RESIDUAL = re.compile(r"Solving for (\w+), Initial residual = ([^,\s]+)")
CONTINUITY = re.compile(r"time step continuity errors : sum local = ([^,\s]+)")


def _residuals(m: Metrics, text: str) -> None:
    """Per time step, the first initial residual of each solved field (outer-iteration start)."""
    marks = [x.start() for x in TIME.finditer(text)]
    steps: list[dict[str, float]] = []
    for a, b in zip(marks, marks[1:] + [len(text)]):
        first: dict[str, float] = {}
        for name, val in RESIDUAL.findall(text[a:b]):
            first.setdefault(name, float(val))
        if first:
            steps.append(first)
    if steps:
        last = steps[-1]
        m.put("solver.residual_initial_last_max", max(last.values()), source="solver logs (last step)")
        drops = [math.log10(max(steps[0][k], 1e-300) / max(v, 1e-300)) for k, v in last.items() if k in steps[0]]
        if drops:
            m.put("solver.residual_drop_orders_min", min(drops), source="solver logs (first vs last step)")
        else:
            m.missing("solver.residual_drop_orders_min", "no field solved in both first and last step")
    else:
        m.missing("solver.residual_initial_last_max", "solver prints no linear-solver residuals")
        m.missing("solver.residual_drop_orders_min", "solver prints no linear-solver residuals")
    cont = [float(x) for x in CONTINUITY.findall(text)]
    if cont:
        m.put("solver.continuity_local_last", cont[-1], source="solver logs")
        m.put("solver.continuity_local_max", max(cont), source="solver logs")
    else:
        m.missing("solver.continuity_local_last", "solver prints no continuity errors")
        m.missing("solver.continuity_local_max", "solver prints no continuity errors")


def _fields(m: Metrics, data: CaseData, d: Diagnostics) -> None:
    saved = data.saved()
    if not saved:
        raise ValueError("no saved solution times")
    finite, positive = True, True
    for _, path in saved:
        for f in d.fields:
            v, _ = data.field(path, f.name)
            finite &= bool(np.isfinite(v).all())
            if f.positive:
                positive &= bool((v > 0).all())
    m.put("fields.finite_all_saved", finite, source="saved fields")
    pos = [f for f in d.fields if f.positive]
    if pos:
        m.put("fields.positive_all_saved", positive, source="saved fields")
    final = saved[-1][1]
    for f in d.fields:
        v, _ = data.field(final, f.name)
        mag = np.linalg.norm(v, axis=1) if v.ndim == 2 else v
        m.put(f"fields.{f.name}.final_min", float(np.min(mag)), f.unit, "final saved field")
        m.put(f"fields.{f.name}.final_max", float(np.max(mag)), f.unit, "final saved field")
    segs = foamio.read_monitor(data.case, "extrema")
    if pos and segs:
        mins = np.vstack([s[1][:, 1:] for s in segs])
        m.put("fields.positive_every_step", bool(np.isfinite(mins).all() and (mins > 0).all()),
              source="per-step extrema monitor")
        m.put("fields.extrema_records", int(len(mins)), source="per-step extrema monitor")
    elif pos:
        m.missing("fields.positive_every_step", "no per-step extrema monitor output")


def _initial(m: Metrics, data: CaseData, d: Diagnostics) -> None:
    if not d.initial_values:
        return
    worst = 0.0
    for name, expected in d.initial_values.items():
        v, _ = foamio.read_field(data.case / "0" / name, data.n)
        e = np.asarray(expected, dtype=float)
        scale = max(float(np.linalg.norm(e)), 1e-300)
        diff = np.linalg.norm(v - e, axis=1) if v.ndim == 2 else np.abs(v - e)
        worst = max(worst, float(np.max(diff)) / scale)
    m.put("setup.initial_state_max_rel_error", worst, source="0/ fields")


def _inlet_mach(m: Metrics, data: CaseData, d: Diagnostics) -> None:
    if not (d.gas and d.inlet):
        return
    path = data.saved()[-1][1]
    u = data.patch_field(path, "U", d.inlet)
    t = data.patch_field(path, "T", d.inlet)
    mach = np.linalg.norm(u, axis=1) / np.sqrt(d.gas.gamma * d.gas.gas_constant * t)
    m.put("flow.inlet_mach_min", float(mach.min()), source=f"{d.inlet} face values")
    m.put("flow.inlet_mach_max", float(mach.max()), source=f"{d.inlet} face values")


def _flux_series(data: CaseData, patches: list[str]):
    """Return segments: list of (time, {patch: flux}) aligned per segment, or raise."""
    per = {p: foamio.read_monitor(data.case, f"flux_{p}") for p in patches}
    starts = {tuple(s[0] for s in segs) for segs in per.values()}
    if len(starts) != 1 or not next(iter(starts)):
        raise ValueError("flux monitors have inconsistent or missing segments")
    out = []
    for k in range(len(next(iter(per.values())))):
        t = per[patches[0]][k][1][:, 0]
        cols = {}
        for p in patches:
            arr = per[p][k][1]
            if arr.shape[0] != t.size or not np.allclose(arr[:, 0], t, rtol=1e-13, atol=1e-300):
                raise ValueError(f"flux monitor {p} time misaligned")
            cols[p] = arr[:, 1]
        out.append((t, cols))
    return out


def _conservation(m: Metrics, data: CaseData, d: Diagnostics) -> None:
    if not (d.inlet and d.outlet):
        return
    flowing = [p for p, b in data.boundary.items() if b["type"] != "empty"]
    undeclared = sorted(set(flowing) - set(d.patches))
    if undeclared:
        raise ValueError(f"patches not monitored, flux balance incomplete: {undeclared}")
    unknown = sorted(set(d.patches) - set(data.boundary))
    if unknown:
        raise ValueError(f"declared patches absent from the mesh: {unknown}")
    # Empty (2-D) patches carry no flux by construction and OpenFOAM writes no monitor for them.
    patches = [p for p in d.patches if data.boundary[p]["type"] != "empty"]
    d = d.model_copy(update={"patches": patches,
                             "impermeable_patches": [p for p in d.impermeable_patches if p in patches]})
    segs = _flux_series(data, d.patches)
    t_all = np.concatenate([s[0] for s in segs])
    fin = np.concatenate([s[1][d.inlet] for s in segs])
    fout = np.concatenate([s[1][d.outlet] for s in segs])
    net = np.concatenate([sum(s[1][p] for p in d.patches) for s in segs])
    scale = np.maximum(np.maximum(abs(fin), abs(fout)), 1e-300)
    m.put("conservation.final_inlet_flux", float(fin[-1]), source="phi monitor")
    m.put("conservation.final_outlet_flux", float(fout[-1]), source="phi monitor")
    m.put("conservation.final_net_flux_rel", float(abs(net[-1]) / scale[-1]), source="phi monitors")
    if d.impermeable_patches:
        wall = np.concatenate([sum(abs(s[1][p]) for p in d.impermeable_patches) for s in segs])
        m.put("conservation.impermeable_flux_max_rel", float(np.max(wall / scale)), source="phi monitors")
    if d.mass_balance:
        _mass_closure(m, data, d, segs)
    if d.stationarity_window:
        w = t_all >= t_all[-1] - d.stationarity_window
        m.put("stationarity.window_covered", bool(t_all[-1] - t_all[0] >= d.stationarity_window),
              source="phi monitors")
        m.put("stationarity.flux_mismatch_max", float(np.max(abs(fin[w] + fout[w]) / scale[w])),
              source="phi monitors (inflow negative)")
        drifts = [_rel_span(fin[w]), _rel_span(fout[w])]
        mass = foamio.read_monitor(data.case, "domain_mass")
        if mass:
            mt = np.concatenate([s[1][:, 0] for s in mass])
            mv = np.concatenate([s[1][:, 1] for s in mass])
            drifts.append(_rel_span(mv[mt >= mt[-1] - d.stationarity_window]))
        m.put("stationarity.monitor_drift_max", max(drifts), source="per-step monitors")


def _mass_closure(m: Metrics, data: CaseData, d: Diagnostics, segs) -> None:
    """Storage-aware closure r_n = (M_n - M_{n-1})/dt_n + Phi_n, per restart segment only.

    Restart seams are not differenced; instead each seam must reproduce the stored
    mass of the checkpoint it continued from, or the run is discontinuous.
    """
    mass = foamio.read_monitor(data.case, "domain_mass")
    if len(mass) != len(segs):
        raise ValueError("mass and flux monitors have different restart segments")
    worst, records, seams_ok = 0.0, 0, True
    prev_last: tuple[float, float] | None = None
    for (start, arr, _), (t, cols) in zip(mass, segs):
        if arr.shape[0] != t.size or not np.allclose(arr[:, 0], t, rtol=1e-13, atol=1e-300):
            raise ValueError("mass/flux time misaligned")
        if arr.shape[0] < 3:
            raise ValueError("too few mass records in a segment")
        tm, mv = arr[:, 0], arr[:, 1]
        dt = np.diff(tm)
        if (dt <= 0).any() or not np.isfinite(mv).all():
            raise ValueError("non-monotonic or non-finite mass history")
        net = sum(cols[p] for p in d.patches)
        scale = np.maximum(np.maximum(abs(cols[d.inlet]), abs(cols[d.outlet])), 1e-300)
        r = (np.diff(mv) / dt + net[1:]) / scale[1:]
        worst = max(worst, float(np.max(abs(r))))
        records += r.size
        if prev_last is not None:
            same_time = abs(tm[0] - prev_last[0]) <= 1e-12 * max(1.0, abs(tm[0]))
            same_mass = abs(mv[0] - prev_last[1]) <= 1e-9 * abs(prev_last[1])
            seams_ok &= bool(same_time and same_mass)
        prev_last = (float(tm[-1]), float(mv[-1]))
    m.put("conservation.mass_closure_max_rel", worst, source="domain mass + phi monitors")
    m.put("conservation.restart_seams_continuous", seams_ok, source="segment boundary records")
    m.put("conservation.restart_segments", len(segs), source="postProcessing")
    m.put("conservation.mass_closure_records", records, source="postProcessing")


def _field_change(m: Metrics, data: CaseData, d: Diagnostics) -> None:
    if not d.stationarity_window:
        return
    saved = data.saved()
    t_end = saved[-1][0]
    ref = [s for s in saved if s[0] <= t_end - d.stationarity_window + 1e-12 * t_end]
    if not ref:
        m.missing("stationarity.field_change_max", "no saved state at window start")
        return
    a, b = ref[-1][1], saved[-1][1]
    worst = 0.0
    for f in d.fields:
        f0, _ = data.field(a, f.name)
        f1, _ = data.field(b, f.name)
        diff = np.sum((f1 - f0) ** 2, axis=1) if f1.ndim == 2 else (f1 - f0) ** 2
        mag = np.sum(f1 ** 2, axis=1) if f1.ndim == 2 else f1 ** 2
        worst = max(worst, float(np.sqrt(np.sum(data.volumes * diff) / np.sum(data.volumes * mag))))
    m.put("stationarity.field_change_max", worst, source=f"saved fields {a.name}->{b.name}")


def _compression(m: Metrics, data: CaseData, d: Diagnostics) -> None:
    c = d.compression
    if c is None:
        return
    path = data.saved()[-1][1]
    x, y = data.centres[:, c.axis], data.centres[:, c.transverse_axis]
    band = (y < c.transverse_max) & (x >= c.x_min) & (x < c.x_max)
    cols = np.round(x[band], 9)
    xs = np.unique(cols)
    prof = {}
    for name in ("p", "rho", "T"):
        v, _ = data.field(path, name)
        vb, wb = v[band], data.volumes[band]
        prof[name] = np.array([np.average(vb[cols == u], weights=wb[cols == u]) for u in xs])
    i = int(np.argmax(np.diff(prof["p"])))  # steepest rise lies between columns i and i+1
    up, down = i - 2, i + 3
    measurable = up >= 0 and down < xs.size and prof["p"][down] > prof["p"][up]
    m.put("compression.front_measurable", bool(measurable), source="final saved fields")
    if measurable:
        m.put("compression.front_x", float(0.5 * (xs[i] + xs[i + 1])), source="final saved fields")
        for name in ("p", "rho", "T"):
            m.put(f"compression.{name}_ratio", float(prof[name][down] / prof[name][up]),
                  source="column averages two cells upstream/three downstream of steepest rise")
    else:
        for name in ("p", "rho", "T"):
            m.missing(f"compression.{name}_ratio", "no resolvable upstream state ahead of the front")


def _nozzle(m: Metrics, data: CaseData, d: Diagnostics) -> None:
    nz, gas = d.nozzle, d.gas
    if nz is None or gas is None or not (d.inlet and d.outlet):
        return
    from ..benchmarks.quasi1d import Nozzle1D

    g, R = gas.gamma, gas.gas_constant
    cp = g * R / (g - 1)
    theory = Nozzle1D(nz.throat_radius, nz.total_pressure, nz.total_temperature, g, R)
    full = 2 * math.pi / math.sin(math.radians(nz.wedge_degrees))
    saved = data.saved()
    path = saved[-1][1]
    T, U, p, rho = (data.field(path, k)[0] for k in ("T", "U", "p", "rho"))
    speed = np.linalg.norm(U, axis=1)
    mach = speed / np.sqrt(g * R * T)
    x = data.centres[:, 0]
    throat = (x > nz.throat_x_min) & (x < nz.throat_x_max)
    m.put("nozzle.throat_mach", float(np.average(mach[throat], weights=data.volumes[throat])))
    h0 = 0.0
    for _, sp in saved:
        Ts, Us = data.field(sp, "T")[0], data.field(sp, "U")[0]
        h0 = max(h0, float(np.max(abs((cp * Ts + 0.5 * np.sum(Us * Us, axis=1)) / (cp * nz.total_temperature) - 1))))
    m.put("nozzle.stagnation_enthalpy_max_rel", h0, source="all saved fields")
    face = {}
    for patch in (d.inlet, d.outlet):
        sf = data.patch_faces(patch)
        area = np.linalg.norm(sf, axis=1)
        pv, tv, uv, rv = (data.patch_field(path, k, patch) for k in ("p", "T", "U", "rho"))
        un = np.sum(uv * sf, axis=1) / area
        a = np.sqrt(g * R * tv)
        bm = np.linalg.norm(uv, axis=1) / a
        face[patch] = dict(area=area, p=pv, T=tv, U=uv, un=un, a=a, M=bm,
                           mdot=float(np.sum(rv * un * area)))
    o, i = face[d.outlet], face[d.inlet]
    avg = lambda arr, f: float(np.average(arr, weights=f["area"]))  # noqa: E731
    exit_state = dict(mach=avg(o["M"], o), p=avg(o["p"], o), T=avg(o["T"], o),
                      U=avg(np.linalg.norm(o["U"], axis=1), o))
    m.put("nozzle.outlet_normal_mach_min", float(np.min(o["un"] / o["a"])), source="outlet faces")
    m.put("nozzle.inlet_mach_max", float(np.max(i["M"])), source="inlet faces")
    m.put("nozzle.inlet_inflow", bool(np.max(i["un"]) < 0), source="inlet faces (outward normal)")
    k = (g - 1) / 2
    m.put("nozzle.inlet_p0_rel_error_max",
          float(np.max(abs(i["p"] * (1 + k * i["M"] ** 2) ** (g / (g - 1)) / nz.total_pressure - 1))))
    m.put("nozzle.inlet_T0_rel_error_max",
          float(np.max(abs(i["T"] * (1 + k * i["M"] ** 2) / nz.total_temperature - 1))))
    segs = _flux_series(data, [d.inlet, d.outlet])
    phi_out = float(segs[-1][1][d.outlet][-1])
    phi_in = float(segs[-1][1][d.inlet][-1])
    m.put("nozzle.flux_consistency_rel", max(abs(o["mdot"] / phi_out - 1), abs(i["mdot"] / phi_in - 1)),
          source="face rho U.S versus solver phi")
    pe, te, ue, me = theory.state(nz.exit_radius, supersonic=True)
    md = theory.choked_mass_flow()
    errs = {"exit_mach": exit_state["mach"] / me - 1, "exit_p": exit_state["p"] / pe - 1,
            "exit_T": exit_state["T"] / te - 1, "exit_U": exit_state["U"] / ue - 1,
            "mass_flow": phi_out * full / md - 1}
    for key, val in exit_state.items():
        m.put(f"nozzle.exit_{key}", val, {"mach": "1", "p": "Pa", "T": "K", "U": "m/s"}[key],
              "outlet area average")
    m.put("nozzle.mass_flow", phi_out * full, "kg/s", "outlet phi scaled to full nozzle")
    for key, val in errs.items():
        m.put(f"nozzle.err_{key}_pct", 100 * val, "%", "versus isentropic quasi-1D theory")
    m.put("nozzle.err_exit_p_abs_pct", abs(100 * errs["exit_p"]), "%")
    m.put("nozzle.err_other_max_abs_pct", max(abs(100 * v) for k2, v in errs.items() if k2 != "exit_p"), "%")
    if d.stationarity_window:
        t_end = saved[-1][0]
        window = [(t, sp) for t, sp in saved if t >= t_end - d.stationarity_window - 1e-12 * t_end]
        series: dict[str, list[float]] = {k: [] for k in ("exit_p", "exit_T", "exit_U", "exit_M", "throat_M")}
        osf = data.patch_faces(d.outlet)
        oarea = np.linalg.norm(osf, axis=1)
        for _, sp in window:
            pv, tv, uv = (data.patch_field(sp, k, d.outlet) for k in ("p", "T", "U"))
            series["exit_p"].append(float(np.average(pv, weights=oarea)))
            series["exit_T"].append(float(np.average(tv, weights=oarea)))
            series["exit_U"].append(float(np.average(np.linalg.norm(uv, axis=1), weights=oarea)))
            series["exit_M"].append(float(np.average(np.linalg.norm(uv, axis=1) / np.sqrt(g * R * tv),
                                                     weights=oarea)))
            Tw, Uw = data.field(sp, "T")[0], data.field(sp, "U")[0]
            mw = np.linalg.norm(Uw, axis=1) / np.sqrt(g * R * Tw)
            series["throat_M"].append(float(np.average(mw[throat], weights=data.volumes[throat])))
        if len(window) >= 2:
            m.put("nozzle.monitor_drift_max", max(_rel_span(np.array(v)) for v in series.values()),
                  source=f"{len(window)} saved states in window")
        else:
            m.missing("nozzle.monitor_drift_max", "fewer than two saved states in window")
    # Radially volume-weighted slab Mach downstream of the throat screens for internal shocks.
    screen = nz.throat_x_max + (nz.throat_x_max - nz.throat_x_min)
    xs = np.round(x, 9)
    down = np.unique(xs[xs > screen])
    slabs = [np.average(mach[xs == u], weights=data.volumes[xs == u]) for u in down]
    if slabs:
        m.put("nozzle.downstream_min_slab_mach", float(min(slabs)), source="final fields")


def _quantities(m: Metrics, data: CaseData, d: Diagnostics) -> None:
    for q in d.quantities:
        name = f"quantity.{q.name}"

        def one(q=q, name=name):
            t, v, _ = foamio.read_quantity(data.case, f"q_{q.name}", q.column)
            if q.statistic == "last":
                m.put(name, float(v[-1]), q.unit, f"function object q_{q.name}")
            else:
                if not d.stationarity_window:
                    raise ValueError("window statistic requires stationarity_window")
                w = t >= t[-1] - d.stationarity_window
                val = float(np.mean(v[w])) if q.statistic == "window_mean" else _rel_span(v[w])
                m.put(name, val, q.unit if q.statistic == "window_mean" else "1",
                      f"function object q_{q.name}")

        m.guard([name], one)


def extract(case: Path, d: Diagnostics, exit_code: int | None, requested_end: float,
            mesh_ok_steps: bool) -> Metrics:
    m = Metrics()
    m.guard(["mesh.check_ok"], lambda: _mesh(m, case, d, mesh_ok_steps))
    m.guard(["solver.completed", "solver.fatal_error"], lambda: _solver(m, case, d, exit_code, requested_end))
    try:
        data = CaseData(case, d)
    except Exception as exc:
        m.errors.append(f"case data unreadable: {exc}"[:500])
        return m
    m.guard(["fields.finite_all_saved", "fields.positive_all_saved"], lambda: _fields(m, data, d))
    m.guard(["setup.initial_state_max_rel_error"], lambda: _initial(m, data, d))
    m.guard(["flow.inlet_mach_min"], lambda: _inlet_mach(m, data, d))
    m.guard(["conservation.final_net_flux_rel", "conservation.mass_closure_max_rel",
             "conservation.restart_seams_continuous", "conservation.impermeable_flux_max_rel",
             "stationarity.flux_mismatch_max", "stationarity.monitor_drift_max"],
            lambda: _conservation(m, data, d))
    m.guard(["stationarity.field_change_max"], lambda: _field_change(m, data, d))
    m.guard(["compression.front_measurable"], lambda: _compression(m, data, d))
    m.guard(["nozzle.throat_mach"], lambda: _nozzle(m, data, d))
    _quantities(m, data, d)
    return m
