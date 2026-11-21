## Overview

Node-aware logic synthesis agent that maps RTL to a gate-level netlist against the active PDK standard-cell library. It infers synthesis intent from natural language, consumes the PDK Binding (Liberty, don't-use, units, corners), drives Yosys + ABC, and extracts gate-level QoR (area, cell count, estimated timing) reported directly in chat. Validated on SkyWater sky130 (sky130_fd_sc_hd).

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/logic-synthesis/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/ghdl/synth:beta`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`chip-logic-synthesis` is defined in [tool.yaml](tools/logic-synthesis/tool.yaml). Its Docker build context is `tools/logic-synthesis/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/logic-synthesis/Dockerfile --tag chip-logic-synthesis:local tools/logic-synthesis
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Logic Synthesis Agent
flow_stage: C - Synthesis, DFT, Constraints
node_awareness: node-aware
tier: 1
nature: reasoning / orchestrated
required_tools:
- Logic Synthesis Tool
required_skills:
- Timing Closure Skill
- QoR Reporting Skill
- PDK Binding Skill
- Design Review Skill
- Provenance Skill
supported_problems:
- generic synthesis
- technology mapping
- PPA-driven optimization
- retiming
- gate-level QoR estimation
emits: Common Design Envelope
```

# Logic Synthesis Agent

**Purpose** — Map RTL to a gate-level netlist against the active node's
standard-cell library, optimizing for the PPA target budget.

**Responsibilities** — Elaboration; technology mapping; timing/area/power-driven
optimization; constraint-aware synthesis; netlist QoR reporting.

**Supported problems** — Generic and technology-mapped synthesis; PPA-driven
optimization; retiming; gate-level QoR estimation.

**Required tools** — Logic Synthesis Tool (Yosys + ABC).

**Required skills** — Timing Closure Skill, QoR Reporting Skill, PDK Binding
Skill, Design Review Skill, Provenance Skill.

**Inputs** — RTL; SDC; PDK Binding (Liberty, don't-use lists, wireload/units,
corners).

**Outputs** — Gate-level netlist; area/cell-count/estimated-timing QoR;
constraint-map report. All outputs conform to the Common Design Envelope and
Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope with the mapped netlist,
Liberty/corner used, estimated PPA (with units) against the target budget, and
don't-use compliance so the PPA Signoff and Design Review Agent can review without
re-running.

**Validation gates**

- Netlist maps only to allowed library cells (don't-use respected).
- Estimated timing/area reported against the budget, with units.
- No combinational loops.
- Node binding and provenance present on every output.

## Node-Specific Notes

Node constants (library name, don't-use cells, buffer/inverter cell names, units,
default corner) are consumed from the `pdk_binding` field of the Common Design
Envelope, never hard-coded in reasoning. Switching nodes is a binding change only.

### sky130 (validation baseline)

- `pdk`: `sky130A`
- `stdcell_library`: `sky130_fd_sc_hd` (high density; `hs`/`ms`/`ls`/`hdll`
  variants selectable via the binding)
- Default synthesis corner: `tt_025C_1v80`; slow signoff estimate `ss_100C_1v60`
- Liberty: `sky130_fd_sc_hd__<corner>.lib` (referenced by the binding)
- Typical don't-use guidance for sky130_fd_sc_hd: exclude very-low-drive
  clock-gate/hold-buffer variants unless explicitly required (the exact list is
  supplied by the binding, not hard-coded here)
- Units from Liberty: capacitance in pF, time in ns, area in μm²

### <future node> (stub)

- `pdk`: _to be provided by the PDK Binding and Node Management Agent_
- `stdcell_library`, corners, Liberty, don't-use, units: _from binding_
- No agent-logic changes required to adopt a new node.
# Acceptance consistency

The default worker reconciles the native mapping verdict with the declared
progress acceptance contract. A blocking acceptance/evidence alignment finding
changes an otherwise passing result to `not_assessable`, retaining the original
execution verdict and progress evidence. Measured mapping QoR remains available,
but no area target or timing acceptance is invented. A native mapping failure
remains a failure.
