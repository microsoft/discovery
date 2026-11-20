## Overview

Node-aware multi-corner static timing analysis agent. Runs OpenSTA on a gate-level netlist with SDC and SPEF, reports WNS/TNS per corner, diagnoses violating paths, and drives timing closure. Consumes the PDK Binding (Liberty, corners). Validated on SkyWater sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/sta/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`sta` is defined in [tool.yaml](tools/sta/tool.yaml). Its Docker build context is `tools/sta/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/sta/Dockerfile --tag chip-sta:local tools/sta
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Static Timing Analysis (STA) Agent
flow_stage: E - Timing, Power, Physical Signoff
node_awareness: node-aware
tier: 1
nature: reasoning / orchestrated
required_tools:
- STA Tool
required_skills:
- Timing Closure Skill
- QoR Reporting Skill
- PDK Binding Skill
- Design Review Skill
- Provenance Skill
supported_problems:
- setup/hold signoff
- multi-corner multi-mode STA
- path-based analysis
- closure diagnosis
emits: Common Design Envelope
```

# Static Timing Analysis (STA) Agent

**Purpose** — Perform multi-corner static timing analysis and drive timing closure.

**Responsibilities** — Multi-corner/multi-mode STA; setup/hold analysis; slack
reporting; critical-path diagnosis; ECO guidance.

**Supported problems** — Setup/hold signoff; MCMM STA; path-based analysis;
closure diagnosis.

**Required tools** — STA Tool (OpenSTA).

**Required skills** — Timing Closure Skill, QoR Reporting Skill, PDK Binding Skill,
Design Review Skill, Provenance Skill.

**Inputs** — Netlist; SDC; SPEF (from extraction); PDK Binding (Liberty, corners).

**Outputs** — WNS/TNS per corner; violating-path reports; setup/hold verdict; ECO
hints. All outputs conform to the Common Design Envelope and Mandatory Output
Fields.

**Handoff contract** — Emit a Common Design Envelope with WNS/TNS (with units) per
corner, pass/fail, worst paths, and the corner/Liberty set used.

**Validation gates**

- Setup and hold evaluated at all signoff corners.
- WNS/TNS reported with units.
- Hold not sacrificed for setup.
- Node binding and provenance present.

## Node-Specific Notes

Liberty and corners are consumed from `pdk_binding`, never hard-coded.

### sky130 (validation baseline)

- `pdk`: `sky130A`; `stdcell_library`: `sky130_fd_sc_hd`
- Corners: `tt_025C_1v80`, `ss_100C_1v60`, `ff_n40C_1v95` (Liberty per corner)
- Engine: OpenSTA (bundled in the OpenROAD image); `engine_class: oss`

### <future node> (stub)

- `pdk`, `stdcell_library`, `liberty`, `corners`: _from binding_.
