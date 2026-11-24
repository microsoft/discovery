import argparse
import runpy
from pathlib import Path

def hdr(cls, obj, loc):
    return f"""FoamFile
{{
    format      ascii;
    class       {cls};
    location    "{loc}";
    object      {obj};
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

"""

files = {}

# ---------------- constant/momentumTransport ----------------
files["constant/momentumTransport"] = hdr("dictionary", "momentumTransport", "constant") + """simulationType laminar;

// ************************************************************************* //
"""

# ---------------- constant/physicalProperties ----------------
files["constant/physicalProperties"] = hdr("dictionary", "physicalProperties", "constant") + """viscosityModel  constant;

nu              1.5e-05;

// ************************************************************************* //
"""

# ---------------- system/blockMeshDict ----------------
x0, x1, x2, x3 = -0.08, 0.0, 0.01, 0.22
y0, y1, y2 = 0.0, 0.01, 0.04
z0, z1 = -0.5, 0.5

nx_A, nx_B, nx_C = 70, 24, 110
ny_low, ny_up = 24, 40

verts = []
for (zi, z) in enumerate([z0, z1]):
    for (yi, y) in enumerate([y0, y1, y2]):
        for (xi, x) in enumerate([x0, x1, x2, x3]):
            verts.append((x, y, z))

def idx(xi, yi, zi):
    return zi*12 + yi*4 + xi

vert_lines = "\n".join(f"    ({v[0]:.6g} {v[1]:.6g} {v[2]:.6g})" for v in verts)

blocks = [
    ("hex", [idx(0,0,0), idx(1,0,0), idx(1,1,0), idx(0,1,0), idx(0,0,1), idx(1,0,1), idx(1,1,1), idx(0,1,1)], nx_A, ny_low, "0.1 1 1"),
    ("hex", [idx(0,1,0), idx(1,1,0), idx(1,2,0), idx(0,2,0), idx(0,1,1), idx(1,1,1), idx(1,2,1), idx(0,2,1)], nx_A, ny_up, "0.1 8 1"),
    ("hex", [idx(1,1,0), idx(2,1,0), idx(2,2,0), idx(1,2,0), idx(1,1,1), idx(2,1,1), idx(2,2,1), idx(1,2,1)], nx_B, ny_up, "1 8 1"),
    ("hex", [idx(2,0,0), idx(3,0,0), idx(3,1,0), idx(2,1,0), idx(2,0,1), idx(3,0,1), idx(3,1,1), idx(2,1,1)], nx_C, ny_low, "15 1 1"),
    ("hex", [idx(2,1,0), idx(3,1,0), idx(3,2,0), idx(2,2,0), idx(2,1,1), idx(3,1,1), idx(3,2,1), idx(2,2,1)], nx_C, ny_up, "15 8 1"),
]

block_lines = []
for (kw, vv, nx, ny, grad) in blocks:
    vstr = " ".join(str(v) for v in vv)
    block_lines.append(f"    {kw} ({vstr}) ({nx} {ny} 1) simpleGrading ({grad})")
blocks_txt = "\n".join(block_lines)

def face(vv):
    return "(" + " ".join(str(v) for v in vv) + ")"

inlet_faces = [face([idx(0,0,0), idx(0,1,0), idx(0,1,1), idx(0,0,1)]),
               face([idx(0,1,0), idx(0,2,0), idx(0,2,1), idx(0,1,1)])]
outlet_faces = [face([idx(3,0,0), idx(3,1,0), idx(3,1,1), idx(3,0,1)]),
                face([idx(3,1,0), idx(3,2,0), idx(3,2,1), idx(3,1,1)])]
walls_faces = [face([idx(0,0,0), idx(1,0,0), idx(1,0,1), idx(0,0,1)]),   # A-lower floor
               face([idx(2,0,0), idx(3,0,0), idx(3,0,1), idx(2,0,1)]),   # C-lower floor
               face([idx(0,2,0), idx(1,2,0), idx(1,2,1), idx(0,2,1)]),   # A-upper ceiling
               face([idx(1,2,0), idx(2,2,0), idx(2,2,1), idx(1,2,1)]),   # B ceiling
               face([idx(2,2,0), idx(3,2,0), idx(3,2,1), idx(2,2,1)])]   # C-upper ceiling
obstacle_faces = [face([idx(1,0,0), idx(1,1,0), idx(1,1,1), idx(1,0,1)]),  # front (upstream) vertical face
                  face([idx(1,1,0), idx(2,1,0), idx(2,1,1), idx(1,1,1)]),  # top horizontal face
                  face([idx(2,0,0), idx(2,1,0), idx(2,1,1), idx(2,0,1)])]  # back (downstream) vertical face

def faces_block(name):
    return "\n".join(f"            {f}" for f in name)

blockmesh = hdr("dictionary", "blockMeshDict", "system") + f"""convertToMeters 1;

vertices
(
{vert_lines}
);

blocks
(
{blocks_txt}
);

edges
(
);

defaultPatch
{{
    name frontAndBack;
    type empty;
}}

boundary
(
    inlet
    {{
        type patch;
        faces
        (
{faces_block(inlet_faces)}
        );
    }}
    outlet
    {{
        type patch;
        faces
        (
{faces_block(outlet_faces)}
        );
    }}
    walls
    {{
        type wall;
        faces
        (
{faces_block(walls_faces)}
        );
    }}
    obstacle
    {{
        type wall;
        faces
        (
{faces_block(obstacle_faces)}
        );
    }}
);

mergePatchPairs
(
);

// ************************************************************************* //
"""
files["system/blockMeshDict"] = blockmesh

ncells = nx_A*ny_low + nx_A*ny_up + nx_B*ny_up + nx_C*ny_low + nx_C*ny_up

# ---------------- system/controlDict ----------------
files["system/controlDict"] = hdr("dictionary", "controlDict", "system") + """solver          incompressibleFluid;

startFrom       startTime;

startTime       0;

stopAt          endTime;

endTime         1.6;

deltaT          0.0001;

writeControl    adjustableRunTime;

writeInterval   0.02;

purgeWrite      0;

writeFormat     ascii;

writePrecision  6;

writeCompression off;

timeFormat      general;

timePrecision   6;

runTimeModifiable yes;

adjustTimeStep  yes;

maxCo           1;

// ************************************************************************* //
"""

# ---------------- system/fvSchemes ----------------
files["system/fvSchemes"] = hdr("dictionary", "fvSchemes", "system") + """ddtSchemes
{
    default         Euler;
}

gradSchemes
{
    default         Gauss linear;
    limited         cellLimited Gauss linear 1;
}

divSchemes
{
    default             none;

    div(phi,U)          Gauss linearUpwind limited;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
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

// ************************************************************************* //
"""

# ---------------- system/fvSolution ----------------
files["system/fvSolution"] = hdr("dictionary", "fvSolution", "system") + """solvers
{
    p
    {
        solver           GAMG;
        smoother         DICGaussSeidel;
        tolerance        1e-7;
        relTol           0.01;
    }

    pFinal
    {
        $p;
        relTol          0;
    }

    U
    {
        solver          PBiCGStab;
        preconditioner  DILU;
        tolerance       1e-08;
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

// ************************************************************************* //
"""

# ---------------- 0/U ----------------
files["0/U"] = hdr("volVectorField", "U", "0") + """dimensions      [0 1 -1 0 0 0 0];

internalField   uniform (0.5 0 0);

boundaryField
{
    inlet
    {
        type            fixedValue;
        value           uniform (0.5 0 0);
    }
    outlet
    {
        type            zeroGradient;
    }
    walls
    {
        type            noSlip;
    }
    obstacle
    {
        type            noSlip;
    }
    frontAndBack
    {
        type            empty;
    }
}

// ************************************************************************* //
"""

# ---------------- 0/p ----------------
files["0/p"] = hdr("volScalarField", "p", "0") + """dimensions      [0 2 -2 0 0 0 0];

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
    obstacle
    {
        type            zeroGradient;
    }
    frontAndBack
    {
        type            empty;
    }
}

// ************************************************************************* //
"""

# ---------------- bundle assembly ----------------
rho = 1.2
U = 0.5
s = 0.01
Aref = s * 1.0  # per-unit-depth frontal area (1 m depth encoded in mesh)
factor = 0.5 * rho * U * U * Aref

bundle = {
    "schema_version": "1.0",
    "name": "wall_mounted_square_obstacle_channel",
    "adapter": "openfoam-foundation14",
    "solver": "incompressibleFluid",
    "files": files,
    "mesh": [
        {"executable": "blockMesh"},
        {"executable": "checkMesh"}
    ],
    "diagnostics": {
        "fields": [
            {"name": "U", "components": 3, "unit": "m/s"},
            {"name": "p", "unit": "m^2/s^2"}
        ],
        "quantities": [
            {
                "name": "Cd_mean",
                "function": "forceCoeffs",
                "settings": {
                    "patches": "(obstacle)",
                    "rhoInf": "1.2",
                    "rho": "rhoInf",
                    "magUInf": "0.5",
                    "lRef": "0.01",
                    "Aref": "0.01",
                    "dragDir": "(1 0 0)",
                    "liftDir": "(0 1 0)",
                    "CofR": "(0.005 0.005 0)",
                    "pitchAxis": "(0 0 1)"
                },
                "column": "Cd",
                "statistic": "window_mean",
                "unit": "1"
            },
            {
                "name": "Cd_span",
                "function": "forceCoeffs",
                "settings": {
                    "patches": "(obstacle)",
                    "rhoInf": "1.2",
                    "rho": "rhoInf",
                    "magUInf": "0.5",
                    "lRef": "0.01",
                    "Aref": "0.01",
                    "dragDir": "(1 0 0)",
                    "liftDir": "(0 1 0)",
                    "CofR": "(0.005 0.005 0)",
                    "pitchAxis": "(0 0 1)"
                },
                "column": "Cd",
                "statistic": "window_relative_span",
                "unit": "1"
            },
            {
                "name": "Cl_mean",
                "function": "forceCoeffs",
                "settings": {
                    "patches": "(obstacle)",
                    "rhoInf": "1.2",
                    "rho": "rhoInf",
                    "magUInf": "0.5",
                    "lRef": "0.01",
                    "Aref": "0.01",
                    "dragDir": "(1 0 0)",
                    "liftDir": "(0 1 0)",
                    "CofR": "(0.005 0.005 0)",
                    "pitchAxis": "(0 0 1)"
                },
                "column": "Cl",
                "statistic": "window_mean",
                "unit": "1"
            }
        ],
        "derived": [
            {"name": "Fx_per_depth", "op": "scale", "a": "quantity.Cd_mean", "factor": factor, "unit": "N/m"},
            {"name": "Fy_per_depth", "op": "scale", "a": "quantity.Cl_mean", "factor": factor, "unit": "N/m"}
        ],
        "patches": ["inlet", "outlet", "walls", "obstacle"],
        "inlet": "inlet",
        "outlet": "outlet",
        "impermeable_patches": ["walls", "obstacle"],
        "expected_cells": ncells,
        "dimensions": 2,
        "target_time": 1.6,
        "mass_balance": False,
        "stationarity_window": 0.4,
        "normalized": False
    },
    "contract": {
        "schema_version": "1.0",
        "id": "square_obstacle_channel_force",
        "title": "Force on a 2D wall-mounted square obstacle in a 40 mm channel at 0.5 m/s",
        "requested_prompt": "A 2D square obstacle (side 10 mm) sits on the floor of a channel 40 mm high carrying air at 0.5 m/s. Report the force on the obstacle per unit depth.",
        "regime": "transient",
        "objectives": [
            {
                "id": "drag_force",
                "description": "Measure the time-averaged streamwise (drag) force per unit depth on the wall-mounted square obstacle (10 mm side) in a 40 mm-high channel with 0.5 m/s uniform air inflow (Re_s = U*s/nu ~ 333 based on obstacle side).",
                "claim": "quantity",
                "check_ids": ["cd_admissible", "cd_bounded_oscillation"]
            },
            {
                "id": "lift_force",
                "description": "Measure the time-averaged wall-normal (lift) force per unit depth on the same obstacle; a non-zero value is physically expected because the obstacle sits on the floor (no top-bottom symmetry) of the blocked channel.",
                "claim": "quantity",
                "check_ids": ["cl_admissible"]
            },
            {
                "id": "mass_conservation",
                "description": "Verify conservation of mass flux between inlet, outlet and impermeable walls over the simulated unsteady flow, and that the flux monitors remain bounded over the trailing multi-period window.",
                "claim": "conservation",
                "check_ids": ["net_flux_balance", "impermeable_walls_sealed", "flux_monitor_bounded"]
            }
        ],
        "checks": [
            {
                "id": "cd_admissible",
                "metric": "quantity.Cd_mean",
                "operator": "between",
                "threshold": [0.0, 5.0],
                "unit": "1",
                "category": "admissibility",
                "rationale": "For a bluff body at Re~O(300), the drag coefficient referenced to frontal area must be a finite, positive, order-1 quantity; values outside [0,5] indicate a divergent solver or a mis-specified force patch/reference area rather than a physical result.",
                "failure": "hard"
            },
            {
                "id": "cl_admissible",
                "metric": "quantity.Cl_mean",
                "operator": "between",
                "threshold": [-5.0, 5.0],
                "unit": "1",
                "category": "admissibility",
                "rationale": "The wall-normal force coefficient on a wall-mounted obstacle in this low-blockage, laminar regime is expected to be bounded and of comparable magnitude to the drag coefficient; |Cl|>5 would indicate an unphysical or diverging solution.",
                "failure": "hard"
            },
            {
                "id": "fx_admissible",
                "metric": "derived.Fx_per_depth",
                "operator": "between",
                "threshold": [-0.01, 0.01],
                "unit": "N/m",
                "category": "admissibility",
                "rationale": "Direct consistency bound on the reported streamwise force per unit depth, derived from the same [0,5] admissible Cd range scaled by 0.5*rho*U^2*Aref = 0.0015 N/m; catches unit/scaling errors in the derived force independently of the dimensionless coefficient check.",
                "failure": "hard"
            },
            {
                "id": "fy_admissible",
                "metric": "derived.Fy_per_depth",
                "operator": "between",
                "threshold": [-0.01, 0.01],
                "unit": "N/m",
                "category": "admissibility",
                "rationale": "Direct consistency bound on the reported wall-normal force per unit depth, derived from the same [-5,5] admissible Cl range scaled by 0.5*rho*U^2*Aref = 0.0015 N/m; catches unit/scaling errors in the derived force independently of the dimensionless coefficient check.",
                "failure": "hard"
            },
            {
                "id": "cd_bounded_oscillation",
                "metric": "quantity.Cd_span",
                "operator": "lt",
                "threshold": 1.5,
                "unit": "1",
                "category": "stationarity",
                "rationale": "At Re~300 a 2D square bluff body is expected to shed periodic Karman-type vortices, producing a bounded instantaneous Cd oscillation of roughly 10-50% of its mean (consistent with 2D laminar square-cylinder studies, e.g. Sohankar et al. 1998); a relative span below 1.5 over the trailing multi-period window confirms the solution has reached a bounded periodic (or steady) regime rather than still being transient or numerically diverging. This is a bounded-oscillation/numerical-health criterion, not a claim that the instantaneous force itself is constant.",
                "failure": "incomplete"
            },
            {
                "id": "net_flux_balance",
                "metric": "conservation.final_net_flux_rel",
                "operator": "lt",
                "threshold": 0.02,
                "unit": "1",
                "category": "conservation",
                "rationale": "Incompressible flow carries zero net mass storage at any instant, so the sum of volumetric flux across all boundary patches (inlet+outlet+walls+obstacle) must vanish up to spatial discretization error at every timestep, independent of the flow being unsteady/periodic; 2% is a generous bound given the modest (~12,500-cell) mesh resolution.",
                "failure": "hard"
            },
            {
                "id": "impermeable_walls_sealed",
                "metric": "conservation.impermeable_flux_max_rel",
                "operator": "lt",
                "threshold": 0.02,
                "unit": "1",
                "category": "conservation",
                "rationale": "The floor/ceiling walls and the obstacle itself are solid no-slip (impermeable) boundaries; any significant net flux measured through them over the run would indicate a leaking boundary condition or a mesh/geometry defect rather than physical flow.",
                "failure": "hard"
            },
            {
                "id": "flux_monitor_bounded",
                "metric": "stationarity.monitor_drift_max",
                "operator": "lt",
                "threshold": 1.0,
                "unit": "1",
                "category": "stationarity",
                "rationale": "Bounded fluctuation of the inlet/outlet flux monitors over the trailing multi-period window indicates the periodic unsteady solution has reached a repeatable regime; 1.0 (100% relative span) is generous given the outlet flux is itself modulated by vortex shedding, while still catching genuine runaway drift or non-convergence.",
                "failure": "incomplete"
            }
        ],
        "assumptions": [
            {"parameter": "inlet_velocity", "value": 0.5, "unit": "m/s", "source": "user", "justification": "Stated directly in the request as the channel inflow speed; applied as a uniform velocity profile at the inlet."},
            {"parameter": "fluid", "value": "air, rho=1.2 kg/m^3, nu=1.5e-5 m^2/s", "source": "documented_default", "justification": "Standard atmospheric air properties (~20C, 1 atm) used because the request specifies 'air' without stating temperature/pressure."},
            {"parameter": "regime", "value": "2D laminar transient", "source": "derived", "justification": "Re_s = U*s/nu = 0.5*0.01/1.5e-5 ~= 333 based on the obstacle side length, well within the range where 2D square bluff bodies (confined or not) exhibit unsteady periodic vortex shedding rather than being fully turbulent; no turbulence model is applied and the flow is resolved as transient laminar."},
            {"parameter": "channel_walls", "value": "floor and ceiling both no-slip solid walls", "source": "documented_default", "justification": "'Channel' denotes a bounded duct; both bounding surfaces are treated as solid no-slip walls, consistent with standard internal-flow terminology."},
            {"parameter": "domain_extent", "value": "upstream fetch 8*s, downstream fetch 21*s, depth 1 m", "source": "derived", "justification": "Upstream/downstream fetch chosen generously relative to the obstacle size to let the approach flow and wake develop without strong boundary feedback from the inlet/outlet; the domain is given a 1 m span so the OpenFOAM-reported total force is numerically equal to the force per unit depth."},
            {"parameter": "mesh_cells", "value": ncells, "unit": "1", "source": "derived", "justification": "Graded 5-block structured mesh (~12,480 cells) refined to ~0.42 mm near the obstacle, kept well under the 50,000-cell budget while resolving the obstacle boundary layer and near wake."}
        ],
        "limitations": [
            "Case is strictly 2D (span-wise infinite obstacle); no 3D end effects are represented.",
            "Flow is laminar (no turbulence model); if the true physical Reynolds number locally exceeds the laminar-to-turbulent transition this would underpredict turbulent mixing in the wake.",
            "Reported force is a time/phase average over a trailing multi-period window of a periodically unsteady signal, not a steady force; the instantaneous force oscillates about this mean due to vortex shedding.",
            "No experimental or literature reference value is claimed for this specific confined (25% blockage) wall-mounted geometry; only internal admissibility/bounded-oscillation checks are used."
        ],
        "authority": "proposed",
        "reference": "No external validation claimed; internal admissibility and bounded-oscillation checks only."
    },
    "budget": {
        "max_attempts": 4,
        "wall_seconds": 1800,
        "cpus": 2,
        "memory_mb": 4096,
        "max_cells": 50000,
        "max_output_mb": 2048,
        "mpi_ranks": 1
    }
}

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the square-obstacle example bundle")
    helper = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/result_paths.py"))
    output = helper["write_bundle"](parser, argv, bundle)
    print("Wrote", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
