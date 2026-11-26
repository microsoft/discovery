# chip-gds-assembly — GDS Assembly and Tapeout Packaging Agent

## Overview

Node-aware GDS Assembly and Tapeout Packaging agent driven by KLayout, consuming the PDK Binding (cell GDS, layer map) and emitting a Common Design Envelope with the final GDSII. Validated on SkyWater sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/gds-assembly/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`gds-assembly` is defined in [tool.yaml](tools/gds-assembly/tool.yaml). Its Docker build context is `tools/gds-assembly/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/gds-assembly/Dockerfile --tag chip-gds-assembly:local tools/gds-assembly
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes


Node-aware **GDS Assembly and Tapeout Packaging** agent. Streams a routed/filled
DEF (+ tech LEF + standard-cell GDS) into the **final GDSII** via **KLayout**, or
merges multiple GDS files into one top-level GDS. This is the tapeout deliverable.

- **Engine:** KLayout (Python API — DEF import + cell-GDS merge + GDS write)
- **Node awareness:** node-aware — standard-cell GDS and the layer map come from
  the PDK Binding (`cell_gds`, `klayout_tech`).
- **Output:** Common Design Envelope (`/output/final_results.json`), including the
  final GDSII in `results/`.

## Scenarios

| Scenario | Purpose |
|---|---|
| `streamout` | DEF → GDSII, merging standard-cell GDS for real geometry; report top-cell / cell / layer stats. |
| `merge` | Merge multiple GDS files (macro/IP + top) into one. |

## Tapeout discipline

The final GDSII must pass DRC and LVS on the assembled GDS before it is
tapeout-ready. This agent produces the deliverable; the DRC and LVS agents own the
gates.
