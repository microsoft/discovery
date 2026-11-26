"""Planted-fault suite: independent reconstructions of the 18 fault categories in the paper,
plus defects the paper reports and extra fail-closed cases. No solver runs here."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass

from ..core.checks import assess
from ..core.hashing import sha256_json
from ..core.models import Assessment, Contract, Evidence, Metric


@dataclass(frozen=True)
class Fault:
    name: str
    expected_check: str
    apply: Callable[[dict], None]
    detectable_by_blind_packet: bool = True


def _set(metric: str, value):
    def f(m: dict) -> None:
        m[metric] = {"value": value, "unit": m.get(metric, {}).get("unit", "1"), "source": "planted fault",
                     "status": "measured"}
    return f


FAULTS: list[Fault] = [
    Fault("solver_not_completed", "solver_completed", _set("solver.completed", False)),
    Fault("fatal_error_present", "no_fatal_error", _set("solver.fatal_error", True)),
    Fault("mesh_invalid", "mesh_ok", _set("mesh.check_ok", False)),
    Fault("cell_count_mismatch", "cell_count_matches_spec", _set("mesh.cell_count_matches", False)),
    Fault("fixed_recipe_edited", "fixed_recipe_unchanged", _set("setup.reference_files_match", False), False),
    Fault("nonpositive_state", "positive_all_saved", _set("fields.positive_all_saved", False)),
    Fault("nonfinite_state", "finite_all_saved", _set("fields.finite_all_saved", False)),
    Fault("negative_step_minimum", "positive_every_step", _set("fields.positive_every_step", False)),
    Fault("mass_imbalance", "transient_mass_closure", _set("conservation.mass_closure_max_rel", 1e-3)),
    Fault("leaking_wall", "impermeable_walls", _set("conservation.impermeable_flux_max_rel", 1e-3)),
    Fault("restart_seam_discontinuous", "restart_seams_continuous",
          _set("conservation.restart_seams_continuous", False)),
    Fault("subsonic_inlet", "supersonic_inlet", _set("flow.inlet_mach_min", 0.8), False),
    Fault("initial_state_drift", "initial_state_as_specified", _set("setup.initial_state_max_rel_error", 1e-3), False),
    Fault("missing_boundary_patch", "expected_boundaries_present", _set("mesh.expected_patches_present", False), False),
    Fault("cyclic_patch_present", "no_cyclic_patches", _set("mesh.cyclic_patch_count", 2), False),
    Fault("courant_nonfinite", "courant_finite_positive", _set("solver.courant_finite_positive", False)),
    Fault("not_two_dimensional", "two_solution_directions", _set("mesh.dimension_matches", False)),
    Fault("mesh_stage_dirty", "mesh_stage_clean", _set("mesh.stage_clean", False)),
]

# Fail-closed additions beyond the paper's 18 categories.
EXTRA: list[Fault] = [
    Fault("metric_missing", "transient_mass_closure",
          lambda m: m.pop("conservation.mass_closure_max_rel", None)),
    Fault("metric_nan", "transient_mass_closure",
          lambda m: m.__setitem__("conservation.mass_closure_max_rel",
                                  {"value": None, "unit": "1", "source": "nan", "status": "invalid"})),
    Fault("wrong_type", "solver_completed", _set("solver.completed", "yes")),
    Fault("compression_partial", "T_rises_across_front", lambda m: m.pop("compression.T_ratio", None)),
    Fault("unit_mismatch", "supersonic_inlet",
          lambda m: m.__setitem__("flow.inlet_mach_min", {**m["flow.inlet_mach_min"], "unit": "m/s"})),
]


def planted(evidence: Evidence, fault: Fault) -> Evidence:
    data = evidence.model_dump(mode="json")
    metrics = copy.deepcopy(data["metrics"])
    fault.apply(metrics)
    data["metrics"] = metrics
    data["origin"] = "synthetic"
    return Evidence.model_validate(data)


def replay(evidence: Evidence) -> Evidence:
    """Re-label native evidence for deterministic re-assessment without the solver."""
    return Evidence.model_validate({**evidence.model_dump(mode="json"), "origin": "reconstructed"})


def scientific_verdict(contract: Contract, evidence: Evidence) -> Assessment:
    """Assess with origin forced native so replayed verdict logic equals the live one."""
    e = Evidence.model_validate({**evidence.model_dump(mode="json"), "origin": "native",
                                 "contract_sha256": sha256_json(contract)})
    return assess(contract, e)


def metric(value, unit="1") -> dict:
    return Metric(value=value, unit=unit, source="fixture").model_dump(mode="json")
