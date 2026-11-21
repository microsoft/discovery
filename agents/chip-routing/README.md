## Overview

Node-aware routing agent driven by the OpenROAD tool set, consuming the PDK Binding and emitting a Common Design Envelope. Validated on SkyWater sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/routing/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`routing` is defined in [tool.yaml](tools/routing/tool.yaml). Its Docker build context is `tools/routing/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/routing/Dockerfile --tag chip-routing:local tools/routing
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Routing Agent
flow_stage: D - Physical Implementation
node_awareness: node-aware
tier: 1
nature: reasoning / orchestrated
required_tools:
- Routing Tool
required_skills:
- Congestion and Routability Skill
- PDK Binding Skill
- QoR Reporting Skill
- Provenance Skill
supported_problems:
- global routing
- detailed routing
- congestion resolution
- DRC-driven routing
emits: Common Design Envelope
```

# Routing Agent

**Purpose** — Perform global and detailed routing to a DRC-clean, connected result.

**Responsibilities** — Global routing / congestion resolution; detailed routing; via
selection from the node stack; antenna-aware routing; short/open resolution.

**Supported problems** — Global routing; detailed routing; congestion resolution;
DRC-driven routing.

**Required tools** — Routing Tool (OpenROAD FastRoute + TritonRoute).

**Required skills** — Congestion and Routability Skill, PDK Binding Skill, QoR
Reporting Skill, Provenance Skill.

**Inputs** — Placed + CTS DEF; PDK Binding (routing layers, via rules, spacing);
SDC.

**Outputs** — Routed DEF; DRC violation count; congestion/overflow report;
connectivity status. All outputs conform to the Common Design Envelope and
Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope with the routed DEF, remaining
DRC/short/open counts, and layer utilization on the node stack.

**Validation gates**

- 100% connectivity (no opens); zero unresolved shorts.
- Routing DRC count reported and trending to zero.
- Only node-legal layers/vias.
- Node binding and provenance present.

## Node-Specific Notes

Routing layers, via rules, and tech LEF are consumed from `pdk_binding`.

### sky130 (validation baseline)

- `pdk`: `sky130A`; routing layers `met1`–`met5` (bottom `met1`, top `met5`)
- Engine OpenROAD FastRoute + TritonRoute; `engine_class: oss`

### <future node> (stub)

- `pdk`, `tech_lef`, `cell_lef`, `routing_layers`, `via_rules`: _from binding_.
