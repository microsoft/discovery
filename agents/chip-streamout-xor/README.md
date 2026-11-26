# chip-streamout-xor

## Overview

Node-aware physical-layout XOR agent using real KLayout XOR and independent Magic/KLayout DEF streamout paths. Emits a fail-closed Common Design Envelope.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/streamout-xor/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`streamout-xor` is defined in [tool.yaml](tools/streamout-xor/tool.yaml). Its Docker build context is `tools/streamout-xor/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/streamout-xor/Dockerfile --tag chip-streamout-xor:local tools/streamout-xor
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes


## Qualified Magic runtime and streamout mapping repair

The Services image in `services-deployment.json` installs upstream Magic
**8.3.693**, pinned to commit `9fd4ee57386c08346b20389a55e4eb9d32553979`.
The canonical Containerfile verifies the archive SHA-256 and builds with
`make -j1`; prior worker and other-engine layers remain unchanged.
Native version/current-SKY technology loading passed on 2026-11-16.
The prior independent SKY mismatch came from KLayout importing routing, pins
and the die boundary onto invented layers: the PDK technology has an empty
inline layer map. When that map is empty, the worker now loads the actual
same-basename `.map` adjacent to the bound technology, if present. Explicit
caller maps and populated inline technology maps remain authoritative.
Actual top-level pin rectangles retain the map's drawing and port purposes.
The source-backed SKY control now has zero XOR polygons and zero difference
area across all compared layers; missing real-cell geometry still fails closed.
Installed-image and geometric regression qualification are recorded separately.
Runtime qualification does not imply staged App activation.

Node-aware final-layout comparison and dual-streamout validation.

- `xor_gds` loads two GDSII or OASIS layouts with KLayout, computes a real
  layer-by-layer geometric XOR, writes a difference layout, and reports exact
  difference polygon count and area.
- `dual_streamout_xor` independently streams a DEF through Magic and KLayout,
  using PDK-bound tech/mapping and cell geometry, then applies the same XOR gate.

Magic loads immutable library GDS with `gds readonly true`, retaining the
supplied cell masks rather than regenerating them through the technology's
`cifinput`/`cifoutput` rules. DEF placement and routing are still imported
independently by Magic. No comparison layers are excluded. For diagnosis,
`diagnose_editable_magic: true` also compares a separate legacy editable-import
control; optional `diagnostic_cell` compares that actual cell under both policies.
Control failures and per-layer differences remain in the CDE and do not replace
the primary all-layer XOR verdict.
`diagnostic_geometry: true` additionally records bounded native polygon
bounding boxes (including truncation flags) for each side and the XOR; it does
not alter shapes, comparison layers, or the verdict.

Before reading LEF, Magic refines its startup grid using the bound LEF
`MANUFACTURINGGRID` and Magic technology `scalefactor`. This prevents coarse-grid
rounding of route widths before a later GDS import refines the grid.
When a default KLayout technology maps terminal pins onto drawing metal but
Magic declares a separate port purpose, a work-directory technology copy
aligns the pin/label purposes to those declarations. Actual top-level DEF pin
rectangles remain on both drawing and port layers; library cells and vendor
views are unchanged. Explicit caller layer maps remain authoritative.
Precision provenance and applied port mappings are recorded in reports.
The bound Magic technology's declared minimum engine version is enforced.
An older or unmeasurable engine remains a capability blocker, not a technology
substitution. Magic output must contain a valid GDS header; exit zero or an
existing empty file alone is not a successful streamout.

The tool fails closed if KLayout/Magic, required inputs, mapping, technology, or
cell-layout references are unavailable. A clean XOR requires zero difference
polygons and zero difference area. Caller settings take precedence over
`pdk_binding.tool_policy.streamout_xor`, which takes precedence over built-ins;
each decision source and override is recorded.

Outputs are split into `results/`, `reports/`, and `logs/`, with `SUMMARY.md` and
a standard 14-field Common Design Envelope at the output root. Provenance hashes
all available input and output artifacts.
