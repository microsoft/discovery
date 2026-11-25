# Examples

Examples are **inputs to inspect and adapt**, not pre-approved scientific
answers or fresh 0.2.1 execution receipts. Every new request needs its own
assumptions, units, measurable objectives, justified checks, and budget before
execution. Keep supplied inputs unchanged; write adapted bundles to new paths.

All new user-generated work belongs in a marked results container directly under
the explicitly selected user project, never under any project `agents` directory
or anywhere in the acquired contribution source, even staged elsewhere. Do not
infer the project from CWD, Git or source acquisition; ask only when the intended
project is ambiguous. Initialize before authoring/freezing; static curated
examples and reviewed test fixtures remain contribution assets. Runtime app
data, configuration, signing keys, resource caps and shared slots stay separate.

## Recommended first input

[channel-path-check.json](channel-path-check.json) is a self-contained,
health-only, two-dimensional laminar channel bundle. It makes no pressure-drop
accuracy, developed-flow, stationarity, experimental-validation, or
mesh-independence claim. Its expected mesh has 6,000 cells. This narrow contract
is intentional, not evidence that broader physical objectives may be omitted
from an engineering request.

From the entry directory after [host installation](../docs/installation.md):

```powershell
$dp = "$env:LOCALAPPDATA\DiscoveryPhysics\venv\Scripts\discovery-physics.exe"
& $dp schema bundle
$lint = & $dp lint .\examples\channel-path-check.json | ConvertFrom-Json
if (-not $lint.ok) { throw ($lint.errors -join '; ') }
```

This checks input without solving. Inspect warnings and all JSON fields; lint
failure can be represented as `ok: false` even when the command exits normally.
Use the actual executable for custom installations.

Before generating/adapting input or freezing a **new** campaign, initialize the
explicit user project's results with the installed
[results helper](../skills/phy-openfoam/scripts/project_results.py):

```powershell
$project = Read-Host 'Existing absolute user project root (not acquired source)'
$entry = Read-Host 'Existing absolute approved phy-openfoam source entry'
foreach ($selected in @($project, $entry)) {
   if (-not [IO.Path]::IsPathFullyQualified($selected)) { throw 'Select an existing absolute path.' }
}
$project = (Resolve-Path -LiteralPath $project -ErrorAction Stop).Path
$entry = (Resolve-Path -LiteralPath $entry -ErrorAction Stop).Path
$py = "$env:LOCALAPPDATA\DiscoveryPhysics\venv\Scripts\python.exe"
$paths = Join-Path $project '.github/skills/phy-openfoam/scripts/project_results.py'
$layout = & $py $paths init --project-root $project --slug channel-path-check | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Results initialization failed; do not author/freeze.' }
$results = $layout.results_root
$bundle = Join-Path $results 'inputs/channel-path-check.json'
Copy-Item -LiteralPath (Join-Path $entry 'examples/channel-path-check.json') -Destination $bundle
& $py $paths check --project-root $project --results-dir $results --destination $bundle
```

This creates unique `results-<slug>-<utc>-<suffix>/` with a manifest and
inputs/analysis/logs/exports/runs/studies directories. Slugs use lowercase
letters/digits with single hyphens; `--exact` requests the exact slug folder and
refuses collisions. Record source revision, original native paths and run/study
IDs in the manifest without copying keys or editing signed records. Initialization
does not authorize a solve. The `check` action is read-only.

An optional **new local execution**, only after operator preflight and approval,
uses that container and the actual installed CLI:

```powershell
$lint = & $py $paths run --project-root $project --results-dir $results --cli $dp `
   -- lint inputs/channel-path-check.json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $lint.ok) { throw 'Input lint failed; do not prepare/execute.' }
$prepared = & $py $paths run --project-root $project --results-dir $results --cli $dp `
   -- prepare inputs/channel-path-check.json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $prepared.error) { throw 'Preparation failed; inspect retained evidence.' }
# Stop and obtain actual user confirmation first if the prepared record requires it.
& $py $paths run --project-root $project --results-dir $results --cli $dp -- execute $prepared.run_id
& $py $paths run --project-root $project --results-dir $results --cli $dp -- status $prepared.run_id
& $py $paths run --project-root $project --results-dir $results --cli $dp -- verify $prepared.run_id
```

The wrapper invokes only the requested command with child-only
`DISCOVERY_PHYSICS_RUNS=<results>/runs`, CWD at results and CLI logs under logs.
Relative inputs resolve from that root; studies stay in its studies sibling.
It does not automatically solve, propose or confirm and changes no global
environment, HOME, operator policy, signing keys, caps or shared solve slots.
These commands create new run records and consume resources. They do not assert
that this candidate was executed while writing the docs. The path/fixture
scripts use the same public input by default; see [scripts](../scripts/README.md).
A health assessment is not permission to claim an accurate physical prediction.
For user-facing live acceptance, follow the full policy proposal/finalization
workflow and require `final_verdict: ACCEPT` with `live_acceptance: true`.
Existing campaign status instead reads its original recorded native path directly,
including legacy external stores: no initializer, wrapper/log creation, report
or timer for a status-only question. See [progress](../docs/progress.md).

## Bounded timed prompts

These prompts request **new**, separately approved investigations, not resumed
campaigns or already validated results. They target a useful local CFD result
and final HTML after setup/approval on a ready worker. Targets are estimates,
**not hard deadlines, measured timings or convergence guarantees**. Cold image
download/build, dependency installation and host provisioning are excluded.
Meshing, reconstruction, extraction, native verification and report packaging
still have overhead: worker caps are not end-to-end report delivery guarantees.

| Prompt | Target, not a guarantee | Frozen numerical scope to propose | Hard worker/output allocation to approve | Explicit exclusions |
|---|---|---|---|---|
| [Thermal quick screen](prompts/01-thermal-quick.txt) | 5–10 minutes after setup and approval | One execution; planned $160 \times 32 = 5120$ cells (at most $6000$); $6000$ steady iterations, final $1000$ for settling | $900\thinspace\mathrm{s}$ worker cap; $512\thinspace\mathrm{MB}$ output; two CPU cores and $4\thinspace\mathrm{GiB}$ RAM | No automatic retry/continuation, extra pilot, alternate height or grid/design study; no mesh-independence or physical-validation claim |
| [Isolated-cylinder comparison](prompts/02-cylinder-hour.txt) | About one hour after setup and approval | Exactly two sequential executions/meshes near $8000$ and $32000$ cells (at most $40000$ each); at most $10000$ steady iterations each, final $2000$ for settling | $2700\thinspace\mathrm{s}$ per execution, at most $5400\thinspace\mathrm{s}$ total worker allocation; $512\thinspace\mathrm{MB}$ output per run; two CPU cores and $4\thinspace\mathrm{GiB}$ RAM | No automatic continuation, extra pilot, third grid, expanded-domain run, second cylinder or tandem-spacing winner |

The thermal prompt measures pressure drop and the native flux-weighted outlet
temperature with a health/settling screen. The cylinder prompt measures drag per
unit depth, drag coefficient, an applicable point-reference discrepancy and a
**two-grid difference only**. Two grids do not establish three-grid GCI, mesh
independence or domain independence. Agree reference normalization and every
numerical/reference tolerance before freezing; retain failed agreement rather
than changing the reference or adding simulations.

Use comparable measured costs before approval. If the expected work does not
reasonably fit the target, explain and ask before solving; generous hard caps
do not authorize extra attempts, unlimited runtime, relaxed checks or edits to
frozen budgets. Report actual measured elapsed cost and its scope, including
missing measurements. End both workflows with a linked professional
self-contained HTML report: concise opening summary, labeled native field
images or an explicitly labeled input schematic if no solution is available,
verified outcomes and limitations. Failure or a blocker must still be reported;
use required `--project-root` and exactly one of an existing marked
`--results-dir` or new report-only `--slug`. Fresh HTML/snapshot/receipt files
default to the marked root. Optional `--out` requires `--results-dir` and stays
inside it, outside signed stores, without overwriting existing report files.
Do not combine `--slug` with `--out`; initialize first for a custom subdirectory.
Rerender into fresh
`reports/v2`. A legacy `--runs-root` is read-only input, not a relocation of
native records or keys. See [reporting](../docs/reporting.md).
These examples do not override the default
completion-focused planning for requests without a tight timing objective.

## Additional authoring references

| Bundle | Intended starting point |
|---|---|
| [cases/channel.json](cases/channel.json) | Channel setup and request-specific diagnostics |
| [cases/poiseuille10pa_bundle.json](cases/poiseuille10pa_bundle.json) | Pressure-driven Poiseuille authoring example; review its units and reference checks |
| [cases/cavity_re100_bundle.json](cases/cavity_re100_bundle.json) | Lid-driven cavity authoring example |
| [cases/bfs_bundle.json](cases/bfs_bundle.json) | Backward-facing-step authoring example |
| [cases/fs.json](cases/fs.json) | Forward-facing-step benchmark-style bundle |
| [cases/nz.json](cases/nz.json) | Nozzle benchmark-style bundle |
| [cases/square_obstacle.json](cases/square_obstacle.json) | Obstacle-flow authoring example |

Run current lint on the actual input revision and review scientific suitability
before use. A filename, prior source-layout lint result, or historical accepted
run does not qualify a new case or establish that a rewritten contract is valid.
Do not silently substitute one of these cases for an unsupported user request.

The CLI can also generate a worked benchmark bundle:

```powershell
& $py $paths run --project-root $project --results-dir $results --cli $dp -- example nozzle inputs/new-nozzle.json
& $py $paths run --project-root $project --results-dir $results --cli $dp -- example forward_step inputs/new-forward-step.json
```

Use fresh results-contained destinations, never source/CWD defaults. The same
wrapper restricts new `geometry` and `export` outputs to the selected results
container. The forward-step generator reads the selected image's
Foundation tutorial, so it requires a working engine/image. It is an allowed
native `example forward_step` action, not an arbitrary developer-script route;
normal user/operator approval and later scientific gates still apply. Published reference
values are comparison targets, never substitutes for newly measured output.

## Developer builders

| Builder | Output type |
|---|---|
| [development/build_bundle.py](development/build_bundle.py) | Channel bundle |
| [development/build_bfs_bundle.py](development/build_bfs_bundle.py) | Backward-facing-step bundle |
| [development/build_poiseuille10pa.py](development/build_poiseuille10pa.py) | Poiseuille bundle |
| [development/gen_bundle.py](development/gen_bundle.py) | Square-obstacle bundle |
| [development/build_dns_channel.js](development/build_dns_channel.js) | Proposed channel/DNS-style authoring input, not demonstrated DNS |

Every builder requires `--project-root <absoluteproject> --results-dir
<existingmarkedresults> --output <freshfile>`. The marked root must already
belong to the selected project; an arbitrary directory or run-store environment
override is insufficient. Supply a fresh results/inputs destination: source/CWD
defaults and overwrites are refused. The four Python builders load the shared
source-entry guard with stdlib Python. The JavaScript builder needs an existing
Node.js supporting `node:util.parseArgs` and invokes that same Python guard;
use `--python` to select the actual interpreter. No pip reinstall or image update
is needed for input authoring. Builder execution creates input, not solver evidence:

```powershell
& $py -X utf8 -B (Join-Path $entry 'examples/development/build_bundle.py') `
   --project-root $project --results-dir $results `
   --output (Join-Path $results 'inputs/new-channel.json')
node (Join-Path $entry 'examples/development/build_dns_channel.js') `
   --project-root $project --results-dir $results `
   --output (Join-Path $results 'inputs/proposed-channel.json') --python $py
```

Keep generated builder scripts, analysis, logs and exports in the same container;
do not write adapted copies back into the acquired source. The native CLI wrapper
does not run arbitrary Python/Node scripts. See [developer routing](../scripts/README.md)
for the child-process source launcher, explicit benchmark output/work destinations
and results-contained test temporaries. Source benchmark checks need both the
entry's tools/openfoam/src and entry root on child-only `PYTHONPATH`; editing
source does not update non-editable installed benchmark modules or the worker.

The proposed DNS-style input must not be presented as a completed or validated
DNS result. The historical H14 substitute remained confirmation-blocked and
unexecuted; generating a bundle does not supply user consent or a final verdict.
See [validation history](../benchmarks/VALIDATION-HISTORY.md).

## Adapting a case safely

1. Clarify geometry, fluid properties, boundary conditions, regime, target
   quantities, fidelity, and budget. Record material unknowns as
   `needs_confirmation`; never confirm them on the user's behalf. Select the
   absolute user project and initialize results before authoring/freezing.
2. Discover actual solver/tutorial support. Foundation 14 and OpenCFD are not
   interchangeable. Geometry conversion alone does not guarantee meshing.
3. Declare diagnostics through supported function objects and bind checks to
   produced metrics with their real units. For incompressible output,
   kinematic pressure has units $\mathrm{m^2\,s^{-2}}$, not automatically
   $\mathrm{Pa}$; any conversion needs justified density/reference information.
4. Cover each requested claim explicitly. Numerical health is not physical
   validation; mesh independence and design ranking need registered cross-run
   evidence and uncertainty criteria.
5. Freeze before solving. Respect correction budgets and immutable evidence.
   Report rejected/unknown checks rather than changing thresholds afterward.

Operator configuration and runtime exceptions are not bundle fields to tune.
See [configuration](../docs/configuration.md),
[architecture](../docs/architecture.md), and
[troubleshooting](../docs/troubleshooting.md).