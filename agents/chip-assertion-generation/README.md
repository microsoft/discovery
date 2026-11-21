## Overview

Node-agnostic assertion generator that authors non-vacuous SystemVerilog assertions (SVA) and cover properties capturing design and protocol intent from the shared verification plan (vplan). Drives SVA authoring + SymbiYosys/Yosys formal checkability screening and reports assertions with formal-checkability status directly in chat.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/assertion-generation/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/library/debian:12-slim@sha256:5ae3c39ebd15e229dcedd5cee596b2497182493d41ff162e824ba13fc1b2b867`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`assertion-generation` is defined in [tool.yaml](tools/assertion-generation/tool.yaml). Its Docker build context is `tools/assertion-generation/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/assertion-generation/Dockerfile --tag chip-assertion-generation:local tools/assertion-generation
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Assertion (SVA) Generation Agent
flow_stage: B - RTL Design and Verification
node_awareness: node-agnostic
tier: 2
nature: reasoning / orchestrated
required_tools:
- Assertion Generation Tool
required_skills:
- Assertion Authoring Skill
- Verification Planning Skill
- Verification and Validation Skill
- Provenance Skill
supported_problems:
- SVA authoring
- protocol assertion generation
- cover-property authoring
- assertion quality/vacuity review
emits: Common Design Envelope
```

# Assertion (SVA) Generation Agent

**Purpose** — Author and check SystemVerilog assertions (SVA) and cover properties
capturing design intent and protocol rules.

**Responsibilities** — Assertion/property authoring; protocol-rule encoding;
assertion density/quality review; formal-checkability triage; vacuity screening.

**Supported problems** — SVA authoring; protocol assertion generation; cover-
property authoring; assertion quality/vacuity review.

**Required tools** — Assertion Generation Tool (SVA authoring + SymbiYosys/Yosys
formal check).

**Required skills** — Assertion Authoring Skill, Verification Planning Skill,
Verification and Validation Skill, Provenance Skill.

**Inputs** — RTL and interfaces; specification/protocol; verification plan
(`vplan`).

**Outputs** — Generated assertions/cover properties; formal-checkability status;
vacuity screen; `vplan` linkage. All outputs conform to the Common Design Envelope
and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope naming each assertion, its
intent/`vplan` linkage, and formal-checkability status so the Formal Verification
Agent can prove them without re-authoring.

**Validation gates**

- Each assertion has explicit intent and is non-vacuous.
- Protocol rules covered per the plan.
- Formal-checkability stated.
- Provenance present (node binding is `none`; node-agnostic).

## Shared verification plan (`vplan`)

Part of the verification cluster that reads and updates the shared `vplan`. This
agent authors and screens assertions; the Formal Verification Agent proves them.
