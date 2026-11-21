## Overview

Node-aware cts agent driven by the OpenROAD tool set, consuming the PDK Binding and emitting a Common Design Envelope. Validated on SkyWater sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/cts/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`cts` is defined in [tool.yaml](tools/cts/tool.yaml). Its Docker build context is `tools/cts/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Clock-tree characterization requires `wire_rc_clock_layer`; `wire_rc_signal_layer` is optional. Both resolve from caller parameters, then `pdk_binding.tool_policy.cts`, then `pdk_binding.routing_layers`, and are applied before native CTS. No missing clock model is replaced with a zero-RC assumption. Use at least two genuinely clocked sinks for a positive smoke test: TritonCTS may skip a single-sink clock, and a skipped clock must not be reported as buffered. A passing worker result requires actual buffered-clock, insertion-delay and inserted-cell evidence.

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/cts/Dockerfile --tag chip-cts:local tools/cts
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Clock Tree Synthesis (CTS) Agent
flow_stage: D - Physical Implementation
node_awareness: node-aware
tier: 1
nature: reasoning / orchestrated
required_tools:
- CTS Tool
required_skills:
- Timing Closure Skill
- PDK Binding Skill
- QoR Reporting Skill
- Provenance Skill
supported_problems:
- CTS
- skew balancing
- clock-buffer sizing
- useful-skew scheduling
emits: Common Design Envelope
```

# Clock Tree Synthesis (CTS) Agent

**Purpose** — Synthesize a balanced clock tree meeting skew and latency targets.

**Responsibilities** — Clock-tree topology synthesis; buffer/inverter insertion from
node cells; skew/latency optimization; post-CTS legalization.

**Supported problems** — CTS; skew balancing; clock-buffer sizing; useful-skew
scheduling.

**Required tools** — CTS Tool (OpenROAD TritonCTS).

**Required skills** — Timing Closure Skill, PDK Binding Skill, QoR Reporting Skill,
Provenance Skill.

**Inputs** — Placed DEF; SDC (clocks); PDK Binding (clock buffers/inverters).

**Outputs** — Clock-tree DEF; skew/latency/insertion-delay report; clock-buffer
inventory. All outputs conform to the Common Design Envelope and Mandatory Output
Fields.

**Handoff contract** — Emit a Common Design Envelope reporting achieved skew and
insertion delay (with units), buffers used, and clock structure. Insertion delay is
reported on every run; it is compared against a budget only when one is declared.

**Validation gates**

- Skew reported against its target.
- Insertion delay ALWAYS measured and reported. It gates **only** when an
  `insertion_delay_budget_ns` is declared; absent a budget it is recorded as
  `not_gating` with the measured number, which is neither a pass nor a waiver.
  A run that could not measure it at all is `not_assessable` -- also never a pass.
- Only node clock cells used.
- Placement legal post-CTS.
- Node binding and provenance present.

## Node-Specific Notes

Clock buffers, Liberty, and LEF are consumed from `pdk_binding`.

### sky130 (validation baseline)

- `pdk`: `sky130A`; clock buffer e.g. `sky130_fd_sc_hd__clkbuf_4` (from the binding)
- Engine OpenROAD TritonCTS; `engine_class: oss`

### <future node> (stub)

- `pdk`, `clock_buffers`, `liberty`, `tech_lef`, `cell_lef`: _from binding_.
