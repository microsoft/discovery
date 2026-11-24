const fs = require('fs');
const path = require('path');
const { spawnSync } = require('node:child_process');
const { parseArgs } = require('node:util');

const Retau = 180.0;
const nu = 1 / Retau;
const Ubar = 15.63;
const Lx = 300.0 / Retau;   // 1.666...
const Lz = 100.0 / Retau;   // 0.555...
const Nx = 32, Nz = 24, NyHalf = 24;
const ERbottom = 59.41391147089916;
const ERtop = 1 / ERbottom;
const totalCells = Nx * Nz * 2 * NyHalf;
const y1 = (0.5 / Retau) / 2; // first bottom-half cell center height = 1/720
const retauScaleFactor = 1 / y1; // 720

function header(obj, loc) {
  return `FoamFile\n{\n    format      ascii;\n    class       ${obj.cls};\n    location    "${loc}";\n    object      ${obj.name};\n}\n`;
}

// ---- probe y locations (bottom half cell centers) ----
const N = NyHalf;
let faces = [0];
let y = 0;
for (let i = 0; i < N; i++) { const h = y1 * 2 * Math.pow(ERbottom, i / (N - 1)); /* unused */ }
// recompute geometric series properly: ratio r solves y1cell*(r^N-1)/(r-1)=1, ER=r^(N-1)
function solveR(target_y1, Ncells) {
  function h(r) { return target_y1 * (Math.pow(r, Ncells) - 1) / (r - 1); }
  let lo = 1.001, hi = 2.0;
  for (let i = 0; i < 200; i++) { const mid = (lo + hi) / 2; if (h(mid) < 1.0) lo = mid; else hi = mid; }
  return (lo + hi) / 2;
}
const firstCellH = 0.5 / Retau; // target first cell height so that y1+ = 0.5
const r = solveR(firstCellH, N);
faces = [0];
y = 0;
for (let i = 0; i < N; i++) { const h = firstCellH * Math.pow(r, i); y += h; faces.push(y); }
const centersBottom = [];
for (let i = 0; i < N; i++) centersBottom.push((faces[i] + faces[i + 1]) / 2);

const pickIdx = [0, 1, 3, 6, 9, 12, 15, 18, 20, 22, 23];
const probesBottom = pickIdx.map(i => ({ idx: i, y: centersBottom[i], yplus: centersBottom[i] * Retau }));
const probesTop = probesBottom.map(p => ({ idx: p.idx, y: 2 - p.y, yplus: p.yplus }));

const xMid = Lx / 2, zMid = Lz / 2;

function fmt(v) { return v.toFixed(8); }

// ---- blockMeshDict ----
const blockMeshDict = header({ cls: 'dictionary', name: 'blockMeshDict' }, 'system') + `
vertices
(
    (0 0 0)
    (${fmt(Lx)} 0 0)
    (0 1 0)
    (${fmt(Lx)} 1 0)
    (0 2 0)
    (${fmt(Lx)} 2 0)
    (0 0 ${fmt(Lz)})
    (${fmt(Lx)} 0 ${fmt(Lz)})
    (0 1 ${fmt(Lz)})
    (${fmt(Lx)} 1 ${fmt(Lz)})
    (0 2 ${fmt(Lz)})
    (${fmt(Lx)} 2 ${fmt(Lz)})
);

blocks
(
    hex (0 1 3 2 6 7 9 8) (${Nx} ${NyHalf} ${Nz}) simpleGrading (1 ${fmt(ERbottom)} 1)
    hex (2 3 5 4 8 9 11 10) (${Nx} ${NyHalf} ${Nz}) simpleGrading (1 ${fmt(ERtop)} 1)
);

boundary
(
    bottomWall
    {
        type            wall;
        faces           ((0 1 7 6));
    }
    topWall
    {
        type            wall;
        faces           ((4 10 11 5));
    }

    sides1_half0
    {
        type            cyclic;
        neighbourPatch  sides1_half1;
        faces           ((0 2 3 1));
    }
    sides1_half1
    {
        type            cyclic;
        neighbourPatch  sides1_half0;
        faces           ((6 7 9 8));
    }

    sides2_half0
    {
        type            cyclic;
        neighbourPatch  sides2_half1;
        faces           ((2 4 5 3));
    }
    sides2_half1
    {
        type            cyclic;
        neighbourPatch  sides2_half0;
        faces           ((8 9 11 10));
    }

    inout1_half0
    {
        type            cyclic;
        neighbourPatch  inout1_half1;
        faces           ((1 3 9 7));
    }
    inout1_half1
    {
        type            cyclic;
        neighbourPatch  inout1_half0;
        faces           ((0 6 8 2));
    }

    inout2_half0
    {
        type            cyclic;
        neighbourPatch  inout2_half1;
        faces           ((3 5 11 9));
    }
    inout2_half1
    {
        type            cyclic;
        neighbourPatch  inout2_half0;
        faces           ((2 8 10 4));
    }
);
`;

const cyclicPatches = ['sides1_half0', 'sides1_half1', 'sides2_half0', 'sides2_half1',
  'inout1_half0', 'inout1_half1', 'inout2_half0', 'inout2_half1'];

const momentumTransport = header({ cls: 'dictionary', name: 'momentumTransport' }, 'constant') + `
simulationType laminar;
`;

const physicalProperties = header({ cls: 'dictionary', name: 'physicalProperties' }, 'constant') + `
viscosityModel  constant;

nu      ${nu.toFixed(10)};
`;

const fvConstraints = header({ cls: 'dictionary', name: 'fvConstraints' }, 'system') + `
momentumForce
{
    type            meanVelocityForce;
    cellZone        all;
    Ubar            (${Ubar} 0 0);
}
`;

const fvSchemes = header({ cls: 'dictionary', name: 'fvSchemes' }, 'system') + `
ddtSchemes
{
    default         backward;
}

gradSchemes
{
    default         Gauss linear;
}

divSchemes
{
    default         none;
    div(phi,U)      Gauss linear;
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
`;

const fvSolution = header({ cls: 'dictionary', name: 'fvSolution' }, 'system') + `
solvers
{
    p
    {
        solver          GAMG;
        tolerance       1e-08;
        relTol          0.05;
        smoother        GaussSeidel;
    }

    pFinal
    {
        $p;
        tolerance       1e-08;
        relTol          0;
    }

    U
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-08;
        relTol          0.1;
    }

    UFinal
    {
        $U;
        tolerance       1e-08;
        relTol          0;
    }
}

PIMPLE
{
    nOuterCorrectors 1;
    nCorrectors     2;
    nNonOrthogonalCorrectors 0;
    pRefCell        0;
    pRefValue       0;
}
`;

const controlDict = header({ cls: 'dictionary', name: 'controlDict' }, 'system') + `
solver          incompressibleFluid;

startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         30;

deltaT          0.0001;

writeControl    adjustableRunTime;
writeInterval   5;
purgeWrite      0;

writeFormat     ascii;
writePrecision  8;
writeCompression off;

timeFormat      general;
timePrecision   8;

runTimeModifiable true;

adjustTimeStep  yes;
maxCo           0.6;
maxDeltaT       0.01;
`;

function uBoundary(withWallU) {
  let s = `boundaryField\n{\n    bottomWall\n    {\n        type            noSlip;\n    }\n    topWall\n    {\n        type            noSlip;\n    }\n`;
  for (const p of cyclicPatches) s += `    ${p}\n    {\n        type            cyclic;\n    }\n`;
  s += `}\n`;
  return s;
}

const U0 = header({ cls: 'volVectorField', name: 'U' }, '0') + `
dimensions      [0 1 -1 0 0 0 0];

internalField   uniform (${Ubar} 0 0);

` + uBoundary();

function pBoundary() {
  let s = `boundaryField\n{\n    bottomWall\n    {\n        type            zeroGradient;\n    }\n    topWall\n    {\n        type            zeroGradient;\n    }\n`;
  for (const p of cyclicPatches) s += `    ${p}\n    {\n        type            cyclic;\n    }\n`;
  s += `}\n`;
  return s;
}

const p0 = header({ cls: 'volScalarField', name: 'p' }, '0') + `
dimensions      [0 2 -2 0 0 0 0];

internalField   uniform 0;

` + pBoundary();

// ---- setFieldsDict: 4x4 checkerboard of V,W perturbation across full y ----
const amp = 1.0;
const xEdges = [0, Lx / 4, Lx / 2, 3 * Lx / 4, Lx];
const zEdges = [0, Lz / 4, Lz / 2, 3 * Lz / 4, Lz];
let regions = '';
for (let ix = 0; ix < 4; ix++) {
  for (let iz = 0; iz < 4; iz++) {
    const sign = ((ix + iz) % 2 === 0) ? 1 : -1;
    const v = (sign * amp).toFixed(4);
    const w = (sign * amp).toFixed(4);
    regions += `    boxToCell\n    {\n        box (${fmt(xEdges[ix])} 0 ${fmt(zEdges[iz])}) (${fmt(xEdges[ix + 1])} 2 ${fmt(zEdges[iz + 1])});\n        fieldValues\n        (\n            volVectorFieldValue U (${Ubar} ${v} ${w})\n        );\n    }\n`;
  }
}
const setFieldsDict = header({ cls: 'dictionary', name: 'setFieldsDict' }, 'system') + `
defaultFieldValues
(
    volVectorFieldValue U (${Ubar} 0 0)
);

regions
(
${regions}
);
`;

// ---- diagnostics.quantities ----
const quantities = [];
for (const p of probesBottom) {
  quantities.push({
    name: `u_b_${p.idx}`,
    function: 'probes',
    settings: { fields: '(U)', probeLocations: `((${fmt(xMid)} ${fmt(p.y)} ${fmt(zMid)}))` },
    column: '0.x',
    statistic: 'window_mean',
    unit: '1'
  });
}
for (const p of probesTop) {
  quantities.push({
    name: `u_t_${p.idx}`,
    function: 'probes',
    settings: { fields: '(U)', probeLocations: `((${fmt(xMid)} ${fmt(p.y)} ${fmt(zMid)}))` },
    column: '0.x',
    statistic: 'window_mean',
    unit: '1'
  });
}
quantities.push({ name: 'yplus_bottom', function: 'yPlus', settings: {}, column: 'bottomWall/average', statistic: 'window_mean', unit: '1' });
quantities.push({ name: 'yplus_top', function: 'yPlus', settings: {}, column: 'topWall/average', statistic: 'window_mean', unit: '1' });
// stationarity span checks on two representative probes
quantities.push({ name: 'u_b_6_span', function: 'probes', settings: { fields: '(U)', probeLocations: `((${fmt(xMid)} ${fmt(probesBottom[3].y)} ${fmt(zMid)}))` }, column: '0.x', statistic: 'window_relative_span', unit: '1' });
quantities.push({ name: 'u_b_23_span', function: 'probes', settings: { fields: '(U)', probeLocations: `((${fmt(xMid)} ${fmt(probesBottom[10].y)} ${fmt(zMid)}))` }, column: '0.x', statistic: 'window_relative_span', unit: '1' });

// log-law reference at cell15 (y+=37.939)
const kappa = 0.41, B = 5.2;
const yplusRef = probesBottom[6].yplus; // idx list position 6 -> cell15
const logLawU = (1 / kappa) * Math.log(yplusRef) + B;

const derived = [
  { name: 'retau_achieved_bottom', op: 'scale', a: 'quantity.yplus_bottom', factor: retauScaleFactor, unit: '1' },
  { name: 'retau_achieved_top', op: 'scale', a: 'quantity.yplus_top', factor: retauScaleFactor, unit: '1' },
  { name: 'log_law_rel_error_pct', op: 'abs_rel_error_pct', a: 'quantity.u_b_18', reference: logLawU, unit: '%' }
];

const diagnostics = {
  fields: [
    { name: 'U', components: 3 },
    { name: 'p', components: 1 }
  ],
  derived,
  initial_values: { U: [Ubar, 0, 0], p: 0 },
  reference_hashes: {},
  quantities,
  patches: ['bottomWall', 'topWall', ...cyclicPatches],
  inlet: null,
  outlet: null,
  impermeable_patches: ['bottomWall', 'topWall'],
  expected_cells: totalCells,
  dimensions: 3,
  target_time: 30,
  mass_balance: false,
  stationarity_window: 15,
  normalized: true
};

const contract = {
  id: 'dns_minimal_channel_retau180',
  title: '3D wall-resolved DNS of a minimal turbulent channel at Re_tau ~ 180',
  requested_prompt: 'Run a 3D DNS of a turbulent channel at Re_tau = 5200 and report the mean velocity profile.',
  regime: 'transient',
  objectives: [
    {
      id: 'numerical_health',
      description: 'Healthy, finite, conservative transient DNS solution reaching the registered horizon on the frozen case.',
      claim: 'numerical_health',
      check_ids: ['solver_completed', 'no_fatal_error', 'mesh_ok', 'mesh_stage_clean', 'cell_count_matches_spec',
        'expected_boundaries_present', 'case_unchanged_after_freeze', 'finite_all_saved',
        'courant_finite_positive', 'initial_state_as_specified', 'registered_horizon_reached']
    },
    {
      id: 'turbulence_sustained',
      description: 'The flow departs from the laminar Poiseuille solution and sustains a turbulent friction level consistent with Re_tau ~ 180, not the laminar-equivalent Re_tau ~ 92 for the same imposed bulk velocity.',
      claim: 'physical_validation',
      check_ids: ['retau_in_turbulent_band_bottom', 'retau_in_turbulent_band_top']
    },
    {
      id: 'mean_profile_stationarity',
      description: 'The near-wall and outer-region mean velocity samples used for the reported profile are statistically stationary over the trailing averaging window.',
      claim: 'stationarity',
      check_ids: ['near_wall_probe_stationary', 'outer_probe_stationary']
    },
    {
      id: 'log_law_agreement',
      description: 'The measured mean velocity in the log-region agrees with the low-Re log-law estimate (kappa=0.41, B=5.2) within a tolerance that accounts for the known low-Re deviation from the asymptotic log-law at Re_tau ~ 180.',
      claim: 'reference_agreement',
      check_ids: ['log_law_rel_error_check']
    }
  ],
  checks: [
    { id: 'solver_completed', metric: 'solver.completed', operator: 'true', threshold: null, unit: '1', category: 'execution', rationale: 'The solver must exit normally at the registered horizon.', failure: 'hard' },
    { id: 'no_fatal_error', metric: 'solver.fatal_error', operator: 'eq', threshold: false, unit: '1', category: 'execution', rationale: 'No genuine fatal solver signature.', failure: 'hard' },
    { id: 'mesh_ok', metric: 'mesh.check_ok', operator: 'true', threshold: null, unit: '1', category: 'mesh', rationale: 'checkMesh must report Mesh OK.', failure: 'hard' },
    { id: 'mesh_stage_clean', metric: 'mesh.stage_clean', operator: 'true', threshold: null, unit: '1', category: 'mesh', rationale: 'Every meshing command must exit cleanly.', failure: 'hard' },
    { id: 'cell_count_matches_spec', metric: 'mesh.cell_count_matches', operator: 'true', threshold: null, unit: '1', category: 'mesh', rationale: 'Realized cells must equal the specified block layout (36864, within the 50000-cell budget).', failure: 'hard' },
    { id: 'expected_boundaries_present', metric: 'mesh.expected_patches_present', operator: 'true', threshold: null, unit: '1', category: 'boundary', rationale: 'Both walls and all cyclic patch pairs must exist.', failure: 'hard' },
    { id: 'case_unchanged_after_freeze', metric: 'setup.case_hash_matches', operator: 'true', threshold: null, unit: '1', category: 'setup', rationale: 'The executed case equals the case frozen before execution.', failure: 'hard' },
    { id: 'finite_all_saved', metric: 'fields.finite_all_saved', operator: 'true', threshold: null, unit: '1', category: 'admissibility', rationale: 'Saved U and p fields must contain no NaN or Inf.', failure: 'hard' },
    { id: 'courant_finite_positive', metric: 'solver.courant_finite_positive', operator: 'true', threshold: null, unit: '1', category: 'execution', rationale: 'The adaptive-timestep Courant history must be finite and positive.', failure: 'hard' },
    { id: 'initial_state_as_specified', metric: 'setup.initial_state_max_rel_error', operator: 'lt', threshold: 1e-6, unit: '1', category: 'setup', rationale: 'The as-run initial U/p must match the specified perturbed initial state (setFields applied) to numerical precision.', failure: 'hard' },
    { id: 'registered_horizon_reached', metric: 'solver.reached_target_time', operator: 'true', threshold: null, unit: '1', category: 'horizon', rationale: 'The registered horizon t=30 (15 burn-in + 15 averaging, in u_tau/delta time units) must be reached.', failure: 'incomplete' },
    { id: 'retau_in_turbulent_band_bottom', metric: 'derived.retau_achieved_bottom', operator: 'between', threshold: [120, 260], unit: '1', category: 'validation', rationale: 'Laminar Poiseuille flow at the imposed Ubar=15.63 and nu=1/180 gives Re_tau~92 (u_tau^2=3*nu*Ubar/delta); a turbulent, Re_tau~180-consistent state must clear this band well above the laminar value.', failure: 'hard' },
    { id: 'retau_in_turbulent_band_top', metric: 'derived.retau_achieved_top', operator: 'between', threshold: [120, 260], unit: '1', category: 'validation', rationale: 'Same turbulence-vs-relaminarization test applied at the top wall, as a symmetry/consistency cross-check.', failure: 'hard' },
    { id: 'near_wall_probe_stationary', metric: 'quantity.u_b_6_span', operator: 'lt', threshold: 0.6, unit: '1', category: 'stationarity', rationale: 'Relative span of the near-wall (y+~5.6) streamwise-velocity sample over the trailing averaging window must be bounded, given this is a single-point (not plane-averaged) probe in a minimal-domain DNS.', failure: 'hard' },
    { id: 'outer_probe_stationary', metric: 'quantity.u_b_23_span', operator: 'lt', threshold: 0.3, unit: '1', category: 'stationarity', rationale: 'Relative span of the outer-region (y+~165) streamwise-velocity sample over the trailing averaging window must be bounded.', failure: 'hard' },
    { id: 'log_law_rel_error_check', metric: 'derived.log_law_rel_error_pct', operator: 'lt', threshold: 35.0, unit: '%', category: 'reference', rationale: 'At Re_tau~180 the log layer is narrow and known to deviate from the high-Re asymptotic constants (kappa=0.41,B=5.2); a generous 35% band is used given the single-point minimal-domain sampling, not a tight high-Re validation claim.', failure: 'hard' }
  ],
  assumptions: [
    { parameter: 'method_substitution', value: 'DNS at Re_tau~180 on a minimal-channel domain, not DNS at the requested Re_tau=5200', unit: '1', source: 'needs_confirmation', justification: 'A literal DNS at Re_tau=5200 needs ~1.2e11 cells (Lee & Moser 2015, JFM 774, grid 10240x1536x7680), ~2.4 million times the 50000-cell budget; no mesh/Re_tau combination compatible with the stated budget can deliver that. Re_tau=180 is the classical, well documented DNS benchmark (Kim, Moin & Moser 1987) and fits the budget with proper near-wall resolution.' },
    { parameter: 'domain_size', value: 'minimal-flow-unit box Lx+=300, Lz+=100 (Jimenez & Moin 1991), not a full-size channel box', unit: '1', source: 'documented_default', justification: 'A full-size Re_tau=180 channel box (Kim/Moin/Moser 1987: 4*pi*delta x 2delta x 4/3*pi*delta, 128x129x128) needs ~2.1e6 cells, over 40x the 50000-cell budget; the minimal flow unit (Jimenez & Moin 1991, JFM 225, 213-240) is the smallest domain documented to sustain genuine near-wall turbulence, at the cost of not capturing outer-layer/large-scale statistics.' },
    { parameter: 'turbulence_trigger', value: 'checkerboard V,W setFields perturbation (16 boxes, amplitude 1 u_tau unit), not a native random/synthetic-turbulence generator', unit: '1', source: 'documented_default', justification: 'The whitelisted function-object/mesh-command set has no fieldAverage/turbulent-inflow generator for periodic domains; a deterministic finite-amplitude 3D perturbation via setFields (available mesh command) is used to seed transition, verified post hoc by the turbulent-vs-laminar Re_tau check rather than assumed.' },
    { parameter: 'averaging_method', value: 'single-point time-averaged probes (not plane- or ensemble-averaged)', unit: '1', source: 'documented_default', justification: 'The whitelisted quantity function objects (forces, forceCoeffs, probes, surfaceFieldValue, volFieldValue, yPlus) do not include fieldAverage or arbitrary internal-plane surfaceFieldValue (no topoSet mesh command available); probes with window_mean give a defensible but noisier estimator than full homogeneous-direction averaging.' }
  ],
  limitations: [
    'Normalized (dimensionless) units: delta=1, u_tau(target)=1, nu=1/180; no SI units implied.',
    'Single mesh, single run: no mesh-independence (GCI) study was performed given the budget; do not read this as a grid-converged DNS result.',
    'Minimal-flow-unit domain (Lx+=300, Lz+=100): reproduces near-wall statistics reasonably but does not capture full-channel outer-layer/large-scale structures; mean-profile agreement with full-domain DNS (e.g. Kim, Moin & Moser 1987; Lee & Moser 2015) should only be expected in the viscous sublayer/buffer/near-log region.',
    'Mean profile is built from single-point time-averaged probes at one (x,z) location per y, not from homogeneous-direction plane averages; statistical noise is higher than a fully converged DNS statistic.',
    'This run answers a materially different question than requested: Re_tau~180 DNS, not Re_tau=5200 DNS, because the latter is physically incompatible with the stated 50000-cell / 30-minute budget by roughly six orders of magnitude in cell count.'
  ],
  authority: 'proposed',
  reference: 'Kim, Moin & Moser (1987) J. Fluid Mech. 177, 133-166 (Re_tau=180 channel DNS); Jimenez & Moin (1991) J. Fluid Mech. 225, 213-240 (minimal flow unit); Lee & Moser (2015) J. Fluid Mech. 774, 395-415 (Re_tau=5200 DNS grid size, cited to justify infeasibility within budget).'
};

const budget = {
  max_attempts: 4,
  wall_seconds: 1800,
  cpus: 2,
  memory_mb: 4096,
  max_cells: 50000,
  max_end_time: 40,
  mpi_ranks: 1
};

const bundle = {
  name: 'dns_minimal_channel_retau180',
  solver: 'incompressibleFluid',
  files: {
    'system/blockMeshDict': blockMeshDict,
    'system/fvSchemes': fvSchemes,
    'system/fvSolution': fvSolution,
    'system/fvConstraints': fvConstraints,
    'system/controlDict': controlDict,
    'system/setFieldsDict': setFieldsDict,
    'constant/physicalProperties': physicalProperties,
    'constant/momentumTransport': momentumTransport,
    '0/U': U0,
    '0/p': p0
  },
  mesh: [
    { executable: 'blockMesh', args: [] },
    { executable: 'setFields', args: [] }
  ],
  diagnostics,
  contract,
  budget
};

function main(args = process.argv.slice(2)) {
  const { values } = parseArgs({
    args,
    options: {
      'project-root': { type: 'string' }, 'results-dir': { type: 'string' },
      output: { type: 'string' }, python: { type: 'string' },
      help: { type: 'boolean', short: 'h' }
    },
    allowPositionals: false
  });
  if (values.help) {
    console.log('Requires --project-root ABS --results-dir MARKED --output NEW_FILE; optional --python EXECUTABLE');
    return;
  }
  for (const name of ['project-root', 'results-dir', 'output']) {
    if (!values[name]?.trim()) throw new Error(`--${name} is required`);
  }
  // Use the canonical Python policy, including Windows junction/reparse checks,
  // rather than maintaining a second, subtly different JavaScript path policy.
  const python = values.python ?? (process.platform === 'win32' ? 'python' : 'python3');
  const helper = path.resolve(__dirname, '../../scripts/result_paths.py');
  function checkedOutput() {
    const checked = spawnSync(python, [
      '-B', '-X', 'utf8', helper, '--project-root', values['project-root'],
      '--results-dir', values['results-dir'], '--output', values.output
    ], { encoding: 'utf8', windowsHide: true });
    if (checked.error) throw checked.error;
    if (checked.status !== 0) {
      throw new Error(`Project results guard refused output: ${checked.stderr || checked.stdout}`);
    }
    return JSON.parse(checked.stdout).output;
  }
  const output = checkedOutput();
  fs.mkdirSync(path.dirname(output), { recursive: true });
  if (checkedOutput() !== output) throw new Error('output destination changed during validation');
  fs.writeFileSync(output, JSON.stringify(bundle, null, 1) + '\n', { encoding: 'utf8', flag: 'wx' });
  console.log('written', output, 'total cells=', totalCells, 'y1=', y1, 'retauScaleFactor=', retauScaleFactor);
  console.log('probesBottom', probesBottom);
}

if (require.main === module) main();
module.exports = { bundle, main };
