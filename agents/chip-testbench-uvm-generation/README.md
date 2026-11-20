## Overview

Node-agnostic verification-environment generator that builds reusable UVM-style / cocotb testbenches (drivers, monitors, scoreboards, agents, BFMs, reference-model stubs) from the specification and shared verification plan (vplan). Drives cocotb/pyuvm + Verilator/Icarus and reports the generated environment and smoke-test result directly in chat.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/testbench-generation/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/verilator/verilator:v5.036@sha256:7e3809f5def31acb9746be550714bc991bae87dd687ac2939de183a541ed84c7`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`testbench-generation` is defined in [tool.yaml](tools/testbench-generation/tool.yaml). Its Docker build context is `tools/testbench-generation/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/testbench-generation/Dockerfile --tag chip-testbench-uvm-generation:local tools/testbench-generation
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Testbench and UVM Generation Agent
flow_stage: B - RTL Design and Verification
node_awareness: node-agnostic
tier: 2
nature: reasoning / orchestrated
required_tools:
- Testbench Generation Tool
required_skills:
- Testbench Generation Skill
- Verification Planning Skill
- Provenance Skill
supported_problems:
- testbench generation
- UVM-style environment construction
- BFM/interface agent generation
- scoreboard/reference-model scaffolding
emits: Common Design Envelope
```

# Testbench and UVM Generation Agent

**Purpose** — Generate reusable verification environments and testbenches
(UVM-style / cocotb) from the specification and verification plan.

**Responsibilities** — Testbench/environment scaffolding; driver/monitor/
scoreboard/agent generation; interface/BFM construction; reference-model
stubbing; wiring the environment to the coverage and assertion agents.

**Supported problems** — Testbench generation; UVM-style environment construction;
BFM/interface agent generation; scoreboard/reference-model scaffolding.

**Required tools** — Testbench Generation Tool (cocotb / pyuvm + Verilator/Icarus).

**Required skills** — Testbench Generation Skill, Verification Planning Skill,
Provenance Skill.

**Inputs** — RTL and interfaces; specification and verification plan (`vplan`);
coverage/assertion intent.

**Outputs** — Generated testbench/environment; connectivity report; smoke-test
result; verification-plan linkage. All outputs conform to the Common Design
Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope naming the generated
environment components, their `vplan` linkage, and a smoke-test result so
downstream stimulus/coverage/debug agents can run without re-scaffolding.

**Validation gates**

- Environment elaborates and compiles.
- Every generated component traces to a `vplan` item.
- Smoke test passes or failure is preserved.
- Provenance present (node binding is `none`; node-agnostic).

## Shared verification plan (`vplan`)

This agent is part of the verification cluster (Testbench/UVM, Stimulus/CRV,
Assertion/SVA, Functional Coverage, Code Coverage, Debug, Regression) that all
read and update the same `vplan` artifact in the Common Design Envelope, so
closure is measured against one authoritative plan.
