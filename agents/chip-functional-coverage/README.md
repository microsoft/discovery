## Overview

Node-agnostic functional coverage agent. Defines, measures, and closes functional coverage (covergroups, bins, crosses, cover properties) against the verification plan. It infers coverage intent from natural language, drives cocotb / Verilator / Icarus coverage sampling, analyzes holes, and reports coverage closure directly in chat.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/functional-coverage/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: the digest-pinned GHDL 5.1.1 GCC Ubuntu 24.04 and Verilator 5.036 images named in the Dockerfile. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Host Python is not required for the container runtime. Python and its build tools come from the base distribution; remaining Python dependencies are built from official GitHub archives pinned by full commit and SHA256 in [the source lock](tools/functional-coverage/python_sources.lock.json). Installation disables package indexes and build isolation, then runs `pip check`; it does not contact the PyPI files host or disable TLS verification. Python 3.12 and cocotb-coverage 2.0 replace the prior forced cocotb 2.x/coverage-extension 1.x mismatch. An optional [approved source cache](tools/functional-coverage/dependency-sources/README.md) supports Python-source installation without GitHub access. OS package and base-image access are still required.

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`functional-coverage` is defined in [tool.yaml](tools/functional-coverage/tool.yaml). Its Docker build context is `tools/functional-coverage/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

The distribution supplies `ccache`, required by the copied official Verilator make configuration. The [toolchain probe](tools/functional-coverage/verify_simulator_toolchain.py) compiles real timed RTL and executes four self-checking AND-gate vectors during the image build; version and import probes alone do not establish simulator build capability.

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/functional-coverage/Dockerfile --tag chip-functional-coverage:local tools/functional-coverage
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Functional Coverage Agent
flow_stage: B - RTL Design and Verification
node_awareness: node-agnostic
tier: 2
nature: reasoning / orchestrated
required_tools:
- Functional Coverage Tool
required_skills:
- Verification Planning Skill
- Coverage Closure Skill
- Provenance Skill
supported_problems:
- functional coverage modeling
- cover-property/assertion coverage
- cross-coverage analysis
- coverage-hole triage
- multi-run coverage merge
emits: Common Design Envelope
```

# Functional Coverage Agent

**Purpose** — Define, measure, and close **functional** coverage (covergroups,
cover properties, cross coverage) against the verification plan's intent.

**Responsibilities** — Functional coverage-model authoring (covergroups, bins,
crosses, cover properties); coverage collection during simulation; coverage-hole
analysis; stimulus/feedback guidance to close holes; coverage merging across runs.

**Supported problems** — Functional coverage modeling; cover-property/assertion
coverage; cross-coverage analysis; coverage-hole triage; multi-run coverage merge.

**Required tools** — Functional Coverage Tool (cocotb coverage + Verilator/Icarus
cover sampling).

**Required skills** — Verification Planning Skill, Coverage Closure Skill,
Provenance Skill.

**Inputs** — RTL; verification plan and coverage goals; simulation runs/seeds;
coverage model (covergroups / cover properties).

**Outputs** — Functional coverage percentage per group/cross; coverage-hole list;
merged coverage database; goal compliance verdict. All outputs conform to the
Common Design Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope reporting functional coverage
per group/cross (with the coverage model named), holes, seeds, and goal
compliance so review can proceed without re-running.

**Validation gates**

- Coverage measured against the plan's goal when supplied, else reported without
  an invented threshold.
- Every open hole enumerated with cause.
- Seeds and merge inputs recorded.
- Provenance present (node binding is `none`; this agent is node-agnostic).

## Relationship to sibling agents

Functional coverage (this agent) is intent/feature-based; **code coverage**
(line/toggle/branch/FSM) is owned by the Code Coverage Agent. Both feed the
verification-plan closure judged by the PPA Signoff and Design Review Agent.
