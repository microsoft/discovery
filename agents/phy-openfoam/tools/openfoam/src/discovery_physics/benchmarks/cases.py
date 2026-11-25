"""Benchmark profiles reconstructed from the CFD Forge paper's published specifications.

These are *independent* case generators for comparison only. Production use is
free-form: CLIO authors cases and contracts for any request.
"""

from __future__ import annotations

import math
from typing import Any

from ..core.hashing import sha256_text

R_UNIVERSAL = 8314.46261815324


def _chk(cid, metric, op, threshold=None, *, unit="1", category, rationale, failure="hard"):
    return {"id": cid, "metric": metric, "operator": op, "threshold": threshold, "unit": unit,
            "category": category, "rationale": rationale, "failure": failure}


def _header(obj: str, cls: str = "dictionary") -> str:
    return f"FoamFile\n{{\n    format ascii;\n    class {cls};\n    object {obj};\n}}\n\n"


# ---------------------------------------------------------------- forward step
def forward_step_bundle(tutorial_files: dict[str, str], *, mach: float = 2.0, step_height: float = 0.2,
                        step_x: float = 0.6, end_time: float = 4.0, target_time: float = 4.0,
                        refinement: int = 1, nx: int = 240, ny: int = 80, sensitivity_request: bool = False,
                        prompt: str | None = None, name: str | None = None) -> dict[str, Any]:
    """Mach-number flow over a 2-D forward step; recipe copied unchanged from the Foundation tutorial."""
    nx, ny = nx * refinement, ny * refinement
    a, b = round(nx * step_x / 3.0), round(ny * step_height / 1.0)
    if not (1 <= a < nx and 1 <= b < ny):
        raise ValueError("step must leave cells on both sides")
    cells = a * ny + (nx - a) * (ny - b)
    recipe = ["system/fvSchemes", "system/fvSolution", "constant/physicalProperties", "constant/momentumTransport"]
    files = {k: tutorial_files[k] for k in recipe}
    xs, h = step_x, step_height
    files["system/blockMeshDict"] = _header("blockMeshDict") + f"""vertices
(
    (0 0 -0.05) ({xs} 0 -0.05) (0 {h} -0.05) ({xs} {h} -0.05) (3 {h} -0.05) (0 1 -0.05) ({xs} 1 -0.05) (3 1 -0.05)
    (0 0 0.05) ({xs} 0 0.05) (0 {h} 0.05) ({xs} {h} 0.05) (3 {h} 0.05) (0 1 0.05) ({xs} 1 0.05) (3 1 0.05)
);
blocks
(
    hex (0 1 3 2 8 9 11 10) ({a} {b} 1) simpleGrading (1 1 1)
    hex (2 3 6 5 10 11 14 13) ({a} {ny - b} 1) simpleGrading (1 1 1)
    hex (3 4 7 6 11 12 15 14) ({nx - a} {ny - b} 1) simpleGrading (1 1 1)
);
defaultPatch {{ type empty; }}
boundary
(
    inlet {{ type patch; faces ((0 8 10 2) (2 10 13 5)); }}
    outlet {{ type patch; faces ((4 7 15 12)); }}
    bottom {{ type symmetryPlane; faces ((0 1 9 8)); }}
    top {{ type symmetryPlane; faces ((5 13 14 6) (6 14 15 7)); }}
    obstacle {{ type patch; faces ((1 3 11 9) (3 4 12 11)); }}
);
"""
    u = mach * math.sqrt(1.0)  # normalized gas: sound speed 1 at T = 1 (gamma 7/5)
    vec = f"({u!r} 0 0)"
    bc = {
        "U": ("volVectorField", "velocity", vec, f"type fixedValue; value uniform {vec};",
              f"type inletOutlet; inletValue uniform {vec};", "type slip;"),
        "p": ("volScalarField", "pressure", "1", "type fixedValue; value uniform 1;", "type zeroGradient;",
              "type zeroGradient;"),
        "T": ("volScalarField", "temperature", "1", "type fixedValue; value uniform 1;",
              "type inletOutlet; inletValue uniform 1;", "type zeroGradient;"),
    }
    for f, (cls, dim, init, inlet, outlet, obstacle) in bc.items():
        files[f"0/{f}"] = _header(f, cls) + (
            f"dimensions [{dim}];\ninternalField uniform {init};\nboundaryField\n{{\n"
            f"    inlet {{ {inlet} }}\n    outlet {{ {outlet} }}\n    bottom {{ type symmetryPlane; }}\n"
            f"    top {{ type symmetryPlane; }}\n    obstacle {{ {obstacle} }}\n"
            f"    defaultFaces {{ type empty; }}\n}}\n")
    files["system/controlDict"] = _header("controlDict") + (
        f"solver shockFluid;\nstartFrom startTime;\nstartTime 0;\nstopAt endTime;\nendTime {end_time!r};\n"
        "deltaT 0.002;\nwriteControl adjustableRunTime;\nwriteInterval 0.1;\npurgeWrite 0;\n"
        "writeFormat ascii;\nwritePrecision 6;\nwriteCompression off;\ntimeFormat general;\n"
        "timePrecision 6;\nrunTimeModifiable true;\nadjustTimeStep yes;\nmaxCo 0.2;\nmaxDeltaT 1;\n")
    checks = [
        _chk("solver_completed", "solver.completed", "true", category="execution",
             rationale="The solver must exit normally at the execution horizon it was asked to reach."),
        _chk("no_fatal_error", "solver.fatal_error", "eq", False, category="execution",
             rationale="Genuine fatal signatures only; the FOAM_SIGFPE start-up banner is excluded."),
        _chk("mesh_ok", "mesh.check_ok", "true", category="mesh", rationale="checkMesh must report Mesh OK."),
        _chk("two_solution_directions", "mesh.dimension_matches", "true", category="mesh",
             rationale="The family is planar: exactly two solution directions."),
        _chk("mesh_stage_clean", "mesh.stage_clean", "true", category="mesh",
             rationale="Every meshing command must exit cleanly."),
        _chk("cell_count_matches_spec", "mesh.cell_count_matches", "true", category="mesh",
             rationale="Realized cells must equal the specified block layout."),
        _chk("expected_boundaries_present", "mesh.expected_patches_present", "true", category="boundary",
             rationale="Inlet, outlet, symmetry planes, and obstacle must exist."),
        _chk("no_cyclic_patches", "mesh.cyclic_patch_count", "eq", 0, category="boundary",
             rationale="A cyclic patch would change the planar problem."),
        _chk("planar_empty_patch", "mesh.planar_patch_present", "true", category="boundary",
             rationale="The spanwise direction must be empty."),
        _chk("fixed_recipe_unchanged", "setup.reference_files_match", "true", category="setup",
             rationale="Schemes, solution controls, and thermophysics equal the Foundation tutorial recipe."),
        _chk("case_unchanged_after_freeze", "setup.case_hash_matches", "true", category="setup",
             rationale="The executed case equals the case frozen before execution."),
        _chk("finite_all_saved", "fields.finite_all_saved", "true", category="admissibility",
             rationale="Saved fields must contain no NaN or Inf."),
        _chk("positive_all_saved", "fields.positive_all_saved", "true", category="admissibility",
             rationale="Pressure, temperature, and density must be positive in saved states."),
        _chk("positive_every_step", "fields.positive_every_step", "true", category="admissibility",
             rationale="Positivity must also hold at every intermediate step."),
        _chk("courant_finite_positive", "solver.courant_finite_positive", "true", category="execution",
             rationale="The Courant history must be finite and positive."),
        _chk("supersonic_inlet", "flow.inlet_mach_min", "gt", 1.0, category="setup",
             rationale="The registered problem is supersonic inflow."),
        _chk("initial_state_as_specified", "setup.initial_state_max_rel_error", "lt", 1e-9, category="setup",
             rationale="The imposed initial state must equal the specification to round-off."),
        _chk("impermeable_walls", "conservation.impermeable_flux_max_rel", "lt", 1e-10,
             category="conservation", rationale="Solid and symmetry boundaries pass no mass (floating-point scale)."),
        _chk("transient_mass_closure", "conservation.mass_closure_max_rel", "lt", 1e-6, category="conservation",
             rationale="Storage-aware discrete balance closes to round-off for this explicit update."),
        _chk("restart_seams_continuous", "conservation.restart_seams_continuous", "true",
             category="conservation", rationale="Each restart must continue the stored checkpoint mass."),
        _chk("compression_front_measurable", "compression.front_measurable", "true", category="admissibility",
             rationale="A compression front must exist ahead of the step with a resolvable upstream state."),
        _chk("p_rises_across_front", "compression.p_ratio", "gt", 1.0, category="admissibility",
             rationale="Direction-of-change test only; no magnitude is required."),
        _chk("rho_rises_across_front", "compression.rho_ratio", "gt", 1.0, category="admissibility",
             rationale="Direction-of-change test only."),
        _chk("T_rises_across_front", "compression.T_ratio", "gt", 1.0, category="admissibility",
             rationale="Direction-of-change test only."),
        _chk("registered_horizon_reached", "solver.reached_target_time", "true", category="horizon",
             failure="incomplete", rationale="The family's reference horizon t = 4 must be reached."),
    ]
    ids = [c["id"] for c in checks]
    objectives = [{"id": "healthy_transient_solution", "claim": "numerical_health",
                   "description": "Healthy, conservative transient solution at the registered horizon.",
                   "check_ids": ids}]
    if sensitivity_request:
        objectives.append({"id": "mesh_sensitivity", "claim": "mesh_independence", "check_ids": [],
                           "description": "Determine whether the result depends on the mesh."})
    req = prompt or (f"Simulate a 2D forward-facing step with inlet Mach number {mach}, step height "
                     f"{step_height} channel heights, step location x = {step_x}. Determine whether the "
                     "final result passes deterministic scientific validation.")
    return {
        "name": name or f"step_M{mach:g}_h{step_height:g}_x{step_x:g}".replace(".", "p"),
        "solver": "shockFluid", "files": files, "mesh": [{"executable": "blockMesh", "args": []}],
        "diagnostics": {
            "fields": [{"name": "p", "positive": True}, {"name": "T", "positive": True},
                       {"name": "rho", "positive": True}, {"name": "U", "components": 3}],
            "initial_values": {"p": 1.0, "T": 1.0, "U": [u, 0.0, 0.0]},
            "reference_hashes": {k: sha256_text(files[k]) for k in recipe},
            "patches": ["inlet", "outlet", "bottom", "top", "obstacle"], "inlet": "inlet", "outlet": "outlet",
            "impermeable_patches": ["bottom", "top", "obstacle"], "expected_cells": cells, "dimensions": 2,
            "gas": {"gas_constant": R_UNIVERSAL / 11640.3, "gamma": 2.5 / (2.5 - R_UNIVERSAL / 11640.3)},
            "target_time": target_time, "mass_balance": True, "normalized": True,
            "compression": {"axis": 0, "transverse_axis": 1, "transverse_max": step_height, "x_min": 0.0,
                            "x_max": step_x},
        },
        "contract": {
            "id": "forward_step_2d_benchmark", "title": f"2-D forward step, Mach {mach}, h = {h}, x = {xs}",
            "requested_prompt": req, "regime": "transient", "objectives": objectives, "checks": checks,
            "authority": "reviewed_benchmark",
            "assumptions": [{"parameter": "gas", "value": "normalized perfect gas, gamma 7/5", "unit": "1",
                             "source": "documented_default", "justification": "Foundation forwardStep tutorial"}],
            "limitations": ["Normalized (dimensionless) quantities; no SI units implied.",
                            "Single-mesh verification; no mesh-independence or experimental validation claim.",
                            "Compression checks are directional, not a reference-field comparison."],
        },
        "budget": {"max_attempts": 4, "wall_seconds": 3600, "cpus": 1, "memory_mb": 4096,
                   "max_cells": 200000, "max_end_time": target_time},
    }


# ---------------------------------------------------------------- nozzle
def nozzle_bundle(*, throat_radius: float = 0.0326, exit_radius: float = 0.0354, inlet_radius: float = 0.05,
                  total_pressure: float = 200000.0, total_temperature: float = 300.0,
                  ambient_pressure: float = 30000.0, end_time: float = 0.006, target_time: float = 0.006,
                  scale: int = 1, prompt: str | None = None, name: str | None = None) -> dict[str, Any]:
    from .quasi1d import Nozzle1D

    g, R = 1.4, 287.0
    xs = [0.0, 0.05, 0.15, 0.16, 0.28, 0.33]
    rs = [inlet_radius, inlet_radius, throat_radius, throat_radius, exit_radius, exit_radius]
    nax = [n * scale for n in (20, 40, 4, 48, 20)]
    nr = 16 * scale
    half = math.radians(2.5)
    verts, blocks, front, back, wall = [], [], [], [], []
    for x, r in zip(xs, rs):
        verts += [(x, 0.0, 0.0), (x, r * math.cos(half), -r * math.sin(half)),
                  (x, r * math.cos(half), r * math.sin(half))]
    for i, n in enumerate(nax):
        b, c = 3 * i, 3 * i + 3
        blocks.append(f"hex ({b} {c} {c+1} {b+1} {b} {c} {c+2} {b+2}) ({n} {nr} 1) simpleGrading (1 1 1)")
        front.append(f"({b} {b+1} {c+1} {c})")
        back.append(f"({b} {c} {c+2} {b+2})")
        wall.append(f"({b+1} {b+2} {c+2} {c+1})")
    last = 3 * (len(xs) - 1)
    files: dict[str, str] = {}
    files["system/blockMeshDict"] = _header("blockMeshDict") + (
        "vertices\n(\n" + "\n".join(f"    ({x!r} {y!r} {z!r})" for x, y, z in verts) + "\n);\n"
        "blocks\n(\n" + "\n".join(f"    {b}" for b in blocks) + "\n);\n"
        "defaultPatch { name axis; type empty; }\nboundary\n(\n"
        "    inlet { type patch; faces ((0 2 1 0)); }\n"
        f"    outlet {{ type patch; faces (({last} {last+1} {last+2} {last})); }}\n"
        f"    walls {{ type wall; faces ({' '.join(wall)}); }}\n"
        f"    wedgeFront {{ type wedge; faces ({' '.join(front)}); }}\n"
        f"    wedgeBack {{ type wedge; faces ({' '.join(back)}); }}\n);\n")
    mw = R_UNIVERSAL / R
    files["constant/physicalProperties"] = _header("physicalProperties") + (
        "thermoType\n{\n    type hePsiThermo;\n    mixture pureMixture;\n    transport const;\n"
        "    thermo eConst;\n    equationOfState perfectGas;\n    specie specie;\n"
        "    energy sensibleInternalEnergy;\n}\n"
        f"mixture\n{{\n    specie {{ molWeight {mw!r}; }}\n    thermodynamics {{ Cv {R / (g - 1)!r}; Hf 0; }}\n"
        "    transport { mu 0; Pr 1; }\n}\n")
    files["constant/momentumTransport"] = _header("momentumTransport") + "simulationType laminar;\n"
    files["system/fvSchemes"] = _header("fvSchemes") + (
        "fluxScheme Kurganov;\nddtSchemes { default Euler; }\ngradSchemes { default Gauss linear; }\n"
        "divSchemes { default none; }\nlaplacianSchemes { default Gauss linear corrected; }\n"
        "interpolationSchemes\n{\n    default linear;\n    reconstruct(rho) Minmod;\n"
        "    reconstruct(U) Minmod;\n    reconstruct(T) Minmod;\n}\nsnGradSchemes { default corrected; }\n")
    files["system/fvSolution"] = _header("fvSolution") + (
        "solvers\n{\n    \"rho.*\" { solver diagonal; }\n    \"(U|e).*\" { solver diagonal; }\n}\n"
        "PIMPLE { nOuterCorrectors 1; }\n")
    q = Nozzle1D(throat_radius, total_pressure, total_temperature, g, R)
    # Quasi-1-D initial state per axial cell column (subsonic upstream of the throat end).
    edges = []
    for j, n in enumerate(nax):
        edges += [xs[j] + (xs[j + 1] - xs[j]) * (k + 0.5) / n for k in range(n)]

    def radius(x: float) -> float:
        for j in range(len(xs) - 1):
            if xs[j] <= x <= xs[j + 1]:
                return rs[j] + (rs[j + 1] - rs[j]) * (x - xs[j]) / (xs[j + 1] - xs[j])
        return rs[-1]

    col = [q.state(max(radius(x), throat_radius), supersonic=x > xs[3]) for x in edges]
    order = []  # blockMesh cell order: block by block, axial fastest, then radial
    start = 0
    for n in nax:
        for _ in range(nr):
            order += list(range(start, start + n))
        start += n
    pin, tin, uin, _ = q.state(inlet_radius, supersonic=False)
    init = {"p": [col[i][0] for i in order], "T": [col[i][1] for i in order],
            "U": [(col[i][2], 0.0, 0.0) for i in order]}

    def lst(vals, vector=False):
        body = "\n".join(f"({a!r} {b!r} {c!r})" for a, b, c in vals) if vector else "\n".join(repr(v) for v in vals)
        kind = "vector" if vector else "scalar"
        return f"nonuniform List<{kind}>\n{len(vals)}\n(\n{body}\n)"

    inlet_bc = {
        "p": f"type totalPressure; p0 uniform {total_pressure!r}; psi psi; gamma {g}; value uniform {pin!r};",
        "T": f"type totalTemperature; T0 uniform {total_temperature!r}; psi psi; gamma {g}; value uniform {tin!r};",
        "U": "type directionMixed; refValue uniform (0 0 0); refGradient uniform (0 0 0); "
             "valueFraction uniform (0 0 0 1 0 1);",
    }
    for f, (cls, dim) in {"p": ("volScalarField", "pressure"), "T": ("volScalarField", "temperature"),
                          "U": ("volVectorField", "velocity")}.items():
        wall_bc = "slip" if f == "U" else "zeroGradient"
        files[f"0/{f}"] = _header(f, cls) + (
            f"dimensions [{dim}];\ninternalField {lst(init[f], f == 'U')};\nboundaryField\n{{\n"
            f"    inlet {{ {inlet_bc[f]} }}\n    outlet {{ type zeroGradient; }}\n    walls {{ type {wall_bc}; }}\n"
            "    wedgeFront { type wedge; }\n    wedgeBack { type wedge; }\n    axis { type empty; }\n}\n")
    files["system/controlDict"] = _header("controlDict") + (
        f"solver shockFluid;\nstartFrom startTime;\nstartTime 0;\nstopAt endTime;\nendTime {end_time!r};\n"
        "deltaT 1e-08;\nadjustTimeStep yes;\nmaxCo 0.4;\nmaxDeltaT 2e-06;\nwriteControl adjustableRunTime;\n"
        "writeInterval 0.00025;\npurgeWrite 0;\nwriteFormat ascii;\nwritePrecision 14;\n"
        "writeCompression off;\ntimePrecision 14;\nrunTimeModifiable false;\n")
    stat = "stationarity"
    checks = [
        _chk("solver_completed", "solver.completed", "true", category="execution",
             rationale="Normal exit at the requested horizon."),
        _chk("no_fatal", "solver.fatal_error", "eq", False, category="execution",
             rationale="No genuine fatal signature in solver logs."),
        _chk("mesh_ok", "mesh.check_ok", "true", category="mesh", rationale="checkMesh reports Mesh OK."),
        _chk("case_unchanged_after_freeze", "setup.case_hash_matches", "true", category="setup",
             rationale="Executed case equals the frozen case."),
        _chk("positive_every_step", "fields.positive_every_step", "true", category="admissibility",
             rationale="p, T, rho positive at every step."),
        _chk("finite_all_saved", "fields.finite_all_saved", "true", category="admissibility",
             rationale="No NaN/Inf in saved states."),
        _chk("courant", "solver.courant_max", "le", 0.4 * 1.02, category="execution",
             rationale="maxCo 0.4 controller target with 2 % tolerance."),
        _chk("outlet_all_supersonic", "nozzle.outlet_normal_mach_min", "gt", 1.05, category="boundary",
             rationale="A zero-gradient outlet is only admissible if every outlet face is supersonic."),
        _chk("inlet_subsonic", "nozzle.inlet_mach_max", "lt", 1.0, category="boundary",
             rationale="Reservoir inflow must be subsonic."),
        _chk("inlet_inflow", "nozzle.inlet_inflow", "true", category="boundary", rationale="No reverse flow at inlet."),
        _chk("reservoir_p0", "nozzle.inlet_p0_rel_error_max", "lt", 1e-3, category="boundary",
             rationale="Inlet faces reproduce the total pressure."),
        _chk("reservoir_T0", "nozzle.inlet_T0_rel_error_max", "lt", 1e-3, category="boundary",
             rationale="Inlet faces reproduce the total temperature."),
        _chk("sonic_throat", "nozzle.throat_mach", "between", [0.9, 1.1], category="reference",
             rationale="Choked throat band."),
        _chk("underexpanded_exit", "nozzle.exit_p", "gt", ambient_pressure, unit="Pa", category="reference",
             rationale="Exit static pressure exceeds nominal ambient (regime assessment only)."),
        _chk("no_internal_normal_shock", "nozzle.downstream_min_slab_mach", "gt", 1.0, category="admissibility",
             rationale="Diverging section remains supersonic."),
        _chk("transient_continuity", "conservation.mass_closure_max_rel", "lt", 1e-4, category="conservation",
             rationale="Storage-aware discrete mass balance (0.01 %)."),
        _chk("restart_seams_continuous", "conservation.restart_seams_continuous", "true", category="conservation",
             rationale="Restarts continue the checkpoint."),
        _chk("stagnation_enthalpy", "nozzle.stagnation_enthalpy_max_rel", "lt", 0.05, category="admissibility",
             rationale="Adiabatic inviscid flow conserves stagnation enthalpy (5 % screen)."),
        _chk("flux_consistency", "nozzle.flux_consistency_rel", "lt", 0.005, category="conservation",
             rationale="Face rho U.S agrees with the solver's numerical flux."),
        _chk("theory_exit_pressure", "nozzle.err_exit_p_abs_pct", "lt", 5.0, unit="%", category="reference",
             rationale="Quasi-1-D exit pressure screening bound for a finite-angle conical nozzle."),
        _chk("theory_other", "nozzle.err_other_max_abs_pct", "lt", 3.0, unit="%", category="reference",
             rationale="Quasi-1-D exit Mach, T, U, and mass-flow screening bound."),
        _chk("physical_time", "solver.reached_target_time", "true", category="horizon", failure="incomplete",
             rationale="The frozen 6 ms horizon must be reached."),
        _chk("stationarity_window", f"{stat}.window_covered", "true", category="stationarity", failure="incomplete",
             rationale="The 2 ms stationarity window must be available."),
        _chk("steady_mass_balance", f"{stat}.flux_mismatch_max", "lt", 1e-3, category="stationarity",
             failure="incomplete", rationale="Inlet and outlet mass flow agree within 0.1 % over the window."),
        _chk("monitors_stationary", f"{stat}.monitor_drift_max", "lt", 2e-3, category="stationarity",
             failure="incomplete", rationale="Per-step monitors drift < 0.2 % over the window."),
        _chk("exit_monitors_stationary", "nozzle.monitor_drift_max", "lt", 2e-3, category="stationarity",
             failure="incomplete", rationale="Exit and throat states drift < 0.2 % over the window."),
        _chk("fields_stationary", f"{stat}.field_change_max", "lt", 2e-3, category="stationarity",
             failure="incomplete", rationale="Relative L2 field change < 0.2 % over the window."),
    ]
    return {
        "name": name or f"nozzle_re{exit_radius*1000:.1f}_p0{total_pressure/1000:g}".replace(".", "p"),
        "solver": "shockFluid", "files": files, "mesh": [{"executable": "blockMesh", "args": []}],
        "diagnostics": {
            "fields": [{"name": "p", "positive": True, "unit": "Pa"}, {"name": "T", "positive": True, "unit": "K"},
                       {"name": "rho", "positive": True, "unit": "kg/m^3"},
                       {"name": "U", "components": 3, "unit": "m/s"}],
            "patches": ["inlet", "outlet", "walls", "wedgeFront", "wedgeBack"], "inlet": "inlet",
            "outlet": "outlet", "impermeable_patches": ["walls", "wedgeFront", "wedgeBack"],
            "expected_cells": sum(nax) * nr, "gas": {"gas_constant": R, "gamma": g},
            "target_time": target_time, "mass_balance": True, "stationarity_window": 0.002,
            "nozzle": {"throat_radius": throat_radius, "exit_radius": exit_radius, "throat_x_min": xs[2],
                       "throat_x_max": xs[3], "total_pressure": total_pressure,
                       "total_temperature": total_temperature, "wedge_degrees": 5.0},
        },
        "contract": {
            "id": "cd_nozzle_benchmark", "title": f"Conical CD nozzle, r_e = {exit_radius*1000:.1f} mm, "
            f"p0 = {total_pressure/1000:g} kPa", "regime": "steady",
            "requested_prompt": prompt or "Simulate the converging-diverging nozzle and compare with quasi-1-D theory.",
            "objectives": [{"id": "settled_nozzle", "claim": "reference_agreement",
                            "description": "Settled, conservative solution consistent with quasi-1-D theory.",
                            "check_ids": [c["id"] for c in checks]}],
            "checks": checks, "authority": "reviewed_benchmark",
            "assumptions": [{"parameter": "ambient_pressure", "value": ambient_pressure, "unit": "Pa",
                             "source": "user", "justification": "Regime assessment only; not imposed at outlet."}],
            "limitations": ["Single-mesh verification of an inviscid axisymmetric wedge.",
                            "Quasi-1-D tolerances are screening bounds, not validation."],
            "reference": "Isentropic quasi-1-D theory (independently implemented).",
        },
        "budget": {"max_attempts": 4, "wall_seconds": 7200, "cpus": 1, "memory_mb": 4096,
                   # Steady family: settling may need time past the 6 ms comparison horizon.
                   "max_cells": 100000, "max_end_time": 2 * target_time},
    }
