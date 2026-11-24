# phy-openfoam — evidence-gated OpenFOAM

## Overview

Use Discovery's **Scientific Researcher** capability to turn a natural-language
CFD request into an **OpenFOAM Foundation 14** case and a request-specific
scientific contract. Scientific Researcher authors and diagnoses;
phy-openfoam's deterministic tools freeze the contract, measure native solver
evidence, and decide `ACCEPT`, `REJECT`, `INCONCLUSIVE`, or `CORRECT_AND_RERUN`.

The implementation is independent of CFD Forge; the
[paper](https://arxiv.org/abs/2610.14104) is a research reference, not a code,
data, or container dependency.

### Arbitrary prompts, not a fixed menu of flow families

**phy-openfoam does not require a request to match a pre-registered flow
family.** Scientific Researcher authors the case, diagnostics, and scientific
contract for each request, then the same deterministic infrastructure freezes
and assesses them. A new supported flow does not need a new family router or
family-specific case builder.

In contrast, the [CFD Forge paper](https://arxiv.org/html/2610.14104v1),
Sections 2.1, 5.3, and 6, describes two **routable agent families**: a
converging-diverging nozzle and a two-dimensional forward-facing step. Text
requests can change parameters within their registered envelopes. The turbulent
cube is a separate offline diagnostic study, not a third routable family.

| Aspect | CFD Forge's published workflow | phy-openfoam |
|---|---|---|
| Request scope | Nozzle/forward-step families within fixed envelopes | Free-form requests within installed solver, safe meshing, diagnostic, and budget capabilities |
| Case construction | Family-specific builder and numerical recipe | Scientific Researcher adapts tutorials and authors a request-specific case |
| Scientific contract | Registered per family | Authored per request; linted, frozen, and hashed before execution |
| Acceptance authority | Deterministic checks, not the model | Same principle: deterministic checks, not the model |
| Corrections | Bounded actions approved by a validator | Bounded actions approved by a validator; scientific criteria stay frozen |
| Mesh/design studies | Nozzle reference refinement; step sensitivity lacked a registered cross-grid criterion | Frozen cross-run studies support the grid-convergence index (GCI) and uncertainty-aware candidate selection |

**Broader authoring, not weaker acceptance.** Arbitrary prompts do not mean
arbitrary physics is supported or every answer will be accepted. Missing inputs,
unavailable measurements, unsuitable models, or unaffordable resolution still
require clarification, refusal, or an inconclusive result. An agent-authored
contract also needs scientific review: enforcing a weak contract does not make
it strong. CFD Forge could be extended with additional families; the comparison
here is to its **published routable workflow**, not a limit of OpenFOAM itself.

### Two bounded CFD prompts beyond the paper's registered families

These are supported **authoring-and-study workflow examples**, not claims that
these exact revised examples have already run or passed. The first targets
**5–10 minutes** and the second **about one hour**, including local CFD and report
generation after setup and approval. These are planning targets on comparable
two-core hardware, **not timing or convergence guarantees**. A cold installation,
image build, model latency, and approval delays are outside those targets.

The scope is deliberately smaller than the former multi-design campaigns:
one thermal screening run, or two isolated-cylinder resolutions. Do not silently
add pilots, three-grid studies, expanded domains, tandem spacings, or retries.
If the proposed work does not fit, ask before solving rather than weaken checks.
The [budgeted example guide](examples/README.md) explains the limits.

All new user-generated work belongs in a marked results container directly under
the explicitly selected user project, never under `agents` or acquired source.
The bundled [results helper](skills/phy-openfoam/scripts/project_results.py)
initializes it before authoring/freezing; runtime configuration and signing keys
remain in private app data. See [results routing](docs/configuration.md).

**CFD prompt 1 — Heated-channel screening · target 5–10 minutes**

> Model one two-dimensional laminar air channel: length $0.2\thinspace\mathrm{m}$,
> full gap $5\thinspace\mathrm{mm}$, uniform inlet temperature
> $300\thinspace\mathrm{K}$, stationary no-slip walls at
> $350\thinspace\mathrm{K}$, and volume flow per unit depth
> $2\times10^{-3}\thinspace\mathrm{m^2/s}$. State constant film properties at
> $325\thinspace\mathrm{K}$, neglect buoyancy, and check the laminar assumptions.
> Measure pressure drop and the native mass-flow-weighted outlet temperature,
> not an area-average substitute.
>
> Propose one structured mesh around $160\times32$ cells, no more than
> $6{,}000$ cells, and $6{,}000$ steady iterations with the final $1{,}000$
> iterations used for settling. Propose a single execution, two CPU cores,
> $4\thinspace\mathrm{GiB}$ RAM, a $900\thinspace\mathrm{s}$ hard worker cap,
> and a $512\thinspace\mathrm{MB}$ output cap. There are no automatic retries,
> continuations, extra pilots, grid studies or alternate heights. Use bounded
> temperature advection. Agree boundary details, conservation, residual,
> settling and temperature-bound tolerances before freezing. Use measured
> comparable costs; if this cannot reasonably fit the target, explain and ask
> before solving. The time target is not a convergence guarantee.

<details>
<summary>Plain text — copy the heated-channel prompt</summary>

Use the code block's Copy button, or
[download the same prompt](examples/prompts/01-thermal-quick.txt).

```text
Model one two-dimensional laminar air channel: length 0.2 metres, full gap 5 millimetres, uniform inlet temperature 300 kelvin, stationary no-slip walls at 350 kelvin, and volume flow per unit depth 0.002 square metres per second. State constant film properties at 325 kelvin, neglect buoyancy, and check the laminar assumptions. Measure pressure drop and the native mass-flow-weighted outlet temperature, not an area-average substitute.

Propose one structured mesh around 160 by 32 cells, no more than 6000 cells, and 6000 steady iterations with the final 1000 iterations used for settling. Propose a single execution, two CPU cores, 4 GiB RAM, a 900-second hard worker cap, and a 512 MB output cap. There are no automatic retries, continuations, extra pilots, grid studies or alternate heights. Use bounded temperature advection. Agree boundary details, conservation, residual, settling and temperature-bound tolerances before freezing. Use measured comparable costs; if this cannot reasonably fit the target, explain and ask before solving. The time target is not a convergence guarantee.
```

</details>

**Why this goes beyond CFD Forge's published families:** it requires viscous
heat transfer and flux-weighted thermal diagnostics—not a parameter change to
an inviscid nozzle or supersonic step. The shorter scope does not claim the
uncertainty-resolved optimization of the earlier multi-height example.

**CFD prompt 2 — Isolated-cylinder resolution comparison · target about one hour**

> Model water at $20^{\circ}\mathrm{C}$ past one circular cylinder of diameter
> $D=10\thinspace\mathrm{mm}$. Use a two-dimensional incompressible laminar
> steady model at $\mathrm{Re}_D=20$ based on uniform upstream speed and cylinder
> diameter. State density and viscosity and derive the speed consistently. Use
> the full cross-stream domain, no-slip cylinder, uniform inlet, downstream fixed
> gauge pressure, slip lateral boundaries, and empty spanwise faces. Propose
> boundaries $20D$ upstream, $40D$ downstream and $20D$ on each side, explicitly
> acknowledging finite-domain error. State the bookkeeping depth and use diameter
> times depth as the drag reference area.
>
> Freeze exactly two body-fitted meshes near $8{,}000$ and $32{,}000$ cells, with
> no more than $40{,}000$ cells each. Use at most $10{,}000$ steady iterations per
> mesh and the final $2{,}000$ iterations for settling. Propose sequential
> execution on two CPU cores with $4\thinspace\mathrm{GiB}$ RAM, one execution
> per mesh, a $2{,}700\thinspace\mathrm{s}$ hard worker cap per execution, a
> $512\thinspace\mathrm{MB}$ output cap per run and at most $5{,}400$
> worker-seconds in total. No automatic continuation, extra pilot, third grid,
> expanded-domain run or second cylinder is authorized. Review measured comparable
> costs before freezing; if the expected work cannot reasonably fit about an
> hour, ask before execution. The generous hard caps are not a runtime prediction
> or a convergence guarantee.
>
> Measure drag per unit depth and drag coefficient on both meshes. Before
> solving, agree conservation, residual and force-settling checks and a $3$
> percent point-reference tolerance against an applicable published unconfined
> $\mathrm{Re}_D=20$ result using the same normalization. Do not substitute a
> confined-channel benchmark. Report the two-grid difference only: two grids
> cannot establish a three-grid convergence index, mesh independence, domain
> independence or a winning tandem spacing. If reference agreement fails, retain
> that failure rather than adding simulations or changing the reference or
> tolerance.

<details>
<summary>Plain text — copy the isolated-cylinder prompt</summary>

Use the code block's Copy button, or
[download the same prompt](examples/prompts/02-cylinder-hour.txt).

```text
Model water at 20 degrees Celsius past one circular cylinder of diameter 10 millimetres. Use a two-dimensional incompressible laminar steady model at Reynolds number 20 based on uniform upstream speed and cylinder diameter. State density and viscosity and derive the speed consistently. Use the full cross-stream domain, no-slip cylinder, uniform inlet, downstream fixed gauge pressure, slip lateral boundaries, and empty spanwise faces. Propose boundaries 20 diameters upstream, 40 downstream and 20 on each side, explicitly acknowledging finite-domain error. State the bookkeeping depth and use diameter times depth as the drag reference area.

Freeze exactly two body-fitted meshes near 8000 and 32000 cells, with no more than 40000 cells each. Use at most 10000 steady iterations per mesh and the final 2000 iterations for settling. Propose sequential execution on two CPU cores with 4 GiB RAM, one execution per mesh, a 2700-second hard worker cap per execution, a 512 MB output cap per run and at most 5400 worker-seconds in total. No automatic continuation, extra pilot, third grid, expanded-domain run or second cylinder is authorized. Review measured comparable costs before freezing; if the expected work cannot reasonably fit about an hour, ask before execution. The generous hard caps are not a runtime prediction or a convergence guarantee.

Measure drag per unit depth and drag coefficient on both meshes. Before solving, agree conservation, residual and force-settling checks and a 3 percent point-reference tolerance against an applicable published unconfined Reynolds-20 result using the same normalization. Do not substitute a confined-channel benchmark. Report the two-grid difference only: two grids cannot establish a three-grid convergence index, mesh independence, domain independence or a winning tandem spacing. If reference agreement fails, retain that failure rather than adding simulations or changing the reference or tolerance.
```

</details>

**Why this goes beyond CFD Forge's published families:** it introduces external
viscous flow, dimensional body-force diagnostics and a registered resolution
comparison. Neither published nozzle/step builder represents that request.
The shorter example deliberately defers three-grid and far-field qualification.

### Where to find results

Each investigation is saved in a **results-&lt;slug&gt;-&lt;utc&gt;-&lt;suffix&gt;**
folder at your project root. Open the generated HTML report linked in chat for
the summary, figures and verdict. The same folder contains detailed inputs,
logs, analyses, native run/study records and exports; see [reporting](docs/reporting.md).

## Architecture

**Discovery coordinates the research. The deterministic runtime decides.**
Scientific Researcher prepares the case and interprets the results; the host
CLI controls execution and scientific acceptance, independently of the solver.

![Local architecture: Scientific Researcher in Microsoft Discovery uses the phy-openfoam skill directly or with the optional phy-openfoam specialist agent. Cases and proposals go to the deterministic host CLI, which exchanges frozen inputs and native measurements with an isolated OpenFOAM worker and retains private run records.](media/architecture.svg)

*Local execution path. Requests travel down; evidence and verdicts return up.
Private run records remain on the host, outside the solver container. This is
not a diagram of an already deployed Azure service.*

- **Scientific Researcher** orchestrates the investigation; phy-openfoam supplies
  the domain workflow and deterministic tools. The optional
  [phy-openfoam agent](integrations/phy-openfoam.agent.md) is the CFD specialist;
  both it and Scientific Researcher follow the
  [phy-openfoam skill](skills/phy-openfoam/SKILL.md).
- The Python distribution remains `discovery-physics-openfoam`, its import
  module is `discovery_physics`, and its command is `discovery-physics`.
- The CLI is JSON-in/JSON-out and makes **no model calls**. It needs no physics
  MCP server, provider key, task graph, or second LLM controller.
- The host owns freezing, verification, and rulings. The container runs
  allowlisted solver commands and native-data extraction.

See [architecture and trust boundaries](docs/architecture.md) for confirmation,
integrity, resource, and cross-run study rules.

## Setup

Use the two prompts below in the Discovery project where you want to run
phy-openfoam. The first acquires and installs it; the second tests the actual
Scientific Researcher workflow. These **setup prompts are separate from the
 CFD examples above**.

## Prerequisites

- **Windows x64** is the qualified setup target; Python **3.11 or later** and
  **PowerShell 7+** are required. Linux and macOS setup are unqualified. The image
  installs an **AMD64 Debian-format package**; there is no qualified ARM image.
- Install and initialize **Podman or Docker independently**. Registry login,
  virtualization, engine maintenance, and runtime licensing are operator duties.
- For **Podman on Windows/WSL**, use **6.2 or later** with a newly provisioned
  **WSL-native systemd** machine and working CPU/memory/PID delegation. Upgrading
  the client does not migrate a legacy machine. Follow the operator-controlled
  [WSL setup and resource preflight](docs/podman-wsl.md); an image build or
  capability listing alone does not establish resource enforcement.
- For agent-led use, enable **Scientific Researcher** in your Discovery
  environment. Historical native-runtime testing used **Discovery
  0.15.21-preview** and observed model `claude-sonnet-5`; see the
  [validation history](benchmarks/VALIDATION-HISTORY.md) for the execution route.
  Those tests do not by themselves qualify the Scientific Researcher engine path
  or other app/model configurations. The deterministic CLI can also be used
  independently of Scientific Researcher.
- Allocate resources for the frozen case budget and operator concurrency policy.
  A container-runtime executable on `PATH` alone does not establish working
  limit enforcement.

### Prompt 1 — Acquire and install

Paste this prompt into your project's chat.

> Install **phy-openfoam** into the currently open Discovery project.
>
> **Source URL:** https://github.com/microsoft/discovery/tree/main/agents/phy-openfoam
>
> Treat that source as authoritative. Acquire the **complete entry**, preserving
> its directory structure, into a local staging location separate from the
> target project. Resolve GitHub folder URLs to actual source files, not saved
> HTML pages. Record the resolved source commit or release and use those same
> bytes throughout installation. If the source is unavailable, stop and request
> a corrected URL rather than substituting another source.
>
> Read the entry's installation instructions and inspect its supplied installers
> before executing them. Keep source staging, target project, and runtime data
> locations distinct. Then complete these steps:
>
> 1. Check Python, PowerShell, and the container runtime. If a vendor runtime
>    needs installation, startup, authentication, or host configuration, explain
>    the required operator action and pause rather than silently changing the machine.
>    For Podman on Windows/WSL, check native-systemd provisioning and actual
>    CPU/memory/PID controller delegation, not only the installed version.
> 2. Use the supplied workspace installer to copy the phy-openfoam skill to
>    `.github/skills/phy-openfoam/SKILL.md` and the prepared companion agent to
>    `.github/agents/phy-openfoam.agent.md` in the target project. Use
>    `-IncludeAgent`; do not generate a different companion from the cloud
>    manifest. Include both supplied reporting and project-results helpers.
>    Preserve unrelated customizations and ask before replacing
>    differing existing files.
> 3. Use the supplied runtime installer to install or update the host CLI from
>    this exact source with a normal, non-editable installation. Build the matching
>    OpenFOAM worker image locally. Do not skip building unless an existing
>    compatible image's source/version identity has been independently verified.
> 4. Verify the installed CLI from outside the source checkout, check dependency
>    consistency, inspect the worker image identity, and run capability discovery
>    and lint on the supplied health-only channel input. Run the documented tiny
>    non-solver resource probe and verify its live CPU/memory/PID limits before
>    reporting a ready runtime. Make any required CLI
>    or data-root overrides explicit in the environment inherited by Discovery;
>    a terminal-only environment change does not update an already running app.
> 5. Check whether Discovery discovers the installed skill and agent. Distinguish
>    copied files from actual application visibility; do not claim Scientific
>    Researcher can dispatch the agent merely because its file exists.
>
> You may acquire the source, install normal package dependencies into a
> user-local runtime, copy the selected workspace customizations, and build the
> local image. Do **not** publish anything, deploy to Azure, copy private evidence or credentials, enable
> unenforced resource limits, change concurrency, or approve scientific assumptions.
>
> Finish with a concise checklist of the source revision, installed versions,
> CLI location, image identity, skill/agent visibility, checks performed, and any
> remaining blockers. Do not run a CFD simulation yet.

<details>
<summary>Plain text — copy the installation prompt</summary>

```text
Install phy-openfoam into the currently open Discovery project.

Source URL: https://github.com/microsoft/discovery/tree/main/agents/phy-openfoam

Use this URL only after publication; before merge, request the approved fork/ref containing the complete entry. Acquire the complete entry into a local staging location separate from the target project and runtime data. Resolve the actual source files, record the source commit or release, and use those same bytes throughout. If unavailable, stop and request a corrected URL rather than substitute another version.

Read the installation instructions and inspect the supplied installers. Check Python, PowerShell and the independent container runtime. Pause for operator installation, startup, authentication or host configuration; do not silently change the machine. On Windows/WSL with Podman, verify native-systemd provisioning and actual CPU/memory/PID delegation, not just version labels.

Use the supplied workspace installer with -IncludeAgent to install the complete phy-openfoam skill folder, including both its reporting and project-results helpers, into .github/skills/phy-openfoam and the prepared companion into .github/agents/phy-openfoam.agent.md. Do not generate a different companion from the cloud manifest. Preserve unrelated customizations; ask before replacing differing files. Keep source staging distinct from the user project: subsequent investigations initialize marked results folders directly under the explicitly selected project, never under agents or anywhere in the acquired source. Installation alone does not start a campaign.

Use the runtime installer for a normal non-editable installation from this exact source and build the matching local worker image. Skip the build only if an existing image's source/version identity was independently verified. Verify CLI operation outside the checkout, dependencies, image identity, capabilities and lint on the supplied health-only input. Run the documented tiny non-solver resource probe and check actual CPU/memory/PID limits. Preserve runtime selection, safe policy and concurrency. Make CLI/data-root overrides explicit in Discovery's inherited environment; terminal-only changes do not update a running app.

Check actual Discovery visibility of the skill and companion, distinguishing it from copied files. Do not claim Scientific Researcher dispatch from file presence alone. You may acquire source, install user-local dependencies, copy the selected customizations and build the local image. Do not publish, deploy, copy credentials/private evidence, enable unenforced limits, change concurrency or approve scientific assumptions. Finish with the source revision, versions, CLI location, image identity, application visibility, completed checks and blockers. Do not run a CFD simulation yet.
```

</details>

### Prompt 2 — Test the Scientific Researcher workflow

After Prompt 1 reports a ready runtime and visible customizations, select the phy-openfoam agent in the chat drop down, and submit a CFD prompt. If you don't have a prompt of your own ready, try asking Discovery for suggestions (or try one from earlier in this document)

## Configuration

The host installer defaults to a user-local virtual environment outside the
source checkout and builds `localhost/phy-openfoam:0.2.1`. Image and runtime
selection are persisted in local operator configuration; existing safety settings
must be preserved. Environment overrides and custom installation roots are
documented in [configuration](docs/configuration.md).

Runtime configuration is separate from case input and cloud deployment settings.
Start from the local-only [operator example](config/operator.example.json);
the [deployment template](config/deployment.example.json) is a separate cloud
worksheet, not local CLI policy or an automatically provisioned deployment.
An agent must **not** enable unenforced limits, increase concurrency, reconfigure
the container engine, authenticate itself as a user, or alter checks to obtain
acceptance. The optional cloud image template is
`{name}.azurecr.io/phy-openfoam:0.2.1`; cloud deployment remains unqualified.

## Usage

Start with [installation](docs/installation.md), then
[examples](examples/README.md). Operational details are in
[configuration](docs/configuration.md), [troubleshooting](docs/troubleshooting.md),
and [deployment readiness](docs/deployment.md).

The prompts handle installation for you. If you prefer the equivalent manual
route, run these commands from this entry directory in a downloaded source checkout:

```powershell
# Host-only runtime installation; does not install workspace instructions.
.\scripts\install-runtime.ps1

# Existing target project: install the skill and, optionally, the companion.
.\scripts\install-workspace.ps1 -ProjectPath 'C:\work\cfd-project' -IncludeAgent

$dp = "$env:LOCALAPPDATA\DiscoveryPhysics\venv\Scripts\discovery-physics.exe"
& $dp schema bundle
& $dp lint .\examples\channel-path-check.json
```

The lint example performs no CFD solve. Inspect the JSON `ok`, `errors`, and
warnings, not only the process exit code. For a custom runtime location, follow
the [installation guide](docs/installation.md) rather than assuming this default
executable path.

For new work, select the existing absolute user project root explicitly; neither
the command's CWD, a Git root nor source staging identifies it. Ask which project
only if ambiguous. Before authoring/freezing, initialize its unique marked
results container with the installed results helper. The
[examples](examples/README.md) show initialization and explicit native-command
routing: child-only `DISCOVERY_PHYSICS_RUNS` selects its runs directory, studies
stay beside it, and CLI logs stay inside results. All generated inputs, scripts,
analyses, exports and reports belong there too. No results go under any `agents`
directory or inside acquired contribution source, even outside that directory.
Keep HOME, operator policy, keys, resource caps and shared slots unchanged;
curated examples/test fixtures remain source assets.

Open the target project in Discovery and use **Scientific Researcher**, or select
the optional `phy-openfoam` companion. For example:

> Set up a laminar channel study. Ask for missing geometry, fluid properties,
> boundary conditions, accuracy requirements, and budget before solving. Register
> a measurable pressure-drop objective and report only what its frozen checks support.

The workflow is `lint` → `prepare` → user confirmation when required → `execute`
→ `status` → `propose` → `finalize`. Only report live acceptance when finalization
returns `final_verdict: ACCEPT` and `live_acceptance: true`. Refusal or an
inconclusive result is a valid outcome; solver exit success is not acceptance.

**Every completed investigation ends with a professional, self-contained HTML
report**, including rejected, inconclusive and blocked outcomes. Its opening
section combines a concise conclusion with labeled native field images (or an
explicitly labeled input schematic if no solution exists). Native verdicts,
cross-run uncertainty, separate analysis and limitations remain distinct.
The bundled [report helper](skills/phy-openfoam/scripts/render_report.py) reads
existing evidence and requires `--project-root` plus exactly one of
`--results-dir <existingmarkedresults>` or `--slug <newslug>`. Fresh
report/snapshot/receipt files default to that marked root; optional `--out`
stays within the same results container and outside signed stores. Never
overwrite report files; rerender into a fresh `reports/v2` subdirectory.
A legacy `--runs-root` is read-only input, not a relocation of historical runs or
signing keys. The helper does not solve or change acceptance. See
[final HTML reports](docs/reporting.md).

For long campaigns, ask **"status"**, **"progress"**, or **"is it still running?"**
in chat. The agent takes one fresh read-only snapshot and reports completed runs,
the current case, actual progress and output freshness; it does not change or
restart the campaign. It uses the original recorded native path directly,
including legacy stores: no results initialization, wrapper/log creation or
new report. [On-demand status](docs/progress.md) is the default;
periodic monitoring is opt-in. No timer or supervision change is needed for a
manual update, and terminal output is not proactive chat.

For manual installation, **download/save the complete skill folder**, including
the [instructions](skills/phy-openfoam/SKILL.md), report helper and results helper, into the
target project's plural **skills** directory. The instructions belong at:

```text
.github/skills/phy-openfoam/SKILL.md
```

The [installation guide](docs/installation.md) includes the conditional upstream
raw URL, optional companion copy, and non-overwriting installer behavior. Do not
copy or update unrelated project-wide Copilot instructions.

## Tools

| CLI commands | Purpose |
|---|---|
| `schema`, `example`, `capabilities`, `tutorial` | Discover input contracts and installed Foundation capabilities |
| `lint`, `prepare`, `confirm` | Check and freeze input; record actual user confirmation |
| `execute`, `status`, `cancel`, `recover` | Run or inspect a guarded execution and handle interruption |
| `verify`, `propose`, `finalize`, `reassess` | Verify pinned evidence and apply deterministic decision policy |
| `study-prepare`, `study-status`, `study-assess`, `design-sample` | Register cross-run studies and sample candidates |
| `geometry`, `export`, `compact` | Convert geometry, export artifacts, or perform operator-controlled retention |

The optional container actions are `evaluate`, `study`, and `lint`; they are not
an MCP interface and have not been qualified through Azure dispatch. See the
[CLI implementation](tools/openfoam/src/discovery_physics/cli.py),
[script reference](scripts/README.md), and [deployment guide](docs/deployment.md).

## Release status and validation

This is the self-contained source entry for the proposed **0.2.1** packaging
update. It is not a publication announcement, first-party approval, deployed
cloud service, or production qualification.

The [benchmark history](benchmarks/VALIDATION-HISTORY.md) is retrospective: the
original 0.2.0 results are not newly executed 0.2.1 receipts.
Fresh [0.2.1 source validation](docs/validation.md) recorded **253 passing tests**
after the repair-documentation follow-up (previously 251) and a separate clean
host installation. A subsequent local runtime installation
built the matching image, and the [WSL repair follow-up](docs/validation.md)
verified bounded rootless execution on Podman **6.2.0**. No new CFD/model campaign,
Scientific Researcher dispatch qualification, or cloud deployment is claimed.

The subsequent [copyable-prompt and HTML-reporting follow-up](docs/validation.md)
passed **303 software tests**. It installed the complete skill/report helper and
previewed a report from existing verified outputs without new CFD. The revised
runtime targets remain unbenchmarked planning estimates, not measured promises.

The later [project-results and migration follow-up](docs/validation.md) recorded
**432 passing tests and one host-permission-dependent skip**. Project-root
output routing, helper installation and byte-verified unsigned migration were
checked without new simulations or changes to original signed campaigns.

## Known Limitations

- Free-form authoring is not universal solver support. Missing inputs,
  unmeasurable objectives, unsupported physics, and unaffordable fidelity block
  execution or acceptance; substitutions need explicit user confirmation.
- Baseline numerical-health checks do not establish model applicability,
  experimental validity, mesh independence, or design superiority. Those claims
  need dedicated evidence and, where applicable, a frozen cross-run study.
- Resource enforcement fails closed by default. Some Windows rootless Podman
  installations cannot enforce CPU, memory, or PID limits. Only an operator may
  authorize a disclosed exception; it is not production enforcement evidence.
- The local wall budget limits meshing and solving, not the complete worker
  lifetime: reconstruction and evidence extraction can continue afterward.
  Output size is checked after writing, not enforced as a live storage quota.
  If a request needs strict whole-worker or peak-storage caps, obtain supported
  enforcement or explicit agreement on weaker limits before freezing. See
  [budget semantics](docs/configuration.md#local-time-and-output-budget-semantics).
- The hardened local worker is not a certified hostile multi-tenant sandbox.
  HMAC-authenticated journals do not isolate a key from the same OS identity,
  provide a public signature, or prove that an omitted suffix never existed.
- No cloud dispatch, production resource enforcement, cloud-study integration,
  durable cloud key custody, or commercial production sign-off is claimed.
- Builds are **not fully reproducible**: the base digest and Foundation package
  bytes are pinned, but apt repositories and some transitive dependencies float.
- Historical 12/12 decision matches and 16/16 behavioral checks are neither all
  `ACCEPT` results nor a new 0.2.1 test run. See
  [validation history](benchmarks/VALIDATION-HISTORY.md) for raw advisory false accepts
  and the unexecuted H14 case.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and the
[source-only distribution checklist](docs/distribution.md). A catalog contribution
must remain scoped to this entry; do not add root workflows or edit protected or
unrelated repository content. Security reports go privately to
[MSRC](https://msrc.microsoft.com/create-report), not public issues; see
[SECURITY.md](SECURITY.md). License boundaries and redistribution obligations are
explained in [licensing](docs/licensing.md). Packaging changes are recorded in
[CHANGELOG.md](CHANGELOG.md).
