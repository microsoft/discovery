# chip-physical-integrity-checker

## Overview

Node-aware physical-integrity aggregation and deterministic OpenROAD checking agent. It never passes a required check without evidence and emits a Common Design Envelope with per-check verdicts and critical-violation totals.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/physical-integrity-checker/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`physical-integrity-checker` is defined in [tool.yaml](tools/physical-integrity-checker/tool.yaml). Its Docker build context is `tools/physical-integrity-checker/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/physical-integrity-checker/Dockerfile --tag chip-physical-integrity-checker:local tools/physical-integrity-checker
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes


Node-aware physical-integrity signoff aggregator with optional deterministic
OpenROAD/OpenDB checks. The `integrity_check` scenario evaluates disconnected
pins, long wires, netlist `assign` statements, unmapped cells, routing DRC,
timing setup/hold, maximum slew/capacitance, PDN violations, and illegal
placement overlaps.

Evidence may be supplied as structured metrics or report files. When an ODB/DEF
and netlist are supplied, the tool runs OpenROAD Tcl and derives deterministic
checks where possible. A required check with absent or unparseable evidence is
`not_assessable`, never `pass`. A violation in a required check fails the run.
Findings in non-required checks remain visible; a restricted check-set pass is
not full physical signoff. Unsupported native wire-length queries leave that
check unmeasured rather than returning a false zero. Top-level terminal
connectivity is checked through its actual OpenDB net. Native Tcl failures
retain a bounded verbatim log tail in the persisted failure evidence.
For DEF input, the technology LEF is read with both technology and library/SITE
sections enabled, before cell LEFs and DEF. Restricting that read to `-tech`
can discard the supplied row sites even when the correct SITE exists in the
unmodified PDK file.
Fresh native measurements are retained if a later placement check exits
nonzero, together with the engine error; that error cannot become a clean pass.
Liberty cell names may be quoted or unquoted. Both forms are compared as the
same identifier against instantiated cells, without exempting unknown masters.
Services mounts must use the exact URI returned by `GetResourceContext`.

## Inputs

- `odb` or `def_file`, plus PDK-bound `tech_lef`/`cell_lef` for DEF input
- optional `netlist`, `liberty`, report paths, and structured `metrics`
- `required_checks` to select mandatory checks (defaults to all supported checks)
- `long_wire_threshold_um`, resolved by caller > `tool_policy.physical_integrity`
  > built-in default
- `pdk_binding`, including node references and tool policy

## Outputs

- `/output/final_results.json`: 14-field Common Design Envelope
- `/output/SUMMARY.md`: concise outcome
- `/output/results/`: structured per-check data
- `/output/reports/`: human-readable reports
- `/output/logs/`: Tcl, command, and verbatim engine logs

Every file referenced by the envelope is SHA-256 hashed in provenance. Missing
engines, inputs, PDK references, or required evidence fail closed.
