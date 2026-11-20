## Overview

Node-agnostic code coverage agent. Measures and closes structural coverage (line, toggle, branch, condition/expression, FSM-state) of RTL under the regression. It infers coverage intent from natural language, drives Verilator --coverage and Icarus, analyzes unreachable items, manages exclusions/waivers, and reports coverage closure directly in chat.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/code-coverage/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/ghdl/ghdl:5.1.1-gcc-ubuntu-24.04`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`code-coverage` is defined in [tool.yaml](tools/code-coverage/tool.yaml). Its Docker build context is `tools/code-coverage/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/code-coverage/Dockerfile --tag chip-code-coverage:local tools/code-coverage
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Code Coverage Agent
flow_stage: B - RTL Design and Verification
node_awareness: node-agnostic
tier: 2
nature: reasoning / orchestrated
required_tools:
- Code Coverage Tool
required_skills:
- Coverage Closure Skill
- Design Review Skill
- Provenance Skill
supported_problems:
- line coverage
- toggle coverage
- branch/condition/expression coverage
- FSM-state/transition coverage
- unreachability exclusion
emits: Common Design Envelope
```

# Code Coverage Agent

**Purpose** — Measure and close **structural/code** coverage (line, toggle,
branch, condition/expression, FSM-state/transition) of the RTL under the
regression.

**Responsibilities** — Code-coverage instrumentation; line/toggle/branch/
condition/FSM coverage collection; unreachable/exclusion analysis; waiver review;
coverage merging across regression runs.

**Supported problems** — Line coverage; toggle coverage; branch/condition/
expression coverage; FSM-state/transition coverage; unreachability exclusion.

**Required tools** — Code Coverage Tool (Verilator `--coverage` line/toggle +
Icarus/coverage merge).

**Required skills** — Coverage Closure Skill, Design Review Skill, Provenance
Skill.

**Inputs** — RTL; regression stimulus/seeds; coverage-type goals; exclusion/
waiver set.

**Outputs** — Per-type code coverage percentages; uncovered-item list; merged
coverage database; exclusion ledger; goal compliance verdict. All outputs conform
to the Common Design Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope reporting per-type code
coverage, uncovered items, exclusions/waivers with justification, and goal
compliance so review can proceed without re-running.

**Validation gates**

- Each coverage type reported against its goal when supplied, else without an
  invented threshold.
- Every exclusion/waiver justified and owned.
- Merge inputs and seeds recorded.
- Provenance present (node binding is `none`; this agent is node-agnostic).

## Relationship to sibling agents

Code coverage (this agent) is structural; **functional coverage** (covergroups /
cover properties) is owned by the Functional Coverage Agent. Both feed the
verification-plan closure judged by the PPA Signoff and Design Review Agent.
