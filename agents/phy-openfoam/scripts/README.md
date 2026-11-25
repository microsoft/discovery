# Script reference

Installer commands use the **entry directory** for source lookup only. All new
user-generated developer and scientific output belongs in marked results under
the explicitly selected user project, never under `agents` or acquired source.
Install the host package first; use explicit development dependencies for tests,
lint, and schema validation. Live CFD and model workflows are optional and need
separate operator authorization. See [installation](../docs/installation.md).

## Inventory and execution scope

| Script/interface | Purpose | Solver/model activity |
|---|---|---|
| [install-runtime.ps1](install-runtime.ps1) | User-local venv, standard non-editable pip install, optional image build; no workspace edits | Build/dependency activity, no CFD or model call |
| [install-workspace.ps1](install-workspace.ps1) | Preflight and copy the full skill (scripts/resources included) and optional companion; refuse collisions without explicit force | No runtime installation or solve |
| [project_results.py](../skills/phy-openfoam/scripts/project_results.py) | Bundled stdlib helper: initialize/check explicit project results; `run` invokes one requested installed CLI command with child-only run-store routing and results-local logs | `init`/`check`: no native command; `run`: only the explicitly requested command, with normal scientific approval |
| [render_report.py](../skills/phy-openfoam/scripts/render_report.py) | Bundled skill helper: package existing native run/study evidence as professional self-contained offline HTML, or record a blocked/no-run outcome | Native status/verify/study-status only; no solve, reassessment, ruling, recovery, runtime/image update or model call |
| [migrate_results.py](../skills/phy-openfoam/scripts/migrate_results.py) | Bundled stdlib helper: copy an explicitly selected unsigned delivery/archive into new marked results with byte/hash provenance; optional separately authorized source cleanup | No native command, solver, model call, signed-history move or runtime/key/config change |
| [result_paths.py](result_paths.py) | Source-entry loader for the shared developer output guard; Node builders use its read-only destination check | No solver/model call; refuses missing routing, source output and existing destinations |
| [setup.ps1](setup.ps1) | Compatibility forwarding to host-runtime installation only | Same as host installer, not workspace setup |
| [validate_manifests.py](validate_manifests.py) | Validate the three manifests against a supplied public schema directory; optional hash/revision receipt | No solver, model, or cloud dispatch |
| [check_release.py](check_release.py) | Read-only public-source inventory, syntax, self-contained links, and bounded credential/workstation-path checks | No export, solve, model call, or publication approval |
| [watch_campaign.py](watch_campaign.py) | Read-only one-line terminal heartbeat for an existing run store, default 60 seconds, bounded observer lifetime | No solver/runtime/model calls, keys, or run-store writes; not proactive chat delivery |
| [validation_receipts.py](validation_receipts.py) | Verify existing paper campaign and supplemental S8 lineages against the selected local stores/key | No new CFD/model call; requires original local artifacts |
| [clio_driver.py](clio_driver.py) | Own an installed native CLIO stdio server through completion and retain RPC/terminal receipts | Model calls; prompt may authorize CLI/solver work |
| [heldout.py](heldout.py) | `run`: native held-out workflows; `score`: audit existing terminal/run/study receipts | `run` may solve/call models; `score` does neither |
| [model_comparison.py](model_comparison.py) | `run`: fresh paired B/C advisory reviews; `collect`: audit existing judgments | New model calls only for `run`; no CFD |
| [live_paths.py](live_paths.py) | Serial/two-rank MPI and local in-image service checks | New local CFD; action named `cloud` is not Azure dispatch |
| [fixture_probe.py](fixture_probe.py) | Generate native function-object fixtures from the public health-only bundle | New short CFD; no physical-validation/finalization claim |

Developer writers require `--project-root <absoluteproject> --results-dir
<existingmarkedresults>` and a fresh `--out`; [bundle builders](../examples/README.md)
use required `--output` instead. A run-store environment override alone does not
satisfy the routing guard. There are no source/CWD output defaults to rely on.
The workspace installer copies the **complete supplied skill folder**, including
the migration helper, and excludes caches/bytecode. Its explicit required-file
preflight remains the skill instructions plus the reporting and results helpers;
the migration helper is a supplied resource, not a third required-helper gate.

## Installation commands

```powershell
.\scripts\install-runtime.ps1
$targetProject = Read-Host 'Existing absolute target user project root (not acquired source)'
if (-not [IO.Path]::IsPathFullyQualified($targetProject)) { throw 'Select an absolute project path.' }
$targetProject = (Resolve-Path -LiteralPath $targetProject -ErrorAction Stop).Path
.\scripts\install-workspace.ps1 -ProjectPath $targetProject -IncludeAgent
```

Host parameters are `-InstallRoot`, `-PythonExecutable`, `-Runtime
auto|podman|docker`, `-Image`, `-SkipImage`, `-Development`, and `-Editable`.
Workspace parameters are `-ProjectPath`, `-IncludeAgent`, `-Force`, and
`-RuntimeExecutable` (the installed physics CLI path). The host installer persists
image/runtime selection while preserving safe operator settings; the workspace
installer does not install a runtime or change unrelated instructions. Full
defaults and custom-root handling are in [installation](../docs/installation.md).

## Final report packaging

The helper is part of the complete skill folder, **not** the installed
`discovery_physics` package. Use an existing Python 3.11+ interpreter; no pip
install or image update is required. After the authorized finalization and
verification, always create and link HTML, including failed, inconclusive,
blocked/refused and unexecuted outcomes. Open with a concise summary and labeled
existing native field images, or an explicitly labeled input schematic when no
solution image exists; never add CFD to decorate a report.

```text
python <skill>/scripts/render_report.py --project-root <absoluteproject> --results-dir <existingmarkedresults> --runs-root <originalrecordedstore> --run <native_run_id>
python <skill>/scripts/render_report.py --project-root <absoluteproject> --slug <newslug> --runs-root <originalrecordedstore> --study <native_study_id>
python <skill>/scripts/render_report.py --project-root <absoluteproject> --slug <newslug> --blocked-reason <reason> [--bundle <existinginputbundle>]
```

`--run` and `--study` are repeatable; studies automatically include current leaf
members. Optional `--title`, `--cli <actualphysicsCLI>`, and
`--analysis <existingrecordedjson>` select presentation inputs. Required
`--project-root` is the explicit absolute user project; choose exactly one of
existing marked `--results-dir` or new `--slug`. Fresh `report.html`,
`evidence-snapshot.json`, and `report-receipt.json` default to that container's
top level. Optional `--out` is accepted only with `--results-dir`, stays inside
that container and outside signed stores. Initialize first if a new container
needs a custom report subdirectory; `--slug` cannot be combined with `--out`.
Never overwrite individual report files; rerender into fresh `reports/v2`.
Legacy `--runs-root` is read-only input, not a relocation of records/keys.
A separate analysis remains
an attributed derivative, not a native-verified verdict. Images/HTML cannot
upgrade failure; leaf wall time is not total lineage/CPU/human cost. See
[reporting](../docs/reporting.md) for scope, security, cost and missing-helper
fallbacks. A status-only question still gets one read-only chat snapshot, not
final-report generation, reassessment, controls or a timer.

## Project-owned output routing

These are commands for future authorized execution, **not receipts generated by
this documentation pass**. Explicitly select the existing absolute user project;
do not derive it from CWD, Git, runtime installation or acquired source. Ask in a
multi-root workspace only if the intended project is ambiguous. Initialize
**before authoring/freezing**, including generated developer inputs/scripts:

```powershell
$py = "$env:LOCALAPPDATA\DiscoveryPhysics\venv\Scripts\python.exe"
$project = Read-Host 'Existing absolute user project root (not acquired source)'
$entry = Read-Host 'Existing absolute approved phy-openfoam source entry'
foreach ($selected in @($project, $entry)) {
	if (-not [IO.Path]::IsPathFullyQualified($selected)) { throw 'Select an existing absolute path.' }
}
$project = (Resolve-Path -LiteralPath $project -ErrorAction Stop).Path
$entry = (Resolve-Path -LiteralPath $entry -ErrorAction Stop).Path
# Source validation uses the canonical standalone helper; no installed-copy update.
$paths = Join-Path $entry 'skills/phy-openfoam/scripts/project_results.py'
$layout = & $py -X utf8 -B $paths init --project-root $project --slug candidate-validation | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Results initialization failed; stop before generating work.' }
$work = $layout.results_root
& $py -X utf8 -B $paths check --project-root $project --results-dir $work
```

`init` creates unique `results-<slug>-<utc>-<suffix>/` with a manifest and
inputs/analysis/logs/exports/runs/studies directories. Slugs use lowercase
letters/digits with single hyphens. `--exact` requests the exact slug folder and
refuses collisions. `check [--destination <path>]` is read-only. Keep every
generated input, script, preregistration, log, analysis, export, HTML and new
native artifact inside this marked container, never anywhere under project
`agents` or the acquired entry, even staged elsewhere. Curated examples/reviewed
test fixtures remain contribution assets. Record source revision, original
native paths and run/study IDs in the manifest; do not copy signing keys.

For an explicitly authorized **native CLI** action use the bundled helper:

```text
python <skill>/scripts/project_results.py run --project-root <absoluteproject> --results-dir <markedresults> [--cli <installedCLI>] -- <nativecommand> <args>
```

It sets child-only `DISCOVERY_PHYSICS_RUNS=<results>/runs`, CWD at results and
CLI transcripts under logs. Relative input arguments resolve from that root;
new example/geometry/export outputs are results-contained. Native `example`
accepts `nozzle` and `forward_step`, not developer-builder scripts; the latter
reads the selected image's Foundation tutorial. All native actions retain their
normal user/operator approval requirements. The wrapper does not
automatically execute a solve, proposal or confirmation. HOME, configuration,
signing keys, image, caps and shared slots stay unchanged. Do not persist a global
override or add results metadata/resource properties to runtime configuration.

Python developer modules/scripts are **not native CLI commands** and cannot be
passed through that wrapper. In the same PowerShell session, this explicit
child-process launcher keeps their CWD, run store, bytecode and temporary-file
routing separate from source and leaves the parent environment/policy unchanged:

```powershell
$scratch = Join-Path $work 'analysis/developer-temp'
New-Item -ItemType Directory -Path $scratch | Out-Null
$sourceImports = @((Join-Path $entry 'tools/openfoam/src'), $entry)
if ($env:PYTHONPATH) { $sourceImports += $env:PYTHONPATH }
$sourcePath = $sourceImports -join [IO.Path]::PathSeparator
function Invoke-ResultsPython {
	$start = [System.Diagnostics.ProcessStartInfo]::new()
	$start.FileName = $py
	$start.UseShellExecute = $false
	$start.WorkingDirectory = $work
	$start.Environment['DISCOVERY_PHYSICS_RUNS'] = Join-Path $work 'runs'
	$start.Environment['PYTHONDONTWRITEBYTECODE'] = '1'
	$start.Environment['PYTHONPATH'] = $sourcePath
	foreach ($name in @('TMP', 'TEMP', 'TMPDIR')) { $start.Environment[$name] = $scratch }
	foreach ($argument in @('-X', 'utf8', '-B')) { $start.ArgumentList.Add($argument) }
	foreach ($argument in $args) { $start.ArgumentList.Add([string]$argument) }
	$child = [System.Diagnostics.Process]::Start($start)
	$child.WaitForExit()
	if ($child.ExitCode -ne 0) { throw "Developer command failed: $($child.ExitCode); preserve outputs." }
}
```

Use the **actual installed** Python for custom runtime locations. This launcher
does not authorize any commands below and is not an installer or cloud action.
Both source import roots are intentional: `tools/openfoam/src` selects the
candidate `discovery_physics` benchmark code, and the entry root selects its
`scripts` namespace. Editing source does **not** update non-editable installed
benchmark modules. This child-only source-validation path uses existing Python
dependencies, with no pip reinstall, host-runtime patch or image rebuild; it
does not update the installed CLI or worker. Developer read inputs resolve
relative to the explicit project, while relative outputs resolve inside marked
results; use absolute inputs as below to avoid confusing either with child CWD.
Native artifacts stay under results/runs, with studies beside each selected
run store; held-out receipts record their per-prompt store explicitly. Discovery's
private application/session state remains separately managed runtime data.

For custom roots use the actual installed Python/CLI and the intended data-root
environment. Every fresh validation needs exact source revision, package/image
identity, environment, commands, results, and remaining gaps. Raw output may
contain paths and native session metadata: do not copy it into a public bundle
without a separate reviewed derivative/provenance process.

## Deterministic and schema checks

```powershell
$checks = Join-Path $work ('analysis/checks-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $checks | Out-Null
Invoke-ResultsPython -m pytest (Join-Path $entry 'tests') `
	-o ("cache_dir=" + (Join-Path $checks 'pytest-cache')) `
	--basetemp (Join-Path $checks 'pytest-temp') --junitxml (Join-Path $checks 'tests.xml')
Invoke-ResultsPython -m ruff check --no-cache --select F (Join-Path $entry 'tools/openfoam/src') `
	(Join-Path $entry 'skills/phy-openfoam/scripts') (Join-Path $entry 'scripts') `
	(Join-Path $entry 'tests') (Join-Path $entry 'examples/development')
Invoke-ResultsPython (Join-Path $entry 'scripts/check_release.py')
$schemas = Read-Host 'Existing absolute approved Discovery docs/schemas directory'
if (-not [IO.Path]::IsPathFullyQualified($schemas)) { throw 'Select an absolute schema path.' }
$schemas = (Resolve-Path -LiteralPath $schemas -ErrorAction Stop).Path
$schemaCommit = Read-Host 'Exact reviewed Discovery schema source commit'
Invoke-ResultsPython (Join-Path $entry 'scripts/validate_manifests.py') $schemas `
	--receipt (Join-Path $checks 'manifests.json') --source-commit $schemaCommit
```

The fresh checks parent exists before pytest creates its disposable base-temp
directory. Cache, JUnit, schema and general TMP/TEMP/TMPDIR output stay in results;
do not reuse a previous test base-temp directory, which pytest may clear.
Obtain public schemas independently from the approved
[Discovery upstream](https://github.com/microsoft/discovery) revision. Passing
schema validation is not action dispatch or installer qualification. Passing
tests is not a new CFD campaign. Original test counts are
[retrospective](../benchmarks/VALIDATION-HISTORY.md), not current-run assertions.
The documented lint gate is the `F` rule set. Broader configured style rules
may report legacy formatting debt; do not describe them as passed without running
them. The bounded source check does not replace the catalog's security scanners.

## New CFD campaign and read-only receipts

```powershell
$campaign = Join-Path $work 'analysis/paper-campaign'
$s8 = Join-Path $work 'analysis/s8-study'
$receiptInputs = Join-Path $work 'analysis/verification-inputs'
$packets = Join-Path $work 'analysis/packets'
Invoke-ResultsPython -m discovery_physics.benchmarks.run `
	--project-root $project --results-dir $work --out $campaign --parallel 2
Invoke-ResultsPython -m discovery_physics.benchmarks.study_s8 `
	--project-root $project --results-dir $work --out $s8 --parallel 2
# The receipt verifier takes one input directory containing both receipt sets.
if (Test-Path -LiteralPath $receiptInputs) { throw 'Choose a fresh verification-input directory.' }
Copy-Item -LiteralPath $campaign -Destination $receiptInputs -Recurse
Copy-Item -LiteralPath (Join-Path $s8 'S8_study.json') -Destination (Join-Path $receiptInputs 'S8_study.json')
Invoke-ResultsPython (Join-Path $entry 'scripts/validation_receipts.py') `
	--project-root $project --results-dir $work --results $receiptInputs `
	--out (Join-Path $work 'analysis/verified.json')
Invoke-ResultsPython -m discovery_physics.benchmarks.comparison `
	--project-root $project --results-dir $work --results $campaign --out $packets
Invoke-ResultsPython -m discovery_physics.benchmarks.report `
	--project-root $project --results-dir $work --results $campaign `
	--comparison (Join-Path $packets 'summary.json') --out (Join-Path $work 'exports/benchmark-summary.md')
```

Every writer requires explicit `--project-root`, marked `--results-dir` and a
fresh `--out`. Campaign and supplemental-study directories must be **different**:
both writers refuse an existing directory. The explicit unsigned receipt-input
copy above preserves the original two output trees and their recorded paths;
the verifier expects all campaign JSON and the supplemental S8 JSON together.
It does not copy native stores or keys. These commands use the child-only native
store from the launcher above; read-only legacy verification instead needs its
actual original store/key context. Receipt/comparison/report outputs must also
be fresh and contained. The Markdown summary is not the final HTML report and
does not independently verify a scientific decision.
The campaign uses a deterministic fixed-rule proposer, not CLIO. Inspect every
per-case result/error and final verdict, not just a successful process exit.
The supplemental S8 study is distinct from the original single-run S8 claim.
Receipt generation needs the matching run/study stores and private key; it cannot
reconstruct the original evidence from the public source checkout alone.
See [benchmark scope](../benchmarks/README.md).

## Native CLIO selection and lifecycle

The native driver selects an independently installed executable in this order:
`--clio-executable`, `DISCOVERY_CLIO_EXE`, `PATH`, then supported Discovery Preview
installation discovery. Invalid explicit overrides fail rather than silently
falling back. Discovery/CLIO binaries and authentication are not redistributed.

```powershell
Invoke-ResultsPython (Join-Path $entry 'scripts/clio_driver.py') tools
# Use an operator-authored results-contained prompt and the explicit user project:
Invoke-ResultsPython (Join-Path $entry 'scripts/clio_driver.py') run `
	(Join-Path $work 'inputs/prompt.txt') --project-root $project --results-dir $work `
	--out (Join-Path $work 'logs/native-run') --cwd $project
```

The prompt is the only positional run input; there is no positional output.
`run` requires `--cwd`, `--project-root`, `--results-dir` and fresh `--out`.
`--cwd` must be the selected project or a non-source directory inside it.
Optional `--runs-root` must stay under the selected results/runs; omission uses
that top-level store. Add `--clio-executable` only with an actual installed path
when automatic discovery is not the intended selection. The discovery-only
`tools` action does not require the writer-routing flags; its temporary RPC log
uses the launcher's results-contained temporary directory.

The server owns runs **in-process**. Keep the driver alive through completion;
killing it kills its work. A historical machine-wide `running` row is not proof
of a live executor. The driver advances native sequence numbers and recognizes
terminal responses without a sequence field. Native RPC logs and app sessions
are private operational evidence, not automatically publishable collateral.

For model-comparison receipt inspection, `DISCOVERY_CLIO_STATE_HOME` selects the
root containing the native science-run and session-state directories. It changes
the inspector's lookup, **not** CLIO's session-writing behavior. Its default is
the current user's Copilot state root, not a hardcoded original workstation.

## Held-out workflows and scoring

Install the skill into the existing target project first. Then, optionally:

```powershell
$heldoutWork = Join-Path $work 'analysis/heldout'
Invoke-ResultsPython (Join-Path $entry 'scripts/heldout.py') run `
	--project-root $project --results-dir $work --workspace $project `
	--work-root $heldoutWork --out (Join-Path $work 'analysis/heldout-run.json') --python $py --parallel 2
Invoke-ResultsPython (Join-Path $entry 'scripts/heldout.py') score `
	--project-root $project --results-dir $work --work-root $heldoutWork `
	--out (Join-Path $work 'analysis/heldout-score.json') --report (Join-Path $work 'analysis/heldout-report.md')
```

Both actions require a fresh JSON `--out`; `run` writes a driver summary, not a
score. `--report` is supported only by `score`. Optional `--work-root` is a fresh
receipts directory for `run` (default: analysis/heldout inside results) and an
existing read input for `score`; always select the actual receipts explicitly.
`--workspace`, when supplied, must equal `--project-root` and contain the skill.
New per-prompt native stores are results/runs/Hxx/runs, with studies beside each
store, not beneath the receipt work directory. Saved driver receipts identify
the exact native paths, including historical layouts.

`--only` restricts prompt IDs; `--clio-executable` or `DISCOVERY_CLIO_EXE` selects
the native executable. Scoring uses saved terminal receipts and verifies local
run/study records; it does not solve, call a model, or confirm H14's proposed
substitution. Behavioral success includes justified refusal, clarification, and
unexecuted confirmation-gate stops, not only accepted numerical answers.

No unconditional unenforced-limit opt-in is injected. Only an **operator** may
request `--allow-unenforced-limits`; otherwise the existing operator config and
inherited environment apply. Omission does not override an existing exception.
An agent must never enable the flag or edit runtime policy. Actual enforcement
and any exception must be disclosed in the retained output.

## Raw B/C advisory comparison

Generate fresh packets from a verified campaign first. The review output path
must be new; do not overwrite prior responses or use correctness feedback to
retry them.

```powershell
$packets = Join-Path $work 'analysis/packets'
$reviews = Join-Path $work 'analysis/reviews'
$reviewWorkRoot = Join-Path $work 'logs/native-reviews'
Invoke-ResultsPython (Join-Path $entry 'scripts/model_comparison.py') run `
	--project-root $project --results-dir $work --packets $packets --out $reviews `
	--work-root $reviewWorkRoot --jobs 2
```

Run the packet-generation command only once. This block reads that existing
packet directory; it does not regenerate packets or overwrite a prior review.
The runner freezes input/protocol, uses paired shuffled aliases and fresh
input-only sessions, withholds truth during review, and validates full answer
coverage and citations. B sees gate outputs; C withholds outcomes, thresholds,
and objective coverage. This is not OS-enforced blinding or an independent model
authority for live acceptance. Set `DISCOVERY_CLIO_EXE` to choose CLIO for this
workflow; there is no separate model-comparison `--clio-executable` option.

`run` creates a unique `clio-*` child under `--work-root` (default: work beneath
the new review output). For recollection, `--work` selects that **actual child**
containing the batch directories, not its parent. `--source` selects the existing
review output containing the protocol and frozen inputs; `--out` is a different,
fresh derivative directory. Required `--packets` selects the same original packets:

```powershell
$nativeWork = Read-Host 'Existing absolute clio-* directory containing the native review batches'
if (-not [IO.Path]::IsPathFullyQualified($nativeWork)) { throw 'Select the actual absolute work path.' }
Invoke-ResultsPython (Join-Path $entry 'scripts/model_comparison.py') collect `
	--project-root $project --results-dir $work --packets $packets --source $reviews `
	--work $nativeWork --out (Join-Path $work 'analysis/reviews-recollected')
```

Collection re-audits retained responses without new model calls; it never
overwrites the prior review, responses or audit failures. It is for audit/receipt
recovery, not judgment tuning. Overflow output is admissible only with its exact
earlier successful same-session creation provenance, not an arbitrary temporary
file. Retain initial audit failures and disclose later audit corrections.

## Optional path and fixture generation

```powershell
Invoke-ResultsPython (Join-Path $entry 'scripts/live_paths.py') mpi `
	--project-root $project --results-dir $work --out (Join-Path $work 'analysis/mpi.json') `
	--work-root (Join-Path $work 'analysis/paths')
Invoke-ResultsPython (Join-Path $entry 'scripts/live_paths.py') cloud `
	--project-root $project --results-dir $work --out (Join-Path $work 'analysis/local-service.json') `
	--work-root (Join-Path $work 'analysis/paths')
Invoke-ResultsPython (Join-Path $entry 'scripts/fixture_probe.py') `
	--project-root $project --results-dir $work --out (Join-Path $work 'exports/fixtures') `
	--work-root (Join-Path $work 'analysis/fixtures')
```

Both scripts default to [examples/channel-path-check.json](../examples/channel-path-check.json)
and accept `--bundle` for an explicit source. No historical run-store fixture or
original-machine source-run variable is required. `fixture_probe` additionally
accepts `--end-time`; its required `--out` is a fresh export directory, not a
positional argument. The path checks require separate fresh JSON `--out` files.
Optional work roots are results-contained parents for unique temporary work
directories; native artifacts use results/runs with its studies sibling.
Fixture generation is health-only and not a finalization path.

The path check named `cloud` exercises the service locally and requires the
container limits it requests; it does not silently retry without them. It is not
Azure dispatch or production enforcement evidence. Serial/MPI agreement on a
selected quantity is not a full-field parallel verification study. Do not copy
generated fixtures into the public tests without separate review and provenance.

## Explicit unsigned-delivery migration

The supplied [migration helper](../skills/phy-openfoam/scripts/migrate_results.py)
is standalone stdlib code beside the reporting/results helpers; no pip or image
update is needed. It has no action subcommand, `--out` or `--results-dir` option:

```text
python <skill>/scripts/migrate_results.py --project-root <absoluteproject> --source <originalabsoluteunsigneddirectory> --slug <slug> [--exact] [--archive] [--remove-source]
```

The default copies only into a new marked results container. `--exact` refuses
a slug-folder collision; `--archive` preserves a legacy tree beneath archive
instead of placing delivery files at the marked root. Only separately approved
`--remove-source` requests cleanup after whole-source inventory and every copied
file's hash verification. Detected journals, keys, configuration and linked/
reparse sources are refused. Report/receipt bytes and historical embedded paths
remain unchanged; the new migration manifest records the original paths,
destination mapping, hashes and sizes. Signed history and keys stay put, and no
CFD is started. See [preservation details](../docs/reporting.md).

## Existing status and platform output

For existing campaign status, bypass all initialization and write-producing
launchers above: inspect its **original recorded native path** directly for one
read-only chat snapshot. No wrapper logs, report, timer or store migration is
part of that request. Unsigned migration is a separately authorized operation,
never an automatic status/report side effect. Native records and keys stay put. Service
`/output` remains the platform mount, with host artifacts materialized into
project results only through actually available publication, not a fictional
cloud helper action or silent execution-route change.
