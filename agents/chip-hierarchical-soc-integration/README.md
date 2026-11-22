## Overview

Node-aware SoC integration agent that assembles a hierarchical chip from blocks/IP, partitions top-level PPA budgets to blocks, and defines the on-chip interconnect (bus/NoC). Consumes the PDK Binding, drives OpenROAD/Yosys hierarchical assembly, and reports the hierarchy, partitioned budgets, and interconnect. Validated on SkyWater sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/soc-integration/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `cgr.dev/chainguard/python:latest-dev@sha256:cf00203e9a81f254f1cdefdc0b0b22527d2cfbe0a884610605443c81d8b084bd`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`chip-soc-integration` is defined in [tool.yaml](tools/soc-integration/tool.yaml). Its Docker build context is `tools/soc-integration/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/soc-integration/Dockerfile --tag chip-hierarchical-soc-integration:local tools/soc-integration
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Hierarchical and SoC Integration Agent
flow_stage: A - Intent, Specification, Architecture
node_awareness: node-aware
tier: 2
nature: reasoning / orchestrated
required_tools:
- SoC Integration Tool
required_skills:
- Hierarchical Integration Skill
- Timing Closure Skill
- QoR Reporting Skill
- PDK Binding Skill
- Design Review Skill
- Provenance Skill
supported_problems:
- hierarchical chip assembly
- IP integration
- timing-budget partitioning
- NoC/interconnect topology
- block-boundary abstraction
emits: Common Design Envelope
```

# Hierarchical and SoC Integration Agent

**Purpose** — Assemble a hierarchical SoC from blocks/IP, partition top-level
budgets, and define the on-chip interconnect so large designs close hierarchically.

**Responsibilities** — Design hierarchy assembly; IP/block integration and
interface stitching; timing/power/area budget partitioning to blocks; interface
(bus/NoC) topology definition; block abstract (ILM/boundary) management;
feedthrough and top-level pin planning.

**Supported problems** — Hierarchical chip assembly; IP integration; timing-budget
partitioning; NoC/interconnect topology; block-boundary abstraction.

**Required tools** — SoC Integration Tool (hierarchy assembly + budget
partitioning; OpenROAD/Yosys hierarchical flow, gdsfactory/KLayout assembly).

**Required skills** — Hierarchical Integration Skill, Timing Closure Skill, QoR
Reporting Skill, PDK Binding Skill, Design Review Skill, Provenance Skill.

**Inputs** — Block-level architecture and per-block budgets (Common Design
Envelope); IP/block Common Design Envelopes and abstracts; PDK Binding.

**Outputs** — SoC hierarchy and integration plan; per-block partitioned budgets;
interconnect topology; boundary constraints/abstracts per block. All outputs
conform to the Common Design Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope naming the hierarchy, the
partitioned per-block budgets (with units), the interconnect topology, and the
boundary constraints each block agent consumes.

**Validation gates**

- Partitioned block budgets sum within the top-level budget.
- Every interface fully specified and consistent across blocks.
- A `functional_padframe` boundary must pass the packaged `pad_connectivity`
  preflight before physical implementation: every contracted signal pad exists,
  its signal terminal is connected to the expected net, and no functional output
  is driven directly by a core cell without the required pad boundary.
- Boundary constraints handed to block agents.
- Node binding and provenance present.

## Position in the flow

Bridges architecture (Microarchitecture and PPA Exploration Agent) and block-level
implementation: it takes the top-level budget, partitions it, and hands each block
agent a closable boundary. It complements — not replaces — the flat block flow for
large, hierarchical production SoCs.

## Node-Specific Notes

Node parameters (library, corners, metal stack) are consumed from `pdk_binding`.

### sky130 (validation baseline)

- `pdk`: `sky130A`; `stdcell_library`: `sky130_fd_sc_hd`; corners tt/ss/ff;
  metal stack `li1`, `met1`–`met5` used for top-level interconnect planning.

### <future node> (stub)

- `pdk`, `stdcell_library`, `corners`, `metal_stack`: _from binding_.
