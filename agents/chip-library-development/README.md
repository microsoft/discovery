## Overview

Node-aware library development agent. Characterizes standard cells, macros, and hard IP for the target node and generates their physical/timing views: Liberty (CCS and NLDM) timing/power models, LEF abstracts, and DEF views. It infers the intent from natural language, consumes the PDK Binding (SPICE models, corners, layers), drives ngspice + Magic/KLayout, and reports library QA directly in chat. Validated on SkyWater sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/library-characterization/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/library/debian:12-slim`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`chip-lib-characterize` is defined in [tool.yaml](tools/library-characterization/tool.yaml). Its Docker build context is `tools/library-characterization/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/library-characterization/Dockerfile --tag chip-library-development:local tools/library-characterization
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Library Development Agent
flow_stage: G - Library and IP Enablement
node_awareness: node-aware
tier: 2
nature: reasoning / orchestrated
required_tools:
- Library Characterization Tool
required_skills:
- Library Characterization Skill
- Circuit Characterization Skill
- PDK Binding Skill
- QoR Reporting Skill
- Provenance Skill
supported_problems:
- Liberty CCS characterization
- Liberty NLDM characterization
- LEF abstract creation
- DEF view creation
- macro/IP library assembly
- multi-corner library QA
emits: Common Design Envelope
```

# Library Development Agent

**Purpose** — Characterize and generate the physical/timing **views** of standard
cells, macros, and hard IP for the target node: Liberty timing/power models (CCS
and NLDM), physical LEF abstracts, and DEF views.

**Responsibilities** — Timing/power/noise characterization by SPICE sweeps
(input-slew × output-load grids); Liberty generation (CCS current-source and NLDM
table models, plus optional CCS-noise/receiver models); LEF abstract creation
(pins, obstructions, antenna, layers) from layout; DEF view generation for macros/
blocks; multi-corner library assembly; library QA/consistency checks.

**Supported problems** — Liberty CCS characterization; Liberty NLDM
characterization; LEF abstract (view) creation; DEF view creation; macro/IP
library assembly; multi-corner library QA.

**Required tools** — Library Characterization Tool (ngspice-based characterization
+ Liberty writer; Magic/KLayout LEF/DEF abstract extraction).

**Required skills** — Library Characterization Skill, Circuit Characterization
Skill, PDK Binding Skill, QoR Reporting Skill, Provenance Skill.

**Inputs** — Cell/macro SPICE netlist and layout (GDS); PDK Binding (SPICE device
models, corners, layers, extraction rules); characterization grid (slews, loads)
and arc/pin definitions.

**Outputs** — Liberty (`.lib`) per corner with CCS and/or NLDM models; LEF
abstract (`.lef`); DEF view; characterization QA report; library manifest. All
outputs conform to the Common Design Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope naming the characterized arcs,
model type (CCS/NLDM), corners, characterization grid, and references to the
generated Liberty/LEF/DEF views so downstream synthesis, STA, and physical agents
can consume them without re-characterizing.

**Validation gates**

- Every timing arc characterized over the declared slew/load grid.
- CCS/NLDM models monotonic and physically plausible.
- LEF pins/obstructions/antenna consistent with layout; DEF matches the abstract.
- Corners and node models from the binding.
- Units and provenance present on every output.

## Position in the flow

The Library Development Agent produces the **views every node-aware agent
consumes**: Liberty feeds the Logic Synthesis, STA, Power/IR, and CTS agents; LEF
feeds Floorplanning, Placement, and Routing; DEF feeds macro-aware physical
stages. It complements the PDK Binding and Node Management Agent — the PDK agent
registers vendor views, while this agent *creates* views for new/custom cells and
macros.

## Node-Specific Notes

Node constants (SPICE model names, corners, layer names, default supply,
characterization defaults) are consumed from the `pdk_binding` field, never
hard-coded. Switching nodes is a binding change only.

### sky130 (validation baseline)

- `pdk`: `sky130A`
- SPICE models: `sky130_fd_pr` primitive device models (referenced by the binding)
- Corners: `tt_025C_1v80`, `ss_100C_1v60`, `ff_n40C_1v95`
- Default supply for characterization: 1.80 V nominal (from the corner)
- Layers for LEF/DEF abstracts: `li1`, `met1`–`met5` (from the metal stack)
- Reference library for cross-check: `sky130_fd_sc_hd` (vendor Liberty/LEF)
- Units: time in ns, capacitance in pF, area in μm² (from Liberty)

### <future node> (stub)

- `pdk`: _to be provided by the PDK Binding and Node Management Agent_
- SPICE models, corners, layers, units: _from binding_
- No agent-logic changes required to adopt a new node.
