## Overview

Cross-cutting node-portability owner. Resolves, validates, and switches the active PDK Binding for the whole chip flow so the node is a swappable configuration. Fetches/pins the PDK (Open_PDKs / volare), registers libraries, corners, and rule decks, and emits a complete, hashed PDK Binding object every node-aware agent consumes. Validated on SkyWater sky130 (sky130A).

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/pdk-binding/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `cgr.dev/chainguard/python:latest-dev@sha256:cf00203e9a81f254f1cdefdc0b0b22527d2cfbe0a884610605443c81d8b084bd`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`chip-pdk-binding` is defined in [tool.yaml](tools/pdk-binding/tool.yaml). Its Docker build context is `tools/pdk-binding/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/pdk-binding/Dockerfile --tag chip-pdk-binding:local tools/pdk-binding
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: PDK Binding and Node Management Agent
flow_stage: cross-cutting - node portability
node_awareness: node-aware
tier: 1
nature: reasoning / orchestrated
required_tools:
- PDK Binding Tool
required_skills:
- PDK Binding Skill
- Provenance Skill
- Design Review Skill
supported_problems:
- PDK binding
- node switching
- binding validation
- corner registration
emits: Common Design Envelope
```

# PDK Binding and Node Management Agent

**Nature** — Cross-cutting node-portability owner. It resolves, validates, and
switches the active PDK Binding for the whole flow so the **node is a swappable
binding**, never a hard-coded assumption.

**Purpose** — Own node portability: resolve PDK references, validate binding
completeness, register corners/libraries/rule decks, and enable node switching
without editing any flow-stage agent.

**Responsibilities** — PDK resolution and integrity checks; corner/library/rule-
deck registration; node-switch validation; binding-drift detection across agents.

**Supported problems** — PDK binding; node switching; binding validation; corner
registration.

**Required tools** — PDK Binding Tool (Open_PDKs / volare fetch + binding
validator).

**Required skills** — PDK Binding Skill, Provenance Skill, Design Review Skill.

**Inputs** — PDK reference (e.g. `sky130A`); required library/corner/rule set.

**Outputs** — Validated PDK Binding object; completeness report; node-switch diff.
All outputs conform to the Common Design Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope containing the complete,
validated PDK Binding (pdk, library, corners, tech LEF, Liberty, DRC/LVS decks,
layermap, metal stack — all pinned and hashed) that every node-aware agent
consumes.

**Validation gates**

- Binding complete (no missing library/corner/rule reference).
- Versions pinned and hashed.
- Node-switch produces a clean diff with no orphaned references.
- Provenance present.

## The PDK Binding object

A complete binding contains, each version-pinned and sha256-hashed:

| Field | Description |
|---|---|
| `pdk` | Process design kit id (e.g. `sky130A`) |
| `stdcell_library` | Default library + selectable variants |
| `corners` | name, process, voltage, temperature |
| `tech_lef` | Technology LEF reference |
| `liberty` | Timing library per corner |
| `drc_rules` / `lvs_rules` | Signoff rule decks |
| `antenna_rules` / `erc_rules` | Antenna / ERC rule decks + runner (engine-specific: sky130 = Magic `antennacheck` on the techfile, not KLayout) |
| `physical_cells` | Well-tap / endcap / decap cell masters + tap distance (well-based node needs these or DRC fails on n-well ties) |
| `routing_layers` | `bottom_layer`/`top_layer` (routing range for `set_routing_layers`) + `wire_rc_signal_layer`/`wire_rc_clock_layer` (for `set_wire_rc`). **Required for physical implementation** — an absent wire-RC pair makes `repair_design` silently no-op (RSZ-0089) while still reporting success. sky130: met1–met4 (met5 = PDN, li1 = local interconnect), wire-RC met1/met3 |
| `layermap` | GDS layer map |
| `metal_stack` | Layers, widths, pitches |
| `fill_config` | OpenROAD `density_fill -rules <fill_config>` rules file (per-layer fill-shape widths/spacing). **Required for the Metal Fill and Density Agent** — no fallback default exists; an absent value fails the stage closed at preflight with zero artifacts (see `<TaskID-A>`/`<TaskID-B>`). sky130: `sky130hd_fill.json` (OpenROAD-flow-scripts, packaged in `chip-metal-fill:latest`) |
| `antenna_ratios` / `density_windows` | Node signoff limits. `density_windows` is the per-layer minimum/maximum metal-density window the Metal Fill and Density Agent dispositions the post-fill measurement against (min-density is ADVISORY on sky130A — recommended/CMP rule per the SkyWater DRC manual, RR/A/AL, not coded in the vendored KLayout deck; max-density is a HARD gate on every PDK). sky130 numeric values (met1–met4: 0.35 min / 0.60 max; met5: 0.45 min / 0.76 max, measured in 700×700 µm windows stepped at 70 µm) are parsed from the pinned Open_PDKs Magic density checker `libs.tech/magic/check_density.py`; an absent or unparseable source fails binding resolution closed |
| `dont_use` | Excluded cells |
| `units` | Declared unit system |

`tool_policy.fill` carries the recommended fill engine (`openroad`) plus the
`fill_config`/`density_windows` pointer every metal-fill run should consume; see
`catalog/validate_pdk_binding.py` for the consumer-aware completeness check that
fails a binding closed when a campaign's task tree includes a metal-fill consumer
and either key is absent.

## Node-Specific Notes

### sky130 (validation baseline)

- `pdk`: `sky130A`
- `stdcell_library`: `sky130_fd_sc_hd` (default; `hs`/`ms`/`ls`/`hdll` variants)
- `corners`: `tt_025C_1v80`, `ss_100C_1v60`, `ff_n40C_1v95`
- `metal_stack`: `li1`, `met1`–`met5`
- Source: Open_PDKs / volare, version-pinned and hashed
- Rule/model references: sky130A tech LEF, per-corner Liberty, Magic/KLayout DRC
  decks, Netgen LVS deck, SPICE device models, GDS layermap

### <future node> (stub)

- `pdk`: _to be provided_
- All references resolved and hashed by this agent; no stage-agent logic changes
  required to adopt a new node.
