## Overview

Node-aware KLayout geometry screening for windowed density, lithography-risk patterns, critical area, and Poisson random-defect yield. PDK limits are required; missing defect densities gate the result rather than inflate yield. OPC, resist and process-window simulation are outside scope. Emits a Common Design Envelope, not an OPC-readiness verdict.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/dfm/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build base: the digest-pinned Debian 12 slim image named in the Dockerfile. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Host Python is not required for the container runtime. Distribution packages supply Python and build tools. KLayout 0.30.10 is built from its official GitHub source pinned by full commit and SHA256 in [the source lock](tools/dfm/python_sources.lock.json), using two compiler jobs and a separate build stage. Its geometry engine is not replaced by a parser or stub. Installation disables package indexes and build isolation and preserves TLS verification. An optional [approved source cache](tools/dfm/dependency-sources/README.md) supports Python-source installation without GitHub access. OS package and base-image access are still required.

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`chip-dfm` is defined in [tool.yaml](tools/dfm/tool.yaml). Its Docker build context is `tools/dfm/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

The exact KLayout source build uses four compiler workers within a single image build and disables debug-symbol generation with `-g0`; upstream already strips these symbols at link time. Normal optimization and the real geometry engine remain enabled. This is not four parallel image builds. Source compilation needs a generous build-time bound; an interrupted build is not an available image or a passing DFM result.

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/dfm/Dockerfile --tag chip-dfm-litho-yield:local tools/dfm
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: DFM, Lithography, and Yield Agent
flow_stage: E - Timing, Power, Physical Signoff
node_awareness: node-aware
tier: 2
nature: reasoning / orchestrated
required_tools:
- DFM Tool
required_skills:
- DFM and Lithography Skill
- DRC/LVS Signoff Skill
- PDK Binding Skill
- QoR Reporting Skill
- Provenance Skill
supported_problems:
- DFM / recommended-rule checking
- geometric lithography hotspot / printability screening
- yield / critical-area analysis
- windowed pattern-density measurement
emits: Common Design Envelope
```

# DFM, Lithography, and Yield Agent

**Purpose** — Assess design-for-manufacturability and yield readiness ahead of
mask preparation, from the actual layout geometry.

**Responsibilities** — DFM/recommended-rule checking; windowed pattern-density
measurement; geometric litho-risk pattern screening; critical-area /
random-defect yield estimation.

**Supported problems** — DFM checking; geometric lithography hotspot screening;
yield / critical-area analysis.

**Required tools** — DFM Tool (KLayout geometry engine: windowed density,
width/space/notch/isolated screening, critical area).

**Required skills** — DFM and Lithography Skill, DRC/LVS Signoff Skill, PDK
Binding Skill, QoR Reporting Skill, Provenance Skill.

## What is measured, and what is out of scope

Everything below is measured from the **real layout** via the KLayout geometry
engine. Previously this tool opened no layout at all — every number was supplied
by the caller, and KLayout was not installed.

| Measured from geometry | Out of scope (declared, never reported clean) |
|---|---|
| windowed pattern density | aerial-image simulation |
| features below the printability limit | resist modelling |
| gaps below the resolution limit | focus/exposure process window |
| notches, isolated features | **OPC/RET verification** |
| critical area (width/space method) | |

### Why there is no OPC-readiness verdict

The tool emits no such field, by any code path. OPC is verified by comparing a
**simulated printed image** against design intent, which requires a calibrated
optical model (NA, sigma, illumination) and resist model from the foundry.
Screening drawn geometry cannot establish it.

The previous implementation was the purest fail-open in the catalog:

```python
hotspots = params.get("hotspots", [])
"opc_ready": len(hotspots) == 0
```

Supply no hotspots, and the design was declared OPC-ready and passed the gate.
Not a check that silently passed — **a claim manufactured from the absence of
input**.

### Why density is measured per window

Density rules are written per window, and a die-average hides exactly the
layouts that fail. On the tool's own test layout the die-average is **0.307**,
comfortably inside a 0.20–0.70 rule, while individual windows sit at **0.0125**.
An average-only check reports that design clean.

The consumer passes the binding's `density_window.step_um` to the geometry
engine, rather than silently measuring only non-overlapping windows.
Measurements record the actual step and window count. Edge windows clip to the
layout bounding box and use their clipped area as denominator; this is an
explicit geometric edge policy, not proof of foundry density-deck equivalence.
An absent required layer remains `not_assessable` even if other layers or
caller-supplied via metrics were measured. Native controls distinguish one
non-overlapping window from one hundred rolling windows and preserve full
density at the edges of a completely filled square.

### Why a missing defect density gates the yield run

$Y = e^{-\lambda}$, so dropping a term shrinks $\lambda$ and **raises** the
reported yield. The old loop silently skipped any defect size with no density,
meaning missing data made the design look better — with a `completed` verdict and
no indication anything had been dropped. Unpriced sizes are now counted and
gating, and the yield is labelled an **upper bound** whenever any exist.

**Inputs** — Layout (GDS); PDK Binding (DFM/recommended rules, litho decks, defect-
density data).

**Outputs** — Dispositioned DFM findings; measured windowed density; geometric
litho-hotspot list; yield/critical-area estimate with method; unpriced defect
sizes; the explicit out-of-scope list. All outputs conform to the Common Design
Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope with the DFM/litho findings,
the yield estimate (with units and method), and everything that was NOT
evaluated, so mask-prep readiness can be judged without re-running.

**Validation gates**

- Recommended-rule/DFM findings enumerated, each carrying its own disposition
  (`undispositioned_findings == 0`, counted from the findings themselves).
- `litho_hotspots == 0` and `unscreened_layers == 0`. A null means nothing was
  screened and does not satisfy the gate.
- `unpriced_defect_sizes == 0` before a yield figure is read as an estimate.
- Node DFM/litho decks recorded; provenance present.

**Known limits** — Via redundancy is computed from caller-supplied counts, not
from geometry, and is labelled as such. Critical area uses a first-order
width/space model, not exact Voronoi extraction, and is net-unaware, so same-net
shapes contribute to the short term. CMP/planarity screening is **not**
implemented. Litho screening is geometric only — see the out-of-scope table.

## Relationship to sibling agents

DFM/recommended rules are distinct from the **mandatory** physical rules owned by
the Design Rule Check Agent. This agent screens *manufacturability* and *yield*
readiness (recommended rules, litho printability, critical area) ahead of
mask-data preparation; it does not replace hard DRC signoff.

## Node-Specific Notes

DFM/recommended rules, litho decks, and defect-density data are consumed from
`pdk_binding`, never hard-coded.

### sky130 (validation baseline)

- `pdk`: `sky130A`; DFM/recommended-rule and litho screening decks resolved from
  the binding; layers `li1`, `met1`–`met5`.
- Geometric screening on the open KLayout engine. Advanced-node litho/OPC signoff
  requires a commercial engine with calibrated optical and resist models; until
  one is bound, those mechanisms stay in the out-of-scope list rather than being
  reported as clean.

### <future node> (stub)

- `pdk`, `dfm_rules`, `recommended_rules`, `litho_decks`, `defect_density`: _from
  binding_.
