## Overview

Node-aware logical equivalence checking (LEC) agent that proves functional equivalence across transformations (RTL to netlist, netlist to netlist after DFT/CTS/ECO) as a first-class signoff gate. Consumes the PDK Binding (cell functional models), drives Yosys equivalence / eqy, and reports an equivalence verdict. Validated on SkyWater sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/lec/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/library/debian:12-slim@sha256:5ae3c39ebd15e229dcedd5cee596b2497182493d41ff162e824ba13fc1b2b867`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`chip-lec` is defined in [tool.yaml](tools/lec/tool.yaml). Its Docker build context is `tools/lec/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/lec/Dockerfile --tag chip-lec:local tools/lec
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Logical Equivalence Checking (LEC) Agent
flow_stage: C - Synthesis, DFT, Constraints
node_awareness: node-aware
tier: 1
nature: reasoning / orchestrated
required_tools:
- LEC Tool
required_skills:
- Equivalence Checking Skill
- Verification and Validation Skill
- PDK Binding Skill
- Provenance Skill
supported_problems:
- RTL-to-netlist equivalence
- netlist-to-netlist equivalence
- post-ECO/post-DFT equivalence
- key-point mapping
emits: Common Design Envelope
```

# Logical Equivalence Checking (LEC) Agent

**Purpose** — Prove functional equivalence across transformations (RTL↔netlist,
netlist↔netlist post-DFT/CTS/ECO) as a first-class signoff gate.

**Responsibilities** — Combinational/sequential equivalence checking; key-point
mapping; non-equivalence diagnosis; transformation (scan/CTS/ECO) equivalence
signoff; black-box/abstraction management.

**Supported problems** — RTL-to-netlist equivalence; netlist-to-netlist
equivalence; post-ECO/post-DFT equivalence; key-point mapping.

**Required tools** — LEC Tool (Yosys equivalence / `eqy` with node cell models).

**Required skills** — Equivalence Checking Skill, Verification and Validation
Skill, PDK Binding Skill, Provenance Skill.

**Inputs** — Reference and revised designs (RTL/netlist); PDK Binding (cell
functional models); mapping/constraints.

**Outputs** — Equivalence verdict; key-point mapping report; non-equivalence
diagnosis; unmapped-point list. All outputs conform to the Common Design Envelope
and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope with the equivalence verdict,
key-point mapping, any non-equivalences with diagnosis, and the cell models used
so the transformation is trusted without re-proving.

**Validation gates**

- All key points mapped (or unmapped points justified).
- Equivalence proved or non-equivalence diagnosed.
- Cell models from the binding.
- Node binding and provenance present.

## Relationship to sibling agents

The Formal Verification Agent proves *properties*; this agent proves *equivalence*
between two design representations across synthesis, scan insertion, CTS, and ECO
— a mandatory signoff gate judged by the PPA Signoff and Design Review Agent.

## Node-Specific Notes

Cell functional models are consumed from `pdk_binding`, never hard-coded.

### sky130 (validation baseline)

- `pdk`: `sky130A`
- `stdcell_library`: `sky130_fd_sc_hd` (functional cell models for mapping)
- No agent-logic changes required to adopt a new node.

### <future node> (stub)

- `pdk`, `stdcell_library`, `cell_models`: _from binding_.
