## Overview

Node-aware power-analysis agent driven by the OpenROAD tool set, consuming the PDK Binding and emitting a Common Design Envelope. Validated on SkyWater sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/power-analysis/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`power-analysis` is defined in [tool.yaml](tools/power-analysis/tool.yaml). Its Docker build context is `tools/power-analysis/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/power-analysis/Dockerfile --tag chip-power-ir:local tools/power-analysis
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Power and IR-Drop Analysis Agent
flow_stage: E - Timing, Power, Physical Signoff
node_awareness: node-aware
tier: 2
nature: reasoning / orchestrated
required_tools:
- Power Analysis Tool
required_skills:
- Power Analysis Skill
- QoR Reporting Skill
- PDK Binding Skill
- Provenance Skill
supported_problems:
- power analysis
- static IR drop
- dynamic IR drop
- EM screening
emits: Common Design Envelope
```

# Power and IR-Drop Analysis Agent

**Purpose** — Analyze static/dynamic power and power-grid IR drop / electromigration.

**Responsibilities** — Power estimation (static + dynamic); IR-drop analysis; EM
check on the PDN; decap guidance.

**Supported problems** — Power analysis; static IR drop; dynamic IR drop; EM
screening.

**Required tools** — Power Analysis Tool (OpenROAD PSM/PDNSim + OpenSTA power).

**Required skills** — Power Analysis Skill, QoR Reporting Skill, PDK Binding Skill,
Provenance Skill.

**Inputs** — Routed DEF; SPEF; switching activity; PDK Binding (layer R, EM/IR
limits).

**Outputs** — Per-group power breakdown (internal/switching/leakage/total); worst IR
drop; adjudicated EM screen (per-layer current vs node limit). All outputs
conform to the Common Design Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope with the power breakdown (with
units), worst IR drop vs the node limit, and an EM status of
`pass`/`fail`/`not_assessable`/`not_run`.

**Validation gates**

- IR drop within the node budget.
- EM conductor current screened against the tech-LEF Iavg limit; an unresolved
  layer is `not_assessable`, never clean.
- Total power compared against the declared power budget when one is supplied.
- Power reported with units, breakdown and activity source.
- Parasitics basis (`spef` / `none`) recorded.
- Node binding and provenance present.

SPECIALNETS diagnostics count generated or LEF-defined vias placed after routed
coordinates, including multiline and wildcard-coordinate paths; VIAS definitions
and ordinary signal routes are not placements on the power grid. This diagnostic
does not replace native grid checks or supply a missing workload-specific IR budget.

## Node-Specific Notes

Layer resistance, IR/EM limits, and Liberty are consumed from `pdk_binding`.

### sky130 (validation baseline)

- `pdk`: `sky130A`; nominal VDD 1.80 V; IR budget e.g. 5% of VDD (from the binding)
- Engine OpenROAD PSM (PDNSim); `engine_class: oss`

### <future node> (stub)

- `pdk`, `layer_r`, `ir_limits`, `em_limits`, `liberty`: _from binding_.
