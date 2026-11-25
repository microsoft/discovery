import argparse
import runpy
from pathlib import Path

L = 0.3
H = 0.005
t = 0.001
nx = 150
ny = 60
rho = 998.2
nu = 1.004e-6
Um = 0.02

blockMeshDict = f"""FoamFile
{{
    format ascii;
    class dictionary;
    object blockMeshDict;
}}

vertices
(
    (0 0 {-t/2}) ({L} 0 {-t/2}) ({L} {H} {-t/2}) (0 {H} {-t/2})
    (0 0 {t/2}) ({L} 0 {t/2}) ({L} {H} {t/2}) (0 {H} {t/2})
);
blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} 1) simpleGrading (1 1 1)
);
defaultPatch {{ type empty; }}
boundary
(
    inlet {{ type patch; faces ((0 3 7 4)); }}
    outlet {{ type patch; faces ((1 2 6 5)); }}
    walls {{ type wall; faces ((0 1 5 4) (3 2 6 7)); }}
    frontAndBack {{ type empty; faces ((0 1 2 3) (4 5 6 7)); }}
);
"""

controlDict = """FoamFile
{
    format ascii;
    class dictionary;
    object controlDict;
}

solver          incompressibleFluid;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         2000;
deltaT          1;
writeControl    timeStep;
writeInterval   20;
purgeWrite      0;
writeFormat     ascii;
writePrecision  8;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;
"""

fvSchemes = """FoamFile
{
    format ascii;
    class dictionary;
    object fvSchemes;
}

ddtSchemes
{
    default steadyState;
}

gradSchemes
{
    default Gauss linear;
}

divSchemes
{
    default none;
    div(phi,U) bounded Gauss linearUpwind grad(U);
}

laplacianSchemes
{
    default Gauss linear corrected;
}

interpolationSchemes
{
    default linear;
}

snGradSchemes
{
    default corrected;
}
"""

fvSolution = """FoamFile
{
    format ascii;
    class dictionary;
    object fvSolution;
}

solvers
{
    p
    {
        solver          GAMG;
        tolerance       1e-09;
        relTol          0.01;
        smoother        GaussSeidel;
    }

    pFinal
    {
        $p;
        tolerance       1e-09;
        relTol          0;
    }

    U
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-10;
        relTol          0.1;
    }
}

SIMPLE
{
    nNonOrthogonalCorrectors 0;
    consistent      yes;

    residualControl
    {
        p   1e-8;
        U   1e-9;
    }
}

relaxationFactors
{
    equations
    {
        U   0.9;
        ".*" 0.9;
    }
}
"""

physicalProperties = f"""FoamFile
{{
    format ascii;
    class dictionary;
    object physicalProperties;
}}

viscosityModel  constant;

nu              {nu} [m^2/s];
"""

momentumTransport = """FoamFile
{
    format ascii;
    class dictionary;
    object momentumTransport;
}

simulationType laminar;
"""

U_file = f"""FoamFile
{{
    format ascii;
    class volVectorField;
    object U;
}}

dimensions [velocity];
internalField uniform ({Um} 0 0);
boundaryField
{{
    inlet {{ type fixedValue; value uniform ({Um} 0 0); }}
    outlet {{ type zeroGradient; }}
    walls {{ type noSlip; }}
    frontAndBack {{ type empty; }}
}}
"""

p_file = """FoamFile
{
    format ascii;
    class volScalarField;
    object p;
}

dimensions [kinematicPressure];
internalField uniform 0;
boundaryField
{
    inlet { type zeroGradient; }
    outlet { type fixedValue; value uniform 0; }
    walls { type zeroGradient; }
    frontAndBack { type empty; }
}
"""

mu_SI = nu * rho
dp_core_ref = 12.0 * mu_SI * Um * (0.25 - 0.05) / H**2
dp_full_ref = 12.0 * mu_SI * Um * L / H**2
entrance_length = 0.04 * (rho * Um * H / mu_SI) * H

bundle = {
    "name": "channel_poiseuille_water_20C",
    "solver": "incompressibleFluid",
    "files": {
        "system/blockMeshDict": blockMeshDict,
        "system/controlDict": controlDict,
        "system/fvSchemes": fvSchemes,
        "system/fvSolution": fvSolution,
        "constant/physicalProperties": physicalProperties,
        "constant/momentumTransport": momentumTransport,
        "0/U": U_file,
        "0/p": p_file,
    },
    "mesh": [
        {"executable": "blockMesh", "args": []},
        {"executable": "checkMesh", "args": []},
    ],
    "diagnostics": {
        "fields": [
            {"name": "p", "unit": "m^2/s^2", "positive": True},
            {"name": "U", "unit": "m/s", "components": 3},
        ],
        "quantities": [
            {"name": "p_inlet", "function": "surfaceFieldValue",
             "settings": {"select": "patch", "patch": "inlet", "operation": "areaAverage", "fields": "(p)"},
             "column": "areaAverage(p)", "statistic": "window_mean", "unit": "m^2/s^2"},
            {"name": "p_outlet", "function": "surfaceFieldValue",
             "settings": {"select": "patch", "patch": "outlet", "operation": "areaAverage", "fields": "(p)"},
             "column": "areaAverage(p)", "statistic": "window_mean", "unit": "m^2/s^2"},
            {"name": "p_x1", "function": "probes",
             "settings": {"fields": "(p)", "probeLocations": "((0.05 0.0025 0))"},
             "column": "0", "statistic": "window_mean", "unit": "m^2/s^2"},
            {"name": "p_x2", "function": "probes",
             "settings": {"fields": "(p)", "probeLocations": "((0.25 0.0025 0))"},
             "column": "0", "statistic": "window_mean", "unit": "m^2/s^2"},
        ],
        "derived": [
            {"name": "dp_core_kin", "op": "difference", "a": "quantity.p_x1", "b": "quantity.p_x2", "unit": "m^2/s^2"},
            {"name": "dp_core_Pa", "op": "scale", "a": "derived.dp_core_kin", "factor": rho, "factor_unit": "kg/m3", "unit": "Pa"},
            {"name": "dp_core_error_pct", "op": "abs_rel_error_pct", "a": "derived.dp_core_Pa", "reference": dp_core_ref, "unit": "%"},
            {"name": "dp_full_kin", "op": "difference", "a": "quantity.p_inlet", "b": "quantity.p_outlet", "unit": "m^2/s^2"},
            {"name": "dp_full_Pa", "op": "scale", "a": "derived.dp_full_kin", "factor": rho, "factor_unit": "kg/m3", "unit": "Pa"},
            {"name": "dp_full_error_pct", "op": "abs_rel_error_pct", "a": "derived.dp_full_Pa", "reference": dp_full_ref, "unit": "%"},
        ],
        "patches": ["inlet", "outlet", "walls", "frontAndBack"],
        "inlet": "inlet",
        "outlet": "outlet",
        "impermeable_patches": ["walls"],
        "expected_cells": nx * ny,
        "dimensions": 2,
        "target_time": 2000,
        "mass_balance": False,
        "stationarity_window": 50,
        "normalized": False,
    },
    "contract": {
        "id": "channel_poiseuille_water_20C",
        "title": "Laminar pressure drop in a 5 mm x 0.3 m 2D water channel at Um=0.02 m/s",
        "requested_prompt": "Water at 20 C flows through a 2D channel of height 5 mm and length 0.3 m at a mean velocity of 0.02 m/s. What is the pressure drop, and how does it compare with the analytic laminar value?",
        "regime": "steady",
        "objectives": [
            {
                "id": "healthy_steady_solution",
                "claim": "numerical_health",
                "description": "A healthy, mesh-resolved steady laminar solution is reached within budget (solver/mesh/case-integrity baseline checks are injected automatically at freeze; these cover the geometry- and field-specific health claims beyond that baseline).",
                "check_ids": [
                    "two_solution_directions", "cell_count_matches_spec", "expected_boundaries_present",
                    "no_cyclic_patches", "planar_empty_patch", "positive_all_saved",
                ],
            },
            {
                "id": "steady_state_reached",
                "claim": "stationarity",
                "description": "The SIMPLE iteration reaches a stationary (residual-converged) state before the horizon, and the reported quantities are read from that stationary window.",
                "check_ids": ["stationary_window_covered", "simple_converged"],
            },
            {
                "id": "pressure_drop_matches_poiseuille",
                "claim": "reference_agreement",
                "description": "The measured pressure drop in the fully-developed core of the channel (x = 0.05-0.25 m, beyond the ~0.02 m laminar entrance length) matches the analytic plane-Poiseuille gradient dp/dx = 12 mu Um / H^2.",
                "check_ids": ["core_pressure_drop_matches_analytic"],
            },
            {
                "id": "total_pressure_drop_reasonable",
                "claim": "quantity",
                "description": "The total inlet-to-outlet pressure drop (which also includes entrance-region excess loss) is reported and is consistent in magnitude with the fully-developed analytic total.",
                "check_ids": ["full_channel_pressure_drop_reasonable"],
            },
        ],
        "checks": [
            {"id": "two_solution_directions", "metric": "mesh.dimension_matches", "operator": "true", "unit": "1",
             "category": "mesh", "rationale": "The channel is planar: exactly two solution directions (x, y).", "failure": "hard"},
            {"id": "cell_count_matches_spec", "metric": "mesh.cell_count_matches", "operator": "true", "unit": "1",
             "category": "mesh", "rationale": "Realized cell count must equal the specified 150x60x1 block layout (9000 cells).", "failure": "hard"},
            {"id": "expected_boundaries_present", "metric": "mesh.expected_patches_present", "operator": "true", "unit": "1",
             "category": "boundary", "rationale": "Inlet, outlet, walls, and the spanwise empty patch must exist.", "failure": "hard"},
            {"id": "no_cyclic_patches", "metric": "mesh.cyclic_patch_count", "operator": "eq", "threshold": 0, "unit": "1",
             "category": "boundary", "rationale": "A cyclic patch would turn this into a different (periodic) problem.", "failure": "hard"},
            {"id": "planar_empty_patch", "metric": "mesh.planar_patch_present", "operator": "true", "unit": "1",
             "category": "boundary", "rationale": "The spanwise (z) direction must be declared empty for the 2D case.", "failure": "hard"},
            {"id": "positive_all_saved", "metric": "fields.positive_all_saved", "operator": "true", "unit": "1",
             "category": "admissibility", "rationale": "With the outlet referenced at p=0 and a monotonically falling pressure, kinematic pressure must stay non-negative everywhere in this unidirectional laminar flow.", "failure": "hard"},
            {"id": "stationary_window_covered", "metric": "stationarity.window_covered", "operator": "true", "unit": "1",
             "category": "stationarity", "rationale": "The reported window_mean statistics must be computed from a window that is at least as long as the declared stationarity window (50 iterations), so they are not contaminated by the startup transient.", "failure": "incomplete"},
            {"id": "simple_converged", "metric": "solver.converged_by_residual_control", "operator": "true", "unit": "1",
             "category": "stationarity", "rationale": "SIMPLE's residualControl block (p<1e-8, U<1e-9) must report convergence, confirming the steady solution has settled rather than merely exhausting the iteration budget.", "failure": "incomplete"},
            {"id": "core_pressure_drop_matches_analytic", "metric": "derived.dp_core_error_pct", "operator": "lt", "threshold": 5.0, "unit": "%",
             "category": "reference",
             "rationale": f"In the fully-developed core (x=0.05-0.25 m, well beyond the ~{entrance_length:.4f} m laminar entrance length for Re~100), the measured pressure gradient must match the analytic plane-Poiseuille formula dp/dx = 12*mu*Um/H^2 (reference {dp_core_ref:.5f} Pa over 0.2 m) to within 5%, a bound that covers the discretization error of a 150x60 orthogonal mesh at this Re without masking a genuine defect.",
             "failure": "hard"},
            {"id": "full_channel_pressure_drop_reasonable", "metric": "derived.dp_full_error_pct", "operator": "lt", "threshold": 25.0, "unit": "%",
             "category": "validation",
             "rationale": f"The inlet-to-outlet drop (reference {dp_full_ref:.5f} Pa for the fully-developed formula over the full 0.3 m) also carries an entrance-region excess loss bounded by a few multiples of the dynamic pressure 0.5*rho*Um^2 ({0.5*rho*Um**2:.4f} Pa, ~{0.5*rho*Um**2/dp_full_ref*100:.1f}% of the analytic total) plus outlet-BC discretization; 25% accommodates this physically-expected excess without masking a genuine solver defect.",
             "failure": "hard"},
        ],
        "authority": "proposed",
        "assumptions": [
            {"parameter": "fluid_density", "value": rho, "unit": "kg/m^3", "source": "documented_default",
             "justification": "Standard density of liquid water at 20 C, 1 atm (e.g. NIST/CRC tables, rho(20C)=998.2 kg/m^3)."},
            {"parameter": "fluid_kinematic_viscosity", "value": nu, "unit": "m^2/s", "source": "documented_default",
             "justification": "Standard kinematic viscosity of liquid water at 20 C (nu=1.004e-6 m^2/s, i.e. dynamic viscosity mu=1.0016e-3 Pa s)."},
            {"parameter": "geometry", "value": "2D planar channel, H=0.005 m, L=0.3 m", "unit": "1", "source": "user",
             "justification": "Directly stated in the request (channel height 5 mm, length 0.3 m, 2D)."},
            {"parameter": "inlet_velocity_profile", "value": "uniform (plug) inlet at the stated mean velocity 0.02 m/s", "unit": "1", "source": "derived",
             "justification": "The request gives only a mean velocity with no inlet profile; a uniform inlet is the standard choice and lets the laminar entrance region develop naturally inside the domain (entrance length ~0.02 m << 0.3 m domain length)."},
            {"parameter": "flow_regime", "value": "laminar, Re=rho*Um*H/mu~99.6", "unit": "1", "source": "derived",
             "justification": "Re~100 is far below the plane-channel transitional Reynolds number (~2300), so a laminar (not RAS/LES) model is the physically correct and budget-cheapest choice; this is not separately gated by a CFD-measured metric but follows directly from the stated geometry and velocity."},
        ],
        "reference": "Analytic reference: fully-developed plane (2D) Poiseuille flow between parallel plates, "
                     "dp/dx = 12*mu*Um/H^2 (e.g. F.M. White, Viscous Fluid Flow, 3rd ed., Sec. 3-2; "
                     "equivalently Fox, McDonald & Pritchard, Introduction to Fluid Mechanics, laminar "
                     "flow between parallel plates). Water properties at 20 C, 1 atm (rho=998.2 kg/m^3, "
                     "nu=1.004e-6 m^2/s) from standard tables (NIST WebBook / CRC Handbook of Chemistry "
                     "and Physics).",
        "limitations": [
            "Single-mesh verification on a 150x60 orthogonal grid; no formal mesh-independence (GCI) study was performed.",
            "The analytic reference (dp/dx = 12 mu Um / H^2) is the fully-developed plane-Poiseuille solution; it does not include the entrance-region excess pressure loss, which is why the full inlet-to-outlet comparison uses a looser tolerance than the core-region comparison.",
            "Water properties are standard 20 C table values, not independently re-derived from an equation of state.",
        ],
    },
    "budget": {
        "max_attempts": 4,
        "wall_seconds": 1800,
        "cpus": 2,
        "memory_mb": 4096,
        "max_cells": 50000,
        "mpi_ranks": 1,
        "max_end_time": 2000,
    },
}

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the water-channel example bundle")
    helper = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/result_paths.py"))
    output = helper["write_bundle"](parser, argv, bundle)
    print("written", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
