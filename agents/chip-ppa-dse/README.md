## Overview

Node-aware PPA / design-space exploration agent that searches recipe/parameter space to optimize power/performance/area against the target budget using deterministic multi-objective search and Pareto bookkeeping over real flow runs. Consumes the PDK Binding and reports the Pareto front and recommended recipe. Validated on SkyWater sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/dse-optimization/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `cgr.dev/chainguard/python:latest-dev@sha256:cf00203e9a81f254f1cdefdc0b0b22527d2cfbe0a884610605443c81d8b084bd`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`chip-dse-optimization` is defined in [tool.yaml](tools/dse-optimization/tool.yaml). Its Docker build context is `tools/dse-optimization/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/dse-optimization/Dockerfile --tag chip-ppa-dse:local tools/dse-optimization
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: PPA and Design-Space Exploration Agent
flow_stage: H - Optimization and Analytics
node_awareness: node-aware
tier: 2
nature: reasoning / orchestrated
required_tools:
- DSE Optimization Tool
required_skills:
- Design-Space Exploration Skill
- QoR Reporting Skill
- Timing Closure Skill
- PDK Binding Skill
- Design Review Skill
- Provenance Skill
supported_problems:
- synthesis/PnR recipe optimization
- multi-objective PPA search
- parameter sweeps
- Pareto analysis
emits: Common Design Envelope
```

# PPA and Design-Space Exploration Agent

**Purpose** — Search recipe/parameter space to optimize power/performance/area
against the target budget — a deterministic (non-learning) multi-objective
autotuner over the flow.

**Responsibilities** — Recipe/parameter sweep design; multi-objective (PPA)
search; Pareto-front construction; sensitivity ranking of knobs; best-recipe
recommendation. Learning-based surrogates remain Tier 3; this agent performs
deterministic search and bookkeeping only.

**Supported problems** — Synthesis/PnR recipe optimization; multi-objective PPA
search; parameter sweeps; Pareto analysis.

**Required tools** — DSE Optimization Tool (parameterized sweeps + Pareto
bookkeeping over Yosys/OpenROAD/OpenSTA runs).

**Required skills** — Design-Space Exploration Skill, QoR Reporting Skill, Timing
Closure Skill, PDK Binding Skill, Design Review Skill, Provenance Skill.

**Inputs** — Flow recipe and tunable knobs; PPA target budget; PDK Binding; per-run
Common Design Envelopes (QoR).

**Outputs** — Explored configurations; Pareto front; knob-sensitivity ranking;
recommended recipe with PPA vs budget. All outputs conform to the Common Design
Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope naming the search space,
explored points, the Pareto front, and the recommended recipe (PPA with units vs
budget) so the choice is reproducible and reviewable without re-running the sweep.

**Validation gates**

- Search space and objectives explicit.
- Every reported point traces to a real run's Common Design Envelope.
- Pareto front reproducible; recommended recipe measured against the budget.
- Node binding and provenance present.

## Scope

Deterministic search only. ML-driven PPA surrogates are explicitly Tier 3 and out
of scope for v1; this agent optimizes by running and bookkeeping real flow
configurations, never by predicting QoR from a learned model.

## Node-Specific Notes

Node parameters (library, corners) are consumed from `pdk_binding`.

### sky130 (validation baseline)

- `pdk`: `sky130A`; `stdcell_library`: `sky130_fd_sc_hd`; corners tt/ss/ff.

### <future node> (stub)

- `pdk`, `stdcell_library`, `corners`: _from binding_.
# Source-validated search

Each point must provide a mounted local `source_cde` JSON file and its exact
file-byte `source_cde_sha256`. The source must have completed with validation
`pass`, a closed progress gate, and no blocking alignment finding. Every claimed
metric must equal a finite recorded source metric; estimated/model-authored
objectives are not accepted as measurements. Unavailable/open upstream evidence
blocks recommendations as `not_assessable`; integrity or metric mismatches fail.
No over-budget fallback is emitted as a recommended recipe.

This is deterministic search over supplied measurements, not a native PPA-flow
launcher. File hashes and CDE contract checks do not cryptographically attest the
originating Services job; callers must retain and independently validate the
native source execution evidence. Synthetic unit CDEs are unit fixtures only.
