# Contributing

This is the `phy-openfoam` source entry proposed for
[microsoft/discovery](https://github.com/microsoft/discovery). Follow the current
upstream contribution process and maintainer review. No document in this entry
grants publication rights, confirms first-party status, or approves production use.

## Scope and review expectations

- Keep this contribution entirely under the `agents/phy-openfoam` entry.
  Do not add root workflows, edit protected repository files, or overwrite
  unrelated project-wide Copilot instructions as part of packaging.
- Retain the landing page's exact headings: **Overview**, **Architecture**,
  **Prerequisites**, **Configuration**, **Usage**, **Tools**,
  **Known Limitations**, and **Contributing**. Keep the **Setup** introduction
  immediately after Architecture, followed by Prerequisites, the two
  installation/test prompts, Configuration, and Usage in that order. The public
  catalog requires Prerequisites, Configuration, and Usage as level-two headings.
- Keep public links inside the entry or to authoritative HTTPS upstream sources.
  Do not link active documentation to private evidence or a parent-project README.
- Keep package identities distinct: `phy-openfoam` is the agent/skill;
  `discovery-physics-openfoam` is the distribution; `discovery_physics` is the
  module; `discovery-physics` is the CLI.
- Confirm publisher metadata and any affiliation/classification with maintainers.
  An existing Microsoft publisher field is not first-party approval.
- Treat contribution source and generated user results as separate boundaries.
  Select the current user's existing absolute project root explicitly, never
  CWD, Git or source acquisition; ask only when the intended project is ambiguous.
  Initialize marked project results before authoring/freezing and keep all new
  generated inputs, scripts, logs, analyses, exports, HTML and native artifacts
  there, never under any project `agents` directory or anywhere in acquired
  contribution source. Curated static examples and reviewed fixtures remain
  contribution assets, not campaign output destinations.

Read [distribution](docs/distribution.md), [architecture](docs/architecture.md),
[licensing](docs/licensing.md), and [security](SECURITY.md) before preparing an
export. Preserve applicable upstream copyright/license headers, including Foam
dictionaries and fixtures. Do not infer a dual-license choice from aggregate
image metadata.

## Development setup

Installer commands assume this entry is the current directory for source lookup,
not results-root selection. Install Python 3.11+ and
the external container runtime independently. Windows x64 is the qualified setup
target; Linux/macOS and ARM are not qualified by these instructions.

```powershell
.\scripts\install-runtime.ps1 -Development
```

For developer checks, use the explicit project-results initialization and
`Invoke-ResultsPython` prelude in [scripts/README.md](scripts/README.md). It supplies
`$work`, `$entry` and the installed Python child launcher: results-local CWD,
child-only `DISCOVERY_PHYSICS_RUNS`, and results-contained temporary output,
without changing HOME, operator config, signing keys, resource caps or shared
slots. Child-only `PYTHONPATH` must include **both** the entry's tools/openfoam/src
and entry root, in that order, to select candidate package code and its scripts
namespace. A source edit does not update non-editable installed benchmark modules.
These source checks use existing dependencies without reinstalling the host
runtime or patching/rebuilding the worker image. The launcher is separate from
the native CLI-only results wrapper.

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
```

The new checks parent exists before pytest creates its disposable base-temp
directory. Do not reuse a previous `--basetemp`, which pytest may clear; retain
all prior JUnit/receipt output. The shared launcher also routes TMP/TEMP/TMPDIR
into results and suppresses source bytecode. No test temporary, cache or receipt
belongs under the contribution or an implicit CWD destination.

Use explicit `-Editable` only when you want an editable development installation;
the normal install is non-editable. Use [installation](docs/installation.md) for
custom roots and separate target-workspace installation. Do not check in a venv,
vendor binary, registry credentials, or operator state.

These are validation commands, **not a statement that they passed for 0.2.1**.
The documented lint gate covers `F`; broader style rules remain separate from
that gate and may expose inherited formatting debt. Native text fixtures are
under `tests/example-input-files` so OpenFOAM's extensionless names follow
the catalog's scientific-input policy without renaming or rewriting the data.
Do not silently skip missing fixtures, test setup errors, or failed checks.
Record the exact command, source revision, dependencies, platform, outcome, and
remaining unexecuted coverage. The historical 157-test result applies only to
the original 0.2.0 validation on 2026-11-22.

## Manifest and documentation checks

Use a locally obtained, reviewed public Discovery schema set. Record its exact
revision/hash separately from the contribution revision. The validator does not
register tools or exercise cloud dispatch.

```powershell
$schemas = Read-Host 'Existing absolute approved Discovery docs/schemas directory'
if (-not [IO.Path]::IsPathFullyQualified($schemas)) { throw 'Select an absolute schema path.' }
$schemas = (Resolve-Path -LiteralPath $schemas -ErrorAction Stop).Path
$schemaCommit = Read-Host 'Exact reviewed Discovery schema source commit'
$receipt = Join-Path $checks 'manifests.json'
Invoke-ResultsPython (Join-Path $entry 'scripts/validate_manifests.py') $schemas `
  --receipt $receipt --source-commit $schemaCommit
```

Use a new results-contained receipt destination for each actual validation
attempt rather than overwriting original evidence. Check all public relative links after
relocation. Verify versions and image references agree across package, catalog,
container, installer, skill, companion, and docs. Keep source-only scope; upstream
CI decisions and root workflow changes require a separate maintainer request.

## Changes to scientific or safety behavior

Add focused tests for the intended invariant. Relevant examples include missing
or non-finite evidence, metric/units binding, objective coverage, forged acceptance,
budget exhaustion, restart continuity, confirmation gates, unsafe paths/code, and
resource enforcement refusal. A synthetic fixture is not a live CFD receipt.

Never relax a scientific contract after observing results, remove a required
objective to force acceptance, or alter solver evidence/journals to satisfy a
test. Keep benchmark-specific tolerances identifiable. Preserve failed attempts
and explain legitimate scoring/audit fixes without rewriting historical runs or
tuning original model judgments against truth.

New solver/image dependencies require their own provenance, licensing, SBOM,
security, and qualification review. Base/solver pins alone do not make apt or
transitive dependencies reproducible. Source packaging must not install a
privileged runtime, log in to services, or authorize unsafe operator choices.

## Optional live validation

The [script reference](scripts/README.md) and [benchmark guide](benchmarks/README.md)
separate deterministic tests, new CFD, native CLIO behavior, raw model judgments,
and local service/MPI checks. Live validation can be expensive and uses separately
installed/authenticated software. Obtain operator/user authorization, freeze the
study first, and use fresh marked results under the explicit user project.
Every developer writer requires `--project-root <absoluteproject> --results-dir
<existingmarkedresults>` plus fresh results-contained `--out`; bundle builders
use `--output`. Supply harness work roots with their documented run/read-input
meaning; a run-store environment override alone is insufficient. Campaign and
supplemental-study outputs must be separate new directories. Model review
`collect` reads existing `--source`, `--work` and `--packets`, and writes a new
derivative `--out`, never the original review. See the exact parser-matched
templates in [scripts/README.md](scripts/README.md), not source/CWD defaults.
Record source revision, original native paths
and run/study IDs in the results manifest without moving signing keys or editing
signed artifacts. Private runtime app data remains separate and unchanged;
results metadata is not a runtime config-model property or resource override.

No harness should silently enable unenforced limits. Where offered,
`--allow-unenforced-limits` is an explicit **operator-only** exception; otherwise
honor the existing operator policy. An agent must not set that flag, change the
runtime/concurrency policy, or approve its own method substitution. Report actual
resource-limit evidence and unresolved infrastructure blockers.

For explicit HTML delivery, use required `--project-root` and exactly one of
existing marked `--results-dir` or new `--slug`. Fresh report files default to
that marked root; optional `--out` is accepted only with `--results-dir`, not
`--slug`, and cannot escape the container, enter a signed
store or overwrite individual report files. Choose fresh `reports/v2` for a
rerender. Legacy `--runs-root` is read-only input: old native paths/keys remain
in place. A status question uses the original recorded path directly, with no
initializer, results run wrapper/logs, new HTML or timers.

Use the supplied [migration helper](skills/phy-openfoam/scripts/migrate_results.py)
only for an explicitly approved unsigned delivery/archive copy. It requires
`--project-root`, original unsigned `--source` and `--slug`, with optional
`--exact`, `--archive` and separately approved `--remove-source`. It defaults to
copy-only, refuses detected journals/keys/configuration/links, and verifies the
whole source inventory and every copied file hash before optional cleanup.
Preserve old receipt bytes, relative-reference dependencies and embedded native
paths; the new migration manifest records the copy mapping and original hashes.
No signed history/key move or CFD is implied. Historical archives may be copied
with `--archive` after preflight, never reused for fresh results or linked from
public source docs. See [migration details](docs/reporting.md).

Cloud/service `/output` remains the platform-managed mount, not a host project
path. Available host/platform publication materializes returned artifacts into
project results; unavailable support is a disclosed location blocker, not a new
tool action or permission to silently reroute execution. See
[reporting](docs/reporting.md) and [configuration](docs/configuration.md).

## Submission checklist

- [ ] Contribution diff contains only approved files within this entry.
- [ ] Fresh test/lint/schema results identify the actual candidate revision and
  are not relabeled historical receipts.
- [ ] Docs distinguish local installation, workspace Markdown, optional cloud
  deployment, and unexecuted production gates.
- [ ] No secrets, capability URLs, private Discovery state, native transcripts,
  absolute operator paths, venvs, or solver outputs are in the public export.
- [ ] Original local evidence remains byte-identical and immutable; any new
  sanitized derivative has explicit source hashes and transformation provenance.
- [ ] The complete skill includes instructions, reporting/results helpers and
  the supplied migration helper/resources. Installer required-file preflight
  remains instructions plus reporting/results helpers, not a third-helper gate;
  tests cover missing-required-helper/all-or-none refusal, collisions,
  idempotent unchanged helpers and excluded caches. Recheck the integrated
  renderer, source writers and installer before live use; docs are not a pass receipt.
- [ ] License texts, notices, provenance, and preserved third-party headers have
  been reviewed; image publication has a separate corresponding-source plan.
- [ ] [CHANGELOG.md](CHANGELOG.md) records the change without implying release,
  first-party approval, new scientific validation, or production sign-off.

Report vulnerabilities privately through [MSRC](https://msrc.microsoft.com/create-report),
not public issues. Upstream catalog issues are disabled; use its current
contribution/review process for non-security feedback.