# chip-antenna-erc — Antenna and ERC Agent

## Overview

Node-aware Antenna and ERC agent driven by KLayout, consuming the PDK Binding (antenna ratios / ERC rules) and emitting a Common Design Envelope. Validated on SkyWater sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/antenna-erc/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`chip-antenna-erc` is defined in [tool.yaml](tools/antenna-erc/tool.yaml). Its Docker build context is `tools/antenna-erc/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/antenna-erc/Dockerfile --tag chip-antenna-erc:local tools/antenna-erc
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes


## Qualified Magic runtime

The Services image in `services-deployment.json` installs upstream Magic
**8.3.693**, pinned to commit `9fd4ee57386c08346b20389a55e4eb9d32553979`.
The canonical Containerfile verifies the archive SHA-256 and builds with
`make -j1`. The published image preserves the prior worker and other engines.
Native version/current-SKY technology loading and the retained bounded KLayout
antenna positive/negative controls were verified serially on 2026-11-16.
This does not extend antenna-rule coverage or activate the staged App candidate.

Node-aware **Antenna and Electrical-Rule-Check (ERC)** agent. Runs a **KLayout**
antenna/ERC deck on a GDS/OASIS/DEF layout, parses the KLayout report database
(`.lyrdb`), and reports the violation count with a per-check breakdown and waiver
adjudication.

- **Engine:** KLayout (`klayout -b -r <deck> -rd input=<layout> -rd report=<db>`)
- **Node awareness:** node-aware — antenna ratios / ERC rules come from the PDK
  Binding (`antenna_rules` / `erc_rules`).
- **Output:** Common Design Envelope (`/output/final_results.json`).

## Scenarios

| Scenario | Purpose |
|---|---|
| `antenna_check` | Run the antenna deck, count per-check violations, adjudicate waivers, emit a verdict. |
| `erc_check` | Alias of `antenna_check` for an ERC deck. |

## Signoff discipline

Zero un-waived violations to sign off. Every waiver must name a `rule`, an
`owner`, and a `justification`. The deck version is recorded in `provenance`.
