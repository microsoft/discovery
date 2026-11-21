# chip-dft - Design-for-Test Agent

## Overview

Node-aware Design-for-Test agent driven by pinned Yosys. Performs honest sequential-element classification, binding-approved scan insertion with functional equivalence, scan-aware stuck-at ATPG, and structural plus simulated scan-chain integrity. Emits a hashed Common Design Envelope. Validated on sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/dft/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/library/debian:12-slim@sha256:5ae3c39ebd15e229dcedd5cee596b2497182493d41ff162e824ba13fc1b2b867`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`chip-dft` is defined in [tool.yaml](tools/dft/tool.yaml). Its Docker build context is `tools/dft/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/dft/Dockerfile --tag chip-dft:local tools/dft
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes


Node-aware **Design-for-Test (DFT)** agent. The `1.1.0` tool pins OSS CAD Suite
`2026-08-25` (Yosys `0.68+130`) and fails its image build unless SAT,
equivalence, simulation, Liberty mapping, and tolerant full-Liberty import probes
execute successfully.

Structural scan populations and chain lengths count storage bits. A vector
Yosys register contributes its `Q` width, not one cell instance; latch and
asynchronous-reset hazard populations use the same bit basis.

- **Engine:** pinned Yosys for structural analysis, scan insertion, equivalence,
	simulation, and deterministic SAT-based stuck-at ATPG.
- **Node awareness:** scan mappings, Liberty, and functional models come from the
	PDK Binding; no node cell is hard-coded.
- **Output:** Common Design Envelope plus retained reports, waveforms, and hashed
	JSON evidence.

## Scenario

| Scenario | Purpose |
|---|---|
| `scan_analysis` | Count all sequential elements, classify latches/async/gated hazards, plan domain-local chains, and estimate scan coverage with an honest denominator. |
| `scan_insert` | Validate Liberty mappings, partition by clock/reset/power, enforce chain length, insert frozen boundary ports, check the netlist, and prove functional equivalence. |
| `fault_atpg` | Generate X-aware SAT patterns for gate-output stuck-at faults, grade and compact them, and retain complete hashed evidence. |
| `scan_chain_integrity` | Trace every chain and run a bit-exact known pattern through the actual emitted netlist using functional or Liberty-derived models. |

## Closure rules

- Scan insertion does not pass without a valid binding-owned mapping, zero
	structural errors, a valid terminal scan-out path, and proven scan-disabled
	functional equivalence.
- ATPG is exhaustive by default. `max_faults` is a diagnostic sample. A
	deterministic `fault_shard_count`/`fault_shard_index` shard must be aggregated
	with every other shard before signoff. Sampling, incomplete grading, or any
	aborted fault prevents a clean pass.
- Scan integrity requires both structural tracing and emitted-netlist simulation.
	Every top-level input is driven, output is sampled after the measured chain
	latency, and every chain must match bit-for-bit.
- The ATPG engine is a transparent full-scan stuck-at floor. It does not claim
	production compression, transition/at-speed coverage, analog test, or MBIST.

## Scope honesty

Structural scan analysis reports a coverage *estimate*. The `fault_atpg`
scenario reports measured stuck-at fault coverage separately, and
`scan_chain_integrity` reports actual emitted-netlist shift results. Structural
traces, ideal models, samples, and isolated shards are never promoted to closure.
