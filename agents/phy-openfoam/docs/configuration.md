# Configuration

Configuration has three separate owners: **operators** select trusted runtime
and storage policy; **users** approve scientific assumptions; **agents** author
case bundles within those boundaries. A bundle cannot authorize host changes or
turn a typed audit field into proof of user identity.

The authoritative local interfaces are
[operator configuration](../tools/openfoam/src/discovery_physics/core/config.py),
[runner selection](../tools/openfoam/src/discovery_physics/openfoam/runner.py),
[key storage](../tools/openfoam/src/discovery_physics/core/integrity.py), and the
[skill](../skills/phy-openfoam/SKILL.md). No provider key is needed by the physics
CLI; Discovery/CLIO and registry authentication remain external.

## Local data and installation roots

Default Windows locations are outside the source checkout:

```text
%LOCALAPPDATA%/DiscoveryPhysics/
  venv/Scripts/discovery-physics.exe
  config.json
  runs/                 (legacy/native default; not the new-project workflow)
  keys/journal.key
  slots/
```

`DISCOVERY_PHYSICS_HOME` selects the data root; absent that override, the default
uses local application data (with a home-directory fallback outside Windows).
This does not qualify Linux/macOS installation. `-InstallRoot` selects the host
installer location. Keep a custom install root and the app's data-root/CLI
environment aligned explicitly; an installer cannot update the environment of
an already running app.

Changing a root or key override can make existing runs appear missing or fail
verification. Do not migrate historical stores, copy secrets into a repository,
or regenerate keys as a diagnostic shortcut. Refer to the correct original
store and key under operator-controlled access.

## Project results are separate from runtime app data

Every new user investigation selects an existing **absolute user project root**
explicitly and initializes a marked results container **before authoring or
freezing**. Do not infer this root from CWD, Git, an installer location or source
acquisition. In a multi-root workspace, ask only if the intended project is
ambiguous. Never select any project `agents` directory or the acquired
contribution itself, even if staged under a different name elsewhere.

The standalone stdlib
[results helper](../skills/phy-openfoam/scripts/project_results.py) is installed
with the complete skill; it does not change the numerical package or JSON
configuration model. With an existing Python and the installed skill:

```powershell
$project = Read-Host 'Existing absolute user project root (not acquired source)'
if (-not [IO.Path]::IsPathFullyQualified($project)) { throw 'Select an absolute project path.' }
$project = (Resolve-Path -LiteralPath $project -ErrorAction Stop).Path
$paths = Join-Path $project '.github/skills/phy-openfoam/scripts/project_results.py'
$layout = python $paths init --project-root $project --slug heated-channel | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Results initialization failed; do not author/freeze.' }
$results = $layout.results_root
python $paths check --project-root $project --results-dir $results
python $paths check --project-root $project --results-dir $results --destination inputs/bundle.json
```

`init` creates a unique direct child named `results-<slug>-<utc>-<suffix>/` with
`results-manifest.json`, `inputs/`, `analysis/`, `logs/`, `exports/`, `runs/` and
`studies/`. Slugs are 1–80 lowercase letters/digits separated by single hyphens.
`--exact` uses `results-<slug>` instead and refuses an existing path; normal
initialization also never overwrites. `check` is read-only, including optional
`--destination`: it validates placement, not scientific content or file existence.
Never reuse an arbitrary unmarked folder, symlink or junction as an output root.

All generated user inputs, geometry, scripts, preregistrations, logs, analyses,
exports, reports and new native artifacts belong inside this container. Curated
static examples and reviewed test fixtures remain contribution assets; they are
read-only starting points for new work. Record source revision, original native
paths and run/study IDs in the results manifest without editing signed records.

For each explicitly authorized lifecycle command, the helper's `run` action
resolves the installed CLI, uses the results root as the child's working
directory and sets only the child's run-store override:

```text
python <skill>/scripts/project_results.py run --project-root <absoluteproject> --results-dir <markedresults> [--cli <installedCLI>] -- <nativecommand> <args>
```

The child receives `DISCOVERY_PHYSICS_RUNS=<results>/runs`; the native study
store is its `studies` sibling. CLI transcripts are retained under results/logs.
Relative input arguments resolve from the results root. New `example`,
`geometry` and `export` output paths must be results-contained and fresh.
Native `example nozzle` and `example forward_step` are allowed wrapper actions;
the latter reads the selected image's tutorial. They retain normal user/operator
approval and do not authorize a developer script or a later solve.
`run` invokes exactly the requested native command; it does not automatically
solve, prepare another campaign, propose or confirm. Scientific/user gates still
apply. For Python developer harnesses, use the child-process routing and explicit
output destinations in [scripts](../scripts/README.md), not this CLI-only wrapper.
Every developer writer requires `--project-root`, existing marked `--results-dir`
and fresh `--out` (`--output` for builders); an environment override alone is not
enough. Source validation needs both tools/openfoam/src and the entry root on
child-only `PYTHONPATH`. Non-editable installed benchmark modules do not track
source edits; this launcher uses existing dependencies without a host-package
reinstall or worker-image patch.

Do **not** change HOME, `DISCOVERY_PHYSICS_HOME`, config/key overrides, image,
resource caps, queue settings or shared solve slots to select results. Runtime
installation, private operator configuration and signing keys stay in app data;
do not copy them into the project or persist a global run-store override. No
results metadata JSON property or new resource override is added to the runtime
configuration model.

Existing campaigns keep their original native paths, including legacy stores
outside the project. A status question reads those paths directly: no initializer,
results run wrapper, wrapper log, new report or timer. Explicit report packaging
may read a legacy `--runs-root`, but new HTML/snapshots/receipts must use a marked
project-results container. The renderer requires `--project-root` and exactly one
of `--results-dir` or `--slug`; optional `--out` stays inside that same container
and outside signed stores and is accepted only with `--results-dir`, not `--slug`.
Initialize first for a custom report subdirectory. See [reporting](reporting.md)
for fresh-file rerenders and preservation-safe derivative copies; neither
operation relocates old keys or native records.

The complete skill also supplies the
[unsigned-migration helper](../skills/phy-openfoam/scripts/migrate_results.py).
Its explicit `--project-root --source --slug` interface defaults to copying into
new marked results, with optional `--exact`, `--archive` and separately authorized
`--remove-source` after inventory/hash verification. It refuses detected journals,
keys/configuration and links; old receipt bytes and embedded paths remain intact.
This is not a native-store/key migration or a runtime-config change and runs no CFD.

## Operator settings

Use the local-only
[config/operator.example.json](../config/operator.example.json) as a shape/example,
not an active configuration file inside the source checkout. If needed, copy it
to the operator's private config location and review it before use; preserve
existing safe settings rather than overwriting them with an example. Never put
private operator values back into the public template.

| JSON property | Default | Meaning and authority |
|---|---|---|
| `allow_unenforced_limits` | `false` | CPU/memory/PID enforcement fails closed. Only an operator may explicitly authorize an exception; an agent must never enable it. |
| `max_concurrent_runs` | `2` | Shared local solve-slot cap; the loader bounds the integer to 1–64. A higher parsed value is not authorization or a memory guarantee. |
| `queue_timeout_s` | `21600` | Time allowed waiting for a solve slot, in seconds; not the case's solver wall-clock budget. |
| `image` | `localhost/phy-openfoam:0.2.1` when not configured | Optional trusted image selection, persisted by the host installer. |
| `runtime` | Automatic Podman/Docker selection when not configured | Installed container-runtime command name or absolute executable path, persisted by the host installer; a single executable, not an argument string. |

The host installer preserves existing safe operator keys while saving its
runtime/image choice. It must not silently enable exceptions or reset concurrency
to make a benchmark complete. Review malformed or stale configuration rather
than assuming it was ignored. Do not put credentials, capability URLs, user
confirmations, or case acceptance thresholds in operator configuration.

## Environment variables and precedence

Environment overrides are inherited by the process running the CLI. For image
and runtime selection, an explicit environment value takes precedence over the
optional local setting, which takes precedence over the default. Operator
settings load defaults, then the selected JSON file, then the documented
environment overrides.

| Variable | Consumer and effect |
|---|---|
| `DISCOVERY_PHYSICS_HOME` | Data root for local configuration and runtime state. |
| `DISCOVERY_PHYSICS_CONFIG` | Select a different operator JSON file instead of the default under the data root. |
| `DISCOVERY_PHYSICS_RUNS` | Existing native run-store override. For new project work the results launcher sets it only in the child to `<results>/runs`; status/legacy verification uses the original recorded store directly. Never persist a global override just to route an investigation. |
| `DISCOVERY_PHYSICS_KEY_FILE` | Select the local HMAC key file. Keep it private and associated with the original records. |
| `DISCOVERY_PHYSICS_IMAGE` | Override the trusted image reference; default candidate image is `localhost/phy-openfoam:0.2.1`. |
| `DISCOVERY_PHYSICS_RUNTIME` | Override the installed container-runtime executable/selection; not the physics CLI path. |
| `DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS` | Operator-only override: exactly `1` enables the exception; another supplied value disables it. Never set this on an agent's initiative. |
| `DISCOVERY_PHYSICS_MAX_CONCURRENT` | Operator-only integer override of the local concurrency cap. |
| `DISCOVERY_PHYSICS_CLI` | Skill/companion discovery of the installed `discovery-physics` command; not a core container-engine setting. |
| `DISCOVERY_CLIO_EXE` | Optional benchmark-driver selection of an independently installed CLIO executable. |
| `DISCOVERY_CLIO_STATE_HOME` | Optional native session-state root used by model-comparison receipt inspection. It does not itself relocate CLIO's own session writer. |

### Podman machine selection

The physics configuration selects an executable and image, not a Podman machine.
Podman resolves its own connection using its normal configuration and inherited
environment. `CONTAINER_CONNECTION` selects a configured connection name;
`CONTAINER_HOST` selects a service URL. These are Podman settings, not physics
JSON properties, and can supersede an operator's saved default connection. Do not
substitute the unrelated `PODMAN_HOST` name or embed connection flags in `runtime`.
Consult the [Podman reference](https://docs.podman.io/en/latest/markdown/podman.1.html)
before changing a host's existing connection configuration.

For a side-by-side Windows installation, an absolute Podman executable path in
`runtime` avoids selecting an older client still on `PATH`. This works through
the existing executable lookup; it does not require editing the package. Changes
to the default connection affect other Podman clients. Process-scoped overrides
must be inherited by Discovery; setting them in a terminal does not retroactively
update the app. After reinstalling the host runtime, inspect selection again:
the installer persists its `-Runtime` choice and can replace a manual path.

For Podman on Windows/WSL, follow the operator-controlled
[native-systemd migration and bounded resource preflight](podman-wsl.md).
Client version, image availability, `podman info`, and `capabilities` are not
substitutes for checking live CPU/memory/PID controls in the worker container.

There is no documented queue-timeout environment variable. Frozen case budgets
remain separate from operator queue policy. The service-only
`DISCOVERY_PHYSICS_OUTPUT` selects its output mount root (default `/output`);
it is not the host run-store override. `/output` remains the platform-managed
worker mount, not an absolute host project path. Available platform/host
publication materializes returned artifacts into project results; if unavailable,
report that location blocker rather than invent a cloud action or silently
switch routes. Internal service variables such as
`DISCOVERY_PHYSICS_IN_CONTAINER` and `DISCOVERY_PHYSICS_IMAGE_REF` are not host
workarounds: never set them to bypass container execution or manufacture image
identity/enforcement claims. The service's temporary key is not a production
key-custody configuration.

The standalone skill resolves `DISCOVERY_PHYSICS_CLI`, then `Get-Command`, then
the default local application-data executable. The native CLIO driver resolves
`--clio-executable`, then `DISCOVERY_CLIO_EXE`, then `PATH`, then supported local
Discovery Preview installation discovery. An explicit bad CLIO override is an
error, not permission to silently use another executable. See
[scripts](../scripts/README.md).

## Local time and output budget semantics

`max_cells` has a measured pre-solve gate as well as an authoring estimate.
After setup, `checkMesh` must complete with one positive measured cell count no
larger than the frozen cap, before decomposition or `foamRun`. Unknown,
ambiguous or excessive counts block serial and MPI solves. Continuations check
the copied mesh again rather than trusting an earlier estimate or log. The raw
packet records the measured/cap values and refusal reason; a successful static
estimate does not authorize a larger generated mesh.

CPU, memory and PID limits are requested from the container runtime; the default
policy refuses execution when those controls cannot be enforced. The case budget's
time and output fields have different semantics:

- `wall_seconds` starts a common deadline for copying, meshing, checking,
  decomposition and solving. Reconstruction can receive additional time;
  derived-field post-processing has separate timeouts, followed by extraction
  and illustrative rendering. The host gives the container invocation an outer
  timeout of `wall_seconds + 600`; a subprocess timeout alone is not proof that
  the entire container/process tree is terminated at the requested deadline.
- `max_output_mb` is assessed after writing by summing retained output file sizes
  in decimal megabytes. It is not a live filesystem quota or a measurement of
  peak storage, and a passing final size does not establish a peak-size bound.

Do not present these fields as hard whole-worker, aggregate end-to-end or live
disk limits. When a prompt requires those stronger limits, disclose the mismatch
before freezing and obtain supported enforcement or the user's explicit agreement
to the existing weaker semantics. Keep scientific checks and the number of
authorized attempts unchanged. Do not enable an unenforced CPU/memory/PID
exception, patch a frozen budget, or silently carry an exception to a new request.

## Safe local selection example

After installing the desired runtime and image independently, an operator can
select them for a new process without changing a case:

```powershell
$env:DISCOVERY_PHYSICS_IMAGE = 'localhost/phy-openfoam:0.2.1'
$env:DISCOVERY_PHYSICS_RUNTIME = 'docker'
$dp = "$env:LOCALAPPDATA\DiscoveryPhysics\venv\Scripts\discovery-physics.exe"
& $dp capabilities
```

This changes trusted execution selection, not scientific thresholds. A model
must not use it to switch runtimes after an infrastructure refusal. An executable
or image reference existing locally is not proof of compatible Foundation bytes,
working enforcement, or a successful scientific run.

## Explicit benchmark exceptions

Benchmark tooling must not unconditionally inject an unenforced-limit opt-in.
Where exposed, `--allow-unenforced-limits` is an **operator-only explicit flag**;
otherwise execution honors the existing operator configuration and inherited
environment. Omitting the flag does not negate an already configured operator
exception. Always disclose effective resource-limit evidence, not just flags.

Default command examples in this entry do not enable the exception. Prefer an
environment that actually enforces limits. An exception is not equivalent to
production CPU, memory, or PID enforcement and does not permit exceeding the
frozen budget or increasing the configured solve cap.

## Scientific confirmation is separate

`confirm` records the user's decision for `needs_confirmation` assumptions.
The agent must first obtain that decision and must not approve its own
`method_substitution`. Do not encode confirmations as environment variables,
operator exceptions, or deployment template defaults. Thresholds, objectives,
and budgets are registered in a bundle/study before execution and cannot be
relaxed after results are seen.

## Cloud settings are not local policy

The optional
[config/deployment.example.json](../config/deployment.example.json) template uses
`{name}.azurecr.io/phy-openfoam:0.2.1`,
`{{CHAT-MODEL}}`, and `{{phyOpenfoamToolId}}` as operator placeholders. It is not
a credential store or proof that a tool resource exists. A deployment worksheet
does not automatically provision Azure or configure the local CLI. See
[deployment readiness](deployment.md) and [distribution](distribution.md) before
substituting any private deployment values.