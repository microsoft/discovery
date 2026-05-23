#!/usr/bin/env python3
"""OpenFOAM utilities library for Discovery platform CFD workflows.

Provides scenario-driven case setup, solver execution, and metrics extraction
for generalizable CFD simulations using OpenFOAM v2512.

Container image: opencfd/openfoam-run:2512 (runtime-only, ~246 MB).
Available binaries: blockMesh, simpleFoam, icoFoam, buoyantSimpleFoam,
    pimpleFoam, topoSet, decomposePar, reconstructPar, postProcess.
NOT available: snappyHexMesh, surfaceFeatureExtract, checkMesh
    (these require the larger openfoam-default image).
"""
import os
import sys
import glob
import json
import logging
import subprocess
import shutil
import re
import shlex
import time
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# ============= CONSTANTS =============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/openfoam_scratch"
OPENFOAM_DIR = os.environ.get("OPENFOAM_DIR", "/usr/lib/openfoam/openfoam2512")
OPENFOAM_BASHRC = os.path.join(OPENFOAM_DIR, "etc", "bashrc")

# Discovery Studio mounts user-attached files at /mnt/work
STUDIO_WORK_DIR = "/mnt/work"


# ============= SETUP FUNCTIONS =============


def _validate_positive(**kwargs) -> None:
    """Raise ValueError if any named argument is not strictly positive."""
    for name, val in kwargs.items():
        if val is None:
            continue
        if not isinstance(val, (int, float)):
            raise TypeError(f"{name} must be numeric, got {type(val).__name__}")
        if val <= 0:
            raise ValueError(f"{name} must be positive, got {val}")


def quick_setup(input_dir: str = '/input', output_dir: str = '/output',
                work_dir: str = '/workdir') -> None:
    """Initialize logging, create directories, copy input files.

    Also copies any user-attached files from /mnt/work (Discovery Studio)
    into the input directory so scripts can access them uniformly via /input/.

    Note: This function mutates module-level globals (INPUT_DIR, OUTPUT_DIR,
    WORK_DIR) for convenience.  It is designed for single-script-per-process
    execution inside an OpenFOAM container and is NOT safe for concurrent use.
    """
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    for d in [WORK_DIR, OUTPUT_DIR, SCRATCH_DIR]:
        os.makedirs(d, exist_ok=True)
    os.chdir(WORK_DIR)
    _copy_studio_files()
    _copy_input_files()
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Input files: {os.listdir(INPUT_DIR) if os.path.exists(INPUT_DIR) else '(none)'}")


def _copy_studio_files() -> None:
    """Copy user-attached files from Discovery Studio's /mnt/work to /input/.

    In Discovery Studio (web UI), user-attached files are mounted at /mnt/work/
    rather than /input/. This function copies them so scripts can uniformly
    read from /input/ regardless of whether they run via Workbench or Studio.
    """
    if not os.path.exists(STUDIO_WORK_DIR):
        return
    studio_files = glob.glob(os.path.join(STUDIO_WORK_DIR, '*'))
    if not studio_files:
        return
    os.makedirs(INPUT_DIR, exist_ok=True)
    for f in studio_files:
        if os.path.isfile(f):
            dest = os.path.join(INPUT_DIR, os.path.basename(f))
            if not os.path.exists(dest):  # don't overwrite existing inputs
                shutil.copy(f, dest)
                logging.info(f"Studio file copied: {os.path.basename(f)}")
        elif os.path.isdir(f):
            dest_dir = os.path.join(INPUT_DIR, os.path.basename(f))
            if not os.path.exists(dest_dir):
                shutil.copytree(f, dest_dir)
                logging.info(f"Studio directory copied: {os.path.basename(f)}")


def _copy_input_files() -> None:
    """Copy input files to working directory."""
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        return
    if os.path.exists(INPUT_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, '*')):
            if os.path.isfile(f):
                shutil.copy(f, WORK_DIR)


def quick_finish() -> None:
    """Copy key output files to /output."""
    _copy_outputs()


def _copy_outputs() -> None:
    """Copy output files to output directory."""
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    patterns = ['*.json', '*.csv', '*.log', '*.dat']
    for pattern in patterns:
        for f in glob.glob(os.path.join(WORK_DIR, pattern)):
            shutil.copy(f, OUTPUT_DIR)
    logging.info("Outputs copied to /output")


def save_final_results(results: Dict, output_files: Dict = None,
                       file_descriptions: Dict = None,
                       status: str = "completed") -> None:
    """Save final results to JSON file (MANDATORY for every script)."""
    final_data = {"status": status, "summary": results}
    if output_files:
        final_data["output_files"] = output_files
    if file_descriptions:
        final_data["file_descriptions"] = file_descriptions
    path = os.path.join(OUTPUT_DIR, 'final_results.json')
    with open(path, 'w') as f:
        json.dump(final_data, f, indent=2, default=str)
    logging.info(f"Saved final_results.json to {path}")


# ============= OPENFOAM COMMAND EXECUTION =============

def run_openfoam_cmd(cmd: List[str], case_dir: str = ".",
                     log_file: Optional[str] = None,
                     timeout: int = 3600) -> subprocess.CompletedProcess:
    """Execute an OpenFOAM command with proper environment sourcing.

    Args:
        cmd: Command and arguments (e.g., ['blockMesh'])
        case_dir: OpenFOAM case directory
        log_file: Optional log file path
        timeout: Timeout in seconds (default 1 hour)

    Returns:
        CompletedProcess result
    """
    # Run command directly — the entrypoint already loaded the OpenFOAM env
    # via /app/openfoam_env.sh. Do NOT re-source the bashrc here; it triggers
    # a fatal pop_var_context error on bash 5.2+.
    cmd_str = ' '.join(shlex.quote(c) for c in cmd)
    shell_cmd = f"cd {shlex.quote(case_dir)} && {cmd_str}"

    # Ensure BASH_ENV is unset so bash doesn't auto-source the bashrc
    run_env = {**os.environ, 'BASH_ENV': ''}

    logging.info(f"Running: {cmd_str} in {case_dir}")
    try:
        result = subprocess.run(
            ['bash', '-c', shell_cmd],
            capture_output=True, text=True, timeout=timeout,
            env=run_env
        )
        if log_file:
            with open(log_file, 'w') as f:
                f.write(f"=== STDOUT ===\n{result.stdout}\n")
                f.write(f"=== STDERR ===\n{result.stderr}\n")
                f.write(f"=== RETURN CODE: {result.returncode} ===\n")

        if result.returncode != 0:
            logging.error(f"Command failed (rc={result.returncode}): {result.stderr[-500:]}")
            raise RuntimeError(
                f"OpenFOAM command '{cmd_str}' failed with rc={result.returncode}.\n"
                f"stderr: {result.stderr[-1000:]}"
            )
        logging.info(f"Command completed: {cmd_str}")
        return result
    except subprocess.TimeoutExpired:
        logging.error(f"Command timed out after {timeout}s: {cmd_str}")
        raise


def run_block_mesh(case_dir: str = ".") -> subprocess.CompletedProcess:
    """Run blockMesh to generate the computational mesh."""
    return run_openfoam_cmd(['blockMesh'], case_dir,
                            log_file=os.path.join(case_dir, 'log.blockMesh'))


def run_solver(solver_name: str, case_dir: str = ".",
               timeout: int = 3600) -> subprocess.CompletedProcess:
    """Run an OpenFOAM solver.

    Args:
        solver_name: e.g. 'simpleFoam', 'icoFoam', 'buoyantSimpleFoam', 'pimpleFoam'
        case_dir: OpenFOAM case directory
        timeout: Timeout in seconds
    """
    return run_openfoam_cmd([solver_name], case_dir,
                            log_file=os.path.join(case_dir, f'log.{solver_name}'),
                            timeout=timeout)


def run_decompose_par(case_dir: str = ".") -> subprocess.CompletedProcess:
    """Run decomposePar for parallel execution.

    Note: The number of subdomains is read from system/decomposeParDict
    (written by write_decompose_par_dict), not from this function's arguments.
    """
    return run_openfoam_cmd(['decomposePar', '-force'], case_dir,
                            log_file=os.path.join(case_dir, 'log.decomposePar'))


def run_parallel_solver(solver_name: str, case_dir: str = ".",
                        n_procs: int = 4,
                        timeout: int = 3600) -> subprocess.CompletedProcess:
    """Run solver in parallel with MPI."""
    cmd = ['mpirun', '-np', str(n_procs), solver_name, '-parallel']
    return run_openfoam_cmd(cmd, case_dir,
                            log_file=os.path.join(case_dir, f'log.{solver_name}'),
                            timeout=timeout)


def run_reconstruct_par(case_dir: str = ".") -> subprocess.CompletedProcess:
    """Run reconstructPar after parallel execution."""
    return run_openfoam_cmd(['reconstructPar'], case_dir,
                            log_file=os.path.join(case_dir, 'log.reconstructPar'))


def run_post_process(func_name: str, case_dir: str = ".",
                     latest_time: bool = True) -> subprocess.CompletedProcess:
    """Run postProcess with a function object.

    Args:
        func_name: e.g. 'yPlus', 'wallShearStress', 'forces'
        case_dir: case directory
        latest_time: if True, only process the latest time step
    """
    cmd = ['postProcess', '-func', func_name]
    if latest_time:
        cmd.append('-latestTime')
    return run_openfoam_cmd(cmd, case_dir,
                            log_file=os.path.join(case_dir, f'log.postProcess.{func_name}'))


# ============= CASE DIRECTORY SETUP =============

def create_case_directory(case_dir: str) -> str:
    """Create the standard OpenFOAM case directory structure.

    Returns the absolute path to the case directory.
    """
    case_path = os.path.abspath(case_dir)
    for subdir in ['0', 'constant', 'system']:
        os.makedirs(os.path.join(case_path, subdir), exist_ok=True)
    logging.info(f"Created case directory: {case_path}")
    return case_path


def write_file(case_dir: str, rel_path: str, content: str) -> str:
    """Write a file to the case directory.

    Args:
        case_dir: Root case directory
        rel_path: Relative path within case (e.g., 'system/controlDict')
        content: File content

    Returns:
        Absolute path to the written file
    """
    full_path = os.path.join(case_dir, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w') as f:
        f.write(content)
    return full_path


# ============= OPENFOAM HEADER =============

def foam_header(class_name: str, object_name: str,
                location: str = "") -> str:
    """Generate standard OpenFOAM file header.

    Args:
        class_name: e.g. 'dictionary', 'volScalarField', 'volVectorField'
        object_name: e.g. 'controlDict', 'p', 'U'
        location: e.g. 'system', 'constant', '0'
    """
    loc_line = f'    location    "{location}";' if location else ''
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       {class_name};
{loc_line}
    object      {object_name};
}}
"""


# ============= SYSTEM DIRECTORY FILES =============

def write_control_dict(case_dir: str, end_time: float = 1000,
                       delta_t: float = 1, write_interval: int = 100,
                       application: str = "simpleFoam",
                       adjustable_time_step: bool = False,
                       max_co: float = 1.0,
                       functions: str = "") -> str:
    """Write system/controlDict.

    Args:
        case_dir: Case directory
        end_time: End time or number of iterations
        delta_t: Time step
        write_interval: Write interval
        application: Solver name
        adjustable_time_step: Enable adaptive time stepping (transient)
        max_co: Maximum Courant number (transient)
        functions: Additional function objects block
    """
    adjust_block = ""
    if adjustable_time_step:
        adjust_block = f"""
adjustTimeStep  yes;
maxCo           {max_co};
"""

    content = foam_header("dictionary", "controlDict", "system") + f"""
application     {application};

startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {end_time};

deltaT          {delta_t};

writeControl    timeStep;
writeInterval   {write_interval};

purgeWrite      3;

writeFormat     ascii;
writePrecision  8;
writeCompression off;

timeFormat      general;
timePrecision   6;

runTimeModifiable true;
{adjust_block}
{functions}
"""
    return write_file(case_dir, 'system/controlDict', content)


def write_fv_schemes(case_dir: str, steady: bool = True) -> str:
    """Write system/fvSchemes with appropriate discretization.

    Args:
        case_dir: Case directory
        steady: True for steady-state (simpleFoam), False for transient
    """
    ddt = "steadyState" if steady else "Euler"
    content = foam_header("dictionary", "fvSchemes", "system") + f"""
ddtSchemes
{{
    default         {ddt};
}}

gradSchemes
{{
    default         Gauss linear;
    grad(U)         cellLimited Gauss linear 1;
    grad(p)         Gauss linear;
}}

divSchemes
{{
    default         none;
    div(phi,U)      bounded Gauss linearUpwind grad(U);
    div(phi,k)      bounded Gauss upwind;
    div(phi,omega)  bounded Gauss upwind;
    div(phi,epsilon) bounded Gauss upwind;
    div(phi,T)      bounded Gauss linearUpwind default;
    div(phi,nuTilda) bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
    div((nuEff*dev(T(grad(U))))) Gauss linear;
}}

laplacianSchemes
{{
    default         Gauss linear corrected;
}}

interpolationSchemes
{{
    default         linear;
}}

snGradSchemes
{{
    default         corrected;
}}

wallDist
{{
    method          meshWave;
}}
"""
    return write_file(case_dir, 'system/fvSchemes', content)


def write_fv_solution(case_dir: str, steady: bool = True,
                      simple_n_non_orthogonal: int = 1,
                      relaxation_U: float = 0.7,
                      relaxation_p: float = 0.3) -> str:
    """Write system/fvSolution with solver settings.

    Args:
        case_dir: Case directory
        steady: True for SIMPLE, False for PISO/PIMPLE
        simple_n_non_orthogonal: Non-orthogonal correctors
        relaxation_U: Velocity relaxation factor (steady)
        relaxation_p: Pressure relaxation factor (steady)
    """
    if steady:
        algo_block = f"""
SIMPLE
{{
    nNonOrthogonalCorrectors {simple_n_non_orthogonal};
    consistent      yes;
    residualControl
    {{
        p               1e-4;
        U               1e-4;
        "(k|omega|epsilon|nuTilda)" 1e-4;
    }}
}}

relaxationFactors
{{
    fields
    {{
        p               {relaxation_p};
    }}
    equations
    {{
        U               {relaxation_U};
        k               0.7;
        omega           0.7;
        epsilon         0.7;
        nuTilda         0.7;
    }}
}}
"""
    else:
        algo_block = """
PIMPLE
{
    nOuterCorrectors 2;
    nCorrectors     2;
    nNonOrthogonalCorrectors 1;
}
"""

    content = foam_header("dictionary", "fvSolution", "system") + f"""
solvers
{{
    p
    {{
        solver          GAMG;
        smoother        GaussSeidel;
        tolerance       1e-6;
        relTol          0.1;
    }}

    "(U|k|omega|epsilon|nuTilda|T)"
    {{
        solver          PBiCGStab;
        preconditioner  DILU;
        tolerance       1e-7;
        relTol          0.1;
    }}

    pFinal
    {{
        $p;
        relTol          0;
    }}

    "(U|k|omega|epsilon|nuTilda|T)Final"
    {{
        $U;
        relTol          0;
    }}
}}

{algo_block}
"""
    return write_file(case_dir, 'system/fvSolution', content)


def write_decompose_par_dict(case_dir: str, n_procs: int = 4,
                             method: str = "scotch") -> str:
    """Write system/decomposeParDict for parallel runs."""
    content = foam_header("dictionary", "decomposeParDict", "system") + f"""
numberOfSubdomains {n_procs};
method          {method};
"""
    return write_file(case_dir, 'system/decomposeParDict', content)


# ============= TRANSPORT & TURBULENCE PROPERTIES =============

def write_transport_properties(case_dir: str, nu: float = 1e-6,
                               transport_model: str = "Newtonian",
                               extra_fields: str = "") -> str:
    """Write constant/transportProperties.

    Args:
        case_dir: Case directory
        nu: Kinematic viscosity [m^2/s] (default: water at 20C)
        transport_model: Transport model
        extra_fields: Additional fields (e.g., Prandtl number for heat transfer)
    """
    content = foam_header("dictionary", "transportProperties", "constant") + f"""
transportModel  {transport_model};

nu              [0 2 -1 0 0 0 0] {nu};
{extra_fields}
"""
    return write_file(case_dir, 'constant/transportProperties', content)


def write_turbulence_properties(case_dir: str,
                                model_type: str = "kOmegaSST",
                                simulation_type: str = "RAS") -> str:
    """Write constant/turbulenceProperties.

    Args:
        case_dir: Case directory
        model_type: Turbulence model (kOmegaSST, kEpsilon, SpalartAllmaras, laminar)
        simulation_type: RAS or LES
    """
    if model_type == "laminar":
        content = foam_header("dictionary", "turbulenceProperties", "constant") + """
simulationType  laminar;
"""
    else:
        content = foam_header("dictionary", "turbulenceProperties", "constant") + f"""
simulationType  {simulation_type};

{simulation_type}
{{
    {simulation_type}Model   {model_type};
    turbulence      on;
    printCoeffs     on;
}}
"""
    return write_file(case_dir, 'constant/turbulenceProperties', content)


# ============= BOUNDARY CONDITION WRITERS =============

def write_scalar_field(case_dir: str, field_name: str,
                       dimensions: str, internal_field: str,
                       boundary_conditions: Dict[str, Dict]) -> str:
    """Write a scalar field file to the 0/ directory.

    Args:
        case_dir: Case directory
        field_name: e.g., 'p', 'k', 'omega', 'epsilon', 'nut', 'T'
        dimensions: OpenFOAM dimensions string e.g. '[0 2 -2 0 0 0 0]'
        internal_field: e.g., 'uniform 0'
        boundary_conditions: Dict mapping patch name to BC dict
            e.g., {'inlet': {'type': 'fixedValue', 'value': 'uniform 0'}}
    """
    bc_text = _format_boundary_conditions(boundary_conditions)
    content = foam_header("volScalarField", field_name, "0") + f"""
dimensions      {dimensions};

internalField   {internal_field};

boundaryField
{{
{bc_text}
}}
"""
    return write_file(case_dir, f'0/{field_name}', content)


def write_vector_field(case_dir: str, field_name: str,
                       dimensions: str, internal_field: str,
                       boundary_conditions: Dict[str, Dict]) -> str:
    """Write a vector field file to the 0/ directory.

    Args:
        case_dir: Case directory
        field_name: e.g., 'U'
        dimensions: e.g., '[0 1 -1 0 0 0 0]'
        internal_field: e.g., 'uniform (1 0 0)'
        boundary_conditions: Dict mapping patch name to BC dict
    """
    bc_text = _format_boundary_conditions(boundary_conditions)
    content = foam_header("volVectorField", field_name, "0") + f"""
dimensions      {dimensions};

internalField   {internal_field};

boundaryField
{{
{bc_text}
}}
"""
    return write_file(case_dir, f'0/{field_name}', content)


def _format_boundary_conditions(bcs: Dict[str, Dict]) -> str:
    """Format boundary conditions dict into OpenFOAM syntax."""
    lines = []
    for patch_name, bc_dict in bcs.items():
        lines.append(f"    {patch_name}")
        lines.append("    {")
        for key, value in bc_dict.items():
            lines.append(f"        {key}    {value};")
        lines.append("    }")
    return '\n'.join(lines)


# ============= BLOCK MESH GENERATORS =============

def write_block_mesh_dict_box(case_dir: str,
                              x_min: float, x_max: float,
                              y_min: float, y_max: float,
                              z_min: float, z_max: float,
                              nx: int, ny: int, nz: int,
                              patches: Dict[str, List[str]] = None) -> str:
    """Write blockMeshDict for a simple rectangular box domain.

    Args:
        case_dir: Case directory
        x_min, x_max, y_min, y_max, z_min, z_max: Domain bounds [m]
        nx, ny, nz: Number of cells in each direction
        patches: Dict mapping patch name to list of face definitions.
            If None, generates standard inlet/outlet/walls/top/bottom.
    """
    if patches is None:
        if nz == 1:
            # 2D case: z-faces must be empty
            patches = {
                "inlet": ["(0 4 7 3)"],
                "outlet": ["(1 2 6 5)"],
                "walls": ["(0 1 5 4)", "(3 7 6 2)"],
                "frontAndBack": ["(0 3 2 1)", "(4 5 6 7)"],
            }
        else:
            patches = {
                "inlet": ["(0 4 7 3)"],
                "outlet": ["(1 2 6 5)"],
                "walls": ["(0 1 5 4)", "(3 7 6 2)"],
                "top": ["(4 5 6 7)"],
                "bottom": ["(0 3 2 1)"],
            }

    patch_text = _format_patches(patches)

    content = foam_header("dictionary", "blockMeshDict", "system") + f"""
scale   1;

vertices
(
    ({x_min} {y_min} {z_min})   // 0
    ({x_max} {y_min} {z_min})   // 1
    ({x_max} {y_max} {z_min})   // 2
    ({x_min} {y_max} {z_min})   // 3
    ({x_min} {y_min} {z_max})   // 4
    ({x_max} {y_min} {z_max})   // 5
    ({x_max} {y_max} {z_max})   // 6
    ({x_min} {y_max} {z_max})   // 7
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)
);

edges
(
);

boundary
(
{patch_text}
);
"""
    return write_file(case_dir, 'system/blockMeshDict', content)


def write_block_mesh_dict_pipe(case_dir: str, length: float = 1.0,
                               radius: float = 0.05, nx: int = 100,
                               nr: int = 20, ntheta: int = 1) -> str:
    """Write blockMeshDict for a 2D axisymmetric pipe (wedge geometry).

    Creates a thin wedge for axisymmetric simulation of pipe flow.

    Args:
        case_dir: Case directory
        length: Pipe length [m]
        radius: Pipe radius [m]
        nx: Cells along pipe axis
        nr: Cells in radial direction
        ntheta: Cells in circumferential direction (1 for 2D)
    """
    import math
    wedge_angle = 2.5  # degrees — standard for axisymmetric
    rad = math.radians(wedge_angle)
    y_top = radius * math.cos(rad)
    z_pos = radius * math.sin(rad)
    z_neg = -z_pos

    content = foam_header("dictionary", "blockMeshDict", "system") + f"""
scale   1;

vertices
(
    (0       0       0)         // 0 - axis inlet
    ({length} 0       0)         // 1 - axis outlet
    ({length} {y_top}  {z_neg})  // 2 - wall outlet back
    (0       {y_top}  {z_neg})  // 3 - wall inlet back
    (0       0       0)         // 4 = 0
    ({length} 0       0)         // 5 = 1
    ({length} {y_top}  {z_pos})  // 6 - wall outlet front
    (0       {y_top}  {z_pos})  // 7 - wall inlet front
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {nr} 1) simpleGrading (1 0.2 1)
);

edges
(
);

boundary
(
    inlet
    {{
        type patch;
        faces ( (0 3 7 4) );
    }}
    outlet
    {{
        type patch;
        faces ( (1 5 6 2) );
    }}
    wall
    {{
        type wall;
        faces ( (3 2 6 7) );
    }}
    axis
    {{
        type empty;
        faces ( (0 4 5 1) );
    }}
    front
    {{
        type wedge;
        faces ( (0 1 2 3) );
    }}
    back
    {{
        type wedge;
        faces ( (4 7 6 5) );
    }}
);
"""
    return write_file(case_dir, 'system/blockMeshDict', content)


def write_block_mesh_dict_cylinder(case_dir: str,
                                   domain_x: float = 20.0,
                                   domain_y: float = 8.0,
                                   domain_z: float = 1.0,
                                   nx: int = 200, ny: int = 80,
                                   nz: int = 1) -> str:
    """Write blockMeshDict for external flow domain (2D with empty z-faces).

    Creates a rectangular domain suitable for flow over objects.
    The object is typically defined via topoSet + refinement or snappyHexMesh.
    For simple 2D cylinder, use with createPatch or topoSet.

    Args:
        case_dir: Case directory
        domain_x: Domain length [m]
        domain_y: Domain height [m]
        domain_z: Domain depth [m] (thin for 2D)
        nx, ny, nz: Cell counts
    """
    x_min = -domain_x * 0.3  # upstream
    x_max = domain_x * 0.7   # downstream
    y_min = -domain_y / 2
    y_max = domain_y / 2
    z_min = 0
    z_max = domain_z

    patches = {
        "inlet": ["(0 4 7 3)"],
        "outlet": ["(1 2 6 5)"],
        "top": ["(4 5 6 7)"],
        "bottom": ["(0 3 2 1)"],
        "frontAndBack": ["(0 1 5 4)", "(3 7 6 2)"],
    }

    return write_block_mesh_dict_box(
        case_dir, x_min, x_max, y_min, y_max, z_min, z_max,
        nx, ny, nz, patches
    )


def _format_patches(patches: Dict[str, List[str]]) -> str:
    """Format patches dict for blockMeshDict."""
    lines = []
    for name, faces in patches.items():
        patch_type = "patch"
        if name in ("walls", "wall", "bottomWall", "topWall"):
            patch_type = "wall"
        if name == "frontAndBack":
            patch_type = "empty"
        lines.append(f"    {name}")
        lines.append("    {")
        lines.append(f"        type {patch_type};")
        lines.append("        faces")
        lines.append("        (")
        for face in faces:
            lines.append(f"            {face}")
        lines.append("        );")
        lines.append("    }")
    return '\n'.join(lines)


# ============= SCENARIO PRESETS =============

def setup_pipe_flow(case_dir: str, velocity: float = 1.0,
                    diameter: float = 0.1, length: float = 1.0,
                    nu: float = 1e-6,
                    n_iterations: int = 500) -> Dict[str, Any]:
    """Set up a complete internal pipe flow case.

    Args:
        case_dir: Case directory
        velocity: Inlet velocity [m/s]
        diameter: Pipe diameter [m]
        length: Pipe length [m]
        nu: Kinematic viscosity [m^2/s]
        n_iterations: Number of SIMPLE iterations

    Returns:
        Dict with case parameters including Reynolds number
    """
    _validate_positive(velocity=velocity, diameter=diameter, length=length, nu=nu)
    radius = diameter / 2.0
    Re = velocity * diameter / nu
    logging.info(f"Setting up pipe flow: D={diameter}m, L={length}m, "
                 f"U={velocity}m/s, Re={Re:.0f}")

    case_path = create_case_directory(case_dir)

    # Determine turbulence model
    if Re < 2300:
        turb_model = "laminar"
    else:
        turb_model = "kOmegaSST"

    # Mesh
    nx = max(50, int(length / diameter * 20))
    nr = max(15, int(20 * (Re / 10000) ** 0.25))
    write_block_mesh_dict_pipe(case_dir, length=length, radius=radius,
                               nx=nx, nr=nr)

    # Transport
    write_transport_properties(case_dir, nu=nu)
    write_turbulence_properties(case_dir, model_type=turb_model)

    # System files
    solver = "simpleFoam" if Re >= 2300 else "icoFoam"
    if solver == "icoFoam":
        # Transient for laminar
        dt = min(0.001, 0.5 * (length / nx) / velocity)
        write_control_dict(case_dir, end_time=length / velocity * 5,
                          delta_t=dt, write_interval=int(1.0 / dt),
                          application=solver)
        write_fv_schemes(case_dir, steady=False)
        write_fv_solution(case_dir, steady=False)
    else:
        write_control_dict(case_dir, end_time=n_iterations,
                          delta_t=1, write_interval=100,
                          application=solver)
        write_fv_schemes(case_dir, steady=True)
        write_fv_solution(case_dir, steady=True)

    # Boundary conditions — U
    write_vector_field(case_dir, 'U', '[0 1 -1 0 0 0 0]',
                      f'uniform ({velocity} 0 0)',
                      {
                          'inlet': {'type': 'fixedValue',
                                   'value': f'uniform ({velocity} 0 0)'},
                          'outlet': {'type': 'zeroGradient'},
                          'wall': {'type': 'noSlip'},
                          'axis': {'type': 'empty'},
                          'front': {'type': 'wedge'},
                          'back': {'type': 'wedge'},
                      })

    # Boundary conditions — p
    write_scalar_field(case_dir, 'p', '[0 2 -2 0 0 0 0]',
                      'uniform 0',
                      {
                          'inlet': {'type': 'zeroGradient'},
                          'outlet': {'type': 'fixedValue',
                                    'value': 'uniform 0'},
                          'wall': {'type': 'zeroGradient'},
                          'axis': {'type': 'empty'},
                          'front': {'type': 'wedge'},
                          'back': {'type': 'wedge'},
                      })

    # Turbulent fields (if applicable)
    if turb_model == "kOmegaSST":
        # Turbulence inlet estimates using 5% intensity and 7% of hydraulic
        # diameter as the integral length scale (standard pipe-flow assumption,
        # see Versteeg & Malalasekera Ch. 3).
        k_val = 1.5 * (0.05 * velocity) ** 2  # 5% turbulence intensity
        omega_val = k_val ** 0.5 / (0.09 ** 0.25 * 0.07 * diameter)

        for field, dims, val in [
            ('k', '[0 2 -2 0 0 0 0]', k_val),
            ('omega', '[0 0 -1 0 0 0 0]', omega_val),
        ]:
            write_scalar_field(case_dir, field, dims, f'uniform {val}',
                              {
                                  'inlet': {'type': 'fixedValue',
                                           'value': f'uniform {val}'},
                                  'outlet': {'type': 'zeroGradient'},
                                  'wall': {'type': f'{'kqRWallFunction' if field == 'k' else 'omegaWallFunction'}',
                                          'value': f'uniform {val}'},
                                  'axis': {'type': 'empty'},
                                  'front': {'type': 'wedge'},
                                  'back': {'type': 'wedge'},
                              })

        write_scalar_field(case_dir, 'nut', '[0 2 -1 0 0 0 0]',
                          'uniform 0',
                          {
                              'inlet': {'type': 'calculated',
                                       'value': 'uniform 0'},
                              'outlet': {'type': 'calculated',
                                        'value': 'uniform 0'},
                              'wall': {'type': 'nutkWallFunction',
                                      'value': 'uniform 0'},
                              'axis': {'type': 'empty'},
                              'front': {'type': 'wedge'},
                              'back': {'type': 'wedge'},
                          })

    return {
        'solver': solver,
        'turbulence_model': turb_model,
        'reynolds_number': Re,
        'diameter': diameter,
        'length': length,
        'velocity': velocity,
        'nu': nu,
        'case_dir': case_path,
    }


def setup_box_flow(case_dir: str, velocity: float = 1.0,
                   domain_x: float = 2.0, domain_y: float = 1.0,
                   domain_z: float = 0.1,
                   nx: int = 100, ny: int = 50, nz: int = 1,
                   nu: float = 1e-6,
                   n_iterations: int = 1000,
                   turb_model: str = "auto") -> Dict[str, Any]:
    """Set up a generic box-domain flow case (external flow, channel, etc.).

    Args:
        case_dir: Case directory
        velocity: Inlet velocity [m/s]
        domain_x/y/z: Domain dimensions [m]
        nx/ny/nz: Cell counts
        nu: Kinematic viscosity [m^2/s]
        n_iterations: SIMPLE iterations
        turb_model: 'auto', 'kOmegaSST', 'kEpsilon', 'laminar', etc.

    Returns:
        Dict with case parameters
    """
    _validate_positive(velocity=velocity, domain_y=domain_y, nu=nu)
    Re = velocity * domain_y / nu
    if turb_model == "auto":
        turb_model = "laminar" if Re < 2300 else "kOmegaSST"

    case_path = create_case_directory(case_dir)

    write_block_mesh_dict_box(case_dir, 0, domain_x, 0, domain_y,
                              0, domain_z, nx, ny, nz)
    write_transport_properties(case_dir, nu=nu)
    write_turbulence_properties(case_dir, model_type=turb_model)
    write_control_dict(case_dir, end_time=n_iterations, delta_t=1,
                      write_interval=100, application="simpleFoam")
    write_fv_schemes(case_dir, steady=True)
    write_fv_solution(case_dir, steady=True)

    # Boundary conditions depend on 2D vs 3D
    is_2d = (nz == 1)

    # U field
    u_bcs = {
        'inlet': {'type': 'fixedValue',
                 'value': f'uniform ({velocity} 0 0)'},
        'outlet': {'type': 'zeroGradient'},
        'walls': {'type': 'noSlip'},
    }
    if is_2d:
        u_bcs['frontAndBack'] = {'type': 'empty'}
    else:
        u_bcs['top'] = {'type': 'slip'}
        u_bcs['bottom'] = {'type': 'noSlip'}
    write_vector_field(case_dir, 'U', '[0 1 -1 0 0 0 0]',
                      f'uniform ({velocity} 0 0)', u_bcs)

    # p field
    p_bcs = {
        'inlet': {'type': 'zeroGradient'},
        'outlet': {'type': 'fixedValue',
                  'value': 'uniform 0'},
        'walls': {'type': 'zeroGradient'},
    }
    if is_2d:
        p_bcs['frontAndBack'] = {'type': 'empty'}
    else:
        p_bcs['top'] = {'type': 'zeroGradient'}
        p_bcs['bottom'] = {'type': 'zeroGradient'}
    write_scalar_field(case_dir, 'p', '[0 2 -2 0 0 0 0]',
                      'uniform 0', p_bcs)

    # Turbulent fields
    if turb_model == "kOmegaSST":
        _write_turbulent_bcs_box(case_dir, velocity, domain_y, is_2d=is_2d)

    return {
        'solver': 'simpleFoam',
        'turbulence_model': turb_model,
        'reynolds_number': Re,
        'velocity': velocity,
        'domain': [domain_x, domain_y, domain_z],
        'case_dir': case_path,
    }


def setup_heated_surface(case_dir: str, velocity: float = 1.0,
                         T_inlet: float = 300.0, T_wall: float = 400.0,
                         domain_x: float = 1.0, domain_y: float = 0.2,
                         domain_z: float = 0.01,
                         nx: int = 100, ny: int = 40, nz: int = 1,
                         nu: float = 1.5e-5,
                         n_iterations: int = 1000) -> Dict[str, Any]:
    """Set up a heated surface convection case.

    Args:
        case_dir: Case directory
        velocity: Inlet velocity [m/s]
        T_inlet: Inlet temperature [K]
        T_wall: Heated wall temperature [K]
        domain_x/y/z: Domain dimensions [m]
        nu: Kinematic viscosity [m^2/s] (default: air at ~300K)
        n_iterations: SIMPLE iterations
    """
    _validate_positive(velocity=velocity, domain_y=domain_y, nu=nu)
    Re = velocity * domain_y / nu
    turb_model = "laminar" if Re < 2300 else "kOmegaSST"

    case_path = create_case_directory(case_dir)

    is_2d = (nz == 1)
    if is_2d:
        # For 2D heated surface, split walls into bottomWall (heated)
        # and topWall so we can apply different thermal BCs.
        # z-faces become empty (frontAndBack).
        custom_patches = {
            "inlet": ["(0 4 7 3)"],
            "outlet": ["(1 2 6 5)"],
            "topWall": ["(3 7 6 2)"],       # y_max face
            "bottomWall": ["(0 1 5 4)"],     # y_min face (heated)
            "frontAndBack": ["(0 3 2 1)", "(4 5 6 7)"],
        }
        write_block_mesh_dict_box(case_dir, 0, domain_x, 0, domain_y,
                                  0, domain_z, nx, ny, nz,
                                  patches=custom_patches)
    else:
        write_block_mesh_dict_box(case_dir, 0, domain_x, 0, domain_y,
                                  0, domain_z, nx, ny, nz)

    # Transport properties with Prandtl for air
    Pr = 0.71
    alpha = nu / Pr
    write_transport_properties(case_dir, nu=nu,
                               extra_fields=f"Pr              [0 0 0 0 0 0 0] {Pr};\nPrt             [0 0 0 0 0 0 0] 0.85;")
    write_turbulence_properties(case_dir, model_type=turb_model)

    # Use buoyantSimpleFoam requires additional setup; for simplicity
    # use simpleFoam with passive scalar transport
    write_control_dict(case_dir, end_time=n_iterations, delta_t=1,
                      write_interval=100, application="simpleFoam",
                      functions="""
functions
{
    scalarTransport
    {
        type            scalarTransport;
        libs            (solverFunctionObjects);
        field           T;
        nCorr           2;
        resetOnStartUp  no;
        fvOptions       {};
    }
}
""")
    write_fv_schemes(case_dir, steady=True)
    write_fv_solution(case_dir, steady=True)

    # Boundary conditions depend on 2D vs 3D
    is_2d = (nz == 1)

    # U field
    u_bcs = {
        'inlet': {'type': 'fixedValue',
                 'value': f'uniform ({velocity} 0 0)'},
        'outlet': {'type': 'zeroGradient'},
    }
    if is_2d:
        u_bcs['bottomWall'] = {'type': 'noSlip'}
        u_bcs['topWall'] = {'type': 'slip'}
        u_bcs['frontAndBack'] = {'type': 'empty'}
    else:
        u_bcs['walls'] = {'type': 'noSlip'}
        u_bcs['top'] = {'type': 'slip'}
        u_bcs['bottom'] = {'type': 'noSlip'}
    write_vector_field(case_dir, 'U', '[0 1 -1 0 0 0 0]',
                      f'uniform ({velocity} 0 0)', u_bcs)

    # p field
    p_bcs = {
        'inlet': {'type': 'zeroGradient'},
        'outlet': {'type': 'fixedValue',
                  'value': 'uniform 0'},
    }
    if is_2d:
        p_bcs['bottomWall'] = {'type': 'zeroGradient'}
        p_bcs['topWall'] = {'type': 'zeroGradient'}
        p_bcs['frontAndBack'] = {'type': 'empty'}
    else:
        p_bcs['walls'] = {'type': 'zeroGradient'}
        p_bcs['top'] = {'type': 'zeroGradient'}
        p_bcs['bottom'] = {'type': 'zeroGradient'}
    write_scalar_field(case_dir, 'p', '[0 2 -2 0 0 0 0]',
                      'uniform 0', p_bcs)

    # T field
    t_bcs = {
        'inlet': {'type': 'fixedValue',
                 'value': f'uniform {T_inlet}'},
        'outlet': {'type': 'zeroGradient'},
    }
    if is_2d:
        t_bcs['bottomWall'] = {'type': 'fixedValue',
                              'value': f'uniform {T_wall}'}
        t_bcs['topWall'] = {'type': 'zeroGradient'}
        t_bcs['frontAndBack'] = {'type': 'empty'}
    else:
        t_bcs['walls'] = {'type': 'zeroGradient'}
        t_bcs['top'] = {'type': 'zeroGradient'}
        t_bcs['bottom'] = {'type': 'fixedValue',
                          'value': f'uniform {T_wall}'}
    write_scalar_field(case_dir, 'T', '[0 0 0 1 0 0 0]',
                      f'uniform {T_inlet}', t_bcs)

    # Turbulent fields
    if turb_model == "kOmegaSST":
        _write_turbulent_bcs_box(case_dir, velocity, domain_y, is_2d=is_2d,
                                 heated_surface=True)

    return {
        'solver': 'simpleFoam',
        'turbulence_model': turb_model,
        'reynolds_number': Re,
        'velocity': velocity,
        'T_inlet': T_inlet,
        'T_wall': T_wall,
        'case_dir': case_path,
    }


def _write_turbulent_bcs_box(case_dir: str, velocity: float,
                             length_scale: float,
                             is_2d: bool = False,
                             heated_surface: bool = False) -> None:
    """Write k, omega, nut boundary conditions for box domain.

    Turbulence inlet estimates use 5% intensity and 7% of ``length_scale``
    as the integral length scale.  This is a standard pipe/duct assumption
    (Versteeg & Malalasekera Ch. 3) and may overestimate the length scale
    for large open domains; callers should override ``length_scale`` when
    domain_y >> characteristic body dimension.
    """
    k_val = 1.5 * (0.05 * velocity) ** 2
    omega_val = k_val ** 0.5 / (0.09 ** 0.25 * 0.07 * length_scale)

    for field, dims, val in [
        ('k', '[0 2 -2 0 0 0 0]', k_val),
        ('omega', '[0 0 -1 0 0 0 0]', omega_val),
    ]:
        wall_type = 'kqRWallFunction' if field == 'k' else 'omegaWallFunction'
        bcs = {
            'inlet': {'type': 'fixedValue',
                     'value': f'uniform {val}'},
            'outlet': {'type': 'zeroGradient'},
        }
        if is_2d and heated_surface:
            bcs['bottomWall'] = {'type': wall_type,
                                'value': f'uniform {val}'}
            bcs['topWall'] = {'type': 'zeroGradient'}
            bcs['frontAndBack'] = {'type': 'empty'}
        elif is_2d:
            bcs['walls'] = {'type': wall_type,
                           'value': f'uniform {val}'}
            bcs['frontAndBack'] = {'type': 'empty'}
        else:
            bcs['walls'] = {'type': wall_type,
                           'value': f'uniform {val}'}
            bcs['top'] = {'type': 'zeroGradient'}
            bcs['bottom'] = {'type': wall_type,
                            'value': f'uniform {val}'}
        write_scalar_field(case_dir, field, dims, f'uniform {val}', bcs)

    # nut field
    nut_bcs = {
        'inlet': {'type': 'calculated',
                 'value': 'uniform 0'},
        'outlet': {'type': 'calculated',
                  'value': 'uniform 0'},
    }
    if is_2d and heated_surface:
        nut_bcs['bottomWall'] = {'type': 'nutkWallFunction',
                                'value': 'uniform 0'}
        nut_bcs['topWall'] = {'type': 'calculated',
                             'value': 'uniform 0'}
        nut_bcs['frontAndBack'] = {'type': 'empty'}
    elif is_2d:
        nut_bcs['walls'] = {'type': 'nutkWallFunction',
                           'value': 'uniform 0'}
        nut_bcs['frontAndBack'] = {'type': 'empty'}
    else:
        nut_bcs['walls'] = {'type': 'nutkWallFunction',
                           'value': 'uniform 0'}
        nut_bcs['top'] = {'type': 'calculated',
                         'value': 'uniform 0'}
        nut_bcs['bottom'] = {'type': 'nutkWallFunction',
                            'value': 'uniform 0'}
    write_scalar_field(case_dir, 'nut', '[0 2 -1 0 0 0 0]',
                      'uniform 0', nut_bcs)


# ============= MRF (MULTIPLE REFERENCE FRAME) UTILITIES =============

def write_mrf_properties(case_dir: str, zone_name: str = "rotorZone",
                         origin: Tuple[float, float, float] = (0, 0, 0),
                         axis: Tuple[float, float, float] = (0, 0, 1),
                         omega: float = 0.0,
                         non_rotating_patches: List[str] = None) -> str:
    """Write constant/MRFProperties for steady-state rotating zone.

    Args:
        case_dir: Case directory
        zone_name: Name of the cellZone for the rotating region
        origin: Rotation origin (x, y, z) [m]
        axis: Rotation axis unit vector
        omega: Angular velocity [rad/s] (use rpm_to_rads() to convert)
        non_rotating_patches: Patches that do NOT rotate with the zone
            (e.g., ['inlet', 'outlet'] — walls inside the zone rotate by default)

    Returns:
        Path to written file
    """
    nr_patches = non_rotating_patches or []
    nr_block = "\n            ".join(nr_patches)

    content = foam_header("dictionary", "MRFProperties", "constant") + f"""
{zone_name}
{{
    cellZone    {zone_name};
    active      yes;

    nonRotatingPatches
    (
        {nr_block}
    );

    origin      ({origin[0]} {origin[1]} {origin[2]});
    axis        ({axis[0]} {axis[1]} {axis[2]});
    omega       {omega};  // rad/s
}}
"""
    return write_file(case_dir, 'constant/MRFProperties', content)


def write_topo_set_dict(case_dir: str,
                        sets: List[Dict[str, Any]]) -> str:
    """Write system/topoSetDict for creating cellZones, cellSets, etc.

    Args:
        case_dir: Case directory
        sets: List of set action dicts. Each must have:
            - name: str — set/zone name
            - type: str — 'cellSet' or 'cellZoneSet'
            - action: str — 'new', 'add', 'delete'
            - source: str — e.g. 'cylinderToCell', 'boxToCell'
            - source_info: dict — source-specific parameters

    Example:
        sets=[
            {
                'name': 'rotorCells',
                'type': 'cellSet',
                'action': 'new',
                'source': 'cylinderToCell',
                'source_info': {
                    'point1': (0, 0, -0.05),
                    'point2': (0, 0, 0.05),
                    'radius': 0.1,
                }
            },
            {
                'name': 'rotorZone',
                'type': 'cellZoneSet',
                'action': 'new',
                'source': 'setToCellZone',
                'source_info': {'set': 'rotorCells'}
            }
        ]

    Returns:
        Path to written file
    """
    actions_text = ""
    for s in sets:
        # Format source info
        si_lines = ""
        for k, v in s['source_info'].items():
            if isinstance(v, (tuple, list)):
                si_lines += f"        {k}   ({v[0]} {v[1]} {v[2]});\n"
            else:
                si_lines += f"        {k}   {v};\n"

        actions_text += f"""
    {{
        name    {s['name']};
        type    {s['type']};
        action  {s['action']};
        source  {s['source']};
        sourceInfo
        {{
{si_lines}        }}
    }}
"""

    content = foam_header("dictionary", "topoSetDict", "system") + f"""
actions
(
{actions_text}
);
"""
    return write_file(case_dir, 'system/topoSetDict', content)


def run_topo_set(case_dir: str) -> subprocess.CompletedProcess:
    """Run topoSet to create cellSets and cellZones from topoSetDict."""
    return run_openfoam_cmd(['topoSet'], case_dir,
                            log_file=os.path.join(case_dir, 'log.topoSet'))


def rpm_to_rads(rpm: float) -> float:
    """Convert RPM to radians per second."""
    return rpm * 2.0 * math.pi / 60.0


def write_fv_options_mrf(case_dir: str, zone_name: str = "rotorZone",
                         origin: Tuple[float, float, float] = (0, 0, 0),
                         axis: Tuple[float, float, float] = (0, 0, 1),
                         omega: float = 0.0,
                         non_rotating_patches: List[str] = None) -> str:
    """Write system/fvOptions with MRF source (alternative to MRFProperties).

    Some OpenFOAM versions prefer fvOptions over constant/MRFProperties.
    This writes the equivalent MRF definition as an fvOptions entry.

    Args:
        Same as write_mrf_properties()

    Returns:
        Path to written file
    """
    nr_patches = non_rotating_patches or []
    nr_block = "\n            ".join(nr_patches)

    content = foam_header("dictionary", "fvOptions", "system") + f"""
MRF1
{{
    type            MRFSource;
    active          true;

    MRFSourceCoeffs
    {{
        cellZone    {zone_name};
        origin      ({origin[0]} {origin[1]} {origin[2]});
        axis        ({axis[0]} {axis[1]} {axis[2]});
        omega       {omega};  // rad/s

        nonRotatingPatches
        (
            {nr_block}
        );
    }}
}}
"""
    return write_file(case_dir, 'system/fvOptions', content)


def setup_mrf_fan_flow(case_dir: str,
                       rpm: float = 3000.0,
                       inlet_velocity: float = 2.0,
                       nu: float = 1.5e-5,
                       duct_length: float = 0.6,
                       duct_radius: float = 0.15,
                       hub_radius: float = 0.04,
                       rotor_length: float = 0.05,
                       rotor_position: float = 0.3,
                       nx: int = 60,
                       ny: int = 20,
                       nz: int = 20,
                       n_iterations: int = 500,
                       turb_model: str = 'kOmegaSST') -> Dict[str, Any]:
    """Set up a steady-state MRF axial fan simulation.

    Creates a rectangular duct with a cylindrical MRF rotating zone
    representing the fan rotor region. Uses simpleFoam with MRFProperties.

    Geometry (simplified — no physical blades):
        - Rectangular duct of length duct_length
        - Cylindrical MRF zone centered at rotor_position along x-axis
        - The MRF zone approximates the swept volume of the fan blades
        - Rotation axis defaults to x-axis (axial fan)

    Args:
        case_dir: Case directory path
        rpm: Rotational speed [RPM]
        inlet_velocity: Axial inlet velocity [m/s]
        nu: Kinematic viscosity [m²/s] (default: air at ~300K)
        duct_length: Total duct length [m]
        duct_radius: Duct outer radius (half-height of box domain) [m]
        hub_radius: Hub radius (not meshed separately, for reference) [m]
        rotor_length: Axial length of the MRF rotor zone [m]
        rotor_position: Axial position of rotor center from inlet [m]
        nx: Mesh cells in x (axial)
        ny: Mesh cells in y
        nz: Mesh cells in z
        n_iterations: SIMPLE iterations
        turb_model: Turbulence model ('kOmegaSST', 'kEpsilon', 'laminar')

    Returns:
        Dict with case parameters including solver, turbulence_model, omega_rads
    """
    _validate_positive(inlet_velocity=inlet_velocity, nu=nu,
                       duct_radius=duct_radius, duct_length=duct_length)
    case_path = create_case_directory(case_dir)
    omega_rads = rpm_to_rads(rpm)

    # --- Determine flow regime ---
    Re = inlet_velocity * (2 * duct_radius) / nu
    is_laminar = turb_model == 'laminar' or (Re < 2300 and turb_model != 'kOmegaSST')
    actual_turb = 'laminar' if is_laminar else turb_model

    logging.info(f"MRF Fan Flow Setup:")
    logging.info(f"  RPM: {rpm}, omega: {omega_rads:.2f} rad/s")
    logging.info(f"  Inlet velocity: {inlet_velocity} m/s")
    logging.info(f"  Re (duct): {Re:.0f}")
    logging.info(f"  Turbulence: {actual_turb}")
    logging.info(f"  Domain: {duct_length}m x {2*duct_radius}m x {2*duct_radius}m")

    # --- Mesh: rectangular duct ---
    half_y = duct_radius
    half_z = duct_radius
    is_2d = (nz == 1 or ny == 1)

    if is_2d:
        logging.warning(
            "MRF fan flow is inherently 3D (rotation about x-axis). "
            f"Detected 2D mesh (ny={ny}, nz={nz}). Results will be "
            "qualitative only — the MRF source term cannot represent "
            "true rotational effects in 2D."
        )

    if is_2d:
        mesh_patches = {
            'inlet':  ['(0 4 7 3)'],
            'outlet': ['(1 2 6 5)'],
            'walls':  ['(0 1 5 4)', '(3 7 6 2)'],
            'frontAndBack': ['(0 3 2 1)', '(4 5 6 7)'],
        }
    else:
        mesh_patches = {
            'inlet':  ['(0 4 7 3)'],
            'outlet': ['(1 2 6 5)'],
            'walls':  ['(0 1 5 4)', '(3 7 6 2)', '(0 3 2 1)', '(4 5 6 7)'],
        }

    write_block_mesh_dict_box(
        case_path,
        x_min=0, x_max=duct_length,
        y_min=-half_y, y_max=half_y,
        z_min=-half_z, z_max=half_z,
        nx=nx, ny=ny, nz=nz,
        patches=mesh_patches,
    )

    # --- System files (MUST exist before blockMesh/topoSet) ---
    solver = 'simpleFoam'
    write_control_dict(case_path, end_time=n_iterations, delta_t=1,
                       write_interval=max(n_iterations // 5, 50),
                       application=solver)
    write_fv_schemes(case_path, steady=True)
    write_fv_solution(case_path, steady=True, relaxation_U=0.7, relaxation_p=0.3)

    # --- Constant files ---
    write_transport_properties(case_path, nu=nu)
    write_turbulence_properties(case_path, model_type=actual_turb)

    # --- Now safe to run mesh generation ---
    run_block_mesh(case_path)

    # --- topoSet: define cylindrical rotor cellZone ---
    rotor_x_min = rotor_position - rotor_length / 2.0
    rotor_x_max = rotor_position + rotor_length / 2.0

    write_topo_set_dict(case_path, sets=[
        {
            'name': 'rotorCells',
            'type': 'cellSet',
            'action': 'new',
            'source': 'cylinderToCell',
            'source_info': {
                'point1': (rotor_x_min, 0, 0),
                'point2': (rotor_x_max, 0, 0),
                'radius': duct_radius * 0.9,  # slightly smaller than duct
            }
        },
        {
            'name': 'rotorZone',
            'type': 'cellZoneSet',
            'action': 'new',
            'source': 'setToCellZone',
            'source_info': {'set': 'rotorCells'}
        }
    ])
    run_topo_set(case_path)

    # --- MRF properties: rotation about x-axis ---
    rotor_center_x = rotor_position
    write_mrf_properties(
        case_path,
        zone_name='rotorZone',
        origin=(rotor_center_x, 0, 0),
        axis=(1, 0, 0),  # x-axis = axial direction
        omega=omega_rads,
        non_rotating_patches=['inlet', 'outlet', 'walls']
    )


    # --- Boundary conditions ---
    # 2D empty BC for frontAndBack patches
    empty_bc = {'type': 'empty'}

    # Velocity: uniform inlet, zeroGradient outlet, noSlip walls
    u_bcs = {
        'inlet':  {'type': 'fixedValue', 'value': f'uniform ({inlet_velocity} 0 0)'},
        'outlet': {'type': 'zeroGradient'},
        'walls':  {'type': 'noSlip'},
    }
    if is_2d:
        u_bcs['frontAndBack'] = empty_bc
    write_vector_field(case_path, 'U', '[0 1 -1 0 0 0 0]',
                       f'uniform ({inlet_velocity} 0 0)', u_bcs)

    # Pressure: zeroGradient inlet, fixedValue outlet
    p_bcs = {
        'inlet':  {'type': 'zeroGradient'},
        'outlet': {'type': 'fixedValue', 'value': 'uniform 0'},
        'walls':  {'type': 'zeroGradient'},
    }
    if is_2d:
        p_bcs['frontAndBack'] = empty_bc
    write_scalar_field(case_path, 'p', '[0 2 -2 0 0 0 0]', 'uniform 0', p_bcs)

    # Turbulence BCs (if turbulent)
    if not is_laminar:
        # Estimate turbulence quantities using 5% intensity and 7% of
        # hydraulic diameter as integral length scale (duct flow assumption).
        I = 0.05  # 5% turbulence intensity
        L = 0.07 * (2 * duct_radius)  # turbulent length scale
        k_val = 1.5 * (inlet_velocity * I) ** 2
        omega_turb = k_val ** 0.5 / (0.09 ** 0.25 * L)
        nut_val = k_val / omega_turb

        k_bcs = {
            'inlet':  {'type': 'fixedValue', 'value': f'uniform {k_val}'},
            'outlet': {'type': 'zeroGradient'},
            'walls':  {'type': 'kqRWallFunction', 'value': f'uniform {k_val}'},
        }
        if is_2d:
            k_bcs['frontAndBack'] = empty_bc
        write_scalar_field(case_path, 'k', '[0 2 -2 0 0 0 0]',
                           f'uniform {k_val}', k_bcs)

        omega_bcs = {
            'inlet':  {'type': 'fixedValue', 'value': f'uniform {omega_turb}'},
            'outlet': {'type': 'zeroGradient'},
            'walls':  {'type': 'omegaWallFunction', 'value': f'uniform {omega_turb}'},
        }
        if is_2d:
            omega_bcs['frontAndBack'] = empty_bc
        write_scalar_field(case_path, 'omega', '[0 0 -1 0 0 0 0]',
                           f'uniform {omega_turb}', omega_bcs)

        nut_bcs = {
            'inlet':  {'type': 'calculated', 'value': f'uniform {nut_val}'},
            'outlet': {'type': 'calculated', 'value': f'uniform {nut_val}'},
            'walls':  {'type': 'nutkWallFunction', 'value': f'uniform 0'},
        }
        if is_2d:
            nut_bcs['frontAndBack'] = empty_bc
        write_scalar_field(case_path, 'nut', '[0 2 -1 0 0 0 0]',
                           f'uniform 0', nut_bcs)

    logging.info(f"MRF fan case setup complete: {case_path}")
    return {
        'solver': solver,
        'turbulence_model': actual_turb,
        'rpm': rpm,
        'omega_rads': omega_rads,
        'inlet_velocity': inlet_velocity,
        'Re_duct': Re,
        'nu': nu,
        'duct_length': duct_length,
        'duct_radius': duct_radius,
        'rotor_position': rotor_position,
        'rotor_length': rotor_length,
        'n_iterations': n_iterations,
        'case_dir': case_path,
    }


def extract_fan_metrics(case_dir: str,
                        inlet_patch: str = "inlet",
                        outlet_patch: str = "outlet",
                        rotor_zone: str = "rotorZone",
                        omega_rads: float = 0.0,
                        duct_radius: float = 0.15) -> Dict[str, Any]:
    """Extract fan performance metrics from a completed MRF simulation.

    Computes:
        - Pressure rise (outlet - inlet) [Pa]
        - Mass flow rate [kg/s]
        - Estimated torque from momentum change [N·m]
        - Fan efficiency estimate

    Args:
        case_dir: Case directory
        inlet_patch: Inlet patch name
        outlet_patch: Outlet patch name
        rotor_zone: MRF zone name (for reference)
        omega_rads: Angular velocity [rad/s] (for efficiency calc)
        duct_radius: Duct radius [m] (for area calculation)

    Returns:
        Dict with fan performance metrics
    """
    metrics = {}

    # Pressure rise
    try:
        dp = extract_pressure_drop(case_dir, inlet_patch, outlet_patch)
        # For a fan, pressure RISES from inlet to outlet
        # extract_pressure_drop returns p_in - p_out, so negate for fan rise
        metrics['pressure_drop_Pa'] = dp.get('pressure_drop_Pa', 0)
        metrics['pressure_rise_Pa'] = -dp.get('pressure_drop_Pa', 0)
        logging.info(f"Fan pressure rise: {metrics['pressure_rise_Pa']:.2f} Pa")
    except Exception as e:
        logging.warning(f"Could not extract pressure drop: {e}")
        metrics['pressure_rise_Pa'] = None

    # Flow velocity and mass flow estimate
    try:
        u_stats = extract_field_statistics(case_dir, 'U')
        metrics['velocity_stats'] = u_stats
        # Rough mass flow: rho * A * U_avg (assume rho ~ 1.225 kg/m3 for air)
        rho = 1.225
        area = math.pi * duct_radius ** 2
        # Use inlet velocity magnitude as approximation
        if u_stats.get('max') is not None:
            metrics['duct_area_m2'] = area
            metrics['rho_kg_m3'] = rho
    except Exception as e:
        logging.warning(f"Could not extract velocity stats: {e}")

    # Parse solver log for convergence
    try:
        log_file = os.path.join(case_dir, 'log.simpleFoam')
        if os.path.exists(log_file):
            log_data = parse_solver_log(log_file)
            metrics['convergence'] = log_data
    except Exception as e:
        logging.warning(f"Could not parse solver log: {e}")

    # Efficiency estimate (if we have pressure rise and omega)
    if omega_rads > 0 and metrics.get('pressure_rise_Pa') is not None:
        # Ideal hydraulic power = deltaP * Q
        # Shaft power = torque * omega
        # For a simplified estimate without actual torque:
        # We report the pressure rise and note that full efficiency
        # requires blade-resolved geometry
        metrics['omega_rads'] = omega_rads
        metrics['note'] = (
            "Efficiency requires torque data from blade-resolved geometry. "
            "MRF with template geometry provides pressure rise and flow "
            "field estimates only."
        )

    return metrics


# ============= METRICS EXTRACTION =============

def parse_solver_log(log_file: str) -> Dict[str, Any]:
    """Parse an OpenFOAM solver log for convergence information.

    Returns:
        Dict with residuals, iterations, convergence status
    """
    if not os.path.exists(log_file):
        logging.warning(f"Log file not found: {log_file}")
        return {'error': f'Log file not found: {log_file}'}

    with open(log_file, 'r') as f:
        log_text = f.read()

    result = {
        'final_residuals': {},
        'n_iterations': 0,
        'converged': False,
        'execution_time': None,
    }

    # Extract final residuals for each field
    for field in ['Ux', 'Uy', 'Uz', 'p', 'k', 'omega', 'epsilon', 'T']:
        pattern = rf'Solving for {field},.*Final residual = ([0-9.eE+-]+)'
        matches = re.findall(pattern, log_text)
        if matches:
            result['final_residuals'][field] = float(matches[-1])

    # Count iterations
    time_pattern = r'^Time = (\S+)'
    time_matches = re.findall(time_pattern, log_text, re.MULTILINE)
    if time_matches:
        result['n_iterations'] = len(time_matches)
        result['last_time'] = time_matches[-1]

    # Check convergence
    if 'SIMPLE solution converged' in log_text or \
       'End' in log_text.split('\n')[-5:]:
        result['converged'] = True

    # Execution time
    exec_pattern = r'ExecutionTime = ([0-9.]+) s'
    exec_matches = re.findall(exec_pattern, log_text)
    if exec_matches:
        result['execution_time'] = float(exec_matches[-1])

    logging.info(f"Parsed log: {result['n_iterations']} iterations, "
                 f"converged={result['converged']}")
    return result


def extract_forces(case_dir: str, patch_name: str = "walls") -> Dict[str, Any]:
    """Extract force coefficients from postProcess output.

    Run postProcess -func 'forces' first, or include forces in controlDict.

    Returns:
        Dict with drag, lift, moment forces
    """
    # Try postProcess forces output
    forces_dir = os.path.join(case_dir, 'postProcessing', 'forces')
    if not os.path.exists(forces_dir):
        # Try running postProcess
        try:
            run_post_process(f"\"forces(patch={patch_name})\"", case_dir)
        except Exception as e:
            logging.warning(f"Could not run forces postProcess: {e}")

    # Find the latest time directory
    forces_dir = os.path.join(case_dir, 'postProcessing')
    force_files = glob.glob(os.path.join(forces_dir, '**/force*.dat'),
                            recursive=True)
    if not force_files:
        force_files = glob.glob(os.path.join(forces_dir, '**/coefficient*.dat'),
                                recursive=True)

    if not force_files:
        return {'error': 'No force data found in postProcessing/'}

    # Parse the latest force file
    latest_file = sorted(force_files)[-1]
    logging.info(f"Reading forces from: {latest_file}")

    forces = {'file': latest_file, 'data': []}
    with open(latest_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('#') or not line:
                continue
            parts = line.split()
            if len(parts) >= 4:
                forces['data'].append({
                    'time': float(parts[0]),
                    'force_x': float(parts[1]),
                    'force_y': float(parts[2]),
                    'force_z': float(parts[3]),
                })

    if forces['data']:
        last = forces['data'][-1]
        forces['drag'] = last['force_x']
        forces['lift'] = last['force_y']
        forces['side'] = last['force_z']

    return forces


def extract_pressure_drop(case_dir: str,
                          inlet_patch: str = "inlet",
                          outlet_patch: str = "outlet") -> Dict[str, float]:
    """Extract pressure drop between inlet and outlet patches.

    Returns:
        Dict with pressure drop [Pa], inlet/outlet average pressures
    """
    # Run patchAverage postProcess
    try:
        result_in = run_openfoam_cmd(
            ['postProcess', '-func',
             f"patchAverage(name={inlet_patch},p)", '-latestTime'],
            case_dir
        )
        result_out = run_openfoam_cmd(
            ['postProcess', '-func',
             f"patchAverage(name={outlet_patch},p)", '-latestTime'],
            case_dir
        )
    except Exception as e:
        logging.warning(f"postProcess patchAverage failed: {e}")
        return _extract_pressure_drop_from_log(case_dir)

    p_in = _parse_patch_average(result_in.stdout)
    p_out = _parse_patch_average(result_out.stdout)

    if p_in is not None and p_out is not None:
        return {
            'pressure_drop_Pa': p_in - p_out,
            'inlet_pressure_Pa': p_in,
            'outlet_pressure_Pa': p_out,
        }
    return _extract_pressure_drop_from_log(case_dir)


def _parse_patch_average(stdout: str) -> Optional[float]:
    """Parse patchAverage output for a value."""
    pattern = r'areaAverage\(.*?\) of p = ([0-9.eE+-]+)'
    match = re.search(pattern, stdout)
    if match:
        return float(match.group(1))
    # Alternative pattern
    pattern2 = r'average\(.*?\) = ([0-9.eE+-]+)'
    match2 = re.search(pattern2, stdout)
    if match2:
        return float(match2.group(1))
    return None


def _extract_pressure_drop_from_log(case_dir: str) -> Dict[str, Any]:
    """Fallback: extract pressure info from solver log."""
    return {'error': 'Could not extract pressure drop from postProcess',
            'suggestion': 'Check that inlet/outlet patch names match the mesh'}


def extract_field_statistics(case_dir: str, field: str = "U",
                             time_dir: str = "latest") -> Dict[str, Any]:
    """Extract min/max/mean statistics for a field.

    Args:
        case_dir: Case directory
        field: Field name (U, p, T, k, etc.)
        time_dir: Time directory or 'latest'
    """
    if time_dir == "latest":
        time_dirs = _get_time_directories(case_dir)
        if not time_dirs:
            return {'error': 'No time directories found'}
        time_dir = time_dirs[-1]

    try:
        result = run_openfoam_cmd(
            ['postProcess', '-func',
             f"fieldMinMax(fields=({field}))", '-latestTime'],
            case_dir
        )

        stats = {'field': field, 'time': time_dir}
        for line in result.stdout.split('\n'):
            if 'min' in line.lower():
                vals = re.findall(r'[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', line)
                if vals:
                    stats['min'] = float(vals[-1])
            if 'max' in line.lower():
                vals = re.findall(r'[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', line)
                if vals:
                    stats['max'] = float(vals[-1])
        return stats
    except Exception as e:
        return {'error': str(e)}


def _get_time_directories(case_dir: str) -> List[str]:
    """Get sorted list of time directories in a case."""
    dirs = []
    for entry in os.scandir(case_dir):
        if entry.is_dir():
            try:
                float(entry.name)
                dirs.append(entry.name)
            except ValueError:
                pass
    return sorted(dirs, key=float)


# ============= COMPREHENSIVE RUN FUNCTION =============

def run_simulation(case_dir: str, solver: str = "simpleFoam",
                   parallel: bool = False, n_procs: int = 4,
                   timeout: int = 3600) -> Dict[str, Any]:
    """Run a complete OpenFOAM simulation: mesh → solve → basic post.

    Args:
        case_dir: Case directory (must already have all config files)
        solver: Solver name
        parallel: Use MPI parallel execution
        n_procs: Number of MPI processes
        timeout: Solver timeout in seconds

    Returns:
        Dict with convergence info and timing
    """
    results = {'solver': solver, 'case_dir': case_dir}

    # Step 1: Generate mesh (skip if already generated by a setup_* function)
    mesh_exists = os.path.isdir(os.path.join(case_dir, 'constant', 'polyMesh'))
    logging.info("="*60)
    if mesh_exists:
        logging.info("STEP 1: Mesh already exists (constant/polyMesh/) — skipping blockMesh")
        results['mesh'] = 'already_exists'
    else:
        logging.info("STEP 1: Generating mesh with blockMesh")
        # Verify system files exist before attempting blockMesh
        control_dict_path = os.path.join(case_dir, 'system', 'controlDict')
        if not os.path.isfile(control_dict_path):
            sys_dir = os.path.join(case_dir, 'system')
            sys_contents = os.listdir(sys_dir) if os.path.isdir(sys_dir) else '(missing)'
            msg = (f"Cannot run blockMesh: {control_dict_path} not found. "
                   f"system/ contents: {sys_contents}")
            logging.error(msg)
            results['mesh'] = f'failed: {msg}'
            results['status'] = 'mesh_failed'
            return results
        try:
            run_block_mesh(case_dir)
            results['mesh'] = 'success'
        except RuntimeError as e:
            results['mesh'] = f'failed: {e}'
            results['status'] = 'mesh_failed'
            return results
    logging.info("="*60)

    # Step 2: Run solver
    logging.info("="*60)
    logging.info(f"STEP 2: Running {solver}")
    logging.info("="*60)
    try:
        if parallel and n_procs > 1:
            write_decompose_par_dict(case_dir, n_procs)
            run_decompose_par(case_dir)
            run_parallel_solver(solver, case_dir, n_procs, timeout)
            run_reconstruct_par(case_dir)
        else:
            run_solver(solver, case_dir, timeout)
        results['solver_status'] = 'success'
    except RuntimeError as e:
        results['solver_status'] = f'failed: {e}'
        results['status'] = 'solver_failed'
        # Copy whatever logs exist and return early — do not parse partial results
        for log in glob.glob(os.path.join(case_dir, 'log.*')):
            shutil.copy(log, OUTPUT_DIR)
        return results

    # Step 3: Parse log
    log_file = os.path.join(case_dir, f'log.{solver}')
    convergence = parse_solver_log(log_file)
    results['convergence'] = convergence

    # Copy logs to output
    for log in glob.glob(os.path.join(case_dir, 'log.*')):
        shutil.copy(log, OUTPUT_DIR)

    results['status'] = results.get('status', 'completed')
    return results


# ============= UTILITY =============

def tool_cleanup(deep: bool = False) -> None:
    """Clean OpenFOAM state between calculations."""
    try:
        if deep:
            _clear_scratch_files()
            logging.info("Deep cleanup completed")
    except Exception as e:
        logging.warning(f"Cleanup warning: {e}")


def _clear_scratch_files() -> None:
    """Remove scratch files."""
    cleared = 0
    try:
        for entry in os.scandir(SCRATCH_DIR):
            if entry.is_file():
                try:
                    os.remove(entry.path)
                    cleared += 1
                except OSError:
                    pass
    except FileNotFoundError:
        pass
    if cleared:
        logging.info(f"Cleared {cleared} scratch files")
