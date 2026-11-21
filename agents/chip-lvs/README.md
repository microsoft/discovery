# chip-lvs — Layout-vs-Schematic Agent

## Overview

Node-aware Layout-vs-Schematic agent driven by Netgen LVS (+ Magic extraction), consuming the PDK Binding (device-matching setup) and emitting a Common Design Envelope. LVS is a mandatory tapeout gate. Validated on SkyWater sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/lvs/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`chip-lvs` is defined in [tool.yaml](tools/lvs/tool.yaml). Its Docker build context is `tools/lvs/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/lvs/Dockerfile --tag chip-lvs:local tools/lvs
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes


## Qualified Magic runtime and LVS repair

The Services image in `services-deployment.json` installs upstream Magic
**8.3.693**, pinned to commit `9fd4ee57386c08346b20389a55e4eb9d32553979`.
The canonical Containerfile verifies the archive SHA-256 and builds with
`make -j1`; prior worker and Netgen layers remain unchanged.
Native version/current-SKY technology loading and real inverter extraction
passed on 2026-11-16 (two devices, matching CDL device-model counts).
The canonical worker now selects both Netgen readers explicitly and passes
numeric circuit handles to LVS, rather than relying on second-file suffix
detection. SKY130 extraction uses subcircuit devices, so the independent
schematic control uses the PDK SPICE view with the same primitive pin contract,
not the CDL MOS-device representation.

The verdict parser also rejects Netgen's "Property errors were found" result
even when topology matches uniquely. Native source-backed controls on
2026-11-16 establish a unique inverter match and reject changed connectivity,
a missing device and doubled transistor width. The repaired worker module is
packaged over the existing immutable Magic/Netgen layers; installed-image
deployment qualification is recorded separately in the campaign evidence.
Neither bounded inverter equivalence nor extraction establishes full-chip
signoff. No staged App activation is claimed.

Node-aware **Layout-vs-Schematic (LVS)** agent. Runs **Netgen** batch LVS to
compare the layout-extracted netlist against the source/schematic netlist
device-for-device and net-for-net, and can extract the layout netlist from a
`.mag`/`.gds` via **Magic** `ext2spice`.

LVS is a **mandatory tapeout gate**: sign off only on a unique match.

- **Engines:** Netgen (`netgen -batch lvs "<layout> <cell>" "<schem> <cell>" <setup> <report>`), Magic (`ext2spice`)
- **Node awareness:** node-aware — the device-matching setup comes from the PDK
  Binding (`lvs_rules`).
- **Output:** Common Design Envelope (`/output/final_results.json`).

## Scenarios

| Scenario | Purpose |
|---|---|
| `lvs_compare` | Netgen comparison of layout vs schematic netlists → unique-match verdict + property/device/net mismatch counts. |
| `extract_layout` | Magic `ext2spice` to produce the layout SPICE netlist from a `.mag`/`.gds`. |

## Signoff discipline

Only a unique match signs off. Netgen returns exit 0 even on a mismatch, so the
verdict is parsed from the comparison report (`Circuits match uniquely` vs
`Netlists do not match`). A property/device/net mismatch is a hard failure and is
never laundered into a pass.

## PDK note

The device-matching setup (`lvs_rules`) is supplied by the PDK Binding. Omit it
(`nosetup`) for a bare structural compare; switching nodes requires only a
different binding.
