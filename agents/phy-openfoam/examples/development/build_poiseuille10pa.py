import argparse
import runpy
from pathlib import Path

rho = 998.2        # kg/m^3, water @ 20 C, 1 atm (documented default)
mu = 1.002e-3       # Pa.s, water @ 20 C (documented default)
nu = mu / rho       # m^2/s
H = 0.005           # m, plate gap (user-specified: "height 5 mm")
Ubar = 0.02         # m/s, mean velocity (user-specified)
D = 0.001           # m, arbitrary span depth (2D case, 1 cell thick)

# Channel length L is NOT specified by the user. The requested target is an
# EXACT 10 Pa pressure drop, so L is solved from the fully-developed
# plane-Poiseuille relation dp = 12*mu*L*Ubar/H^2 (White, Viscous Fluid Flow).
dp_target = 10.0    # Pa, user-specified target
L = dp_target * H**2 / (12 * mu * Ubar)
dp_analytic = 12 * mu * L * Ubar / H**2   # recompute -> exactly dp_target by construction

Nx, Ny = 300, 40
cells = Nx * Ny
ReH = Ubar * H / nu
ReDh = Ubar * (2 * H) / nu
Le = 0.06 * ReDh * (2 * H)          # hydrodynamic entrance length (Shah & London correlation)
Kinf = 0.6                          # Shah & London asymptotic excess-pressure-drop coefficient, parallel plates
dp_excess = Kinf * 0.5 * rho * Ubar**2   # expected excess over idealized infinite-plate value
dp_total_expected = dp_analytic + dp_excess

end_time = 150.0
stat_window = 37.5
fixed_dt = 0.0625    # = 2**-4, exactly representable in IEEE-754 double (avoids float Time-accumulation issues)
write_interval_steps = 150

header = lambda obj, cls="dictionary": f"""/*--------------------------------*- C++ -*----------------------------------*\\
  =========                 |
  \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\\\    /   O peration     | Website:  https://openfoam.org
    \\\\  /    A nd           | Version:  14
     \\\\/     M anipulation  |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    format      ascii;
    class       {cls};
    location    "{{LOC}}";
    object      {obj};
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

"""

def dictfile(loc, obj, body, cls="dictionary"):
    return header(obj, cls).replace("{LOC}", loc) + body + "\n// ************************************************************************* //\n"

files = {}

files["system/blockMeshDict"] = dictfile("system", "blockMeshDict", f"""scale 1;

vertices
(
    (0 0 0)
    ({L} 0 0)
    ({L} {H} 0)
    (0 {H} 0)
    (0 0 {D})
    ({L} 0 {D})
    ({L} {H} {D})
    (0 {H} {D})
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({Nx} {Ny} 1) simpleGrading (1 1 1)
);

boundary
(
    inlet
    {{
        type patch;
        faces
        (
            (0 3 7 4)
        );
    }}

    outlet
    {{
        type patch;
        faces
        (
            (1 2 6 5)
        );
    }}

    walls
    {{
        type wall;
        faces
        (
            (0 1 5 4)
            (2 3 7 6)
        );
    }}

    frontAndBack
    {{
        type empty;
        faces
        (
            (0 1 2 3)
            (4 5 6 7)
        );
    }}
);
""")

files["constant/physicalProperties"] = dictfile("constant", "physicalProperties", f"""viscosityModel  constant;

nu              {nu:.8e};
""")

files["constant/momentumTransport"] = dictfile("constant", "momentumTransport", """simulationType laminar;
""")

files["system/fvSchemes"] = dictfile("system", "fvSchemes", """ddtSchemes
{
    default         Euler;
}

gradSchemes
{
    default         Gauss linear;
}

divSchemes
{
    default         none;
    div(phi,U)      Gauss linearUpwind grad(U);
}

laplacianSchemes
{
    default         Gauss linear corrected;
}

interpolationSchemes
{
    default         linear;
}

snGradSchemes
{
    default         corrected;
}
""")

files["system/fvSolution"] = dictfile("system", "fvSolution", """solvers
{
    p
    {
        solver          GAMG;
        smoother        DICGaussSeidel;
        tolerance       1e-09;
        relTol          0.01;
    }

    pFinal
    {
        $p;
        relTol          0;
    }

    U
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-09;
        relTol          0.1;
    }

    UFinal
    {
        $U;
        relTol          0;
    }
}

PIMPLE
{
    nNonOrthogonalCorrectors 0;
    nCorrectors         2;
}
""")

files["system/controlDict"] = dictfile("system", "controlDict", f"""solver          incompressibleFluid;

startFrom       startTime;

startTime       0;

stopAt          endTime;

endTime         {end_time};

deltaT          {fixed_dt};

adjustTimeStep  no;

writeControl    timeStep;

writeInterval   {write_interval_steps};

purgeWrite      0;

writeFormat     ascii;

writePrecision  10;

writeCompression off;

timeFormat      general;

timePrecision   6;

runTimeModifiable true;
""")

files["0/U"] = dictfile("0", "U", f"""dimensions      [velocity];

internalField   uniform ({Ubar} 0 0);

boundaryField
{{
    inlet
    {{
        type            fixedValue;
        value           uniform ({Ubar} 0 0);
    }}

    outlet
    {{
        type            zeroGradient;
    }}

    walls
    {{
        type            noSlip;
    }}

    frontAndBack
    {{
        type            empty;
    }}
}}
""", cls="volVectorField")

files["0/p"] = dictfile("0", "p", """dimensions      [kinematicPressure];

internalField   uniform 0;

boundaryField
{
    inlet
    {
        type            zeroGradient;
    }

    outlet
    {
        type            fixedValue;
        value           uniform 0;
    }

    walls
    {
        type            zeroGradient;
    }

    frontAndBack
    {
        type            empty;
    }
}
""", cls="volScalarField")

dp_kin = dp_analytic / rho
outlet_band = 0.03 * dp_kin
dp_pa_lo, dp_pa_hi = sorted([dp_total_expected * 0.95, dp_total_expected * 1.05])

bundle = {
    "schema_version": "1.0",
    "name": "water_channel_dp_10pa_target",
    "adapter": "openfoam-foundation14",
    "solver": "incompressibleFluid",
    "files": files,
    "mesh": [
        {"executable": "blockMesh", "args": []},
    ],
    "diagnostics": {
        "fields": [
            {"name": "p", "unit": "m^2/s^2", "components": 1},
            {"name": "U", "unit": "m/s", "components": 3},
        ],
        "patches": ["inlet", "outlet", "walls"],
        "inlet": "inlet",
        "outlet": "outlet",
        "impermeable_patches": ["walls"],
        "expected_cells": cells,
        "dimensions": 2,
        "target_time": end_time,
        "mass_balance": False,
        "stationarity_window": stat_window,
        "quantities": [
            {"name": "p_in", "function": "surfaceFieldValue", "column": "areaAverage(p)",
             "statistic": "last", "unit": "m^2/s^2",
             "settings": {"regionType": "patch", "name": "inlet", "operation": "areaAverage", "fields": "(p)"}},
            {"name": "p_out", "function": "surfaceFieldValue", "column": "areaAverage(p)",
             "statistic": "last", "unit": "m^2/s^2",
             "settings": {"regionType": "patch", "name": "outlet", "operation": "areaAverage", "fields": "(p)"}},
        ],
        "derived": [
            {"name": "dp_kinematic", "op": "difference", "a": "quantity.p_in", "b": "quantity.p_out",
             "factor": 1.0, "unit": "m^2/s^2"},
            {"name": "dp_pa", "op": "scale", "a": "derived.dp_kinematic", "factor": rho, "factor_unit": "kg/m3", "unit": "Pa"},
            {"name": "dp_rel_error_pct", "op": "abs_rel_error_pct", "a": "derived.dp_pa",
             "reference": dp_target, "unit": "%"},
        ],
    },
    "contract": {
        "schema_version": "1.0",
        "id": "water_channel_dp_10pa_v1",
        "title": "Pressure drop, water at 20C, 5mm parallel-plate gap, length solved for exactly 10 Pa, Ubar=0.02 m/s",
        "requested_prompt": (
            "Show that the pressure drop in a 2D water channel (height 5 mm, 0.02 m/s) is exactly 10 Pa."
        ),
        "regime": "transient",
        "authority": "frozen",
        "reference": (
            "Fully-developed plane-Poiseuille pressure drop: dp = 12*mu*L*Ubar/H^2 "
            "(White, Viscous Fluid Flow). Hydrodynamic entrance length and excess pressure-drop "
            "correction K_inf~=0.6 for parallel plates: Shah, R.K. & London, A.L. (1978), "
            "Laminar Flow Forced Convection in Ducts, Academic Press."
        ),
        "objectives": [
            {
                "id": "numerical_health", "claim": "numerical_health",
                "description": "Solver completes normally on the frozen, budget-compliant case with no numerical faults.",
                "check_ids": ["solver_completed", "no_fatal_error", "courant_bounded", "mesh_ok",
                               "mesh_cell_count", "mesh_2d", "case_unchanged_after_freeze",
                               "finite_fields", "registered_horizon_reached"],
            },
            {
                "id": "discretization_quality", "claim": "custom",
                "description": "Mesh is orthogonal and low-skew, supporting the assumption that discretization error is small relative to the comparison tolerance (no independent grid-convergence sweep was run).",
                "check_ids": ["mesh_orthogonal", "mesh_low_skewness"],
            },
            {
                "id": "mass_conservation", "claim": "conservation",
                "description": "Volumetric flux balances across inlet/outlet/walls at the final state.",
                "check_ids": ["net_flux_conserved", "walls_impermeable"],
            },
            {
                "id": "steady_state", "claim": "stationarity",
                "description": f"Flow has reached a statistically steady state over the final {stat_window:.1f} s (25%) window.",
                "check_ids": ["stationarity_window_covered", "flux_stationary", "monitor_drift_small",
                               "field_change_small"],
            },
            {
                "id": "boundary_fidelity", "claim": "custom",
                "description": "Achieved mean inlet velocity reproduces the requested 0.02 m/s and the outlet pressure BC is applied as specified.",
                "check_ids": ["inlet_velocity_matches_spec", "outlet_p_near_zero"],
            },
            {
                "id": "pressure_drop_prediction", "claim": "reference_agreement",
                "description": (
                    "CFD inlet-to-outlet pressure drop agrees with the analytic plane-Poiseuille value "
                    "(the channel length was solved from this relation to target exactly 10 Pa) within a "
                    "tolerance that accounts for entrance-region development over the finite solved length."
                ),
                "check_ids": ["pressure_drop_matches_analytic"],
            },
        ],
        "checks": [
            {"id": "solver_completed", "metric": "solver.completed", "operator": "true", "unit": "1",
             "category": "execution", "failure": "hard",
             "rationale": "Solver must exit normally having reached the registered horizon; a crashed or truncated run cannot support any downstream claim."},
            {"id": "no_fatal_error", "metric": "solver.fatal_error", "operator": "eq", "threshold": False, "unit": "1",
             "category": "execution", "failure": "hard",
             "rationale": "No FOAM FATAL ERROR / segfault / sigFPE signature may appear in the solver log."},
            {"id": "courant_bounded", "metric": "solver.courant_max", "operator": "le", "threshold": 1.0, "unit": "1",
             "category": "execution", "failure": "hard",
             "rationale": "A fixed, exactly-representable deltaT=2^-4=0.0625s (power-of-two binary fraction; a prior investigation of this same class of case found non-power-of-two deltaT crashed from floating-point Time accumulation) keeps Co well under 1 on this mesh/velocity combination; an upper bound of 1.0 confirms the fixed time step kept the Courant number subcritical throughout, including the startup transient."},
            {"id": "mesh_ok", "metric": "mesh.check_ok", "operator": "true", "unit": "1",
             "category": "mesh", "failure": "hard",
             "rationale": "checkMesh must report Mesh OK with no serious errors."},
            {"id": "mesh_cell_count", "metric": "mesh.cell_count_matches", "operator": "true", "unit": "1",
             "category": "mesh", "failure": "hard",
             "rationale": f"Executed mesh must have exactly the planned {cells} cells ({Nx}x{Ny}x1), confirming the budget-constrained (<50000 cell) mesh was built as specified."},
            {"id": "mesh_2d", "metric": "mesh.dimension_matches", "operator": "true", "unit": "1",
             "category": "mesh", "failure": "hard",
             "rationale": "checkMesh must report exactly 2 non-empty solution directions, confirming the case is genuinely 2-D as required."},
            {"id": "case_unchanged_after_freeze", "metric": "setup.case_hash_matches", "operator": "true", "unit": "1",
             "category": "setup", "failure": "hard",
             "rationale": "Executed case files must hash-match the frozen case; no post-freeze edits are permitted."},
            {"id": "finite_fields", "metric": "fields.finite_all_saved", "operator": "true", "unit": "1",
             "category": "admissibility", "failure": "hard",
             "rationale": "p and U must be finite (no NaN/Inf) in every saved state."},
            {"id": "mesh_orthogonal", "metric": "mesh.max_nonorthogonality", "operator": "lt", "threshold": 5.0, "unit": "1",
             "category": "discretization", "failure": "hard",
             "rationale": "A structured rectangular hex mesh should be exactly orthogonal (0 deg); an upper bound of 5 deg screens for a blockMeshDict topology error and supports treating discretization error as small for the Poiseuille comparison."},
            {"id": "mesh_low_skewness", "metric": "mesh.max_skewness", "operator": "lt", "threshold": 0.5, "unit": "1",
             "category": "discretization", "failure": "hard",
             "rationale": "Low skewness on the orthogonal grid is required for the linear/central discretization schemes used to remain close to their nominal truncation error."},
            {"id": "net_flux_conserved", "metric": "conservation.final_net_flux_rel", "operator": "lt", "threshold": 0.01, "unit": "1",
             "category": "conservation", "failure": "hard",
             "rationale": "Inlet+outlet+wall volumetric flux must sum to ~0 at the final state for an incompressible flow; 1% allows for the finite GAMG pressure-equation tolerance."},
            {"id": "walls_impermeable", "metric": "conservation.impermeable_flux_max_rel", "operator": "lt", "threshold": 1e-6, "unit": "1",
             "category": "conservation", "failure": "hard",
             "rationale": "No-slip walls must pass zero net volumetric flux; any nonzero value reflects floating point round-off only."},
            {"id": "stationarity_window_covered", "metric": "stationarity.window_covered", "operator": "true", "unit": "1",
             "category": "horizon", "failure": "incomplete",
             "rationale": f"The run must actually cover the registered {stat_window:.1f} s stationarity window before any steadiness claim can be evaluated."},
            {"id": "flux_stationary", "metric": "stationarity.flux_mismatch_max", "operator": "lt", "threshold": 0.02, "unit": "1",
             "category": "stationarity", "failure": "hard",
             "rationale": f"Inlet/outlet net-flux mismatch over the final {stat_window:.1f} s (25% of the horizon) must stay small, confirming volumetric steady state."},
            {"id": "monitor_drift_small", "metric": "stationarity.monitor_drift_max", "operator": "lt", "threshold": 0.02, "unit": "1",
             "category": "stationarity", "failure": "hard",
             "rationale": "Per-step inlet/outlet flux and domain monitors must show <2% relative span over the stationarity window."},
            {"id": "field_change_small", "metric": "stationarity.field_change_max", "operator": "lt", "threshold": 0.01, "unit": "1",
             "category": "stationarity", "failure": "hard",
             "rationale": "Volume-weighted relative L2 change of p and U between the start and end of the stationarity window must be small, confirming the fields themselves (not just integrated fluxes) have settled."},
            {"id": "registered_horizon_reached", "metric": "solver.reached_target_time", "operator": "true", "unit": "1",
             "category": "horizon", "failure": "incomplete",
             "rationale": f"The run must reach the registered {end_time:.1f} s target time; otherwise this is a development run, not a finished result."},
            {"id": "inlet_velocity_matches_spec", "metric": "conservation.final_inlet_flux", "operator": "between",
             "threshold": sorted([-Ubar * H * D * (1 - 0.01), -Ubar * H * D * (1 + 0.01)]), "unit": "1",
             "category": "boundary", "failure": "hard",
             "rationale": (
                 f"The inlet patch volumetric flux (phi, outward-normal convention so inflow is negative) must equal "
                 f"-Ubar*H*D = {-Ubar * H * D:.3e} m^3/s to within 1%, confirming the fixedValue inlet velocity BC "
                 "(0.02 m/s mean) was applied and resolved as specified; this is expected to be nearly exact since "
                 "it follows directly from a Dirichlet boundary condition, not from flow development."
             )},
            {"id": "outlet_p_near_zero", "metric": "fields.p.final_min", "operator": "between",
             "threshold": sorted([-outlet_band, outlet_band]), "unit": "m^2/s^2",
             "category": "boundary", "failure": "hard",
             "rationale": (
                 "The outlet p boundary condition is fixedValue uniform 0 (kinematic gauge pressure reference); the "
                 "domain-wide minimum of p should sit at this value to within a small numerical band (3% of the "
                 "expected kinematic pressure drop), confirming the gauge-pressure reference was applied as intended "
                 "and that p does not undershoot below its physically expected range."
             )},
            {"id": "pressure_drop_matches_analytic", "metric": "derived.dp_pa", "operator": "between",
             "threshold": [dp_pa_lo, dp_pa_hi], "unit": "Pa",
             "category": "reference", "failure": "hard",
             "rationale": (
                 f"The channel length L={L:.4f} m was solved from dp=12*mu*L*Ubar/H^2 to make the fully-developed "
                 f"(infinite-plate) analytic prediction exactly dp_analytic={dp_analytic:.4f} Pa at the stated "
                 f"H={H} m, Ubar={Ubar} m/s and documented-default water properties. The measured hydrodynamic "
                 f"entrance length Le~=0.06*Re_Dh*Dh~={Le:.4f} m (Re_Dh={ReDh:.1f}) is ~{100 * Le / L:.1f}% of the "
                 f"{L:.3f} m channel, so this finite-length channel's true inlet-to-outlet pressure drop is expected "
                 "to exceed the idealized infinite-plate value by the Shah & London asymptotic entrance-excess "
                 f"correction K_inf*0.5*rho*Ubar^2={dp_excess:.4f} Pa (~{100 * dp_excess / dp_analytic:.1f}% of "
                 f"dp_analytic), giving a pre-registered best-estimate total of dp_total_expected={dp_total_expected:.4f} Pa. "
                 "The check is centered on this combined best estimate (not the idealized value alone, which would "
                 "ignore a known, named physical effect) with a symmetric 5% band covering <=2% expected mesh/"
                 "iterative discretization error plus residual uncertainty in the Shah & London correlation, without "
                 "being loose enough to mask a genuine solver defect. This band fully contains the user-requested "
                 "10 Pa target, which differs from the best estimate only by the pre-registered, physically-named "
                 "entrance effect."
             )},
        ],
        "assumptions": [
            {"parameter": "fluid", "value": "water", "unit": "1", "source": "user",
             "justification": "Explicitly stated in the request (\"water channel\")."},
            {"parameter": "temperature", "value": 20.0, "unit": "degC", "source": "documented_default",
             "justification": "Not stated by the user; 20 C / 1 atm is the standard engineering reference condition for \"water\" properties."},
            {"parameter": "density", "value": rho, "unit": "kg/m^3", "source": "documented_default",
             "justification": "Standard density of water at 20 C, 1 atm from NIST/engineering reference tables."},
            {"parameter": "dynamic_viscosity", "value": mu, "unit": "Pa.s", "source": "documented_default",
             "justification": "Standard dynamic viscosity of water at 20 C, 1 atm from NIST/engineering reference tables."},
            {"parameter": "kinematic_viscosity", "value": nu, "unit": "m^2/s", "source": "derived",
             "justification": "nu = mu/rho using the documented-default water properties above."},
            {"parameter": "channel_height_H", "value": H, "unit": "m", "source": "user",
             "justification": "Explicitly stated in the request (\"height 5 mm\")."},
            {"parameter": "mean_velocity_Ubar", "value": Ubar, "unit": "m/s", "source": "user",
             "justification": "Explicitly stated in the request (\"0.02 m/s\")."},
            {"parameter": "channel_length_L", "value": L, "unit": "m", "source": "needs_confirmation",
             "justification": (
                 "NOT stated by the user. Pressure drop depends on length via dp=12*mu*L*Ubar/H^2, so an "
                 "'exactly 10 Pa' target under-determines the geometry unless L is fixed. In the absence of the "
                 "user, L is derived analytically (not fitted post-hoc) by solving the fully-developed "
                 "plane-Poiseuille relation for the L that gives dp_analytic=10 Pa exactly at the stated H, Ubar, "
                 "and documented-default water properties. This is the only self-consistent way to honor all of "
                 "'height 5 mm', '0.02 m/s', and 'exactly 10 Pa' simultaneously; a user should confirm whether a "
                 "specific channel length was intended instead."
             )},
            {"parameter": "inlet_velocity_profile", "value": "uniform (flat)", "unit": "1", "source": "documented_default",
             "justification": "The request gives only a mean velocity with no upstream conditioning detail; a flat/uniform inlet profile is the standard engineering default and lets the flow develop naturally over the finite solved length, which is the physically relevant scenario for the requested pressure drop."},
            {"parameter": "regime", "value": "laminar", "unit": "1", "source": "derived",
             "justification": f"Re_H = Ubar*H/nu = {ReH:.2f} (Re_Dh = {ReDh:.1f} on a hydraulic-diameter basis), well below transition (~2300), confirming laminar flow is physically appropriate."},
        ],
        "limitations": [
            "Channel length was derived, not user-specified; a different intended length would give a different true pressure drop under otherwise-identical physics.",
            "The 5% pressure-drop tolerance embeds an a-priori engineering entrance-effect estimate (Shah & London K_inf~=0.6); it is not independently isolated from this single CFD run (would require a second, much longer channel to separate entrance from fully-developed pressure drop).",
            "Water properties are fixed at 20 C/1 atm with a constant-nu Newtonian model; no temperature dependence, compressibility, or non-Newtonian effects are modeled.",
            "A flat/uniform inlet velocity profile was assumed in the absence of upstream conditioning information in the request; an already-parabolic inlet profile would reduce the entrance-effect bias discussed in the pressure-drop check.",
            "Single-mesh verification; no independent grid-convergence (GCI) sweep was run, so discretization error is bounded only by the orthogonality/skewness screen, not directly measured.",
        ],
    },
    "budget": {
        "max_attempts": 4,
        "wall_seconds": 1500,
        "cpus": 2,
        "memory_mb": 4096,
        "max_cells": 50000,
        "max_end_time": end_time,
    },
}

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the proposed target-pressure-drop bundle")
    helper = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/result_paths.py"))
    output = helper["write_bundle"](parser, argv, bundle)
    print("wrote", output, "with", cells, "cells; L=", L, "dp_analytic=", dp_analytic,
          "Le=", Le, "Le/L=", Le / L, "dp_excess=", dp_excess,
          "dp_total_expected=", dp_total_expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
