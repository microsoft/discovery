# Installation

Install the **host runtime** once, then install the **skill** into each existing
project that will use it. These are separate operations. Both installers live
inside this entry; neither requires copying project-wide Copilot instructions.
Installer commands below assume PowerShell with this entry as the current
directory for source lookup only; it is never inferred as the user results root.

## Supported and external prerequisites

- Setup qualification is limited to **Windows x64**, with Python **3.11+**
  and **PowerShell 7+ (`pwsh`)**; legacy Windows PowerShell 5 is not supported.
  Linux/macOS setup and ARM execution are unqualified. The worker installs an
  AMD64 Debian-format Foundation package; an ARM host or emulation layer is not
  evidence of native ARM support.
- Install Python, then independently install and initialize
  [Podman](https://podman.io/docs/installation) or
  [Docker](https://docs.docker.com/engine/install/). Complete engine startup,
  virtualization configuration, registry login, and licensing outside this
  package. The installer does not install vendor runtimes or log in for you.
- For Podman on Windows/WSL, use **6.2 or later** with a newly provisioned
  **WSL-native systemd** machine, cgroup v2, and delegated CPU/memory/PID
  controllers. A client upgrade leaves legacy machines on their old bootstrap.
  Follow [WSL migration and bounded preflight](podman-wsl.md) before treating the
  runtime as ready; do not disable limits to work around a missing controller.
- Install Discovery/CLIO separately for agent-led workflows. Historical testing
  used Discovery **0.15.21-preview** and observed `claude-sonnet-5`; newer app/model
  combinations need qualification. The physics tool accepts no provider keys.
- Obtain this entry from an approved source revision. Do not assume its candidate
  files are available on upstream `main` before merge.
- Permit network access for dependency installation and image build. Normal
  solver-worker execution has no network. Available disk and memory must cover
  the image, case budgets, outputs, and configured concurrency.

Do not copy an existing virtual environment, CLIO/vendor executable, credentials,
or registry configuration from another workstation. Recreate dependencies using
their supported installers. See [licensing](licensing.md) for image obligations.

## 1. Install the host runtime

The [host installer](../scripts/install-runtime.ps1) is separate from the
[workspace installer](../scripts/install-workspace.ps1).

```powershell
.\scripts\install-runtime.ps1

$dp = "$env:LOCALAPPDATA\DiscoveryPhysics\venv\Scripts\discovery-physics.exe"
& $dp schema bundle
& $dp capabilities
```

The installer creates a user-local virtual environment, uses a standard
**non-editable pip installation** of `discovery-physics-openfoam`, and builds the
worker image. It does **not** write workspace skills, agents, or instructions.
`schema` checks the CLI path without solving; `capabilities` additionally needs
a working engine and image. Neither demonstrates a scientifically accepted run,
and `capabilities` is not a resource-enforcement check. On Windows/WSL, also run
the [bounded non-solver probe](podman-wsl.md) against the selected worker image.

| Parameter | Default | Meaning |
|---|---|---|
| `-InstallRoot` | Current user's local application data, under DiscoveryPhysics | Host installation location; keep it outside synchronized source trees |
| `-PythonExecutable` | `python` | Python executable used to create the virtual environment; must be 3.11+ |
| `-Runtime` | `auto` | `auto`, `podman`, or `docker`; chooses an independently installed engine |
| `-Image` | `localhost/phy-openfoam:0.2.1` | Image reference to build/select |
| `-SkipImage` | Off | Install the Python runtime without building the image; solves still need a compatible image |
| `-Development` | Off | Include development/test dependencies |
| `-Editable` | Off | Explicit developer-only editable installation; retain the source tree |

The selected image and runtime are persisted in local operator configuration;
the [operator example](../config/operator.example.json) is local-only guidance,
not a file to populate with private values in the source checkout.
Existing safety/concurrency settings are preserved rather than silently reset.
The installer must not enable an unenforced-limit exception. Environment
overrides can supersede the saved selection; see [configuration](configuration.md).
Do not interpret `-SkipImage` as an image compatibility check or solver readiness.

For a custom installation/data root, make the CLI and data location explicit in
the environment inherited by Discovery:

```powershell
$installRoot = Read-Host 'Operator-approved absolute installation/data root outside source'
if (-not [IO.Path]::IsPathFullyQualified($installRoot)) { throw 'Select an absolute installation path.' }
$env:DISCOVERY_PHYSICS_HOME = $installRoot
.\scripts\install-runtime.ps1 -InstallRoot $env:DISCOVERY_PHYSICS_HOME -Runtime docker
$env:DISCOVERY_PHYSICS_CLI = Join-Path $env:DISCOVERY_PHYSICS_HOME 'venv\Scripts\discovery-physics.exe'
& $env:DISCOVERY_PHYSICS_CLI schema bundle
```

Process environment changes affect only that process and its future children.
An already running Discovery app does not inherit them retroactively. Operators
must arrange their own persistent launch environment if needed. Installing into
a custom root alone is not a promise that every future shell will discover it.
Do not move historical run stores or keys as part of this example.

For development only:

```powershell
.\scripts\install-runtime.ps1 -Development -Editable
```

With a normal non-editable install, source edits do not update the installed CLI;
reinstall the intended revision. A source change may also require rebuilding the
image. Do not install an editable checkout as an undocumented production default.
This is distinct from **source benchmark validation**: the child launcher in
[scripts](../scripts/README.md) puts both tools/openfoam/src and the entry root
on child-only `PYTHONPATH` and uses existing dependencies. It selects candidate
benchmark/script code without a new pip installation or worker-image patch;
it does not update the installed CLI/worker. Documentation/standalone-helper
changes alone do not authorize a runtime reinstall or image rebuild.

The [compatibility wrapper](../scripts/setup.ps1) forwards to the host-runtime
installer only. It no longer means “install everything into this workspace.”

## 2. Install into an existing workspace

```powershell
$project = Read-Host 'Existing absolute target user project root (not acquired source)'
if (-not [IO.Path]::IsPathFullyQualified($project)) { throw 'Select an absolute project path.' }
$project = (Resolve-Path -LiteralPath $project -ErrorAction Stop).Path
.\scripts\install-workspace.ps1 -ProjectPath $project

# Optional companion agent, using the same installed runtime:
.\scripts\install-workspace.ps1 -ProjectPath $project -IncludeAgent
```

The target project must already exist. The workspace installer copies the
**complete supplied [skill folder](../skills/phy-openfoam/)**: its instructions,
[stdlib reporting helper](../skills/phy-openfoam/scripts/render_report.py), and
[stdlib results helper](../skills/phy-openfoam/scripts/project_results.py), plus
the [unsigned-migration helper](../skills/phy-openfoam/scripts/migrate_results.py)
and other supplied scripts/resources. It excludes caches, Python bytecode and
environment/build artifacts. With `-IncludeAgent` it also copies the
[companion](../integrations/phy-openfoam.agent.md). It does not create a virtual
environment, build an image, install a container engine, or change global
operator policy. Its destinations include:

```text
<project>/.github/skills/phy-openfoam/SKILL.md
<project>/.github/skills/phy-openfoam/scripts/render_report.py
<project>/.github/skills/phy-openfoam/scripts/project_results.py
<project>/.github/skills/phy-openfoam/scripts/migrate_results.py
<project>/.github/skills/phy-openfoam/<other supplied resources, preserving layout>
<project>/.github/agents/phy-openfoam.agent.md    (only with -IncludeAgent)
```

Existing destination files are not overwritten without **explicit `-Force`**.
Review local customizations before authorizing replacement. Do not use force
as a routine installation shortcut. Every source/destination is preflighted
before copying: the skill instructions and **both** reporting and project-results
helpers are explicitly required. The migration helper is included through
complete-folder copying, not a third required-helper gate.
A missing required helper, differing helper, companion collision,
or file blocking a required directory refuses before any integration file is
copied. Identical files are left untouched, so repeating the install is
idempotent. Linked resources/destination parents require review and are refused.
This is collision preflight, not a transaction against concurrent filesystem
changes or later I/O failures. Unrelated instructions and agents are not
part of this installation; in particular, do not vendor or update the target's
project-wide Copilot instructions.

`-RuntimeExecutable` validates an installed `discovery-physics` CLI path and
prints a launch-environment reminder; it does not persist the path or rewrite
the standalone skill. It is not the Podman/Docker executable. Set
`DISCOVERY_PHYSICS_CLI` explicitly in the app's launch environment. For a custom location:

```powershell
.\scripts\install-workspace.ps1 -ProjectPath $project `
    -IncludeAgent -RuntimeExecutable $env:DISCOVERY_PHYSICS_CLI
```

Open the target project in Discovery. The skill's CLI lookup is self-contained: it resolves
`DISCOVERY_PHYSICS_CLI` first, then `Get-Command`, then the default local
application-data executable. Custom launch environments must be visible to the
app. Select `clio-mode`, or the optional `phy-openfoam` companion, and ask it to
clarify missing scientific inputs before preparing a case.

## Manual skill installation

1. **Download/copy the complete [skills/phy-openfoam/](../skills/phy-openfoam/)
  folder**, including its scripts/resources, from the approved entry revision.
  Review the source; do not copy caches, bytecode, environments or private state.
2. Create the target project's plural **skills** directory and preserve the
  supplied relative layout. The complete supplied folder currently includes
  these files; a URL bookmark or Markdown-only copy is not the installation:

    ```text
    .github/skills/phy-openfoam/SKILL.md
    .github/skills/phy-openfoam/scripts/render_report.py
    .github/skills/phy-openfoam/scripts/project_results.py
    .github/skills/phy-openfoam/scripts/migrate_results.py
    ```

3. If desired, copy
   [integrations/phy-openfoam.agent.md](../integrations/phy-openfoam.agent.md)
   to the optional companion destination shown above.
4. Install the host runtime separately and make its CLI discoverable. Copying
  the skill does not install Python, OpenFOAM, CLIO, or the container engine.
  All three helpers use only stdlib Python; standalone-helper/instruction updates
  do not require reinstalling pip packages or rebuilding/updating the image.
5. Follow [project results routing](configuration.md) before authoring/freezing,
  then [final HTML reporting](reporting.md). A raw Markdown-only copy lacks the
  supplied helpers: obtain the complete skill before starting a new campaign.
  A report-only escaped-HTML fallback still needs a validated marked project-results
  destination; otherwise disclose a packaging blocker, never claim complete
  reporting without HTML.

**Only after this contribution is merged**, the upstream raw skill URL is:

[https://raw.githubusercontent.com/microsoft/discovery/main/agents/phy-openfoam/skills/phy-openfoam/SKILL.md](https://raw.githubusercontent.com/microsoft/discovery/main/agents/phy-openfoam/skills/phy-openfoam/SKILL.md)

Before merge, replace `main` in that URL with the **approved contribution ref**
(and use the approved repository if the ref is in a fork). Do not describe the
unmerged URL as an available release. Do not copy unrelated workspace-wide
Copilot instructions from the source checkout.
This raw URL supplies **instructions only**, not the supplied helpers/resources;
prefer the approved full folder or the collision-safe workspace installer.

## 3. Initialize results for a new investigation

Installation alone does not initialize or authorize a campaign. When starting
new work, select the current user's existing absolute project root explicitly,
not CWD, Git, runtime installation or the acquired entry. In a multi-root workspace
ask only when the intended user project is ambiguous. Source staging remains
read-only for investigation outputs even outside an `agents` directory.

```powershell
$project = Read-Host 'Existing absolute user project root (not acquired source)'
if (-not [IO.Path]::IsPathFullyQualified($project)) { throw 'Select an absolute project path.' }
$project = (Resolve-Path -LiteralPath $project -ErrorAction Stop).Path
$paths = Join-Path $project '.github/skills/phy-openfoam/scripts/project_results.py'
$layout = python $paths init --project-root $project --slug flow-investigation | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Results initialization failed; stop before authoring/freezing.' }
$results = $layout.results_root
python $paths check --project-root $project --results-dir $results
```

The helper creates `results-<slug>-<utc>-<suffix>/` directly under the selected
project with a manifest and inputs/analysis/logs/exports/runs/studies directories.
Use a lowercase alphanumeric, hyphen-separated slug. Optional `--exact` requests
the exact slug folder and refuses a collision. Keep all generated inputs,
geometry, scripts, logs, analyses, exports, HTML and new native artifacts inside
the marked container, never under project `agents` or anywhere in acquired source.
Static curated inputs and reviewed fixtures remain contribution assets.

For explicitly authorized native commands, the helper's `run --project-root
<absoluteproject> --results-dir <markedresults> [--cli <installedCLI>] --
<nativecommand> <args>` sets child-only `DISCOVERY_PHYSICS_RUNS=<results>/runs`,
CWD at results and logs under results. Relative input paths resolve there;
new example/geometry/export outputs are results-contained. It does not
automatically solve, propose, confirm or grant approval. HOME, runtime config,
signing keys, caps and shared slots remain unchanged; no global override or
results configuration-model property is needed.

Existing campaign status reads the original recorded native path directly,
without initializing results, using the run wrapper or writing logs/reports.
For explicit HTML delivery, select that project's existing marked results with
`--results-dir`, or create a new report-only container with `--slug`, always
with required `--project-root`. Optional `--out` cannot escape the container or
overwrite report files and is accepted only with `--results-dir`, not `--slug`.
Initialize first when a new report container needs a custom subdirectory.
Legacy `--runs-root` is read-only evidence input, not a
move of historical records or keys. See [reporting](reporting.md).

## Optional unsigned-delivery preservation

The complete skill's migration helper has this separate, explicitly authorized
interface; installation and status/report observation never invoke it automatically:

```text
python <skill>/scripts/migrate_results.py --project-root <absoluteproject> --source <originalabsoluteunsigneddirectory> --slug <slug> [--exact] [--archive] [--remove-source]
```

It defaults to copy-only into a new marked container. `--archive` preserves a
legacy tree beneath archive; `--exact` refuses a destination collision.
Separately approved `--remove-source` cleanup follows whole-source inventory
and every copied file's hash verification. Detected journals, keys/configuration
and links are refused; old report/receipt bytes and embedded paths are not rewritten.
No signed history/key move, native CLI action, new runtime installation or CFD is
performed. See [preservation and receipts](reporting.md) before use.

## Preflight and safe updates

Use the [health-only example](../examples/channel-path-check.json) for input lint
and optional execution-path checks, not a pressure-drop accuracy claim. Follow
[examples](../examples/README.md) and [scripts](../scripts/README.md) for explicit
commands and fresh project-owned results locations. Runtime installation and
private operator app data remain separate from user-generated results.

CPU/memory/PID limits fail closed if the engine cannot enforce them. A successful
image build, `podman info` label, or tutorial listing is not a substitute for
reading back the requested limits in an actual capped container. An agent
must report the infrastructure blocker, not change settings or add exception
flags. Only an operator can make and disclose that decision. See
[configuration](configuration.md) and [troubleshooting](troubleshooting.md).

To update, review the candidate revision and its scope. CLI/container changes
may require deliberately reinstalling the host package/image; skill/report-only
changes require only the full workspace skill update, not pip or image changes.
Review every changed workspace resource before any forced replacement. Keep runtime data,
original evidence, and signing keys out of source control; never replace a key
merely to make an old run verify. See [candidate validation](validation.md) for
the separately scoped source, installation, image, and local bounded-runtime
checks actually performed. These do not qualify Scientific Researcher dispatch,
physical predictions, or the cloud route.

Existing editable installations tied to the old source location must be
reinstalled after this reorganization. Do not copy or rewrite the old virtual
environment, run store, or signing key to hide a stale import path. Choose the
intended source revision and deliberately reinstall/rebuild when ready.