# OpenFOAM CFD Agent

A generalizable CFD simulation agent powered by OpenFOAM v2512. It infers simulation
scenarios from natural language prompts, automatically maps physical parameters, executes
appropriate solvers, and extracts quantitative metrics reported directly in chat.

## Overview

This agent solves the problem of making CFD accessible to non-specialists. Instead of
requiring users to manually set up OpenFOAM case directories, select solvers, define boundary
conditions, and parse output files, the agent:

- **Infers** the scenario type from a natural language description
- **Maps** physical parameters using engineering defaults where needed
- **Sets up** the complete OpenFOAM case (mesh, BCs, solver settings)
- **Runs** the appropriate solver (simpleFoam, icoFoam, buoyantSimpleFoam, etc.)
- **Extracts** quantitative metrics (ΔP, Cd, Cl, Nu, heat flux, etc.)
- **Reports** results as structured data — no visualizations

**Intended users**: Engineers, researchers, and students who need quick CFD estimates
without deep OpenFOAM expertise.

## Architecture

```
User prompt → LLM (scenario inference) → Python script
    → openfoam_utils.py (case setup)
    → blockMesh (mesh generation)
    → solver (simpleFoam/icoFoam/etc.)
    → postProcess (metrics extraction)
    → final_results.json → chat response
```

- **Model**: GPT (configured at deploy time via `{{CHAT-MODEL}}`)
- **Container**: `opencfd/openfoam-run:2512` base + Python scientific stack
- **No external APIs**: All computation runs locally in the container
- **Data flow**: User prompt → Python script → OpenFOAM case → metrics JSON

## Prerequisites

- Azure subscription with Discovery workspace
- Model deployment (e.g., `gpt-5-2`, `gpt-4o`)
- CPU compute nodepool (4+ vCPU, 8+ GB RAM recommended)
- No GPU required

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Model deployment name | `gpt-5-2` |

## Tools

| Tool | Description |
|---|---|
| `openfoam` | OpenFOAM v2512 CFD simulation tool. Container includes blockMesh, simpleFoam, icoFoam, buoyantSimpleFoam, pimpleFoam, decomposePar, reconstructPar, postProcess. Runs on CPU nodes (2-4 vCPU, 8-32 GB RAM). Input via Python scripts at `/input/`, output to `/output/`. |

## Usage

### Example 1: Pipe Flow Pressure Drop

**Prompt**: "What's the pressure drop in a 2-inch pipe with water flowing at 2 m/s over 5 meters?"

**Agent infers**: Internal pipe flow, D=0.0508m, L=5m, U=2m/s, ν=1e-6, Re≈101,600 (turbulent)

**Output**:
```json
{
  "pressure_drop_Pa": 1523.7,
  "friction_factor": 0.0184,
  "reynolds_number": 101600,
  "converged": true
}
```

### Example 2: Drag on a Cylinder

**Prompt**: "Calculate drag coefficient on a cylinder at Re=100"

**Agent infers**: External flow, Re=100, laminar, D=0.01m → U=0.01m/s

### Example 3: Heated Plate Convection

**Prompt**: "Convective heat transfer from a 400K plate in 1 m/s airflow"

**Agent infers**: Heat transfer, T_wall=400K, T_inf=300K, U=1m/s, air (ν=1.5e-5)

## Supported Scenarios

| Scenario | Solver | Key Metrics |
|----------|--------|-------------|
| Internal pipe/duct flow | simpleFoam / icoFoam | ΔP, friction factor, Re |
| External flow over body | simpleFoam | Cd, Cl, wake frequency |
| Heat transfer | simpleFoam + scalar transport | Nu, heat flux, ΔT |
| Lid-driven cavity | icoFoam | Centerline profiles, vortex positions |
| Rotating machinery (MRF) | simpleFoam + MRF | Pressure rise, torque |

## Support

- Issues: https://github.com/microsoft/discovery-catalog/issues
- Contact: discovery-catalog@microsoft.com

## Known Limitations

- **2D/simplified geometry only**: Uses blockMesh for structured grids. Complex 3D
  geometries (CAD imports, snappyHexMesh) are not yet supported.
- **No visualization**: Reports metrics as numbers only. Use ParaView separately for
  flow visualization.
- **Steady-state bias**: Most scenarios default to steady-state RANS. Transient LES/DNS
  requires explicit user request.
- **Single-phase only**: No multiphase (VOF, Euler-Euler) support currently.
- **No compressible flow**: Subsonic incompressible only (no rhoSimpleFoam/rhoPimpleFoam).

## Contributing

See the repository's CONTRIBUTING.md for guidelines on adding new scenarios, solvers,
or mesh generation capabilities.
