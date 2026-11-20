## Overview

Node-aware pdn agent driven by the OpenROAD tool set, consuming the PDK Binding and emitting a Common Design Envelope. Validated on SkyWater sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/pdn/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`pdn` is defined in [tool.yaml](tools/pdn/tool.yaml). Its Docker build context is `tools/pdn/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/pdn/Dockerfile --tag chip-pdn:local tools/pdn
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Power Delivery Network (PDN) Agent
flow_stage: D - Physical Implementation
node_awareness: node-aware
tier: 2
nature: reasoning / orchestrated
required_tools:
- PDN Tool
required_skills:
- Power Analysis Skill
- PDK Binding Skill
- Congestion and Routability Skill
- Provenance Skill
supported_problems:
- power-grid synthesis
- PDN template application
- grid connectivity checking
emits: Common Design Envelope
```

# Power Delivery Network (PDN) Agent

**Purpose** — Build the power grid (rings, straps, rails) and prepare for IR/EM
analysis.

**Responsibilities** — PDN topology definition; ring/strap/rail generation from the
node metal stack; connectivity to std-cell rails; PDN DRC pre-check.

**Supported problems** — Power-grid synthesis; PDN template application; grid
connectivity checking.

**Required tools** — PDN Tool (OpenROAD `pdngen`).

**Required skills** — Power Analysis Skill, PDK Binding Skill, Congestion and
Routability Skill, Provenance Skill.

**Inputs** — Floorplan DEF; PDK Binding (metal stack, layer widths/pitches, via
rules); power intent.

**Outputs** — Power grid (DEF); connectivity report; PDN pre-DRC status. All outputs
conform to the Common Design Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope naming the PDN topology, metal
layers/widths used from the node, and grid connectivity status.

**Validation gates**

- Every std-cell row reached by power/ground.
- Grid uses only node-legal layers/widths.
- No floating power nets.
- Node binding and provenance present.

## Node-Specific Notes

Metal stack, layers, and via rules are consumed from `pdk_binding`.

### sky130 (validation baseline)

- `pdk`: `sky130A`; std-cell rails on `met1`; straps typically on `met4`/`met5`
- Engine OpenROAD pdngen; `engine_class: oss`

### <future node> (stub)

- `pdk`, `metal_stack`, `layers`, `via_rules`: _from binding_.
