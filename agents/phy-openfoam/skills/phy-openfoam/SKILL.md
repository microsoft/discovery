---
name: phy-openfoam
description: "Use when: running, setting up, or assessing CFD / OpenFOAM, or answering status, progress, and 'is it still running?' questions about an existing campaign. Covers channels, heat transfer, external aerodynamics, and compressible or incompressible flows. Author a free-form case plus a scientific contract, freeze it, run OpenFOAM Foundation 14 in a sandbox, and let deterministic checks decide ACCEPT / REJECT / INCONCLUSIVE / CORRECT_AND_RERUN. Works with clio-mode; no Discovery tasks or engines."
license: MIT
compatibility: "Discovery with shell access; Python 3.11+ host CLI and Podman or Docker Linux/AMD64 worker installed separately. Qualified installer: Windows x64."
metadata:
   version: "0.2.1"
---

# phy-openfoam — Evidence-gated physics with OpenFOAM

You (the reasoning agent, normally `clio-mode`) do the open-ended work: interpret
the request, design the case, write the scientific contract, read evidence,
diagnose, and propose actions. **You never decide acceptance.** The
`discovery-physics` CLI measures the evidence and its deterministic gate decides.
Never state that a result is accepted unless `finalize` returned
`final_verdict: ACCEPT` with `live_acceptance: true`.

## Calling the tools

Run the `discovery-physics` CLI from your shell tool (JSON in, JSON out). There
is no MCP server; do not look for `physics_*` tools.

Install the complete supplied `skills/phy-openfoam/` folder at
`.github/skills/phy-openfoam/` in the user's Discovery project (`skills` is
plural), including this file, [the results helper](./scripts/project_results.py),
and [the reporting helper](./scripts/render_report.py).
That installs the workflow, results routing, and report packaging, not the runtime.
Obtain the runtime separately from the approved `agents/phy-openfoam` source revision;
do not assume an unmerged candidate is published upstream. Do not copy
application binaries, credentials, signing keys, virtual environments, or
another user's run store. A Markdown-only copy lacks both helpers: obtain the
complete skill before authoring/freezing a new campaign. A report-only fallback
must still obey the marked project-results policy below, or disclose a blocker.

## Project-owned results

- **Select the current user's project explicitly.** Use its existing absolute
   project root, never the shell CWD, a guessed Git root, or the acquired
   contribution as project identity. In a multi-root workspace, ask only when the
   intended user project is ambiguous. Source staging and runtime installation
   are not results roots, even if the acquired entry is outside `agents`.
- **Initialize before authoring or freezing.** The stdlib results helper's
   `init --project-root <absoluteuserproject> --slug <slug>` creates a unique
   direct child `results-<slug>-<utc>-<suffix>/` with `results-manifest.json` and
   `inputs/`, `analysis/`, `logs/`, `exports/`, `runs/`, `studies/`. Use lowercase
   letters/digits separated by single hyphens. `--exact` instead requests
   `results-<slug>` and refuses collisions; never overwrite/reuse an unmarked folder.
- Keep **all newly generated user inputs, bundles, geometry, scripts,
   preregistrations, logs, analyses, exports, HTML and native run/study artifacts**
   inside that marked container. Never write results under any project `agents`
   directory or anywhere inside the acquired contribution source. Static curated
   examples and reviewed test fixtures remain contribution assets, not output
   destinations. Record source revision, original native paths and run/study IDs
   in the results manifest without editing signed records or copying signing keys.
- `check --project-root <absoluteuserproject> --results-dir <markedresults>
   [--destination <path>]` is read-only. Use it to validate a selected container
   or generated destination, not to create a campaign during a status question.
- For an **explicitly authorized** native command, use `run --project-root
   <absoluteuserproject> --results-dir <markedresults> [--cli <installedCLI>]
   -- <nativecommand> <args>`. It invokes only the installed CLI, with child-only
   `DISCOVERY_PHYSICS_RUNS=<results>/runs`, CWD set to the results container, and
   retained CLI logs under `logs/`. Relative input arguments resolve from that
   results root; new `example`, `geometry` and `export` outputs must stay inside it.
   It does not automatically solve, propose, confirm, or authorize any lifecycle
   action. Keep HOME, operator configuration, signing keys, image, caps and shared
   solve slots unchanged; do not persist a global run-store override or add
   results metadata/resource overrides to the configuration model.
- **Existing campaigns keep their recorded native paths.** Status-only questions
   read that original store directly, including legacy stores outside the project:
   no initializer, `run` wrapper/logs, new report or timer. Read-only reporting may
   inspect a legacy store, but every new delivery belongs in project results.

The following is native-command vocabulary for an approved new campaign, not
permission to execute the whole list. Replace the explicit project and IDs;
resolve Python to an existing Python 3.11+ interpreter. Author the referenced
inputs inside the initialized container before invoking commands that read them.

```powershell
$dp = $env:DISCOVERY_PHYSICS_CLI
if (-not $dp) {
   $command = Get-Command discovery-physics -ErrorAction SilentlyContinue
   if ($command) { $dp = $command.Source }
   else {
      $data = if ($env:DISCOVERY_PHYSICS_HOME) { $env:DISCOVERY_PHYSICS_HOME } else { Join-Path $env:LOCALAPPDATA 'DiscoveryPhysics' }
      $dp = Join-Path $data 'venv/Scripts/discovery-physics.exe'
   }
}
if (-not (Test-Path -LiteralPath $dp)) { throw 'Operator action required: install the phy-openfoam runtime separately.' }
& $dp capabilities
& $dp tutorial shockFluid/forwardStep
$py = 'python'
$project = 'C:\work\cfd-project' # Explicit user project, not source staging or CWD.
$paths = Join-Path $project '.github/skills/phy-openfoam/scripts/project_results.py'
$layout = & $py $paths init --project-root $project --slug flow-investigation | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Results initialization failed; stop before authoring/freezing.' }
$results = $layout.results_root
# Each call below is a separate lifecycle action, subject to the workflow gates.
& $py $paths run --project-root $project --results-dir $results --cli $dp -- lint inputs/bundle.json
& $py $paths run --project-root $project --results-dir $results --cli $dp -- prepare inputs/bundle.json
& $py $paths run --project-root $project --results-dir $results --cli $dp -- confirm <run_id> inputs/conf.json
& $py $paths run --project-root $project --results-dir $results --cli $dp -- execute <run_id> [--detach]
# Lifecycle inspection only here; status questions read the recorded store directly.
& $py $paths run --project-root $project --results-dir $results --cli $dp -- status <run_id>
& $py $paths run --project-root $project --results-dir $results --cli $dp -- verify <run_id>
& $py $paths run --project-root $project --results-dir $results --cli $dp -- propose <run_id> inputs/proposal.json
& $py $paths run --project-root $project --results-dir $results --cli $dp -- finalize <run_id>
& $py $paths run --project-root $project --results-dir $results --cli $dp -- study-prepare inputs/study.json
& $py $paths run --project-root $project --results-dir $results --cli $dp -- study-status <study_id>
& $py $paths run --project-root $project --results-dir $results --cli $dp -- study-assess <study_id>
& $py $paths run --project-root $project --results-dir $results --cli $dp -- design-sample inputs/space.json
& $py $paths run --project-root $project --results-dir $results --cli $dp -- geometry inputs/part.step inputs/part.stl
& $py $paths run --project-root $project --results-dir $results --cli $dp -- export <run_id> exports/run.zip
```

Schemas: `& $dp schema bundle|study|proposal|confirmation`. Worked bundles to adapt:
use the same results wrapper with `-- example forward_step inputs/fs.json` or
`-- example nozzle inputs/nz.json`; never generate them into contribution source.
If the CLI or image is missing, stop for the operator to run the catalog entry's
`scripts/install-runtime.ps1`; that script is not part of this skill folder.
Stop scientific execution, not outcome reporting: create the blocked HTML in
step 7 without installing anything or calling a missing runtime.
Respect the operator's configured image/runtime and `DISCOVERY_PHYSICS_HOME`.
Never install a private signing key or set resource-limit exceptions. Errors come back as
JSON `{"error":..., "detail":..., "errors":[...]}` with exit code 2: fix the bundle and retry.

## Workflow

1. **Scope.** Restate the request as measurable objectives with units. List every
   assumption (fluid, dimensions, boundary conditions, regime, turbulence model,
   horizon) with its source: `user`, `derived`, `documented_default`, or
   `needs_confirmation`. If a value that changes the physics materially is
   unknown, ask the user before running rather than guessing. For a new campaign,
   select the absolute user project and initialize its results container before
   authoring inputs or freezing; this does not authorize scientific execution.
2. **Discover.** `capabilities` lists solver modules and Foundation
   tutorials. Start from the closest tutorial (`tutorial <path>`) and adapt it.
   If the request needs physics the installed modules cannot represent, stop with
   `REJECT_UNSUPPORTED` and explain what is missing.
   **Never silently answer a different question.** If the user named a method,
   fidelity, or quantity you cannot deliver within the budget (e.g. "DNS" when
   only RANS is feasible, 3-D when only 2-D fits), do not substitute it on your
   own. Either stop (`REJECT_UNSUPPORTED` / `REQUEST_CLARIFICATION`) offering the
   alternative, or record the substitution as an assumption with
   `source: needs_confirmation` (parameter `method_substitution`), which blocks
   `execute` until the user confirms it.
3. **Author a bundle** (`schema`; adapt `example`): free-form case files under `0/`,
   `constant/`, `system/`; meshing commands; diagnostics (fields, patches, inlet,
   outlet, impermeable patches, target time, optional mass balance, stationarity
   window, quantities read from whitelisted function objects); a budget; and a
   **contract** written *before* seeing results:
   - every objective maps to checks (an objective without checks can never be
     accepted; mesh-independence or validation claims need dedicated
     discretization/validation checks with measured evidence);
   - every threshold states a physical or numerical rationale; never choose a
     threshold to make an expected answer pass;
   - development criteria (horizon, stationarity) use `failure: incomplete`;
     health/physics criteria use `failure: hard`.
   Do not add a `functions` block to `controlDict`; declare outputs as
   `diagnostics.quantities` (function object + column, e.g. `surfaceFieldValue`
   `areaAverage(p)` on a patch) and combine them with `diagnostics.derived`
   (`difference`, `ratio`, `scale`, `abs_rel_error_pct` against a stated
   reference) so a check can threshold e.g. a pressure drop or its error versus
   an analytic value. Do not use coded/dynamic-code features.
4. **Freeze and run.** `lint`, then `prepare` (safety gate, baseline checks,
   contract lint, cost estimate, freeze). If it lists
   `assumptions_needing_confirmation`, ask the user and record their answer with
   `confirm` (`{"parameter":..., "decision":"confirmed", "confirmed_by":"<user>"}`);
   never confirm on the user's behalf. Then `execute` (use `--detach` for runs
   longer than a few minutes). Thresholds cannot change after `prepare`.
   For mesh independence, parameter sweeps, or choosing between designs, write a
   **study** (`schema study`): members are ordinary bundles; cross-run criteria
   (`gci` with `max_gci_pct`, `monotonic`, `range`, `best` with an uncertainty
   margin) are frozen up front and judged by code. A single run cannot claim mesh
   independence. The design surrogate is advisory: verify its suggestion with a run.
   Set `budget.mpi_ranks` (<= `cpus`) for parallel solves.
5. **Diagnose.** Read `status`. Distinguish insufficient run time from
   under-resolution from numerical failure; solver completion or agreement with a
   reference is *not* evidence of a settled or correct result. Cite only metric
   names that exist in the evidence.
6. **Propose one action** with `propose <run_id> proposal.json`: `ACCEPT`, `CONTINUE_RUN`
   (end_time), `REFINE_MESH` (refinement_factor, then `prepare` the refined bundle
   with `--parent <run_id>`), `REDUCE_MAX_CO`, `REBUILD_CASE`, `FAIL_SAFELY`,
   `REQUEST_CLARIFICATION`, `REJECT_UNSUPPORTED`. A refusal is an answer: do not
   retry the same proposal with different wording. Corrections keep the same
   contract; a different contract is a new lineage the user must know about.
7. **Finalize, verify, and deliver HTML.** After the authorized lifecycle's
    `finalize`, run `verify` and **always create and link a professional,
    self-contained HTML final report**. This includes `REJECT`, `INCONCLUSIVE`,
    `CORRECT_AND_RERUN`, blocked, unsupported, refused, or unexecuted outcomes;
    do not finalize or invent a native verdict for a request that never ran.
    Use the native report/status and verification: verdict, failing/unknown
    checks, measured values with recorded units (normalized cases have no SI
    units), assumptions, limitations, and run/study IDs. Label interpretation.
   - **Opening section:** a concise executive summary and conclusion plus attractive, clearly labeled
       existing native field images, with source run IDs and recorded field/time/
       units where available. Images illustrate; they never decide acceptance.
       If no solution image exists, use a clearly labeled **input geometry
       schematic, not simulated flow**. If geometry cannot be drawn safely,
       state that no solution image/schematic is available. Never fabricate fields,
       run extra CFD, or add late diagnostics/flows just to obtain a picture.
    - Invoke Python on `./scripts/render_report.py` (relative to this skill),
       passing required `--project-root <absoluteuserproject>` and exactly one of
       `--results-dir <existingmarkedresults>` or `--slug <newslug>`. Select
       evidence with `--runs-root <originalrecordedstore>`, repeatable
       `--run <native_run_id>` and/or `--study <native_study_id>`.
       Study selection automatically includes its current leaf members. Optional
       `--title`, `--cli <actualphysicsCLI>`, and `--analysis <existingrecordedjson>`
       select presentation inputs. For no-runtime/no-run outcomes use only
      the required project/results selection plus `--blocked-reason <reason>`
      and optional `--bundle <existinginputbundle>` for the schematic; no CLI is required.
    - The stdlib helper writes `report.html`, `evidence-snapshot.json`, and
       `report-receipt.json` at the marked results root by default when all three
       are fresh files. Optional `--out` must stay inside that same container,
       **outside signed run/study stores**; never under `agents` or acquired source.
       Never overwrite an individual report file: rerender into a fresh
       `reports/v2` subdirectory instead. A legacy `--runs-root` is read-only input,
       not permission to move old records or keys. The helper calls only
       native `status`, `verify`, and `study-status`; no solve, reassessment,
       ruling, recovery, installation, or runtime/image update. Preserve failures
       and verification uncertainty. Health-contract acceptance, grid convergence,
       domain sensitivity, reference validation, and design ranking are distinct
       scopes. A report cannot upgrade failure or infer a campaign winner.
    - An optional separate, previously recorded/preregistered analysis is a
       clearly attributed **derivative, not a native-verified verdict**; retain
       its failed/pending criteria. Report only recorded cost with its scope:
       displayed leaf wall time is not total lineage cost, CPU time, or human effort.
    - If the helper is missing or packaging fails, generate equivalent escaped
       HTML in a validated marked project-results destination outside signed stores:
       inline CSS, embedded safe PNG/input schematic,
       evidence provenance, limitations and the same authority boundaries; no
       JavaScript, CDN, external assets or dependencies. Otherwise report an
       explicit **report-packaging blocker**. Never call an investigation
       completely reported without an accessible HTML link. Keep native records
       unchanged; no success claim based solely on a successful renderer exit.

## Completion-focused budget planning

- **Budget for completion, not a short demo.** Unless the user requests a quick
   smoke test or tight cost limit, propose generous approved headroom for the
   registered horizon and settling criteria. Hours-long runs are acceptable;
   minimizing wall time is not the scientific objective. Never promise that a
   finite budget guarantees convergence.
- Separate the **runtime estimate**, **hard wall-time cap**, **iteration or
   physical-time horizon**, **allowed attempts/continuations**, and total worst-case
   CPU-hours, memory and disk. More wall time does not authorize more CPUs,
   concurrency, an unenforced-limit exception, or unlimited execution.
- Calibrate against comparable measured solver/hardware/mesh/monitor-I/O costs
   where possible. The generic cell-step estimator is a rough planning aid,
   not a thermal/pressure-based runtime guarantee. Do not extrapolate fine-grid
   convergence or linear-solver costs from cell count or cheap coarse grids alone.
   For an unfamiliar expensive setup, propose an authorized pilot and review its
   cost before freezing the production studies; do not silently add pilot solves.
- Include substantial uncertainty and mesh/startup, MPI, reconstruction and
   extraction overhead in the proposal. Set a generous maximum horizon and
   allowed attempts before freezing when scientifically justified, so supported
   `CONTINUE_RUN` actions can address insufficient settling within approved
   limits. Reaching an iteration count is not evidence of convergence, and
   continuation is not a workaround for hard numerical/admissibility failures.
- Respect the installed interface's actual limits and obtain user approval for
   the concrete allocation. If more is needed, request a supported continuation
   or a separately approved new lineage; never edit a frozen budget, raise an
   operator cap, disable timeouts, or weaken tolerances to finish. Preserve
   timeout/failure evidence. Extra runtime alone does not repair bad numerics.

## Long-running campaign status

- **On-demand by default.** Treat "status", "progress", or "is it still running?"
   as a request for **one fresh read-only snapshot**, not continuous monitoring.
   Use the campaign's original recorded native path and run/study IDs directly,
   whether project-local or legacy; ask which campaign only if ambiguous. Do not
   initialize results, invoke the results `run` wrapper, or write new wrapper logs.
- Read existing `status` / `study-status` results. Before saying a solve is
   currently running, cross-check its exact run ID against a live container or
   executor and inspect a bounded solver-log tail for progress/output freshness.
   A saved `running` label or old heartbeat alone is not proof of liveness.
- Reply directly in chat with one or two lines, or a compact table: checked
   time, finalized/total runs, current case, latest observed iteration or solver
   time, output age, and any verified failures or pending design decision.
   Example format: `5/9 finalized; H5 fine running, iteration 1200/4000; output 8s old; no verified winner.`
   Fill values from the new observation, not this example or an earlier reply.
- If process/log access fails, say **status unavailable** or **liveness
   uncertain**. Missing logs can mean startup/meshing; unchanged logs do not by
   themselves prove a hang. Iterations are not physical elapsed time. Do not
   invent an ETA, acceptance, convergence, or numerical-health claim.
- A status question authorizes observation only: do not start, resume, retry,
   cancel or recover a run, change supervision/control flow, extend a budget,
   alter policy, or edit frozen inputs/signed evidence. Stop after the snapshot;
   do not keep the chat open, add a timer, or start a polling loop.
   Do not generate a final report, regrade/reassess, finalize, or change controls
   or the scheduler in response to a status-only question.
- Periodic monitoring is **opt-in**. Do not launch an observer or promise
   proactive messages merely because a campaign is long. The optional acquired
   entry helper `scripts/watch_campaign.py` prints terminal stdout, not chat;
   it is not included in this skill folder and does not send chat messages.
   Any requested timed chat delivery still depends on host support.

## Gotchas

- Never reconfigure the host: do not run `podman machine set/stop/rm`,
  `podman system reset`, change rootful/rootless mode, or delete images. If
  `execute` fails for an infrastructure reason (container cannot start, socket
  refused), report it as an infrastructure blocker and stop; it is not a CFD
  result and must not be worked around by editing the tool code.
- Do not edit the `discovery_physics` package or its checks to make a run pass.
- Never edit, delete, or rewrite anything in a run directory (journal, evidence,
  plan, bundle). Records are signed; any edit makes the run fail `verify` and
  blocks every further decision on it.
- Never set `allow_unenforced_limits`, `DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS`,
  or the concurrency cap. If `execute` refuses because resource limits cannot be
  enforced, report that to the user as an operator decision.
- `ACCEPT` means "the frozen contract is satisfied", not universal validity.
- Transient compressible mass checks use stored mass plus outward flux; unequal
  inlet/outlet flux is not a conservation failure in transient flow.
- Restarts are audited for continuity; never edit fields between segments.
- Keep runs within the budget; the gate refuses corrections past it.
