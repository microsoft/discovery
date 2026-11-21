## Overview

Node-agnostic RTL design agent. The agent authors synthesizable RTL and the tool verifies it in the same run, so authored RTL is never reported as good until it has elaborated and passed hygiene. Screens inferred latches, undriven and multiply-driven nets, and reset hygiene read structurally from the elaborated Yosys netlist (mixed async/sync style, mixed polarity, reset sampled as data, reset tied off). Node-agnostic (no PDK binding required).

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/rtl-design/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/ghdl/synth:beta`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`rtl-design` is defined in [tool.yaml](tools/rtl-design/tool.yaml). Its Docker build context is `tools/rtl-design/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/rtl-design/Dockerfile --tag chip-rtl-design:local tools/rtl-design
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: RTL Design Agent
flow_stage: B - RTL Design and Verification
node_awareness: node-agnostic
tier: 1
nature: reasoning / orchestrated
required_tools:
- RTL Design Tool
required_skills:
- RTL Design Skill
- Verification Planning Skill
- Provenance Skill
supported_problems:
- synthesizable RTL authoring
- RTL hygiene / lint (inferred latches, undriven/multidriven nets)
- reset and clock-domain hygiene
- clock-domain-crossing enumeration for downstream signoff
emits: Common Design Envelope
```

# RTL Design Agent

**Purpose** — Author synthesizable, hygienic RTL from a specification or
verification plan, and prove it: no inferred latches, no undriven or
multiply-driven nets, and a coherent reset architecture.

**Responsibilities** — Author RTL; elaborate and confirm synthesizability; screen
for inferred latches, undriven and multiply-driven nets; check reset hygiene;
relate the RTL surface (ports, clocks, resets) to the shared verification plan.

**Supported problems** — Synthesizable RTL authoring with verification; RTL
hygiene/lint; reset hygiene; a starting clock/reset list for CDC signoff.

**Required tools** — RTL Design Tool (Yosys elaboration, hygiene and reset-hygiene
checks; emits a Common Design Envelope).

**Required skills** — RTL Design Skill, Verification Planning Skill, Provenance
Skill.

## Ordinary local execution

This is an OpenSTA-style source package: `agent.yaml`, `metadata.yaml`, this README,
and the complete `tools/rtl-design` build context. No shared source tree or host
Python launcher is needed. The Discovery parent owns dispatch and handoffs.

The local `.github/skills/discovery-add-agents/SKILL.md` Steps 5/6 copy the selected
source to `discovery_catalog/<name>` and generate a companion with lazy bootstrap.
For these local sources use `agents-docker` as Step 5's `$srcRoot`, select exactly
the three role folders, and run Step 6 unchanged. Do not fetch upstream over local
edits. Copy only if the destination is absent; archive/reconcile existing edits first:

```powershell
$name = 'chip-rtl-design'
$dst = Join-Path (Get-Location) "discovery_catalog\$name"
if (Test-Path $dst) { throw "Destination exists: $dst" }
New-Item -ItemType Directory -Force discovery_catalog | Out-Null
Copy-Item -Recurse "agents-docker\$name" $dst
# Run the local skill's Step 6 generation with $selected=@($name).
```

This local branch **does not register actions or configure mounts**. `toolId` is
a deployment placeholder, not a callable Copilot tool. Use the `run` action only
where genuinely registered with the mount contract below; otherwise run one
container directly. The fixed action reads `/input/params.json` with the schema
in `tools/rtl-design/params.schema.json`; no raw JSON is interpolated into a shell.

Importer tag: **`rtl-design:latest`**. Inspect first; bootstrap only a missing image:
`docker build -t rtl-design:latest agents-docker\chip-rtl-design\tools\rtl-design`.
After import use `discovery_catalog\chip-rtl-design\tools\rtl-design` as context.
Podman accepts the same build/run arguments. Engine installation, local daemon
readiness and context selection are integration responsibilities, not host Python.
An existing image is not automatically refreshed after source edits; select an
explicit source-current tag. Never silently use a stale image.

Independent PowerShell single-operation example, from project root:

```powershell
$op = Join-Path (Get-Location) ("results\rtl-design-" + [guid]::NewGuid().ToString('N'))
if (Test-Path $op) { throw "Operation already exists: $op" }
New-Item -ItemType Directory $op -ErrorAction Stop | Out-Null
'input','output','work','tmp','var-tmp','home','run','shm','evidence' | ForEach-Object {
    New-Item -ItemType Directory (Join-Path $op $_) -ErrorAction Stop | Out-Null
}
# Copy only required RTL into "$op\input"; example filename is dut.v, module dut.
# Reject linked paths and freeze input bytes before invocation.
'{"scenario":"check_authored","top":"dut","rtl_files":["/input/dut.v"]}' |
    Set-Content "$op\input\params.json" -Encoding utf8
docker run --rm --pull=never --read-only --network=none --cpus=2 --memory=4g --pids-limit=256 `
    --mount "type=bind,source=$op\input,target=/input,readonly" `
    --mount "type=bind,source=$op\output,target=/output" `
    --mount "type=bind,source=$op\work,target=/workdir" `
    --mount "type=bind,source=$op\tmp,target=/tmp" `
    --mount "type=bind,source=$op\var-tmp,target=/var/tmp" `
    --mount "type=bind,source=$op\home,target=/home/worker" `
    --mount "type=bind,source=$op\run,target=/run" `
    --mount "type=bind,source=$op\shm,target=/dev/shm" `
    rtl-design:latest python3 -B -u /app/run.py --params-file /input/params.json `
    1> "$op\evidence\stdout.log" 2> "$op\evidence\stderr.log"
$containerExit = $LASTEXITCODE
$containerExit | Set-Content "$op\evidence\container-exit.txt"
Get-Content "$op\output\common_design_envelope.json" -Raw
```

Use absolute native paths with no links/junctions; on POSIX adapt host separators
and shell quoting only. All inputs, writable mounts and logs stay under `results`;
do not use tmpfs. Dockerfile sets HOME, TMPDIR/TMP/TEMP and XDG_CACHE_HOME to these
mounts. Windows Docker Desktop integration may add `--context desktop-linux`
before `run`/`build`; do not bake it into source behavior. If engine/image/mounts
are unavailable report BLOCKED, never install software or invent a registered action.

Return the actual container exit, CDE status/verdict/error, native engine codes,
logs and formatting proposals separately. Exit 0 requires completed/pass, but
still inspect every required metric. CDE relative artifact references resolve
under `$op\output`, not the source folder. The worker refuses nonempty output/work
directories. Never reuse an operation; retain failed attempts. Run regressions in
this same mount layout with `python3 -B -m unittest discover -s /app -p 'test_*.py' -v`.

## Who authors, and who checks

The **agent** authors the RTL — that is its primary job, and real design work.
The **tool** is the bench instrument: it reports what the *elaborated* design
actually became, which is the only place several of these defects are visible at
all. An inferred latch is in the netlist, not in the source; the source only
contains the omission that caused it.

The tool deliberately does not generate RTL. An algorithm cannot write the RTL a
specification implies, and a template generator that pretended to would emit code
that elaborates cleanly and does the wrong thing — worse than emitting nothing.

### The authoring loop

1. **Interface first** — ports, widths, clock, reset polarity and style. Anything
   the request left open is either asked about or chosen *and stated*.
2. **Author** the module.
3. **Check** with `check_authored`.
4. **Repair** and re-check. Two or three passes are normal.
5. **Report** the RTL, the evidence, and the assumptions.

For file-supplied `rtl_files`, `check_authored` verifies formatting without changing
the read-only inputs. Final RTL stays at
`$op\input\<file.v>`; separate formatting proposals under
`$op\output\results` are not accepted RTL. Inline `rtl` is normalized
before checking and saved at `$op\output\results\<top>.authored.v`.
Freeze those final output bytes and rerun file-supplied checks before handoff.
Retain failed attempts; adopting a proposal requires a fresh design check,
DEFAULT lint/format and simulation on byte-identical RTL.

### Repair integrity

When the check fails, the fix belongs in the design — never in the measurement,
and never in the functionality that provoked it.

The cheapest way to clear an inferred latch is to delete the branch that caused
it, tie the signal off, or drop a case arm. Each makes the gate pass, and each
converts a *detected* hygiene defect into an *undetected* functional bug. If the
specification and the hygiene gate genuinely conflict, that is a finding to
report — not something to resolve by quietly shrinking what the module does.

A clean check means the design elaborates, infers no latch, has no undriven or
multiply-driven net, and has a coherent reset architecture. It says nothing about
whether the module does what was asked. Functional verification is a separate
gate.

## Reset hygiene: proven vs. advised

Reset defects are among the most expensive in a design. They are intermittent,
they survive most functional simulation — which typically applies one clean reset
at time zero — and they surface on silicon as a rare failure-to-start.

These are read from Yosys **cell types and parameters**, so they are facts about
the elaborated design rather than about spelling. They **gate**:

| Finding | Why it matters |
|---|---|
| one reset net used both async and sync | the two groups leave reset on different cycles, so there is no single reset boundary |
| one reset net used at both polarities | on assertion, half the design resets and half keeps running |
| a reset also sampled as data | defeats reset-tree treatment; a classic reset-domain-crossing bug |

These are **advisory**, because none is provable from structure alone:

- a net named `rst_n` used active-high (legal silicon, illegal communication)
- an async reset arriving straight from a port with no de-assertion
  synchronizer. Asserting asynchronously is fine; *releasing* asynchronously
  violates recovery/removal timing — but the synchronizer may legitimately live
  in a parent module, which is exactly why it does not gate
- a reset pin tied to a constant, so those flops never reset

A null `reset_hygiene_violations` means the netlist could not be examined. That
is not a clean reset result.

### Why structural and not regex

The `cdc_scan` path in this same tool infers clock domains by regex over raw
source text and then forms a cartesian product of clock names. Reset hygiene
deliberately does not repeat that method: when an elaborated netlist is
available, the netlist is the evidence.

**Inputs** — RTL (inline or file paths); top module; the shared verification plan
(optional) for surface tracing.

**Outputs** — Synthesizability verdict; hygiene findings (inferred-latch count,
undriven/multidriven nets, `check` problems); reset-hygiene findings separated
into gating and advisory; the clock/reset surface. All outputs conform to the
Common Design Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope naming the RTL surface, the
hygiene and reset findings, and the clock/reset list so the Functional
Verification, CDC/RDC Signoff, and Logic Synthesis agents can consume it without
re-elaborating.

**Validation gates**

- Design elaborates without error.
- No inferred latches and no undriven/multiply-driven nets (or the run fails
  closed).
- `reset_hygiene_violations == 0`. A **null does not satisfy this gate** — resets
  that could not be examined return `pass_with_caveats`, never a flat `pass`,
  because "we could not check" is not "there is nothing wrong".
- Advisory findings are reported even when the gate is clean; a headline of "no
  issues" beside a non-empty advisory list is its own small lie.
- Authored RTL has been through `check_authored` before it is reported.
- Provenance present (node binding is `none`; node-agnostic).

**Known limits** — `cdc_scan` derives clock names by regex over the source text
and then lists every pair of names as a candidate crossing; it does not trace
dataflow, so it both over-reports (clocks that never interact) and under-reports
(gated, divided or mux-selected clocks). Treat it as a starting list for the
CDC/RDC signoff agent, which does the real enumeration — not as a crossing
analysis. Reset-hygiene analysis covers the module elaborated as top; a
synchronizer implemented in a parent is not visible from inside a submodule.

## Position in the flow

The front-end entry point: it produces hygienic, synthesizable RTL and the
clock/reset/crossing surface that every downstream agent depends on. It is
node-agnostic — technology mapping, corners, and node constants belong to the
Logic Synthesis and signoff agents, never to RTL hygiene.

## Node-Specific Notes

None. RTL hygiene is technology-independent; this agent introduces no node
constants, library cells, or corners.
# Services qualification deployment

`services-deployment.json` pins the qualified Services image when deployed.
`tools/rtl-design/Services.Dockerfile` overlays the current self-contained worker
on the immutable original Services engine image without installing software.
`services-instructions.md` is appended to the source agent instructions.
Jobs are capped at 2 CPU / 4Gi. The worker emits the exact persisted envelope as
`CDE_JSON=` so failed jobs that omit output assets remain auditable.
