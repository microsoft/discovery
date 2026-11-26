"""Catalog of metrics the OpenFOAM extractor can emit, with their unit and type.

The contract linter binds every check to this catalog before anything runs, so a
misspelled, unit-mismatched, or wrongly typed criterion is refused at freeze time
instead of silently becoming UNKNOWN after an expensive solve.
"""

from __future__ import annotations

from ..core.models import Check, Diagnostics
from ..core.units import validate

B, N = "bool", "number"

_ALWAYS: dict[str, tuple[str, str]] = {
    "mesh.check_ok": (B, "1"), "mesh.stage_clean": (B, "1"), "mesh.cells": (N, "1"),
    "mesh.within_cell_budget": (B, "1"),
    "mesh.max_nonorthogonality": (N, "1"), "mesh.max_skewness": (N, "1"), "mesh.max_aspect_ratio": (N, "1"),
    "mesh.solution_directions": (N, "1"), "mesh.expected_patches_present": (B, "1"),
    "mesh.cyclic_patch_count": (N, "1"), "mesh.planar_patch_present": (B, "1"),
    "solver.exit_code": (N, "1"), "solver.fatal_error": (B, "1"), "solver.steps": (N, "1"),
    "solver.final_time": (N, "1"), "solver.requested_end_time": (N, "1"),
    "solver.reached_requested_end": (B, "1"), "solver.reached_target_time": (B, "1"),
    "solver.completed": (B, "1"), "solver.converged_by_residual_control": (B, "1"),
    "solver.courant_max": (N, "1"), "solver.courant_finite_positive": (B, "1"),
    # Present when the solver prints linear-solver residuals / continuity errors.
    "solver.residual_initial_last_max": (N, "1"), "solver.residual_drop_orders_min": (N, "1"),
    "solver.continuity_local_last": (N, "1"), "solver.continuity_local_max": (N, "1"),
    "fields.finite_all_saved": (B, "1"), "setup.case_hash_matches": (B, "1"),
}

# Run-health checks every contract carries. Added at freeze time when a contract omits them.
BASELINE: list[Check] = [
    Check(id="baseline_solver_completed", metric="solver.completed", operator="true", category="execution",
          rationale="The solver must finish its requested horizon cleanly (exit 0, End banner)."),
    Check(id="baseline_no_fatal_error", metric="solver.fatal_error", operator="eq", threshold=False,
          category="execution", rationale="No fatal error, signal, or crash signature may appear in solver logs."),
    Check(id="baseline_mesh_ok", metric="mesh.check_ok", operator="true", category="mesh",
          rationale="checkMesh must report the mesh OK with no failed quality checks."),
    Check(id="baseline_mesh_stage_clean", metric="mesh.stage_clean", operator="true", category="mesh",
          rationale="Every meshing command must exit successfully."),
    Check(id="baseline_fields_finite", metric="fields.finite_all_saved", operator="true",
          category="admissibility", rationale="Every saved field value must be finite (no NaN/Inf)."),
    Check(id="baseline_case_unchanged", metric="setup.case_hash_matches", operator="true", category="setup",
          rationale="The executed case must be byte-identical to the frozen case, horizon keys excepted."),
    Check(id="baseline_target_reached", metric="solver.reached_target_time", operator="true",
          category="horizon", failure="incomplete",
          rationale="The run must reach the declared diagnostic target time before any claim is made."),
]


def known_metrics(d: Diagnostics) -> dict[str, tuple[str, str]]:
    out = dict(_ALWAYS)
    if d.expected_cells:
        out["mesh.cell_count_matches"] = (B, "1")
    if d.dimensions:
        out["mesh.dimension_matches"] = (B, "1")
    for f in d.fields:
        out[f"fields.{f.name}.final_min"] = (N, f.unit)
        out[f"fields.{f.name}.final_max"] = (N, f.unit)
    if any(f.positive for f in d.fields):
        out.update({"fields.positive_all_saved": (B, "1"), "fields.positive_every_step": (B, "1"),
                    "fields.extrema_records": (N, "1")})
    if d.initial_values:
        out["setup.initial_state_max_rel_error"] = (N, "1")
    if d.reference_hashes:
        out["setup.reference_files_match"] = (B, "1")
    if d.gas and d.inlet:
        out.update({"flow.inlet_mach_min": (N, "1"), "flow.inlet_mach_max": (N, "1")})
    if d.inlet and d.outlet:
        out.update({"conservation.final_inlet_flux": (N, "1"), "conservation.final_outlet_flux": (N, "1"),
                    "conservation.final_net_flux_rel": (N, "1")})
        if d.impermeable_patches:
            out["conservation.impermeable_flux_max_rel"] = (N, "1")
        if d.mass_balance:
            out.update({"conservation.mass_closure_max_rel": (N, "1"),
                        "conservation.restart_seams_continuous": (B, "1"),
                        "conservation.restart_segments": (N, "1"), "conservation.mass_closure_records": (N, "1")})
        if d.stationarity_window:
            out.update({"stationarity.window_covered": (B, "1"), "stationarity.flux_mismatch_max": (N, "1"),
                        "stationarity.monitor_drift_max": (N, "1")})
    if d.stationarity_window:
        out["stationarity.field_change_max"] = (N, "1")
    if d.compression:
        out.update({"compression.front_measurable": (B, "1"), "compression.front_x": (N, "1"),
                    **{f"compression.{k}_ratio": (N, "1") for k in ("p", "rho", "T")}})
    if d.nozzle and d.gas and d.inlet and d.outlet:
        out.update({k: (N, "1") for k in (
            "nozzle.throat_mach", "nozzle.stagnation_enthalpy_max_rel", "nozzle.outlet_normal_mach_min",
            "nozzle.inlet_mach_max", "nozzle.inlet_p0_rel_error_max", "nozzle.inlet_T0_rel_error_max",
            "nozzle.flux_consistency_rel", "nozzle.exit_mach", "nozzle.monitor_drift_max",
            "nozzle.downstream_min_slab_mach")})
        out.update({"nozzle.inlet_inflow": (B, "1"), "nozzle.exit_p": (N, "Pa"), "nozzle.exit_T": (N, "K"),
                    "nozzle.exit_U": (N, "m/s"), "nozzle.mass_flow": (N, "kg/s"),
                    "nozzle.err_exit_p_abs_pct": (N, "%"), "nozzle.err_other_max_abs_pct": (N, "%"),
                    **{f"nozzle.err_{k}_pct": (N, "%") for k in
                       ("exit_mach", "exit_p", "exit_T", "exit_U", "mass_flow")}})
    for q in d.quantities:
        out[f"quantity.{q.name}"] = (N, q.unit if q.statistic != "window_relative_span" else "1")
    for dv in d.derived:
        # Invalid/forward/incompatible derived outputs must not become bindable
        # merely because the request supplied an output unit label.
        try:
            validate(dv, {name: unit for name, (kind, unit) in out.items() if kind == N})
        except ValueError:
            continue
        out[f"derived.{dv.name}"] = (N, dv.unit)
    return out
